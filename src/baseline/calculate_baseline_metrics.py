import json
import re
from typing import Any

from project_paths import MODEL_OUTPUT_FILE


INPUT_FILE = MODEL_OUTPUT_FILE

# 递归描述完整输出契约；叶子 None 表示必须是非空字符串。
EXPECTED_SCHEMA: dict[str, Any] = {
    "cot_reasoning": None,
    "global_analysis": {
        "blue_team_win_condition": None,
        "red_team_win_condition": None,
        "power_spike_comparison": None,
    },
    "positional_strategies": {
        "top_lane": {
            "matchup_analysis": None,
            "blue_top_strategy": None,
            "red_top_strategy": None,
        },
        "jungle": {
            "matchup_analysis": None,
            "blue_jungle_strategy": None,
            "red_jungle_strategy": None,
        },
        "mid_lane": {
            "matchup_analysis": None,
            "blue_mid_strategy": None,
            "red_mid_strategy": None,
        },
        "bottom_lane": {
            "matchup_analysis": None,
            "blue_bottom_strategy": None,
            "red_bottom_strategy": None,
        },
    },
}


def validate_schema_integrity(
    data: Any,
    expected: dict[str, Any] = EXPECTED_SCHEMA,
    path: str = "$",
) -> list[str]:
    """递归校验完整键集、对象类型以及所有文本叶子。"""
    if not isinstance(data, dict):
        return [f"{path} 必须是对象"]

    errors: list[str] = []
    actual_keys = set(data)
    expected_keys = set(expected)

    for missing_key in sorted(expected_keys - actual_keys):
        errors.append(f"{path}.{missing_key} 缺失")
    for extra_key in sorted(actual_keys - expected_keys):
        errors.append(f"{path}.{extra_key} 是未声明字段")

    for key in sorted(expected_keys & actual_keys):
        child_path = f"{path}.{key}"
        child_schema = expected[key]
        value = data[key]

        if child_schema is None:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{child_path} 必须是非空字符串")
        else:
            errors.extend(
                validate_schema_integrity(value, child_schema, child_path)
            )

    return errors


def check_schema_integrity(data: Any) -> bool:
    """保留原布尔接口，同时使用完整递归 Schema 校验。"""
    return not validate_schema_integrity(data)


def detect_numerical_hallucination(data: Any) -> bool:
    """只扫描输出值中的阿拉伯数字，不让 JSON 键名干扰统计。"""
    if isinstance(data, dict):
        return any(
            detect_numerical_hallucination(value)
            for value in data.values()
        )
    if isinstance(data, list):
        return any(detect_numerical_hallucination(value) for value in data)
    if isinstance(data, str):
        return bool(re.search(r"\d+", data))
    return isinstance(data, (int, float)) and not isinstance(data, bool)


def main() -> None:
    total_samples = 0
    valid_json_count = 0
    schema_intact_count = 0
    numerical_hallucination_count = 0
    schema_error_samples: list[tuple[Any, list[str]]] = []

    with INPUT_FILE.open("r", encoding="utf-8") as input_file:
        for line_number, line in enumerate(input_file, start=1):
            if not line.strip():
                continue
            total_samples += 1

            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            raw_output = record.get("y_base_raw_output")
            if not isinstance(raw_output, str):
                continue

            try:
                parsed_data = json.loads(raw_output)
            except json.JSONDecodeError:
                continue

            valid_json_count += 1
            schema_errors = validate_schema_integrity(parsed_data)
            if schema_errors:
                sample_id = record.get("sample_id", f"line:{line_number}")
                schema_error_samples.append((sample_id, schema_errors))
            else:
                schema_intact_count += 1

            if detect_numerical_hallucination(parsed_data):
                numerical_hallucination_count += 1

    print("=" * 40)
    print("零样本基线评估 (Zero-shot Baseline Metrics)")
    print("=" * 40)
    print(f"总测试样本数: {total_samples}")
    if total_samples == 0:
        return

    json_rate = valid_json_count / total_samples * 100
    print(
        f"[1] JSON 格式合法率: {json_rate:.2f}% "
        f"({valid_json_count}/{total_samples})"
    )

    if valid_json_count > 0:
        schema_rate = schema_intact_count / valid_json_count * 100
        print(
            f"[2] 完整 Schema 合法率: {schema_rate:.2f}% "
            f"({schema_intact_count}/{valid_json_count})"
        )

        hallucination_rate = (
            numerical_hallucination_count / valid_json_count * 100
        )
        print(
            f"[3] 数值幻觉触发率: {hallucination_rate:.2f}% "
            f"({numerical_hallucination_count}/{valid_json_count})"
        )

    if schema_error_samples:
        print(f"[诊断] Schema 不合法样本数: {len(schema_error_samples)}")
        for sample_id, errors in schema_error_samples[:5]:
            print(f"  - sample_id={sample_id}: {'；'.join(errors)}")
        if len(schema_error_samples) > 5:
            print("  - 其余错误已省略")

    print("=" * 40)


if __name__ == "__main__":
    main()
