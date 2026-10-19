import json
import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI
from tqdm import tqdm

from project_paths import (
    JUDGE_OUTPUT_FILE,
    MODEL_OUTPUT_FILE,
    TEST_SET_FILE,
)


# ==========================================
# 1. 裁判参数与路径配置
# ==========================================
INPUT_FILE = MODEL_OUTPUT_FILE
OUTPUT_FILE = JUDGE_OUTPUT_FILE

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get(
    "OPENAI_BASE_URL",
    "https://api.poixe.com/v1",
)
JUDGE_MODEL = "gpt-5.6-sol"


# ==========================================
# 2. 裁判系统提示词 (Judge Prompt)
# ==========================================
JUDGE_SYSTEM_PROMPT = """你是一位英雄联盟顶级职业电竞教练和数据分析专家。
你的任务是对 AI 引擎生成的【英雄联盟战术推演结果】进行绝对客观、犀利的语义与逻辑评估。

你需要根据提供的【对局特征与阵容】以及【待测 AI 的输出】，在以下两个维度给出 0 到 5 分的整数评分：

【评估维度 1：事实与机制准确度 (Factual & Mechanism Accuracy)】
- 5分：所有英雄定位、伤害类型分布、技能克制关系完全准确，无任何事实性错误。
- 3分：大体准确，但存在对冷门英雄机制的微小认知模糊，但不影响全局。
- 0-1分：存在严重的常识倒置（如将刺客当做重装战士，或虚构了根本不存在的克制关系）。

【评估维度 2：战术因果自洽性 (Causal Consistency)】
- 5分：宏观制胜条件与各分路的微观战术建议构成了严密的因果逻辑闭环，无自相矛盾。
- 3分：推演逻辑尚可，但部分分路策略过于宽泛，或与制胜条件耦合度不高。
- 0-1分：逻辑断裂（例如：宏观建议抗压避战，微观却建议越塔强杀；或红蓝双方战术视角发生混淆）。

【强制输出格式】
你必须仅输出合法的 JSON 格式数据，不得包含任何 Markdown 标记。JSON 字典结构必须如下：
{
    "judge_reasoning": "简明扼要地指出待测AI输出中的机制亮点或逻辑漏洞（150字以内）",
    "factual_score": 整数评分(0-5),
    "consistency_score": 整数评分(0-5)
}"""


# ==========================================
# 3. 读取、关联与响应校验
# ==========================================
def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL，并在错误信息中保留文件名和行号。"""
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
                raise TypeError(
                    f"{path.name} 第 {line_number} 行的根节点必须是对象"
                )
            records.append(record)
    return records


def load_scenarios(path: Path) -> dict[int, dict[str, Any]]:
    """按照测试集行序建立稳定的 sample_id -> scenario 映射。"""
    records = load_jsonl(path)
    return {
        sample_id: scenario
        for sample_id, scenario in enumerate(records, start=1)
    }


def extract_json(text: str) -> dict[str, Any]:
    """解析并严格校验裁判输出，解析失败交给上层记为 evaluation_error。"""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    payload = json.loads(match.group(0) if match else text)
    if not isinstance(payload, dict):
        raise TypeError("裁判输出的 JSON 根节点必须是对象")

    reasoning = payload.get("judge_reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("judge_reasoning 必须是非空字符串")

    for score_name in ("factual_score", "consistency_score"):
        score = payload.get(score_name)
        if (
            not isinstance(score, int)
            or isinstance(score, bool)
            or not 0 <= score <= 5
        ):
            raise ValueError(f"{score_name} 必须是 0 到 5 的整数")

    return {
        "judge_reasoning": reasoning.strip(),
        "factual_score": payload["factual_score"],
        "consistency_score": payload["consistency_score"],
    }


def serialize_scenario(scenario: dict[str, Any]) -> str:
    """把 canonical 测试样本完整提供给裁判。"""
    return json.dumps(scenario, ensure_ascii=False, indent=2)


def call_judge_llm(
    client: OpenAI,
    scenario_info: str,
    ai_output: str,
) -> dict[str, Any]:
    """调用 API 裁判；异常由主流程记录，不能伪装成 0 分。"""
    user_prompt = f"""[对局特征与阵容信息]
{scenario_info}

[待测 AI 输出的战术推演]
{ai_output}"""

    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=500,
    )
    raw_result = response.choices[0].message.content
    if not raw_result:
        raise ValueError("裁判模型返回了空内容")
    return extract_json(raw_result)


def make_evaluation_error(
    error: Exception | str,
    *,
    stage: str,
) -> dict[str, str]:
    """生成不含伪造分数的统一错误结构。"""
    if isinstance(error, Exception):
        error_type = type(error).__name__
        message = str(error)
    else:
        error_type = "EvaluationError"
        message = error
    return {
        "stage": stage,
        "type": error_type,
        "message": message,
    }


def collect_successful_evaluations(
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """只返回成功评分；任何 evaluation_error 都不得进入均值。"""
    return [
        result["judge_evaluation"]
        for result in results
        if "judge_evaluation" in result
        and "evaluation_error" not in result
    ]


# ==========================================
# 4. 主执行管线
# ==========================================
def main() -> None:
    if not INPUT_FILE.is_file():
        raise FileNotFoundError(f"未找到 baseline 结果：{INPUT_FILE}")
    if not TEST_SET_FILE.is_file():
        raise FileNotFoundError(f"未找到 canonical 测试集：{TEST_SET_FILE}")
    if not API_KEY:
        raise RuntimeError("未设置 OPENAI_API_KEY，拒绝覆盖现有 judge 结果")
    if OUTPUT_FILE.exists():
        raise FileExistsError(
            f"{OUTPUT_FILE} 已存在；请设置新的 LOL_EXPERIMENT_ID，"
            "禁止静默覆盖实验结果"
        )

    baseline_records = load_jsonl(INPUT_FILE)
    scenarios = load_scenarios(TEST_SET_FILE)
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    print(f"启动 LLM-as-a-Judge 评估管线 (模型: {JUDGE_MODEL})...")
    results: list[dict[str, Any]] = []

    for source_record in tqdm(baseline_records, desc="正在评估基线数据"):
        record = dict(source_record)
        record.pop("judge_evaluation", None)
        record.pop("evaluation_error", None)

        sample_id = record.get("sample_id")
        if (
            not isinstance(sample_id, int)
            or isinstance(sample_id, bool)
            or sample_id not in scenarios
        ):
            record["evaluation_error"] = make_evaluation_error(
                f"无法通过 sample_id={sample_id!r} 关联 canonical 测试集",
                stage="scenario_link",
            )
            results.append(record)
            continue

        scenario = scenarios[sample_id]
        record["input_scenario"] = scenario
        record["input_prompt"] = serialize_scenario(scenario)

        if not record.get("is_valid_json"):
            record["evaluation_error"] = make_evaluation_error(
                "baseline 输出不是合法 JSON，跳过语义评分",
                stage="baseline_output_validation",
            )
            results.append(record)
            continue

        ai_output = record.get("y_base_raw_output")
        if not isinstance(ai_output, str) or not ai_output.strip():
            record["evaluation_error"] = make_evaluation_error(
                "baseline 输出为空或不是字符串",
                stage="baseline_output_validation",
            )
            results.append(record)
            continue

        try:
            record["judge_evaluation"] = call_judge_llm(
                client,
                serialize_scenario(scenario),
                ai_output,
            )
        except Exception as error:
            print(f"sample_id={sample_id} 评估失败：{error}")
            record["evaluation_error"] = make_evaluation_error(
                error,
                stage="judge_api_or_response",
            )
        results.append(record)

    with OUTPUT_FILE.open("w", encoding="utf-8") as output_file:
        for result in results:
            output_file.write(json.dumps(result, ensure_ascii=False) + "\n")

    successful = collect_successful_evaluations(results)
    error_count = sum("evaluation_error" in result for result in results)

    print("\n" + "=" * 40)
    print("语义与逻辑盲测打分结果 (Semantic & Logic Evaluation)")
    print("=" * 40)
    print(f"baseline 总样本数: {len(results)}")
    print(f"成功评分样本数: {len(successful)}")
    print(f"评估错误样本数: {error_count}（不计入均值）")

    if successful:
        valid_count = len(successful)
        avg_factual = sum(
            item["factual_score"] for item in successful
        ) / valid_count
        avg_consistency = sum(
            item["consistency_score"] for item in successful
        ) / valid_count
        perfect_factual = sum(
            item["factual_score"] == 5 for item in successful
        )
        perfect_consistency = sum(
            item["consistency_score"] == 5 for item in successful
        )

        print(f"事实与机制准确度平均分: {avg_factual:.2f} / 5.00")
        print(f"战术因果自洽性平均分: {avg_consistency:.2f} / 5.00")
        print(
            "绝对无错率 (Factual Score == 5): "
            f"{perfect_factual / valid_count * 100:.2f}%"
        )
        print(
            "绝对自洽率 (Consistency Score == 5): "
            f"{perfect_consistency / valid_count * 100:.2f}%"
        )
    else:
        print("无成功评分样本，未计算均值。")

    print("=" * 40)
    print(f"裁判批注、错误状态与分数已落盘至: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
