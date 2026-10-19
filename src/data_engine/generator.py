from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from openai import AsyncOpenAI, OpenAIError, PermissionDeniedError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAP_REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "gap_report.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "patches" / "patch_baseline.jsonl"

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get(
    "OPENAI_BASE_URL",
    "https://api.poixe.com/v1",
)
MODEL = "gpt-5.6-sol"

MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 180.0

SCENARIO_TYPES = ("standard_meta", "extreme_comps", "off_meta")

SYSTEM_PROMPT_TEMPLATE = (
    "你是一个英雄联盟多实体状态空间生成器。"
    "请生成 {batch_size} 条独立对局数据的 JSON。\n"
    "【本次定向补齐要求】：{gap_requirements}\n"
    "必须严格遵守上述各类别数量，不得增减或互换标签。\n"
    "【硬性格式约束】：你必须且只能输出严格符合以下 Schema 的 "
    "JSON 结构，最外层必须是 'data' 键：\n"
    "{{\n"
    "  'data': [\n"
    "    {{\n"
    "      'scenario_type': "
    "'<枚举值：standard_meta, extreme_comps, off_meta>',\n"
    "      'scenario_description': '<一句话简述阵容战术意图>',\n"
    "      'draft_phase_lineup': {{\n"
    "        'blue_team': {{'top': '...', 'jungle': '...', "
    "'mid': '...', 'bottom': '...', 'support': '...'}},\n"
    "        'red_team': {{'top': '...', 'jungle': '...', "
    "'mid': '...', 'bottom': '...', 'support': '...'}}\n"
    "      }}\n"
    "    }}\n"
    "  ]\n"
    "}}\n"
    "【绝对逻辑红线】：\n"
    "1. 实体命名：必须且只能使用英雄联盟当前官方中文全称"
    "（如“深海泰坦”、“荒漠屠夫”、“德玛西亚皇子”），"
    "绝对禁止使用任何简称、外号、旧称或英雄本名。"
    "每条数据中的10个英雄必须互不重复。\n"
    "2. 分路键名：下路必须严格使用 'bottom'，禁止使用 'adc'。\n"
    "3. 静态特征：本数据仅代表BP阶段结束时的纯静态特征。"
    "绝对禁止生成任何动态对局数值"
    "（如击杀、金币、防御塔、装备等）。"
)


@dataclass(frozen=True)
class GapReport:
    """保存校验器计算出的定向生成缺口。"""

    total_deficit: int
    details: dict[str, int]


def load_gap_report(path: Path) -> GapReport | None:
    """加载并强校验缺口状态；无需生成时返回 None。"""
    if not path.is_file():
        return None

    try:
        with path.open("r", encoding="utf-8") as input_file:
            payload: Any = json.load(input_file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"gap_report.json 不是合法 JSON：{error.msg}"
        ) from error

    if not isinstance(payload, Mapping):
        raise ValueError("gap_report.json 根节点必须是对象")

    total_deficit = payload.get("total_deficit")
    if (
        not isinstance(total_deficit, int)
        or isinstance(total_deficit, bool)
        or total_deficit < 0
    ):
        raise ValueError("total_deficit 必须是非负整数")
    if total_deficit == 0:
        return None

    raw_details = payload.get("details")
    if not isinstance(raw_details, Mapping):
        raise ValueError("details 必须是对象")

    unknown_types = set(raw_details.keys()) - set(SCENARIO_TYPES)
    if unknown_types:
        raise ValueError(
            "details 含有未知场景类型："
            + ", ".join(sorted(str(item) for item in unknown_types))
        )

    details: dict[str, int] = {}
    for scenario_type in SCENARIO_TYPES:
        count = raw_details.get(scenario_type, 0)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
        ):
            raise ValueError(
                f"details.{scenario_type} 必须是非负整数"
            )
        if count:
            details[scenario_type] = count

    if sum(details.values()) != total_deficit:
        raise ValueError(
            "details 非零项之和必须严格等于 total_deficit"
        )

    return GapReport(total_deficit=total_deficit, details=details)


def build_gap_requirements(details: Mapping[str, int]) -> str:
    """把非零缺口转换为可直接注入系统提示词的中文要求。"""
    requirements = [
        f"{count} 条 {scenario_type} 战术"
        for scenario_type in SCENARIO_TYPES
        if (count := details.get(scenario_type, 0)) > 0
    ]
    if not requirements:
        raise ValueError("details 中不存在非零缺口")

    return "必须精确包含 " + "，".join(requirements) + "。"


def strip_markdown_fence(content: str) -> str:
    """剥离劣质中转站可能保留的 Markdown JSON 围栏。"""
    return re.sub(
        r"^\s*```(?:json)?\s*|\s*```\s*$",
        "",
        content,
        flags=re.IGNORECASE,
    ).strip()


def parse_and_validate_response(
    content: str,
    gap_report: GapReport,
) -> list[dict[str, Any]]:
    """强解析模型响应，并核对返回条数与场景标签频次。"""
    payload: Any = json.loads(strip_markdown_fence(content))
    if not isinstance(payload, dict):
        raise TypeError("模型返回的 JSON 根节点必须是对象")
    if set(payload.keys()) != {"data"}:
        raise ValueError("模型返回的根节点必须且只能包含 data")

    data = payload.get("data")
    if not isinstance(data, list):
        raise TypeError("模型返回的 data 必须是列表")
    if len(data) != gap_report.total_deficit:
        raise ValueError(
            f"期望 {gap_report.total_deficit} 条，实际返回 {len(data)} 条"
        )

    records: list[dict[str, Any]] = []
    scenario_counts: Counter[str] = Counter()
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise TypeError(f"第 {index} 条数据不是 JSON 对象")

        scenario_type = item.get("scenario_type")
        if scenario_type not in SCENARIO_TYPES:
            raise ValueError(
                f"第 {index} 条 scenario_type 非法：{scenario_type!r}"
            )

        scenario_counts[scenario_type] += 1
        records.append(item)

    actual_details = {
        scenario_type: scenario_counts[scenario_type]
        for scenario_type in SCENARIO_TYPES
        if scenario_counts[scenario_type]
    }
    if actual_details != gap_report.details:
        raise ValueError(
            f"类别频次不符合缺口：期望 {gap_report.details}，"
            f"实际 {actual_details}"
        )

    return records


def append_jsonlines(
    path: Path,
    records: Iterable[dict[str, Any]],
) -> None:
    """以追加模式写入补丁 JSONL，绝不覆盖主数据文件。"""
    with path.open("a", encoding="utf-8") as output_file:
        for record in records:
            output_file.write(json.dumps(record, ensure_ascii=False) + "\n")


async def request_patch(
    client: AsyncOpenAI,
    prompt: str,
    gap_report: GapReport,
) -> list[dict[str, Any]]:
    """调用模型并对瞬态或格式错误执行指数退避重试。"""
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "system", "content": prompt}],
                response_format={"type": "json_object"},
            )
            print(f"中转站实际返回模型：{response.model}")

            content = response.choices[0].message.content
            if not content:
                raise ValueError("模型返回内容为空")

            return parse_and_validate_response(content, gap_report)

        except PermissionDeniedError as error:
            raise RuntimeError(f"中转站拒绝请求：{error}") from error
        except (
            json.JSONDecodeError,
            OpenAIError,
            OSError,
            TimeoutError,
            TypeError,
            ValueError,
            IndexError,
        ) as error:
            last_error = error
            if attempt >= MAX_RETRIES:
                break

            backoff_seconds = INITIAL_BACKOFF_SECONDS * (2**attempt)
            print(
                f"第 {attempt + 1} 次请求失败："
                f"{type(error).__name__}: {error}；"
                f"{backoff_seconds:.1f} 秒后重试"
            )
            await asyncio.sleep(backoff_seconds)

    raise RuntimeError(
        f"请求在重试 {MAX_RETRIES} 次后仍然失败"
    ) from last_error


async def main() -> int:
    """读取缺口、动态构建提示词并追加生成补丁数据。"""
    try:
        gap_report = load_gap_report(GAP_REPORT_PATH)
    except (OSError, ValueError) as error:
        print(f"缺口状态加载失败：{error}")
        return 2

    if gap_report is None:
        print("无需生成，数据集已齐备")
        return 0

    if not API_KEY:
        print("未配置 OPENAI_API_KEY，无法调用生成接口")
        return 2

    gap_requirements = build_gap_requirements(gap_report.details)
    prompt = SYSTEM_PROMPT_TEMPLATE.format(
        batch_size=gap_report.total_deficit,
        gap_requirements=gap_requirements,
    )

    print(f"本次自动生成数量：{gap_report.total_deficit}")
    print(f"定向要求：{gap_requirements}")

    client = AsyncOpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        max_retries=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    try:
        records = await request_patch(client, prompt, gap_report)
        append_jsonlines(OUTPUT_PATH, records)
    except (OSError, RuntimeError) as error:
        print(f"补丁生成失败：{error}")
        return 1
    finally:
        await client.close()

    print(
        f"已向 {OUTPUT_PATH.resolve()} 追加写入 "
        f"{len(records)} 条补丁数据"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
