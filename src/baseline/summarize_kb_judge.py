#!/usr/bin/env python3
"""Summarize E1-E5 Judge results for paired KB experiments."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from project_paths import PROJECT_ROOT
from run_kb_judge import CONDITIONS, DIMENSIONS, KB_CRITERIA, load_jsonl


def rounded_mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    context_views = {record.get("knowledge_context_view", "full") for record in records}
    if len(context_views) > 1:
        raise ValueError(f"一次汇总不能混用多个知识上下文视图：{sorted(context_views)}")
    summary: dict[str, Any] = {
        "knowledge_context_view": next(iter(context_views), None),
        "schema_version": "kb-judge-summary-v1",
        "record_count": len(records),
        "conditions": {},
        "paired_semantic_comparison": {},
    }
    successful_by_pair: dict[tuple[int, str], dict[str, Any]] = {}
    for condition in CONDITIONS:
        condition_records = [item for item in records if item["condition"] == condition]
        successful = [item for item in condition_records if "judge_evaluation" in item]
        errors = [item for item in condition_records if "evaluation_error" in item]
        dimension_values: dict[str, list[float]] = {dimension: [] for dimension in DIMENSIONS}
        semantic_values: list[float] = []
        kb_values: list[float] = []
        criterion_distribution: dict[str, Counter[str]] = defaultdict(Counter)
        cross_entity_count = 0
        unsupported_claim_count = 0
        usage_totals: Counter[str] = Counter()
        for item in successful:
            evaluation = item["judge_evaluation"]
            successful_by_pair[(item["sample_id"], condition)] = evaluation
            for dimension in DIMENSIONS:
                dimension_values[dimension].append(float(evaluation["dimension_scores"][dimension]))
            semantic_values.append(float(evaluation["semantic_score"]))
            if evaluation["knowledge_faithfulness_score"] is not None:
                kb_values.append(float(evaluation["knowledge_faithfulness_score"]))
            for criterion in evaluation["criterion_results"] + evaluation["kb_criterion_results"]:
                criterion_distribution[criterion["criterion_id"]][str(criterion["score"])] += 1
            cross_entity_count += bool(evaluation["cross_entity_confusion"])
            unsupported_claim_count += len(evaluation["unsupported_mechanism_claims"])
            usage = item.get("api_usage") or {}
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    usage_totals[key] += value
        summary["conditions"][condition] = {
            "requested_count": len(condition_records),
            "success_count": len(successful),
            "error_count": len(errors),
            "dimension_means": {
                dimension: rounded_mean(values)
                for dimension, values in dimension_values.items()
            },
            "semantic_score_mean": rounded_mean(semantic_values),
            "knowledge_faithfulness_mean": rounded_mean(kb_values),
            "cross_entity_confusion_count": cross_entity_count,
            "unsupported_mechanism_claim_count": unsupported_claim_count,
            "criterion_distribution": {
                criterion_id: dict(counts)
                for criterion_id, counts in sorted(criterion_distribution.items())
            },
            "api_usage_totals": dict(usage_totals),
            "errors": [
                {
                    "sample_id": item["sample_id"],
                    "evaluation_error": item["evaluation_error"],
                }
                for item in errors
            ],
        }

    winners = Counter()
    pairs: list[dict[str, Any]] = []
    sample_ids = sorted({item["sample_id"] for item in records})
    for sample_id in sample_ids:
        closed = successful_by_pair.get((sample_id, "closed_book"))
        fixed = successful_by_pair.get((sample_id, "fixed_kb"))
        if closed is None or fixed is None:
            continue
        closed_score = float(closed["semantic_score"])
        fixed_score = float(fixed["semantic_score"])
        if fixed_score > closed_score:
            winner = "fixed_kb"
        elif closed_score > fixed_score:
            winner = "closed_book"
        else:
            winner = "tie"
        winners[winner] += 1
        pairs.append({
            "sample_id": sample_id,
            "closed_book_semantic_score": closed_score,
            "fixed_kb_semantic_score": fixed_score,
            "delta_fixed_minus_closed": round(fixed_score - closed_score, 2),
            "winner": winner,
        })
    summary["paired_semantic_comparison"] = {
        "comparable_pair_count": len(pairs),
        "winner_counts": dict(winners),
        "mean_delta_fixed_minus_closed": rounded_mean([
            item["delta_fixed_minus_closed"] for item in pairs
        ]),
        "pairs": pairs,
        "interpretation": (
            "按 E2 20%、E3 25%、E4 25%、E5 30% 的辅助语义综合分比较；"
            "E1 单独报告，不进入该分数。"
        ),
    }
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--input-name", default="judge_results_e1_e5.jsonl")
    parser.add_argument("--output-name", default="judge_summary_e1_e5.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for value in (args.experiment_id, args.input_name, args.output_name):
        if Path(value).name != value:
            raise ValueError("路径参数必须是单个安全名称")
    experiment_dir = PROJECT_ROOT / "experiments" / args.experiment_id
    input_path = experiment_dir / args.input_name
    output_path = experiment_dir / args.output_name
    if output_path.exists():
        raise FileExistsError(f"{output_path} 已存在；禁止静默覆盖")
    result = summarize(load_jsonl(input_path))
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
