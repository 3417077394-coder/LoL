import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from openai import AsyncOpenAI, OpenAIError, PermissionDeniedError


# 填入中转站提供的 API Key。
API_KEY = os.environ.get("OPENAI_API_KEY", "")

# 填入中转站 API 域名，例如：
# https://api.your-proxy-domain.com/v1
BASE_URL = "https://api.poixe.com/v1"

MODEL = "gpt-5.6-sol"
OUTPUT_PATH = Path("baseline_test_set.jsonl")

TOTAL_RECORDS = 50
BATCH_COUNT = 5
BATCH_SIZE = TOTAL_RECORDS // BATCH_COUNT

MAX_CONCURRENCY = 2
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 1.0

JsonDict = dict[str, Any]

SYSTEM_PROMPT_TEMPLATE = (
    "你是一个英雄联盟多实体状态空间生成器。请基于预设的分布矩阵，生成 {batch_size} 条独立对局数据的 JSON。\n"
    "分布要求：40%常规标准局，30%极端战术体系，30%对抗性非主流局（如全物理输出、无前排或冷门摇摆位）。\n"
    "【硬性格式约束】：你必须且只能输出严格符合以下 Schema 的 JSON 结构，最外层必须是 'data' 键：\n"
    "{{\n"
    "  'data': [\n"
    "    {{\n"
    "      'scenario_type': '<枚举值：standard_meta, extreme_comps, off_meta>',\n"
    "      'scenario_description': '<一句话简述阵容战术意图>',\n"
    "      'draft_phase_lineup': {{\n"
    "        'blue_team': {{'top': '...', 'jungle': '...', 'mid': '...', 'bottom': '...', 'support': '...'}},\n"
    "        'red_team': {{'top': '...', 'jungle': '...', 'mid': '...', 'bottom': '...', 'support': '...'}}\n"
    "      }}\n"
    "    }}\n"
    "  ]\n"
    "}}\n"
    "【绝对逻辑红线】：\n"
    "1. 实体命名：必须且只能使用英雄联盟官方中文全称（如“深海泰坦”、“荒漠屠夫”、“德玛西亚皇子”），绝对禁止使用任何简称或外号。10个英雄必须互不重复。\n"
    "2. 分路键名：下路必须严格使用 'bottom'，禁止使用 'adc'。\n"
    "3. 静态特征：本数据仅代表BP阶段结束时的纯静态特征。绝对禁止生成任何动态对局数值（如击杀、金币、防御塔、装备等）。"
)


async def generate_batch(
    client: AsyncOpenAI,
    semaphore: asyncio.Semaphore,
    write_lock: asyncio.Lock,
    batch_id: int,
    batch_size: int,
) -> list[JsonDict]:
    """生成一个批次的数据，并在失败时执行指数退避重试。"""
    prompt = SYSTEM_PROMPT_TEMPLATE.format(batch_size=batch_size)
    last_error: Exception | None = None

    # 首次请求失败后最多额外重试 MAX_RETRIES 次。
    for retry_index in range(MAX_RETRIES + 1):
        try:
            # 信号量只包裹真实 API 请求，退避等待不会占用并发名额。
            async with semaphore:
                response = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": prompt,
                        }
                    ],
                    response_format={"type": "json_object"},
                )

            # 打印中转站实际返回的模型名称，便于检查是否被降级。
            print(
                f"批次 {batch_id} 返回模型：{response.model}",
                flush=True,
            )

            content = response.choices[0].message.content
            if not content:
                raise ValueError("模型返回内容为空")

            # 在 json.loads() 前强制剥离可能存在的 Markdown JSON 围栏。
            cleaned_content = re.sub(
                r"^\s*```(?:json)?\s*|\s*```\s*$",
                "",
                content,
                flags=re.IGNORECASE,
            ).strip()

            payload: Any = json.loads(cleaned_content)
            if not isinstance(payload, dict):
                raise TypeError("模型返回的 JSON 顶层必须是对象")

            data = payload.get("data")
            if not isinstance(data, list):
                raise TypeError("模型返回的 data 字段必须是列表")

            # 确保每个批次确实返回指定数量，避免最终数据集不足 50 条。
            if len(data) != batch_size:
                raise ValueError(
                    f"批次 {batch_id} 期望 {batch_size} 条数据，"
                    f"实际得到 {len(data)} 条"
                )

            records: list[JsonDict] = []
            for index, item in enumerate(data, start=1):
                if not isinstance(item, dict):
                    raise TypeError(
                        f"批次 {batch_id} 的第 {index} 条数据不是 JSON 对象"
                    )
                records.append(item)

            # 一个批次校验通过后立即落盘，避免其他批次失败时丢失成果。
            async with write_lock:
                append_jsonlines(OUTPUT_PATH, records)

            print(
                f"批次 {batch_id} 已追加写入 {len(records)} 条数据",
                flush=True,
            )
            return records

        except PermissionDeniedError as error:
            # 403（如余额、模型权限或账号路由限制）不因等待而恢复，不重试。
            raise RuntimeError(
                f"批次 {batch_id} 被中转站拒绝：{error}"
            ) from error

        except (
            json.JSONDecodeError,
            OpenAIError,
            OSError,
            TimeoutError,
            ValueError,
            TypeError,
            IndexError,
        ) as error:
            last_error = error

            if retry_index >= MAX_RETRIES:
                break

            # 退避时间依次为 1、2、4 秒。
            backoff_seconds = INITIAL_BACKOFF_SECONDS * (2 ** retry_index)
            print(
                f"批次 {batch_id} 第 {retry_index + 1} 次请求失败："
                f"{type(error).__name__}: {error}；"
                f"{backoff_seconds:.1f} 秒后重试",
                flush=True,
            )
            await asyncio.sleep(backoff_seconds)

    raise RuntimeError(
        f"批次 {batch_id} 在重试 {MAX_RETRIES} 次后仍然失败"
    ) from last_error


def append_jsonlines(
    output_path: Path,
    records: Iterable[JsonDict],
) -> None:
    """以 JSON Lines 格式将数据逐行追加到文件。"""
    with output_path.open(mode="a", encoding="utf-8") as output_file:
        for record in records:
            json_line = json.dumps(record, ensure_ascii=False)
            output_file.write(f"{json_line}\n")


async def main() -> None:
    """并发生成全部测试数据并写入 JSONL 文件。"""
    if TOTAL_RECORDS != BATCH_COUNT * BATCH_SIZE:
        raise ValueError("总数据量必须等于批次数乘以单批数据量")

    # 禁用 SDK 内置重试，保证重试次数完全由本脚本控制。
    client = AsyncOpenAI(
        api_key=API_KEY,
        base_url=BASE_URL,
        max_retries=0,
        timeout=120.0,
    )
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    write_lock = asyncio.Lock()

    try:
        batch_tasks = [
            generate_batch(
                client=client,
                semaphore=semaphore,
                write_lock=write_lock,
                batch_id=batch_id,
                batch_size=BATCH_SIZE,
            )
            for batch_id in range(1, BATCH_COUNT + 1)
        ]

        # 等待全部批次结束，确保已成功的批次都完成追加写入。
        batch_results = await asyncio.gather(
            *batch_tasks,
            return_exceptions=True,
        )
        failed_batches = [
            result
            for result in batch_results
            if isinstance(result, BaseException)
        ]
        saved_records = sum(
            len(result)
            for result in batch_results
            if isinstance(result, list)
        )

        if failed_batches:
            print(
                f"运行未完全成功：已有 {saved_records} 条数据保存到 "
                f"{OUTPUT_PATH.resolve()}",
                flush=True,
            )
            raise RuntimeError(
                f"{len(failed_batches)} 个批次失败；已成功的数据已保留"
            ) from failed_batches[0]

        if saved_records != TOTAL_RECORDS:
            raise RuntimeError(
                f"期望生成 {TOTAL_RECORDS} 条数据，"
                f"实际写入 {saved_records} 条"
            )

        print(
            f"生成完成：已向 {OUTPUT_PATH.resolve()} "
            f"追加写入 {saved_records} 条数据",
            flush=True,
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
