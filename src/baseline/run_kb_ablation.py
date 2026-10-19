#!/usr/bin/env python3
"""Run a paired closed-book vs fixed-KB development ablation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from project_paths import MODEL_PATH, PROJECT_ROOT, TEST_SET_FILE
from run_baseline_eval import (
    INFERENCE_CONFIG,
    SYSTEM_PROMPT,
    extract_json_payload,
    serialize_user_prompt,
)

KNOWLEDGE_SOURCE = PROJECT_ROOT / "src" / "knowledge_base"
sys.path.insert(0, str(KNOWLEDGE_SOURCE))
from query_kb import (  # noqa: E402
    COMPACT_CONTEXT_VIEW_ID,
    LEGACY_COMPACT_CONTEXT_VIEW_ID,
    SNAPSHOT_ID,
    SNAPSHOT_ROOT,
    assemble_context,
)


DEFAULT_SAMPLE_IDS = (1, 4, 10, 15, 19, 20, 21, 27, 36)
POSITIONS = ("top", "jungle", "mid", "bottom", "support")
CONDITIONS = ("closed_book", "fixed_kb")
RULESET_ID = "lol-pc-ddragon-16.16.1-asof-2026-08-21"
KNOWLEDGE_CONTEXT_VIEWS = (
    "full",
    LEGACY_COMPACT_CONTEXT_VIEW_ID,
    COMPACT_CONTEXT_VIEW_ID,
)
PROMPT_TEMPLATE_VERSIONS = {
    "full": "fixed-kb-ablation-prompt-v2",
    LEGACY_COMPACT_CONTEXT_VIEW_ID: "compact-kb-ablation-prompt-v1",
    COMPACT_CONTEXT_VIEW_ID: "compact-kb-ablation-prompt-v2",
}
CONTEXT_VIEW_MANIFESTS = {
    "full": SNAPSHOT_ROOT / "manifest.json",
    LEGACY_COMPACT_CONTEXT_VIEW_ID: (
        PROJECT_ROOT
        / "data/knowledge/context_views"
        / SNAPSHOT_ID
        / LEGACY_COMPACT_CONTEXT_VIEW_ID
        / "manifest.json"
    ),
    COMPACT_CONTEXT_VIEW_ID: (
        PROJECT_ROOT
        / "data/knowledge/context_views"
        / SNAPSHOT_ID
        / COMPACT_CONTEXT_VIEW_ID
        / "manifest.json"
    ),
}
TEAM_LABELS = {"blue_team": "蓝方", "red_team": "红方"}
POSITION_LABELS = {
    "top": "上路",
    "jungle": "打野",
    "mid": "中路",
    "bottom": "下路",
    "support": "辅助",
}

SHARED_SYSTEM_PROMPT = SYSTEM_PROMPT + """

【本次实验约束】
评估规则版本固定为 Data Dragon 16.16.1，知识截止日为 2026-08-21。
如果用户提供固定英雄知识，必须把它作为英雄机制事实依据，但仍需自行完成阵容交互和战术推演；不得把知识卡逐条照抄成答案。
如果用户没有提供固定英雄知识，则仅依靠模型自身已有知识作答。
除非能够确认技能槽位与效果完全对应，否则不要写“Q/W/E/R具有某效果”，应直接描述可确认的机制，严禁按技能键猜测。"""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def lineup_names(row: dict[str, Any]) -> list[str]:
    return [
        row["draft_phase_lineup"][team][position]
        for team in ("blue_team", "red_team")
        for position in POSITIONS
    ]


def build_positioned_knowledge_context(
    row: dict[str, Any], knowledge_context_view: str = "full"
) -> tuple[list[str], str]:
    champion_ids: list[str] = []
    sections: list[str] = []
    for team in ("blue_team", "red_team"):
        for position in POSITIONS:
            input_name = row["draft_phase_lineup"][team][position]
            resolved_ids, single_context = assemble_context(
                [input_name], context_view=knowledge_context_view
            )
            champion_id = resolved_ids[0]
            champion_ids.append(champion_id)
            body_parts = single_context.strip().split("\n\n", 1)
            if len(body_parts) != 2:
                raise ValueError(f"{input_name}: 单英雄上下文结构不符合预期")
            body = body_parts[1]
            first_line = body.splitlines()[0]
            if not first_line.startswith("英雄："):
                raise ValueError(f"{input_name}: 无法读取标准中文名")
            official_name_zh = (
                first_line.removeprefix("英雄：").split("（", 1)[0].strip()
            )
            sections.append(
                f"### {TEAM_LABELS[team]} / {POSITION_LABELS[position]}"
                f" | 输入称号：{input_name} | 标准名：{official_name_zh}"
                f" | ID：{champion_id}\n{body}"
            )
    if len(set(champion_ids)) != len(champion_ids):
        raise ValueError("同一阵容不能包含重复英雄")
    header = (
        f"知识快照：{SNAPSHOT_ID}\n"
        f"上下文视图：{knowledge_context_view}\n"
        "规则：每张卡已与阵营和位置显式绑定；卡片只提供英雄机制事实，"
        "不提供阵容结论。分析时必须保持英雄、阵营和技能机制对应。"
    )
    return champion_ids, header + "\n\n" + "\n\n---\n\n".join(sections) + "\n"


def load_selected_rows(sample_ids: list[int]) -> list[tuple[int, dict[str, Any]]]:
    rows = [
        json.loads(line)
        for line in TEST_SET_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not sample_ids or len(sample_ids) != len(set(sample_ids)):
        raise ValueError("sample_ids 不能为空或重复")
    invalid = [sample_id for sample_id in sample_ids if not 1 <= sample_id <= len(rows)]
    if invalid:
        raise ValueError(f"sample_id 超出测试集范围：{invalid}")
    return [(sample_id, rows[sample_id - 1]) for sample_id in sample_ids]


def build_condition_prompt(
    row: dict[str, Any], condition: str, knowledge_context_view: str = "full"
) -> tuple[list[str], str, str]:
    base_prompt = serialize_user_prompt(row)
    final_instruction = "请直接输出符合系统要求的 JSON 数据。"
    if not base_prompt.endswith(final_instruction):
        raise ValueError("Baseline user prompt 末尾协议发生了未预期变化")
    prompt_stem = base_prompt[: -len(final_instruction)].rstrip()
    champion_ids, knowledge_context = build_positioned_knowledge_context(
        row, knowledge_context_view=knowledge_context_view
    )

    if condition == "closed_book":
        condition_context = "【可用英雄机制知识】\n本条件不提供外部英雄机制知识。"
    elif condition == "fixed_kb":
        condition_context = (
            "【可用英雄机制知识】\n"
            "以下十名英雄资料来自固定知识快照。文中的【数值】表示本实验未展开的版本化数值；"
            "不要自行补写具体数值。\n\n"
            + knowledge_context.rstrip()
        )
    else:
        raise ValueError(f"未知实验条件：{condition}")

    return (
        champion_ids,
        knowledge_context,
        f"{prompt_stem}\n\n{condition_context}\n\n{final_instruction}",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--sample-ids", type=int, nargs="+", default=list(DEFAULT_SAMPLE_IDS))
    parser.add_argument("--max-new-tokens", type=int, default=INFERENCE_CONFIG["max_new_tokens"])
    parser.add_argument(
        "--knowledge-context-view",
        choices=KNOWLEDGE_CONTEXT_VIEWS,
        default="full",
        help="fixed_kb 条件使用完整英雄卡或紧凑机制视图",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if Path(args.experiment_id).name != args.experiment_id or args.experiment_id in {"", ".", ".."}:
        raise ValueError("experiment-id 必须是单个安全目录名")
    if args.max_new_tokens < 1:
        raise ValueError("max-new-tokens 必须为正整数")
    if not MODEL_PATH.is_dir():
        raise FileNotFoundError(f"未找到模型目录：{MODEL_PATH}")

    selected_rows = load_selected_rows(args.sample_ids)
    prepared: list[tuple[int, dict[str, Any], list[str], str, dict[str, str]]] = []
    for sample_id, row in selected_rows:
        champion_ids, knowledge_context, closed_prompt = build_condition_prompt(
            row, "closed_book", args.knowledge_context_view
        )
        kb_ids, kb_context, kb_prompt = build_condition_prompt(
            row, "fixed_kb", args.knowledge_context_view
        )
        if kb_ids != champion_ids or kb_context != knowledge_context:
            raise ValueError(f"sample_id={sample_id} 两条件的检索结果不一致")
        prepared.append(
            (
                sample_id,
                row,
                champion_ids,
                knowledge_context,
                {"closed_book": closed_prompt, "fixed_kb": kb_prompt},
            )
        )

    experiment_dir = PROJECT_ROOT / "experiments" / args.experiment_id
    output_path = experiment_dir / "paired_outputs.jsonl"
    config_path = experiment_dir / "config.json"
    if experiment_dir.exists() and any(experiment_dir.iterdir()):
        raise FileExistsError(f"{experiment_dir} 已包含产物；禁止静默覆盖")
    experiment_dir.mkdir(parents=True, exist_ok=True)

    inference_config = dict(INFERENCE_CONFIG)
    inference_config["max_new_tokens"] = args.max_new_tokens
    config = {
        "schema_version": "kb-ablation-config-v2",
        "experiment_id": args.experiment_id,
        "status": "running",
        "purpose": "方向性开发验证，不是正式 baseline",
        "model_path": str(MODEL_PATH.resolve()),
        "model_config_sha256": sha256_file(MODEL_PATH / "config.json"),
        "dataset_path": str(TEST_SET_FILE.relative_to(PROJECT_ROOT)),
        "dataset_sha256": sha256_file(TEST_SET_FILE),
        "sample_ids": args.sample_ids,
        "conditions": list(CONDITIONS),
        "ruleset_id": RULESET_ID,
        "knowledge_snapshot_id": SNAPSHOT_ID,
        "knowledge_context_view": args.knowledge_context_view,
        "prompt_template_version": PROMPT_TEMPLATE_VERSIONS[args.knowledge_context_view],
        "knowledge_manifest_sha256": sha256_file(SNAPSHOT_ROOT / "manifest.json"),
        "knowledge_context_view_manifest_sha256": sha256_file(
            CONTEXT_VIEW_MANIFESTS[args.knowledge_context_view]
        ),
        "aliases_sha256": sha256_file(SNAPSHOT_ROOT / "aliases.json"),
        "system_prompt": SHARED_SYSTEM_PROMPT,
        "system_prompt_sha256": sha256_bytes(SHARED_SYSTEM_PROMPT.encode("utf-8")),
        "runner_sha256": sha256_file(Path(__file__)),
        "inference": inference_config,
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    torch.manual_seed(inference_config["seed"])
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH), trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_PATH),
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model.eval()

    with output_path.open("x", encoding="utf-8") as output_file:
        total = len(prepared) * len(CONDITIONS)
        completed = 0
        for sample_id, row, champion_ids, knowledge_context, prompts in prepared:
            record: dict[str, Any] = {
                "sample_id": sample_id,
                "scenario_type": row.get("scenario_type", "unknown"),
                "input_scenario": row,
                "retrieved_champion_ids": champion_ids,
                "knowledge_snapshot_id": SNAPSHOT_ID,
                "knowledge_context_view": args.knowledge_context_view,
                "knowledge_context_sha256": sha256_bytes(knowledge_context.encode("utf-8")),
                "conditions": {},
            }
            for condition in CONDITIONS:
                prompt = prompts[condition]
                messages = [
                    {"role": "system", "content": SHARED_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                chat_text = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                model_inputs = tokenizer([chat_text], return_tensors="pt").to(model.device)
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                started = time.perf_counter()
                with torch.no_grad():
                    generated = model.generate(
                        **model_inputs,
                        max_new_tokens=inference_config["max_new_tokens"],
                        repetition_penalty=inference_config["repetition_penalty"],
                        do_sample=inference_config["do_sample"],
                    )
                if torch.cuda.is_available():
                    torch.cuda.synchronize()
                latency_seconds = time.perf_counter() - started
                output_ids = generated[0][model_inputs.input_ids.shape[1] :]
                raw_response = tokenizer.decode(output_ids, skip_special_tokens=True)
                cleaned_response = extract_json_payload(raw_response)
                try:
                    json.loads(cleaned_response)
                    is_valid_json = True
                except json.JSONDecodeError:
                    is_valid_json = False
                record["conditions"][condition] = {
                    "input_prompt": prompt,
                    "input_prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                    "input_token_count": int(model_inputs.input_ids.shape[1]),
                    "output_token_count": int(output_ids.shape[0]),
                    "latency_seconds": round(latency_seconds, 3),
                    "is_valid_json": is_valid_json,
                    "model_output": cleaned_response,
                    "original_uncleaned_output": raw_response if not is_valid_json else None,
                }
                completed += 1
                print(
                    f"[{completed}/{total}] sample_id={sample_id} condition={condition} "
                    f"input_tokens={model_inputs.input_ids.shape[1]} "
                    f"output_tokens={output_ids.shape[0]} valid_json={is_valid_json}",
                    flush=True,
                )
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            output_file.flush()

    config["status"] = "completed"
    config["completed_pair_count"] = len(prepared)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"开发对照实验完成：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
