from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "data" / "raw" / "baseline_test_set.jsonl"
OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "clean_baseline_candidate.jsonl"
)
GAP_REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "gap_report.json"
TARGET_SIZE = 50

DDRAGON_VERSIONS_URL = (
    "https://ddragon.leagueoflegends.com/api/versions.json"
)
DDRAGON_CHAMPIONS_URL = (
    "https://ddragon.leagueoflegends.com/cdn/"
    "{version}/data/zh_CN/champion.json"
)
REQUEST_TIMEOUT = (5.0, 30.0)

ROOT_KEYS = {
    "scenario_type",
    "scenario_description",
    "draft_phase_lineup",
}
TEAM_KEYS = {"blue_team", "red_team"}
LANE_KEYS = {"top", "jungle", "mid", "bottom", "support"}
TEAM_ORDER = ("blue_team", "red_team")
LANE_ORDER = ("top", "jungle", "mid", "bottom", "support")
SCENARIO_TYPES = ("standard_meta", "extreme_comps", "off_meta")
TARGET_SCENARIO_COUNTS = {
    "standard_meta": 20,
    "extreme_comps": 15,
    "off_meta": 15,
}

# 显式映射高频俗称、旧称、本名及已确认错字。
# 只进行精确匹配，禁止模糊搜索或相似度猜测。
NICKNAME_MAP: dict[str, str] = {
    "泰坦": "深海泰坦",
    "鳄鱼": "荒漠屠夫",
    "皇子": "德玛西亚皇子",
    "卡牌": "卡牌大师",
    "男枪": "法外狂徒",
    "女警": "皮城女警",
    "日女": "曙光女神",
    "瞎子": "盲僧",
    "厄斐琉斯": "残月之肃",
    "机械先驱": "奥术先驱",
    "审判天使": "正义天使",
    "熔铁少女": "镕铁少女",
}

OFFICIAL_HEROES: set[str] = set()
seen_signatures: set[str] = set()


@dataclass(frozen=True)
class ValidationResult:
    """保存单条数据的确定性校验结果。"""

    errors: list[str]
    clean_record: dict[str, Any] | None
    correction_count: int


@dataclass(frozen=True)
class ExistingDatasetState:
    """保存已有纯净数据集的指纹、数量与类别分布。"""

    count: int
    signatures: set[str]
    scenario_counts: Counter[str]


def fetch_json(session: requests.Session, url: str) -> Any:
    """请求并强解析 JSON；网络与 HTTP 异常交给调用方处理。"""
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def load_latest_official_heroes() -> tuple[str, set[str]]:
    """从最新版 DDragon 构建官方中文英雄全称集合。"""
    with requests.Session() as session:
        session.headers.update(
            {"User-Agent": "lol-baseline-etl-validator/1.0"}
        )
        versions_payload = fetch_json(session, DDRAGON_VERSIONS_URL)

        if (
            not isinstance(versions_payload, list)
            or not versions_payload
            or not isinstance(versions_payload[0], str)
        ):
            raise ValueError("DDragon versions.json 结构无效")

        latest_version = versions_payload[0]
        champions_payload = fetch_json(
            session,
            DDRAGON_CHAMPIONS_URL.format(version=latest_version),
        )

    if not isinstance(champions_payload, Mapping):
        raise ValueError("DDragon champion.json 根节点必须是对象")

    champion_data = champions_payload.get("data")
    if not isinstance(champion_data, Mapping):
        raise ValueError("DDragon champion.json 缺少对象类型的 data 字段")

    hero_names: list[str] = []
    for champion_id, champion_info in champion_data.items():
        # Jade_ 为衍生实体，不属于当前常规英雄池。
        if isinstance(champion_id, str) and champion_id.startswith("Jade_"):
            continue

        if not isinstance(champion_info, Mapping):
            raise ValueError(f"英雄 {champion_id!r} 的数据不是对象")

        hero_name = champion_info.get("name")
        if not isinstance(hero_name, str) or not hero_name:
            raise ValueError(f"英雄 {champion_id!r} 缺少有效 name")

        hero_names.append(hero_name)

    duplicates = sorted(
        name for name, count in Counter(hero_names).items() if count > 1
    )
    if duplicates:
        raise ValueError(
            "DDragon 常规英雄存在重复中文全称："
            + ", ".join(duplicates)
        )

    official_heroes = set(hero_names)
    if not official_heroes:
        raise ValueError("DDragon 返回的官方英雄集合为空")

    return latest_version, official_heroes


def validate_nickname_map() -> None:
    """确保每一个静态映射目标都是当前官方中文全称。"""
    invalid_targets = sorted(set(NICKNAME_MAP.values()) - OFFICIAL_HEROES)
    if invalid_targets:
        raise ValueError(
            "NICKNAME_MAP 包含非官方映射目标："
            + ", ".join(invalid_targets)
        )


def compare_exact_keys(
    value: Mapping[str, Any],
    expected_keys: set[str],
    location: str,
) -> list[str]:
    """校验对象的键集合是否与 Schema 完全相等。"""
    actual_keys = set(value.keys())
    missing_keys = expected_keys - actual_keys
    extra_keys = actual_keys - expected_keys
    errors: list[str] = []

    if missing_keys:
        errors.append(
            f"{location} 缺少键：{', '.join(sorted(missing_keys))}"
        )
    if extra_keys:
        errors.append(
            f"{location} 含有非法键：{', '.join(sorted(extra_keys))}"
        )

    return errors


def validate_and_clean_record(record: Any) -> ValidationResult:
    """投影根节点，并执行名称修正及全部单局强断言。"""
    if not isinstance(record, dict):
        return ValidationResult(
            errors=["JSON 根节点必须是字典对象"],
            clean_record=None,
            correction_count=0,
        )

    errors: list[str] = []
    correction_count = 0

    # 根节点额外字段不会进入 clean_record；
    # 缺失核心字段则直接失败。
    missing_root_keys = ROOT_KEYS - set(record.keys())
    if missing_root_keys:
        errors.append(
            "根节点缺少键：" + ", ".join(sorted(missing_root_keys))
        )

    scenario_type = record.get("scenario_type")
    if scenario_type not in SCENARIO_TYPES:
        errors.append(
            "scenario_type 必须是：" + ", ".join(SCENARIO_TYPES)
        )

    scenario_description = record.get("scenario_description")
    if (
        not isinstance(scenario_description, str)
        or not scenario_description.strip()
    ):
        errors.append("scenario_description 必须是非空字符串")

    lineup = record.get("draft_phase_lineup")
    if not isinstance(lineup, Mapping):
        errors.append("draft_phase_lineup 必须是对象")
        return ValidationResult(errors, None, correction_count)

    errors.extend(
        compare_exact_keys(lineup, TEAM_KEYS, "draft_phase_lineup")
    )

    heroes: list[str] = []
    clean_lineup: dict[str, dict[str, str]] = {}

    for team_name in TEAM_ORDER:
        team = lineup.get(team_name)
        location = f"draft_phase_lineup.{team_name}"

        if not isinstance(team, Mapping):
            errors.append(f"{location} 必须是对象")
            continue

        # adc、players、hero 等任意异构键都会在这里被强拦截。
        errors.extend(compare_exact_keys(team, LANE_KEYS, location))
        if set(team.keys()) != LANE_KEYS:
            continue

        clean_team: dict[str, str] = {}
        for lane in LANE_ORDER:
            hero_name = team[lane]

            # 禁止嵌套字典；英雄必须直接表现为非空字符串。
            if not isinstance(hero_name, str) or not hero_name:
                errors.append(f"{location}.{lane} 必须是英雄全称字符串")
                continue

            normalized_name = NICKNAME_MAP.get(hero_name, hero_name)
            if normalized_name != hero_name:
                correction_count += 1

            heroes.append(normalized_name)
            clean_team[lane] = normalized_name

        clean_lineup[team_name] = clean_team

    if len(heroes) == 10:
        hero_counts = Counter(heroes)
        duplicate_heroes = sorted(
            hero for hero, count in hero_counts.items() if count > 1
        )
        if len(set(heroes)) != 10:
            errors.append("英雄重复：" + ", ".join(duplicate_heroes))

        oov_heroes = sorted(set(heroes) - OFFICIAL_HEROES)
        if oov_heroes:
            errors.append(
                "OOV/非官方中文全称：" + ", ".join(oov_heroes)
            )

    if errors:
        return ValidationResult(errors, None, correction_count)

    # 只保留三个核心根节点，确定性剥离任何冗余字段。
    clean_record = {
        "scenario_type": scenario_type,
        "scenario_description": scenario_description.strip(),
        "draft_phase_lineup": clean_lineup,
    }
    return ValidationResult([], clean_record, correction_count)


def build_lineup_signature(clean_record: Mapping[str, Any]) -> str:
    """按固定队伍和分路顺序生成唯一阵容字符串签名。"""
    lineup = clean_record["draft_phase_lineup"]
    ordered_heroes = [
        lineup[team_name][lane]
        for team_name in TEAM_ORDER
        for lane in LANE_ORDER
    ]
    return json.dumps(
        ordered_heroes,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def load_existing_clean_dataset(path: Path) -> ExistingDatasetState:
    """严格检查已有输出，避免追加运行产生跨批次重复。"""
    if not path.exists():
        return ExistingDatasetState(0, set(), Counter())

    signatures: set[str] = set()
    scenario_counts: Counter[str] = Counter()
    count = 0

    with path.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, start=1):
            if not raw_line.strip():
                continue

            try:
                record: Any = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"已有纯净文件第 {line_number} 行 JSON 无效："
                    f"{error.msg}"
                ) from error

            result = validate_and_clean_record(record)
            if result.errors or result.clean_record is None:
                details = "；".join(result.errors)
                raise ValueError(
                    f"已有纯净文件第 {line_number} 行不再合法：{details}"
                )
            if result.correction_count:
                raise ValueError(
                    f"已有纯净文件第 {line_number} 行仍含未固化别名"
                )

            signature = build_lineup_signature(result.clean_record)
            if signature in signatures:
                raise ValueError(
                    f"已有纯净文件第 {line_number} 行阵容全局重复"
                )

            signatures.add(signature)
            scenario_counts[result.clean_record["scenario_type"]] += 1
            count += 1

    return ExistingDatasetState(count, signatures, scenario_counts)


def append_clean_records(
    output_path: Path,
    records: list[dict[str, Any]],
) -> None:
    """以 JSON Lines 形式追加纯净记录。"""
    with output_path.open("a", encoding="utf-8") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_distribution(
    scenario_counts: Counter[str],
    valid_count: int,
) -> None:
    """输出最终存活数据的场景频次和比例。"""
    print("\n===== 最终 scenario_type 分布 =====")
    for scenario_type in SCENARIO_TYPES:
        count = scenario_counts[scenario_type]
        ratio = count / valid_count if valid_count else 0.0
        print(f"{scenario_type}: {count}（{ratio:.2%}）")


def calculate_gap_details(
    scenario_counts: Counter[str],
    total_deficit: int,
) -> dict[str, int]:
    """将总缺口确定性分配到当前完成度最低的场景类别。"""
    details = {scenario_type: 0 for scenario_type in SCENARIO_TYPES}

    for _ in range(total_deficit):
        scenario_type = min(
            SCENARIO_TYPES,
            key=lambda item: (
                (
                    scenario_counts[item] + details[item]
                ) / TARGET_SCENARIO_COUNTS[item],
                SCENARIO_TYPES.index(item),
            ),
        )
        details[scenario_type] += 1

    return details


def write_gap_report(
    path: Path,
    valid_count: int,
    total_deficit: int,
    details: Mapping[str, int],
) -> None:
    """原子写入供生成器读取的缺口状态文件。"""
    report = {
        "target_size": TARGET_SIZE,
        "valid_count": valid_count,
        "total_deficit": total_deficit,
        "details": dict(details),
    }
    temporary_path = path.with_suffix(path.suffix + ".tmp")

    try:
        with temporary_path.open("w", encoding="utf-8") as output_file:
            json.dump(report, output_file, ensure_ascii=False, indent=2)
            output_file.write("\n")
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    """执行解析、修正、单局断言、全局去重和追加落盘。"""
    global OFFICIAL_HEROES, seen_signatures

    try:
        ddragon_version, OFFICIAL_HEROES = load_latest_official_heroes()
        validate_nickname_map()
        existing_state = load_existing_clean_dataset(OUTPUT_PATH)
    except (
        requests.RequestException,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ) as error:
        print(f"ETL 初始化失败：{error}")
        return 2

    seen_signatures = set(existing_state.signatures)
    final_scenario_counts = Counter(existing_state.scenario_counts)

    print(
        f"DDragon 版本：{ddragon_version}；"
        f"官方中文英雄全称：{len(OFFICIAL_HEROES)}。"
    )
    print(f"已有纯净数据：{existing_state.count} 条。")

    if not INPUT_PATH.is_file():
        print(f"未找到输入文件：{INPUT_PATH.resolve()}")
        return 2

    total_read = 0
    parse_rejected_count = 0
    logic_rejected_count = 0
    global_duplicate_count = 0
    correction_count = 0
    new_clean_records: list[dict[str, Any]] = []

    with INPUT_PATH.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, start=1):
            if not raw_line.strip():
                continue

            total_read += 1
            try:
                record: Any = json.loads(raw_line)
            except json.JSONDecodeError as error:
                parse_rejected_count += 1
                print(
                    f"[第 {line_number} 行] 抛弃: JSON 解析失败："
                    f"{error.msg}（列 {error.colno}）"
                )
                continue

            result = validate_and_clean_record(record)
            correction_count += result.correction_count

            if result.errors or result.clean_record is None:
                logic_rejected_count += 1
                print(
                    f"[第 {line_number} 行] 抛弃: "
                    + "；".join(result.errors)
                )
                continue

            signature = build_lineup_signature(result.clean_record)
            if signature in seen_signatures:
                global_duplicate_count += 1
                print(f"[第 {line_number} 行] 抛弃: 阵容全局重复")
                continue

            seen_signatures.add(signature)
            new_clean_records.append(result.clean_record)
            final_scenario_counts[result.clean_record["scenario_type"]] += 1

    try:
        append_clean_records(OUTPUT_PATH, new_clean_records)
    except OSError as error:
        print(f"纯净数据追加写入失败：{error}")
        return 2

    valid_count = existing_state.count + len(new_clean_records)
    target_deficit = max(0, TARGET_SIZE - valid_count)
    gap_details = calculate_gap_details(
        final_scenario_counts,
        target_deficit,
    )

    try:
        write_gap_report(
            GAP_REPORT_PATH,
            valid_count,
            target_deficit,
            gap_details,
        )
    except OSError as error:
        print(f"缺口状态文件写入失败：{error}")
        return 2

    print("\n===== ETL 度量 =====")
    print(f"总读取量：{total_read}")
    print(f"映射修正触发次数：{correction_count}")
    print(f"JSON 解析异常抛弃量：{parse_rejected_count}")
    print(f"逻辑异常抛弃量：{logic_rejected_count}")
    print(f"全局重复抛弃量：{global_duplicate_count}")
    print(f"本次新增有效量：{len(new_clean_records)}")
    print(f"最终有效数据量：{valid_count}")
    print(f"目标缺口：{target_deficit}")

    if target_deficit:
        print(f"还需定向生成 {target_deficit} 条数据。")
    else:
        print("目标数据量已满足。")

    print_distribution(final_scenario_counts, valid_count)
    print(f"纯净数据文件：{OUTPUT_PATH.resolve()}")
    print(f"缺口状态文件：{GAP_REPORT_PATH.resolve()}")
    print("提示：阵容战术语义仍需由领域专家人工审查。")

    rejected_count = (
        parse_rejected_count
        + logic_rejected_count
        + global_duplicate_count
    )
    return 0 if rejected_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
