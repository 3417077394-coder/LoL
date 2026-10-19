#!/usr/bin/env python3
"""Judge paired closed-book/fixed-KB outputs with Evaluation Rubric v1.0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from openai import OpenAI

from calculate_baseline_metrics import (
    detect_numerical_hallucination,
    validate_schema_integrity,
)
from project_paths import PROJECT_ROOT
from run_kb_ablation import build_positioned_knowledge_context


PROMPT_PATH = PROJECT_ROOT / "prompts" / "kb_judge_e1_e5_v1.txt"
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "kb_judge_evaluation_v1.schema.json"
DEFAULT_BASE_URL = "https://api.poixe.com/v1"
DEFAULT_JUDGE_MODEL = "gpt-5.6-sol"
RUBRIC_VERSION = "evaluation-rubric-v1.0"
JUDGE_PROTOCOL_VERSION = "kb-judge-e1-e5-v1"
CONDITIONS = ("closed_book", "fixed_kb")
DIMENSIONS = ("E1", "E2", "E3", "E4", "E5")
KB_CRITERIA = tuple(f"KB{index}" for index in range(1, 6))

CAPABILITY_BY_CRITERION = {
    "E1.1": "Q03", "E1.2": "Q03", "E1.3": "B01", "E1.4": "B01", "E1.5": "B02",
    "E2.1": "K01", "E2.2": "K02", "E2.3": "K01", "E2.4": "K03", "E2.5": "Q01",
    "E3.1": "R01", "E3.2": "R03", "E3.3": "R02", "E3.4": "R02", "E3.5": "R03",
    "E4.1": "C01", "E4.2": "C02", "E4.3": "C02", "E4.4": "T01", "E4.5": "T02",
    "E5.1": "P01", "E5.2": "P01", "E5.3": "P02", "E5.4": "P03", "E5.5": "Q02",
}
EXPECTED_CRITERIA = tuple(CAPABILITY_BY_CRITERION)
ALLOWED_CAPS = {"E2": {2.0}, "E3": {2.5}, "E4": {2.0}, "E5": {2.0, 3.0}}
EXPECTED_CRITERION_KEYS = {
    "criterion_id", "score", "evidence_quote", "explanation",
    "capability_id", "severity", "confidence",
}
EXPECTED_KB_CRITERION_KEYS = {
    "criterion_id", "score", "evidence_quote", "explanation",
    "severity", "confidence",
}
ALLOWED_ENV_KEYS = {"OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_JUDGE_MODEL"}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_project_env(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load only Judge-related keys from a gitignored local .env file."""
    if not path.is_file():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in ALLOWED_ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        if "\n" in value or "\r" in value:
            raise ValueError(f".env 第 {line_number} 行包含非法换行")
        if key not in os.environ and value:
            os.environ[key] = value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path.name} 第 {line_number} 行不是合法 JSON：{error.msg}") from error
        if not isinstance(record, dict):
            raise TypeError(f"{path.name} 第 {line_number} 行根节点必须是对象")
        records.append(record)
    return records


def extract_json_object(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    payload = json.loads(match.group(0) if match else text)
    if not isinstance(payload, dict):
        raise TypeError("Judge 输出根节点必须是对象")
    return payload


def is_valid_score(value: Any) -> bool:
    return value == "NA" or (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and float(value) in {0.0, 0.5, 1.0}
    )


def dimension_score(items: list[dict[str, Any]]) -> float:
    numeric = [float(item["score"]) for item in items if item["score"] != "NA"]
    if not numeric:
        raise ValueError("维度不能全部为 NA")
    return round(sum(numeric) / len(numeric) * 5, 2)


def validate_and_enrich(
    payload: dict[str, Any],
    *,
    condition: str,
    program_checks: dict[str, Any],
    validator: Draft202012Validator,
) -> dict[str, Any]:
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    capability_id_corrections: list[dict[str, str | None]] = []
    criterion_items = payload.get("criterion_results")
    if isinstance(criterion_items, list):
        for item in criterion_items:
            if not isinstance(item, dict):
                continue
            criterion_id = item.get("criterion_id")
            expected = CAPABILITY_BY_CRITERION.get(criterion_id)
            if expected is not None and item.get("capability_id") != expected:
                capability_id_corrections.append({
                    "criterion_id": criterion_id,
                    "judge_value": item.get("capability_id"),
                    "canonical_value": expected,
                })
                item["capability_id"] = expected

    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        message = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
        raise ValueError(f"Judge JSON Schema 校验失败：{message}")

    criteria = payload["criterion_results"]
    ids = [item["criterion_id"] for item in criteria]
    if len(ids) != len(set(ids)) or set(ids) != set(EXPECTED_CRITERIA):
        raise ValueError("criterion_results 必须恰好覆盖 E1.1～E5.5")
    for item in criteria:
        if set(item) != EXPECTED_CRITERION_KEYS:
            raise ValueError(f"{item.get('criterion_id')}: 字段集合不合法")
        criterion_id = item["criterion_id"]
        if item["capability_id"] != CAPABILITY_BY_CRITERION[criterion_id]:
            raise ValueError(f"{criterion_id}: capability_id 不匹配")
        if not is_valid_score(item["score"]):
            raise ValueError(f"{criterion_id}: score 不合法")

    by_id = {item["criterion_id"]: item for item in criteria}
    expected_e11 = 1 if program_checks["is_valid_json"] else 0
    expected_e12 = 1 if program_checks["is_valid_schema"] else 0
    if by_id["E1.1"]["score"] != expected_e11 or by_id["E1.2"]["score"] != expected_e12:
        raise ValueError("Judge 没有遵循程序给定的 E1.1/E1.2 分数")

    kb_criteria = payload["kb_criterion_results"]
    kb_ids = [item["criterion_id"] for item in kb_criteria]
    if len(kb_ids) != len(set(kb_ids)) or set(kb_ids) != set(KB_CRITERIA):
        raise ValueError("kb_criterion_results 必须恰好覆盖 KB1～KB5")
    for item in kb_criteria:
        if set(item) != EXPECTED_KB_CRITERION_KEYS or not is_valid_score(item["score"]):
            raise ValueError(f"{item.get('criterion_id')}: KB 检查项不合法")
        if condition == "closed_book" and item["score"] != "NA":
            raise ValueError("closed_book 的 KB1～KB5 必须全部为 NA")
        if condition == "fixed_kb" and item["score"] == "NA":
            raise ValueError("fixed_kb 的 KB1～KB5 不得为 NA")

    cap_by_dimension: dict[str, float] = {}
    for cap in payload["applied_caps"]:
        dimension_id = cap["dimension_id"]
        max_score = float(cap["max_score"])
        if max_score not in ALLOWED_CAPS[dimension_id]:
            raise ValueError(f"{dimension_id}: 不允许的封顶 {max_score}")
        cap_by_dimension[dimension_id] = min(max_score, cap_by_dimension.get(dimension_id, 5.0))

    raw_scores: dict[str, float] = {}
    final_scores: dict[str, float] = {}
    for dimension in DIMENSIONS:
        items = [item for item in criteria if item["criterion_id"].startswith(f"{dimension}.")]
        raw = dimension_score(items)
        raw_scores[dimension] = raw
        cap = cap_by_dimension.get(dimension, 5.0)
        if dimension == "E1":
            if not program_checks["is_valid_json"]:
                cap = 0.0
            elif not program_checks["is_valid_schema"]:
                cap = min(cap, 3.0)
        final_scores[dimension] = round(min(raw, cap), 2)

    semantic_score = round(
        final_scores["E2"] * 0.20
        + final_scores["E3"] * 0.25
        + final_scores["E4"] * 0.25
        + final_scores["E5"] * 0.30,
        2,
    )
    knowledge_faithfulness_score = (
        None if condition == "closed_book" else dimension_score(kb_criteria)
    )
    return {
        "rubric_version": RUBRIC_VERSION,
        "judge_protocol_version": JUDGE_PROTOCOL_VERSION,
        **payload,
        "capability_id_corrections": capability_id_corrections,
        "raw_dimension_scores": raw_scores,
        "dimension_scores": final_scores,
        "semantic_score": semantic_score,
        "knowledge_faithfulness_score": knowledge_faithfulness_score,
    }


def make_program_checks(result: dict[str, Any]) -> dict[str, Any]:
    output = result.get("model_output")
    is_valid_json = False
    is_valid_schema = False
    schema_errors: list[str] = []
    numerical_trigger = False
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            is_valid_json = True
            schema_errors = validate_schema_integrity(parsed)
            is_valid_schema = not schema_errors
            numerical_trigger = detect_numerical_hallucination(parsed)
    return {
        "is_valid_json": is_valid_json,
        "is_valid_schema": is_valid_schema,
        "schema_errors": schema_errors,
        "numerical_trigger": numerical_trigger,
        "E1.1_score": 1 if is_valid_json else 0,
        "E1.2_score": 1 if is_valid_schema else 0,
    }


def build_user_prompt(
    *,
    condition: str,
    scenario: dict[str, Any],
    reference_context: str,
    program_checks: dict[str, Any],
    model_output: str,
) -> str:
    return f"""【实验条件】
{condition}

【原始阵容输入】
{json.dumps(scenario, ensure_ascii=False, indent=2)}

【Data Dragon 16.16.1 十英雄参考知识】
{reference_context}

【程序检查结果】
{json.dumps(program_checks, ensure_ascii=False, indent=2)}

【待评模型原始输出】
{model_output}
"""


def make_evaluation_error(error: Exception | str, *, stage: str) -> dict[str, str]:
    if isinstance(error, Exception):
        error_type = type(error).__name__
        message = str(error)
    else:
        error_type = "EvaluationError"
        message = error
    return {"stage": stage, "type": error_type, "message": message}


def call_judge(
    client: OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_completion_tokens: int,
) -> tuple[str, dict[str, Any] | None]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("Judge 返回空内容")
    usage = response.usage.model_dump() if response.usage is not None else None
    return content, usage


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    parser.add_argument("--sample-ids", type=int, nargs="+")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output-name", default="judge_results_e1_e5.jsonl")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if Path(args.experiment_id).name != args.experiment_id:
        raise ValueError("experiment-id 必须是单个安全目录名")
    if Path(args.output_name).name != args.output_name or not args.output_name.endswith(".jsonl"):
        raise ValueError("output-name 必须是安全的 JSONL 文件名")
    if args.attempts < 1 or args.attempts > 3:
        raise ValueError("attempts 必须为 1～3")
    if args.max_tokens < 1000:
        raise ValueError("max-tokens 不能小于 1000")
    load_project_env()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY；没有发起 Judge API 请求")

    experiment_dir = PROJECT_ROOT / "experiments" / args.experiment_id
    input_path = experiment_dir / "paired_outputs.jsonl"
    output_path = experiment_dir / args.output_name
    config_path = experiment_dir / (Path(args.output_name).stem + ".config.json")
    if output_path.exists() or config_path.exists():
        raise FileExistsError("Judge 产物已存在；禁止静默覆盖")

    records = load_jsonl(input_path)
    selected_ids = set(args.sample_ids) if args.sample_ids else None
    tasks: list[tuple[dict[str, Any], str]] = []
    for record in records:
        if selected_ids is not None and record["sample_id"] not in selected_ids:
            continue
        for condition in args.conditions:
            tasks.append((record, condition))
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("limit 必须为正整数")
        tasks = tasks[: args.limit]
    if not tasks:
        raise ValueError("没有待评分任务")

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    model = os.environ.get("OPENAI_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.timeout, max_retries=0)

    config = {
        "schema_version": "kb-judge-run-config-v1",
        "experiment_id": args.experiment_id,
        "input_path": str(input_path.relative_to(PROJECT_ROOT)),
        "input_sha256": sha256_file(input_path),
        "output_path": str(output_path.relative_to(PROJECT_ROOT)),
        "judge_model": model,
        "base_url": base_url,
        "prompt_path": str(PROMPT_PATH.relative_to(PROJECT_ROOT)),
        "prompt_sha256": sha256_file(PROMPT_PATH),
        "schema_path": str(SCHEMA_PATH.relative_to(PROJECT_ROOT)),
        "schema_sha256": sha256_file(SCHEMA_PATH),
        "runner_sha256": sha256_file(Path(__file__)),
        "rubric_version": RUBRIC_VERSION,
        "conditions": args.conditions,
        "sample_ids": args.sample_ids,
        "task_count": len(tasks),
        "attempts": args.attempts,
        "max_completion_tokens": args.max_tokens,
        "temperature": "omitted_for_model_compatibility",
        "status": "running",
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    results: list[dict[str, Any]] = []
    with output_path.open("x", encoding="utf-8") as output_file:
        for index, (source, condition) in enumerate(tasks, start=1):
            sample_id = source["sample_id"]
            scenario = source["input_scenario"]
            result = source["conditions"][condition]
            model_output = result.get("original_uncleaned_output") or result.get("model_output", "")
            program_checks = make_program_checks(result)
            knowledge_context_view = source.get("knowledge_context_view", "full")
            champion_ids, reference_context = build_positioned_knowledge_context(
                scenario, knowledge_context_view=knowledge_context_view
            )
            if champion_ids != source["retrieved_champion_ids"]:
                raise ValueError(f"sample_id={sample_id}: Judge 重建的英雄 ID 不一致")
            if sha256_bytes(reference_context.encode("utf-8")) != source["knowledge_context_sha256"]:
                raise ValueError(f"sample_id={sample_id}: Judge 参考知识哈希不一致")
            user_prompt = build_user_prompt(
                condition=condition,
                scenario=scenario,
                reference_context=reference_context,
                program_checks=program_checks,
                model_output=model_output,
            )
            judged: dict[str, Any] = {
                "sample_id": sample_id,
                "scenario_type": source["scenario_type"],
                "condition": condition,
                "knowledge_snapshot_id": source["knowledge_snapshot_id"],
                "knowledge_context_view": knowledge_context_view,
                "reference_context_sha256": source["knowledge_context_sha256"],
                "source_output_sha256": sha256_bytes(model_output.encode("utf-8")),
                "program_checks": program_checks,
                "judge_user_prompt_sha256": sha256_bytes(user_prompt.encode("utf-8")),
            }
            attempt_errors: list[dict[str, str]] = []
            for attempt in range(1, args.attempts + 1):
                try:
                    raw, usage = call_judge(
                        client,
                        model=model,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        max_completion_tokens=args.max_tokens,
                    )
                    payload = extract_json_object(raw)
                    judged["judge_evaluation"] = validate_and_enrich(
                        payload,
                        condition=condition,
                        program_checks=program_checks,
                        validator=validator,
                    )
                    judged["judge_raw_output"] = raw
                    judged["api_usage"] = usage
                    judged["attempt_count"] = attempt
                    break
                except Exception as error:
                    attempt_errors.append(make_evaluation_error(error, stage="judge_api_or_response"))
            if "judge_evaluation" not in judged:
                judged["evaluation_error"] = attempt_errors[-1]
                judged["attempt_errors"] = attempt_errors
            results.append(judged)
            output_file.write(json.dumps(judged, ensure_ascii=False) + "\n")
            output_file.flush()
            status = "ok" if "judge_evaluation" in judged else "error"
            print(f"[{index}/{len(tasks)}] sample_id={sample_id} {condition}: {status}", flush=True)

    config["status"] = "completed"
    config["success_count"] = sum("judge_evaluation" in item for item in results)
    config["error_count"] = sum("evaluation_error" in item for item in results)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Judge 结果：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
