import json
import re

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from project_paths import (
    EXPERIMENT_DIR,
    MODEL_OUTPUT_FILE,
    MODEL_PATH,
    TEST_SET_FILE,
)

# ==========================================
# 1. 全局配置与路径映射
# ==========================================
INPUT_FILE = TEST_SET_FILE
OUTPUT_FILE = MODEL_OUTPUT_FILE

# 冻结推理超参数以控制变量
INFERENCE_CONFIG = {
    "max_new_tokens": 2048,
    "repetition_penalty": 1.05,
    "do_sample": False,
    "seed": 42
}

# ==========================================
# 2. 强拓扑约束 System Prompt
# ==========================================
SYSTEM_PROMPT = """你是一个英雄联盟高阶战术推演引擎。你的任务是基于给定的红蓝双方阵容，进行严密的机制交互分析与战术推演。

【核心推演原则】
1. 机制优先：严禁输出任何具体的技能冷却时间、伤害数值或属性数据。仅基于英雄的机制特性（如控制链、伤害类型分布、开团/反手能力、清线效率）进行逻辑推演。
2. 零幻觉：如果对某个冷门英雄或特殊摇摆位的对线关系数据不足，必须在分析中客观指出“存在不确定性”，严禁凭空捏造对抗逻辑。
3. 战术闭环：各分路的打法建议必须服务于该阵容的“核心制胜条件”。

【严格输出格式】
你必须且只能输出合法的纯 JSON 格式数据。绝对禁止输出任何 Markdown 标记（如 ```json）、前言或后记。JSON 结构必须严格遵循以下 Schema：

{
  "cot_reasoning": "全局战术推演过程（200字以内，分析双方控制链、伤害类型与前中后期发力点对比）",
  "global_analysis": {
    "blue_team_win_condition": "蓝方核心制胜条件",
    "red_team_win_condition": "红方核心制胜条件",
    "power_spike_comparison": "双方阵容强势期对比评估"
  },
  "positional_strategies": {
    "top_lane": {
      "matchup_analysis": "上路机制克制关系与线权推演",
      "blue_top_strategy": "蓝方上路战术执行建议",
      "red_top_strategy": "红方上路战术执行建议"
    },
    "jungle": {
      "matchup_analysis": "野区入侵能力与刷野速度优劣势推演",
      "blue_jungle_strategy": "蓝方打野控图与Gank规划",
      "red_jungle_strategy": "红方打野控图与Gank规划"
    },
    "mid_lane": {
      "matchup_analysis": "中路推线权与游走辐射能力推演",
      "blue_mid_strategy": "蓝方中路战术执行建议",
      "red_mid_strategy": "红方中路战术执行建议"
    },
    "bottom_lane": {
      "matchup_analysis": "下路双人组机制对抗与对线期优劣势推演",
      "blue_bottom_strategy": "蓝方下路双人组战术执行建议",
      "red_bottom_strategy": "红方下路双人组战术执行建议"
    }
  }
}"""

# ==========================================
# 3. 辅助函数
# ==========================================
def serialize_user_prompt(row: dict) -> str:
    """将输入的嵌套字典序列化为标准文本态势特征"""
    return f"""请对以下对局阵容进行战术推演：

【对局特征】
阵容风格标签：{row.get('scenario_type', '未知')}
对局背景描述：{row.get('scenario_description', '无')}

【蓝方阵容 (Blue Team)】
上路 (Top): {row['draft_phase_lineup']['blue_team']['top']}
打野 (Jungle): {row['draft_phase_lineup']['blue_team']['jungle']}
中路 (Mid): {row['draft_phase_lineup']['blue_team']['mid']}
下路 (Bottom): {row['draft_phase_lineup']['blue_team']['bottom']}
辅助 (Support): {row['draft_phase_lineup']['blue_team']['support']}

【红方阵容 (Red Team)】
上路 (Top): {row['draft_phase_lineup']['red_team']['top']}
打野 (Jungle): {row['draft_phase_lineup']['red_team']['jungle']}
中路 (Mid): {row['draft_phase_lineup']['red_team']['mid']}
下路 (Bottom): {row['draft_phase_lineup']['red_team']['bottom']}
辅助 (Support): {row['draft_phase_lineup']['red_team']['support']}

请直接输出符合系统要求的 JSON 数据。"""

def extract_json_payload(raw_text: str) -> str:
    """使用正则强制剥离可能的 Markdown 标记，确保 JSON 解析率"""
    match = re.search(r'\{.*\}', raw_text, re.DOTALL)
    if match:
        return match.group(0)
    return raw_text

# ==========================================
# 4. 主执行管线
# ==========================================
def main():
    if not MODEL_PATH.is_dir():
        raise FileNotFoundError(f"未找到模型目录：{MODEL_PATH}")
    if not INPUT_FILE.is_file():
        raise FileNotFoundError(f"未找到冻结测试集：{INPUT_FILE}")
    if OUTPUT_FILE.exists():
        raise FileExistsError(
            f"{OUTPUT_FILE} 已存在；请设置新的 LOL_EXPERIMENT_ID，"
            "禁止静默覆盖实验结果"
        )

    EXPERIMENT_DIR.mkdir(parents=True, exist_ok=True)

    # 强制固定全局随机种子，保障分布可复现
    torch.manual_seed(INFERENCE_CONFIG["seed"])
    
    print(f"正在挂载 Qwen2.5-7B-Instruct 权重至显存...\n路径: {MODEL_PATH}")
    tokenizer = AutoTokenizer.from_pretrained(
        str(MODEL_PATH), trust_remote_code=True
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(MODEL_PATH),
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True
    )
    model.eval()
    print("模型加载完成。开始执行确定性零样本基线推理...")

    with open(INPUT_FILE, "r", encoding="utf-8") as infile, open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:
        lines = infile.readlines()
        total_samples = len([l for l in lines if l.strip()])
        current_idx = 0

        for line in lines:
            if not line.strip():
                continue
            
            current_idx += 1
            row = json.loads(line.strip())
            user_prompt = serialize_user_prompt(row)
            
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ]
            
            text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
            
            with torch.no_grad():
                generated_ids = model.generate(
                    **model_inputs,
                    max_new_tokens=INFERENCE_CONFIG["max_new_tokens"],
                    repetition_penalty=INFERENCE_CONFIG["repetition_penalty"],
                    do_sample=INFERENCE_CONFIG["do_sample"]
                )
            
            # 截断输入 prompt，仅保留生成的 Token
            generated_ids = [
                output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
            ]
            raw_response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
            
            # 后处理剥离
            cleaned_response = extract_json_payload(raw_response)
            
            # 验证 JSON 合法性
            is_valid_json = True
            try:
                json.loads(cleaned_response)
            except json.JSONDecodeError:
                is_valid_json = False

            record = {
                "sample_id": current_idx,
                "scenario_type": row.get("scenario_type", "unknown"),
                "input_scenario": row,
                "input_prompt": user_prompt,
                "is_valid_json": is_valid_json,
                "y_base_raw_output": cleaned_response,
                "original_uncleaned_output": raw_response if not is_valid_json else None
            }
            
            outfile.write(json.dumps(record, ensure_ascii=False) + "\n")
            outfile.flush()  # 确保实时落盘，防止 OOM 或 SSH 断开导致数据丢失
            
            print(f"进度: [{current_idx}/{total_samples}] | JSON 契约合法性: {is_valid_json}")

    print(f"\n物理采样管线执行完毕。全量基线结果已落盘至: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()