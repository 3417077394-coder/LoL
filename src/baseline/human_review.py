import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from project_paths import (
    HUMAN_REVIEW_FILE,
    MODEL_OUTPUT_FILE,
    TEST_SET_FILE,
)


DEFAULT_BASELINE = MODEL_OUTPUT_FILE
DEFAULT_TEST_SET = TEST_SET_FILE
DEFAULT_OUTPUT = HUMAN_REVIEW_FILE


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"{path.name} 第 {line_number} 行不是合法 JSON：{error.msg}"
                ) from error
            if not isinstance(record, dict):
                raise TypeError(f"{path.name} 第 {line_number} 行必须是对象")
            records.append(record)
    return records


def select_stratified(
    records: list[dict[str, Any]],
    sample_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    """按 scenario_type 轮询抽样，兼顾类别平衡与可复现性。"""
    if sample_size <= 0:
        raise ValueError("sample_size 必须大于 0")
    if sample_size > len(records):
        raise ValueError(
            f"sample_size={sample_size} 超过可用记录数 {len(records)}"
        )

    rng = random.Random(seed)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get("scenario_type", "unknown"))].append(record)
    for group in groups.values():
        rng.shuffle(group)

    selected: list[dict[str, Any]] = []
    group_names = sorted(groups)
    while len(selected) < sample_size:
        made_progress = False
        for group_name in group_names:
            group = groups[group_name]
            if group and len(selected) < sample_size:
                selected.append(group.pop())
                made_progress = True
        if not made_progress:
            break

    return sorted(selected, key=lambda item: item["sample_id"])


def prepare_review(args: argparse.Namespace) -> None:
    if args.output.exists() and not args.overwrite:
        raise FileExistsError(
            f"{args.output} 已存在；如需覆盖请显式传入 --overwrite"
        )

    baseline_records = load_jsonl(args.baseline)
    scenarios = {
        sample_id: scenario
        for sample_id, scenario in enumerate(
            load_jsonl(args.test_set),
            start=1,
        )
    }

    joined: list[dict[str, Any]] = []
    for baseline in baseline_records:
        sample_id = baseline.get("sample_id")
        if (
            not isinstance(sample_id, int)
            or isinstance(sample_id, bool)
            or sample_id not in scenarios
        ):
            continue

        raw_output = baseline.get("y_base_raw_output")
        try:
            model_output: Any = json.loads(raw_output)
        except (json.JSONDecodeError, TypeError):
            model_output = raw_output

        scenario = scenarios[sample_id]
        joined.append(
            {
                "sample_id": sample_id,
                "scenario_type": scenario.get("scenario_type", "unknown"),
                "input_scenario": scenario,
                "model_output": model_output,
                "human_evaluation": {
                    "reviewer": "",
                    "factual_score": None,
                    "consistency_score": None,
                    "critical_errors": [],
                    "notes": "",
                    "approved": None,
                },
            }
        )

    selected = select_stratified(joined, args.sample_size, args.seed)
    with args.output.open("w", encoding="utf-8") as output_file:
        for record in selected:
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(
        f"已生成 {len(selected)} 条分层人工盲审样本：{args.output}\n"
        "请填写 human_evaluation；该文件不包含 LLM judge 分数，以减少锚定偏差。"
    )


def summarize_review(args: argparse.Namespace) -> None:
    records = load_jsonl(args.input)
    reviewed: list[dict[str, Any]] = []
    invalid_count = 0

    for record in records:
        evaluation = record.get("human_evaluation")
        if not isinstance(evaluation, dict):
            invalid_count += 1
            continue

        factual = evaluation.get("factual_score")
        consistency = evaluation.get("consistency_score")
        approved = evaluation.get("approved")
        scores_valid = all(
            isinstance(score, int)
            and not isinstance(score, bool)
            and 0 <= score <= 5
            for score in (factual, consistency)
        )
        if scores_valid and isinstance(approved, bool):
            reviewed.append(evaluation)
        else:
            invalid_count += 1

    print("=" * 40)
    print("人工抽查汇总")
    print("=" * 40)
    print(f"总记录数: {len(records)}")
    print(f"已完成记录数: {len(reviewed)}")
    print(f"未完成或格式错误: {invalid_count}")

    if reviewed:
        count = len(reviewed)
        print(
            "事实与机制准确度平均分: "
            f"{sum(item['factual_score'] for item in reviewed) / count:.2f} / 5.00"
        )
        print(
            "战术因果自洽性平均分: "
            f"{sum(item['consistency_score'] for item in reviewed) / count:.2f} / 5.00"
        )
        print(
            "人工通过率: "
            f"{sum(item['approved'] for item in reviewed) / count * 100:.2f}%"
        )
    print("=" * 40)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Baseline 人工抽查工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="生成分层盲审集")
    prepare.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    prepare.add_argument("--test-set", type=Path, default=DEFAULT_TEST_SET)
    prepare.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    prepare.add_argument("--sample-size", type=int, default=12)
    prepare.add_argument("--seed", type=int, default=42)
    prepare.add_argument("--overwrite", action="store_true")
    prepare.set_defaults(func=prepare_review)

    summarize = subparsers.add_parser("summarize", help="汇总已填写的人工评分")
    summarize.add_argument("--input", type=Path, default=DEFAULT_OUTPUT)
    summarize.set_defaults(func=summarize_review)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
