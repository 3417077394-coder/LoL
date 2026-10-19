#!/usr/bin/env python3
"""Generate fixed-KB development outputs with an OpenAI-compatible API model."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from calculate_baseline_metrics import (
    detect_numerical_hallucination,
    validate_schema_integrity,
)
from project_paths import PROJECT_ROOT, TEST_SET_FILE
from run_baseline_eval import extract_json_payload
from run_kb_ablation import (
    COMPACT_CONTEXT_VIEW_ID,
    CONTEXT_VIEW_MANIFESTS,
    DEFAULT_SAMPLE_IDS,
    PROMPT_TEMPLATE_VERSIONS,
    RULESET_ID,
    SHARED_SYSTEM_PROMPT,
    SNAPSHOT_ID,
    SNAPSHOT_ROOT,
    build_condition_prompt,
    load_selected_rows,
    sha256_bytes,
    sha256_file,
)
from run_kb_judge import DEFAULT_BASE_URL, load_project_env


DEFAULT_API_MODEL = "gpt-5.6-sol"
CONDITION = "fixed_kb"


def call_generator(
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
        raise ValueError("生成 API 返回空内容")
    usage = response.usage.model_dump() if response.usage is not None else None
    return content, usage


def make_generation_error(error: Exception) -> dict[str, str]:
    return {
        "stage": "generation_api_or_response",
        "type": type(error).__name__,
        "message": str(error),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--sample-ids", type=int, nargs="+", default=list(DEFAULT_SAMPLE_IDS)
    )
    parser.add_argument("--model", default=DEFAULT_API_MODEL)
    parser.add_argument("--max-tokens", type=int, default=6000)
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument(
        "--knowledge-context-view",
        choices=tuple(CONTEXT_VIEW_MANIFESTS),
        default=COMPACT_CONTEXT_VIEW_ID,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if (
        Path(args.experiment_id).name != args.experiment_id
        or args.experiment_id in {"", ".", ".."}
    ):
        raise ValueError("experiment-id 必须是单个安全目录名")
    if not args.model.strip():
        raise ValueError("model 不能为空")
    if args.max_tokens < 1000:
        raise ValueError("max-tokens 不能小于 1000")
    if args.attempts < 1 or args.attempts > 3:
        raise ValueError("attempts 必须为 1～3")

    load_project_env()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("未设置 OPENAI_API_KEY；没有发起生成 API 请求")
    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)

    selected_rows = load_selected_rows(args.sample_ids)
    prepared: list[tuple[int, dict[str, Any], list[str], str, str]] = []
    for sample_id, row in selected_rows:
        champion_ids, knowledge_context, prompt = build_condition_prompt(
            row,
            CONDITION,
            knowledge_context_view=args.knowledge_context_view,
        )
        prepared.append((sample_id, row, champion_ids, knowledge_context, prompt))

    experiment_dir = PROJECT_ROOT / "experiments" / args.experiment_id
    output_path = experiment_dir / "model_outputs.jsonl"
    config_path = experiment_dir / "config.json"
    if experiment_dir.exists() and any(experiment_dir.iterdir()):
        raise FileExistsError(f"{experiment_dir} 已包含产物；禁止静默覆盖")
    experiment_dir.mkdir(parents=True, exist_ok=True)

    config: dict[str, Any] = {
        "schema_version": "kb-api-generation-config-v1",
        "experiment_id": args.experiment_id,
        "status": "running",
        "purpose": "强模型知识使用容量对照；方向性开发验证，不是正式 baseline",
        "generation_model": args.model,
        "base_url": base_url,
        "dataset_path": str(TEST_SET_FILE.relative_to(PROJECT_ROOT)),
        "dataset_sha256": sha256_file(TEST_SET_FILE),
        "sample_ids": args.sample_ids,
        "condition": CONDITION,
        "ruleset_id": RULESET_ID,
        "knowledge_snapshot_id": SNAPSHOT_ID,
        "knowledge_context_view": args.knowledge_context_view,
        "prompt_template_version": PROMPT_TEMPLATE_VERSIONS[
            args.knowledge_context_view
        ],
        "knowledge_manifest_sha256": sha256_file(SNAPSHOT_ROOT / "manifest.json"),
        "knowledge_context_view_manifest_sha256": sha256_file(
            CONTEXT_VIEW_MANIFESTS[args.knowledge_context_view]
        ),
        "system_prompt": SHARED_SYSTEM_PROMPT,
        "system_prompt_sha256": sha256_bytes(SHARED_SYSTEM_PROMPT.encode("utf-8")),
        "runner_sha256": sha256_file(Path(__file__)),
        "api_inference": {
            "max_completion_tokens": args.max_tokens,
            "temperature": "omitted_for_model_compatibility",
            "repetition_penalty": "unsupported_by_api",
            "attempts": args.attempts,
            "timeout_seconds": args.timeout,
        },
    }
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=args.timeout,
        max_retries=0,
    )
    results: list[dict[str, Any]] = []
    with output_path.open("x", encoding="utf-8") as output_file:
        for index, (
            sample_id,
            row,
            champion_ids,
            knowledge_context,
            prompt,
        ) in enumerate(prepared, start=1):
            result: dict[str, Any] = {
                "sample_id": sample_id,
                "scenario_type": row.get("scenario_type", "unknown"),
                "input_scenario": row,
                "retrieved_champion_ids": champion_ids,
                "knowledge_snapshot_id": SNAPSHOT_ID,
                "knowledge_context_view": args.knowledge_context_view,
                "knowledge_context_sha256": sha256_bytes(
                    knowledge_context.encode("utf-8")
                ),
                "condition": CONDITION,
                "input_prompt": prompt,
                "input_prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                "generation_model": args.model,
            }
            attempt_errors: list[dict[str, str]] = []
            for attempt in range(1, args.attempts + 1):
                started = time.perf_counter()
                try:
                    raw_response, usage = call_generator(
                        client,
                        model=args.model,
                        system_prompt=SHARED_SYSTEM_PROMPT,
                        user_prompt=prompt,
                        max_completion_tokens=args.max_tokens,
                    )
                    latency_seconds = time.perf_counter() - started
                    cleaned_response = extract_json_payload(raw_response)
                    try:
                        parsed = json.loads(cleaned_response)
                    except json.JSONDecodeError:
                        parsed = None
                    schema_errors = (
                        validate_schema_integrity(parsed) if parsed is not None else []
                    )
                    result.update(
                        {
                            "attempt_count": attempt,
                            "latency_seconds": round(latency_seconds, 3),
                            "api_usage": usage,
                            "is_valid_json": parsed is not None,
                            "is_valid_schema": parsed is not None and not schema_errors,
                            "schema_errors": schema_errors,
                            "numerical_trigger": (
                                detect_numerical_hallucination(parsed)
                                if parsed is not None
                                else False
                            ),
                            "model_output": cleaned_response,
                            "original_uncleaned_output": (
                                raw_response if parsed is None else None
                            ),
                        }
                    )
                    break
                except Exception as error:
                    attempt_errors.append(make_generation_error(error))
            if "model_output" not in result:
                result["generation_error"] = attempt_errors[-1]
                result["attempt_errors"] = attempt_errors
            results.append(result)
            output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            output_file.flush()
            status = "ok" if "model_output" in result else "error"
            print(
                f"[{index}/{len(prepared)}] sample_id={sample_id} {CONDITION}: {status}",
                flush=True,
            )

    usage_totals: dict[str, int] = {}
    for result in results:
        usage = result.get("api_usage")
        if not isinstance(usage, dict):
            continue
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                usage_totals[key] = usage_totals.get(key, 0) + value
    config.update(
        {
            "status": "completed",
            "success_count": sum("model_output" in item for item in results),
            "error_count": sum("generation_error" in item for item in results),
            "api_usage_totals": usage_totals,
            "output_sha256": sha256_file(output_path),
        }
    )
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"API 生成实验完成：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

