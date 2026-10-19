#!/usr/bin/env python3
"""Summarize non-semantic metrics for a paired fixed-KB ablation."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from calculate_baseline_metrics import (
    detect_numerical_hallucination,
    validate_schema_integrity,
)
from project_paths import PROJECT_ROOT


CONDITIONS = ("closed_book", "fixed_kb")


def mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    context_views = {record.get("knowledge_context_view", "full") for record in records}
    if len(context_views) > 1:
        raise ValueError(f"一次汇总不能混用多个知识上下文视图：{sorted(context_views)}")
    summary: dict[str, Any] = {
        "knowledge_context_view": next(iter(context_views), None),
        "pair_count": len(records),
        "conditions": {},
        "paired": {},
        "interpretation_boundary": (
            "这些指标只评价输出协议、数值硬约束与计算成本；"
            "不能单独证明知识库改善了语义质量。"
        ),
    }
    for condition in CONDITIONS:
        valid_json = 0
        valid_schema = 0
        numerical = 0
        input_tokens: list[float] = []
        output_tokens: list[float] = []
        latencies: list[float] = []
        schema_errors: dict[str, list[str]] = {}
        for record in records:
            result = record["conditions"][condition]
            input_tokens.append(float(result["input_token_count"]))
            output_tokens.append(float(result["output_token_count"]))
            latencies.append(float(result["latency_seconds"]))
            try:
                parsed = json.loads(result["model_output"])
            except (json.JSONDecodeError, TypeError):
                continue
            valid_json += 1
            errors = validate_schema_integrity(parsed)
            if errors:
                schema_errors[str(record["sample_id"])] = errors
            else:
                valid_schema += 1
            if detect_numerical_hallucination(parsed):
                numerical += 1
        count = len(records)
        summary["conditions"][condition] = {
            "sample_count": count,
            "valid_json_count": valid_json,
            "valid_json_rate": round(valid_json / count, 4) if count else None,
            "valid_schema_count": valid_schema,
            "valid_schema_rate_over_all": round(valid_schema / count, 4) if count else None,
            "numerical_trigger_count": numerical,
            "numerical_trigger_rate_over_valid_json": (
                round(numerical / valid_json, 4) if valid_json else None
            ),
            "mean_input_tokens": mean(input_tokens),
            "mean_output_tokens": mean(output_tokens),
            "mean_latency_seconds": mean(latencies),
            "schema_errors": schema_errors,
        }
    summary["paired"] = {
        "identical_output_count": sum(
            record["conditions"]["closed_book"]["model_output"]
            == record["conditions"]["fixed_kb"]["model_output"]
            for record in records
        ),
        "mean_input_token_increase": mean([
            float(record["conditions"]["fixed_kb"]["input_token_count"])
            - float(record["conditions"]["closed_book"]["input_token_count"])
            for record in records
        ]),
        "mean_latency_increase_seconds": mean([
            float(record["conditions"]["fixed_kb"]["latency_seconds"])
            - float(record["conditions"]["closed_book"]["latency_seconds"])
            for record in records
        ]),
    }
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if Path(args.experiment_id).name != args.experiment_id:
        raise ValueError("experiment-id 必须是单个安全目录名")
    experiment_dir = PROJECT_ROOT / "experiments" / args.experiment_id
    input_path = experiment_dir / "paired_outputs.jsonl"
    output_path = experiment_dir / "automatic_metrics.json"
    if output_path.exists():
        raise FileExistsError(f"{output_path} 已存在；禁止静默覆盖")
    records = [
        json.loads(line)
        for line in input_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    summary = summarize_records(records)
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
