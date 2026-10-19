from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests


INPUT_PATH = Path("baseline_test_set.jsonl")
OUTPUT_PATH = Path("clean_baseline_test_set.jsonl")
TARGET_COUNT = 50

DDRAGON_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
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
LINEUP_KEYS = {"blue_team", "red_team"}
LANE_KEYS = {"top", "jungle", "mid", "bottom", "support"}
SCENARIO_TYPES = {"standard_meta", "extreme_comps", "off_meta"}

# 高频俗称、旧称和已确认错字到当前 DDragon
# 官方全称的显式映射。
# 这里只做精确键匹配，不进行模糊搜索或相似度猜测。
NICKNAME_MAP: dict[str, str] = {
    "泰坦": "深海泰坦",
    "鳄鱼": "荒漠屠夫",
    "皇子": "德玛西亚皇子",
    "卡牌": "卡牌大师",
    "男枪": "法外狂徒",
    "女警": "皮城女警",
    "日女": "曙光女神",
    "瞎子": "盲僧",
    # 当前批次中已确定的本名、旧称和错字。
    "厄斐琉斯": "残月之肃",
    "机械先驱": "奥术先驱",
    "审判天使": "正义天使",
    "熔铁少女": "镕铁少女",
}

# 启动时从最新版 DDragon 动态同步，
# 仅保留当前常规英雄的官方中文全称。
OFFICIAL_HEROES: set[str] = set()

LineupSignature = tuple[str, ...]


@dataclass(frozen=True)
class ValidationResult:
    """单条数据的清洗结果与可观测度量。"""

    errors: list[str]
    clean_record: dict[str, Any] | None
    correction_count: int
    has_logic_error: bool


def fetch_json(session: requests.Session, url: str) -> Any:
    """请求 JSON，并将网络、HTTP 与解析错误交给调用方处理。"""
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def load_latest_official_heroes() -> tuple[str, set[str]]:
    """从最新版 DDragon 加载常规英雄的官方中文全称集合。"""
    headers = {"User-Agent": "lol-baseline-validator/1.0"}
    with requests.Session() as session:
        session.headers.update(headers)

        versions_payload = fetch_json(session, DDRAGON_VERSIONS_URL)
        if (
            not isinstance(versions_payload, list)
            or not versions_payload
            or not isinstance(versions_payload[0], str)
        ):
            raise ValueError("DDragon versions.json 结构无效")

        latest_version = versions_payload[0]
        champions_url = DDRAGON_CHAMPIONS_URL.format(
            version=latest_version
        )
        champions_payload = fetch_json(session, champions_url)

    if not isinstance(champions_payload, Mapping):
        raise ValueError("DDragon champion.json 根节点必须是对象")

    champion_data = champions_payload.get("data")
    if not isinstance(champion_data, Mapping):
        raise ValueError("DDragon champion.json 缺少对象类型的 data 字段")

    hero_names: list[str] = []
    for champion_id, champion_info in champion_data.items():
        # Jade_ 是衍生实体，不属于当前常规英雄池。
        if isinstance(champion_id, str) and champion_id.startswith("Jade_"):
            continue

        if not isinstance(champion_info, Mapping):
            raise ValueError(f"英雄 {champion_id!r} 的数据不是对象")

        hero_name = champion_info.get("name")
        if not isinstance(hero_name, str) or not hero_name:
            raise ValueError(f"英雄 {champion_id!r} 缺少有效 name")

        hero_names.append(hero_name)

    duplicate_names = sorted(
        name for name, count in Counter(hero_names).items() if count > 1
    )
    if duplicate_names:
        raise ValueError(
            "DDragon 常规英雄存在重复中文全称："
            + ", ".join(duplicate_names)
        )

    official_heroes = set(hero_names)
    if not official_heroes:
        raise ValueError("DDragon 返回的常规英雄集合为空")

    return latest_version, official_heroes


def compare_exact_keys(
    value: Mapping[str, Any],
    expected_keys: set[str],
    location: str,
) -> list[str]:
    """验证对象的键集合与 Schema 是否完全相等。"""
    errors: list[str] = []
    actual_keys = set(value.keys())

    missing_keys = expected_keys - actual_keys
    extra_keys = actual_keys - expected_keys

    if missing_keys:
        errors.append(
            f"{location} 缺少键：{', '.join(sorted(missing_keys))}"
        )
    if extra_keys:
        errors.append(
            f"{location} 含有非法键：{', '.join(sorted(extra_keys))}"
        )

    return errors


def validate_nickname_map() -> None:
    """确保所有映射目标本身均为当前 DDragon 官方全称。"""
    invalid_targets = sorted(set(NICKNAME_MAP.values()) - OFFICIAL_HEROES)
    if invalid_targets:
        raise ValueError(
            "NICKNAME_MAP 包含非官方映射目标："
            + ", ".join(invalid_targets)
        )


def validate_record(record: Any) -> ValidationResult:
    """执行单条样本的严格 Schema、实体和集合正交性校验。"""
    if not isinstance(record, dict):
        return ValidationResult(
            errors=["JSON 根节点必须是字典对象"],
            clean_record=None,
            correction_count=0,
            has_logic_error=False,
        )

    errors: list[str] = []
    correction_count = 0

    # 根节点只要求三个核心字段存在；
    # 额外字段不会进入纯净输出。
    missing_root_keys = ROOT_KEYS - set(record.keys())
    if missing_root_keys:
        errors.append(
            "根节点缺少键：" + ", ".join(sorted(missing_root_keys))
        )

    scenario_type = record.get("scenario_type")
    if not isinstance(scenario_type, str):
        errors.append("scenario_type 必须是字符串")
    elif scenario_type not in SCENARIO_TYPES:
        errors.append(
            "scenario_type 不是允许的枚举值：" + scenario_type
        )

    scenario_description = record.get("scenario_description")
    if (
        not isinstance(scenario_description, str)
        or not scenario_description.strip()
    ):
        errors.append("scenario_description 必须是非空字符串")

    draft_phase_lineup = record.get("draft_phase_lineup")
    if not isinstance(draft_phase_lineup, Mapping):
        errors.append("draft_phase_lineup 必须是对象")
        return ValidationResult(errors, None, correction_count, False)

    # 阵容节点不允许任何额外容器或动态字段。
    errors.extend(
        compare_exact_keys(
            draft_phase_lineup,
            LINEUP_KEYS,
            "draft_phase_lineup",
        )
    )

    heroes: list[str] = []
    clean_lineup: dict[str, dict[str, str]] = {}

    for team_name in ("blue_team", "red_team"):
        team = draft_phase_lineup.get(team_name)
        location = f"draft_phase_lineup.{team_name}"

        if not isinstance(team, Mapping):
            errors.append(f"{location} 必须是对象")
            continue

        # 只允许五个固定分路；adc、players 等任何变体都直接失败。
        errors.extend(compare_exact_keys(team, LANE_KEYS, location))
        if set(team.keys()) != LANE_KEYS:
            continue

        clean_team: dict[str, str] = {}
        for lane in ("top", "jungle", "mid", "bottom", "support"):
            hero_name = team[lane]

            # 分路值必须直接是字符串，
            # 绝不解析 hero/players 等嵌套对象。
            if not isinstance(hero_name, str) or not hero_name:
                errors.append(f"{location}.{lane} 必须是英雄全称字符串")
                continue

            # 在所有实体断言之前进行精确映射归一化。
            normalized_name = NICKNAME_MAP.get(hero_name, hero_name)
            if normalized_name != hero_name:
                correction_count += 1

            heroes.append(normalized_name)
            clean_team[lane] = normalized_name

        clean_lineup[team_name] = clean_team

    has_logic_error = False
    if len(heroes) == 10:
        hero_counts = Counter(heroes)
        duplicate_heroes = sorted(
            hero for hero, count in hero_counts.items() if count > 1
        )
        if len(set(heroes)) != 10:
            has_logic_error = True
            errors.append("英雄重复：" + ", ".join(duplicate_heroes))

        oov_heroes = sorted(set(heroes) - OFFICIAL_HEROES)
        if oov_heroes:
            errors.append(
                "OOV/非官方中文全称：" + ", ".join(oov_heroes)
            )

    if errors:
        return ValidationResult(
            errors=errors,
            clean_record=None,
            correction_count=correction_count,
            has_logic_error=has_logic_error,
        )

    # 只投影三个核心根字段；根节点额外字段在此被确定性剥离。
    clean_record = {
        "scenario_type": scenario_type,
        "scenario_description": scenario_description,
        "draft_phase_lineup": clean_lineup,
    }
    return ValidationResult(
        errors=[],
        clean_record=clean_record,
        correction_count=correction_count,
        has_logic_error=False,
    )


def build_lineup_signature(
    clean_record: Mapping[str, Any],
) -> LineupSignature:
    """按固定队伍与分路顺序生成全局阵容指纹。"""
    lineup = clean_record["draft_phase_lineup"]
    return tuple(
        lineup[team_name][lane]
        for team_name in ("blue_team", "red_team")
        for lane in ("top", "jungle", "mid", "bottom", "support")
    )


def write_clean_records(
    output_path: Path,
    records: list[dict[str, Any]],
) -> None:
    """覆盖写入纯净记录，保证重复运行结果幂等。"""
    with output_path.open("w", encoding="utf-8") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def print_distribution(
    scenario_counts: Counter[str],
    valid_count: int,
) -> None:
    """打印有效样本中各场景类别的频次与实际比例。"""
    print("\n===== 有效样本 scenario_type 分布 =====")
    for scenario_type in (
        "standard_meta",
        "extreme_comps",
        "off_meta",
    ):
        count = scenario_counts[scenario_type]
        ratio = count / valid_count if valid_count else 0.0
        print(f"{scenario_type}: {count}（{ratio:.2%}）")


def main() -> int:
    """同步英雄字典，校验 JSONL，并追加写入纯净数据集。"""
    global OFFICIAL_HEROES

    try:
        ddragon_version, OFFICIAL_HEROES = load_latest_official_heroes()
        validate_nickname_map()
    except (
        requests.RequestException,
        json.JSONDecodeError,
        ValueError,
    ) as error:
        print(f"DDragon 官方英雄字典同步失败：{error}")
        return 2

    print(
        f"DDragon 版本：{ddragon_version}；"
        f"已加载 {len(OFFICIAL_HEROES)} 个官方中文英雄全称。"
    )

    if not INPUT_PATH.is_file():
        print(f"未找到待校验文件：{INPUT_PATH.resolve()}")
        return 2

    checked_count = 0
    clean_records: list[dict[str, Any]] = []
    rejected_line_numbers: list[int] = []
    scenario_counts: Counter[str] = Counter()
    seen_lineups: set[LineupSignature] = set()
    correction_count = 0
    logic_rejected_count = 0
    global_duplicate_count = 0

    with INPUT_PATH.open("r", encoding="utf-8") as input_file:
        for line_number, raw_line in enumerate(input_file, start=1):
            if not raw_line.strip():
                continue

            checked_count += 1
            try:
                record: Any = json.loads(raw_line)
            except json.JSONDecodeError as error:
                print(
                    f"[第 {line_number} 行] JSON 强解析失败："
                    f"{error.msg}（列 {error.colno}）"
                )
                rejected_line_numbers.append(line_number)
                continue

            result = validate_record(record)
            correction_count += result.correction_count

            if result.errors:
                rejected_line_numbers.append(line_number)
                if result.has_logic_error:
                    logic_rejected_count += 1
                for error in result.errors:
                    print(f"[第 {line_number} 行] {error}")
                continue

            if result.clean_record is None:
                continue

            # 单条断言全部通过后，再进行数据集级阵容指纹去重。
            lineup_signature = build_lineup_signature(result.clean_record)
            if lineup_signature in seen_lineups:
                global_duplicate_count += 1
                rejected_line_numbers.append(line_number)
                print(f"[第 {line_number} 行] 抛弃: 阵容全局重复")
                continue

            seen_lineups.add(lineup_signature)
            clean_records.append(result.clean_record)
            scenario_counts[result.clean_record["scenario_type"]] += 1

    try:
        write_clean_records(OUTPUT_PATH, clean_records)
    except OSError as error:
        print(f"纯净数据写入失败：{error}")
        return 2

    valid_count = len(clean_records)
    pass_rate = valid_count / checked_count if checked_count else 0.0
    target_deficit = TARGET_COUNT - valid_count

    print("\n===== ETL 校验汇总 =====")
    print(f"校验总数：{checked_count}")
    print(f"触发映射修正次数：{correction_count}")
    print(f"因逻辑错误丢弃行数：{logic_rejected_count}")
    print(f"因阵容全局重复丢弃数量：{global_duplicate_count}")
    print(f"最终落盘的绝对有效数据量：{valid_count}")
    print(f"目标缺口：{target_deficit}")
    if target_deficit > 0:
        print(f"接下来还需定向生成 {target_deficit} 条数据。")
    else:
        print("目标数量已满足，无需补充生成。")
    print(f"丢弃数量：{len(rejected_line_numbers)}")
    print(f"有效通过率：{pass_rate:.2%}")
    if rejected_line_numbers:
        print(
            "丢弃行号："
            + ", ".join(str(number) for number in rejected_line_numbers)
        )

    print_distribution(scenario_counts, valid_count)
    print(
        f"本次已覆盖写入 {OUTPUT_PATH.resolve()}，"
        f"共 {valid_count} 条纯净数据。"
    )
    print("提示：阵容战术语义需由领域专家人工审查。")

    return 0 if not rejected_line_numbers else 1


if __name__ == "__main__":
    raise SystemExit(main())
