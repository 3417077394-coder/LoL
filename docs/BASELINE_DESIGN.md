# Baseline 设计

状态：历史 Baseline v1 代码已修正；输出契约 v2 已接受、运行链路待迁移  
最后更新：2026-08-26

## 1. 目的

Baseline 用于测量未经 LoL 领域微调、且不接外部知识库的基座模型在固定任务上的
表现。当前实验明确命名为 **closed-book / model-only baseline**。

它用于诊断模型原有的 LoL 知识与阵容推理能力，不代表未来“模型 + 知识库”完整系统
的基线。Baseline 不用于证明模型已经“懂 LoL”，也不把格式合法率等同于语义质量。

## 2. 冻结条件

### 模型

- Qwen2.5-7B-Instruct。
- 默认本地权重位于项目外：
  `../models/models/Qwen--Qwen2.5-7B-Instruct/snapshots/master`。
- 可用 `LOL_MODEL_PATH` 显式覆盖本地权重路径。
- 本阶段不加载 LoRA adapter，不做领域微调。

### 测试集

- 唯一 Canonical 文件：`data/eval/baseline-test-v1.jsonl`。
- 历史输入快照：`experiments/LEGACY-0001/input_snapshot.jsonl`，
  只用于追溯，不是第二个数据源。
- Canonical 与历史快照均为 50 条，SHA-256 均为
  `e5b4e0d0a590ae64bad31ed7be272f3d7acb919441f1a2ff0b9f9671832e5682`。
- 分布：`standard_meta: 20`、`extreme_comps: 15`、
  `off_meta: 15`。
- 版本元数据：`data/eval/baseline-test-v1.metadata.json`。
- EXP-0001 的工程 ruleset：`lol-pc-ddragon-16.16.1-asof-2026-08-21`。
- 主版本为 Data Dragon `16.16.1`；`26.16` 只作为官方补丁说明别名保留，知识截止日
  为 2026-08-21。
- `authored_ruleset` 为未知；当前 ruleset 是事后绑定的事实/规则评判目标，不代表这些
  阵容在该竞技环境下获得过专家语义背书。

该测试集通过结构、实体和去重校验，但没有专家参考答案，不能称为
语义黄金答案。数据引擎只写 processed 候选，不能覆盖 eval v1。

### 推理

当前实现在 `src/baseline/run_baseline_eval.py`：

- Zero-shot，不提供示例。
- `do_sample: false`，使用 greedy decoding。
- `max_new_tokens: 2048`。
- `repetition_penalty: 1.05`。
- 随机种子保留为 42，但 greedy 模式不依赖采样。

### Prompt 和输出协议

System Prompt 当前仍内嵌在 `run_baseline_eval.py`。模型必须输出纯 JSON：

- `cot_reasoning`
- `global_analysis`
  - `blue_team_win_condition`
  - `red_team_win_condition`
  - `power_spike_comparison`
- `positional_strategies`
  - `top_lane`
  - `jungle`
  - `mid_lane`
  - `bottom_lane`

每个分路包含一项对局分析和蓝红双方策略。输出不得包含具体冷却、伤害或
属性数值；不确定场景应明确表达不确定性。正式 EXP-0001 前必须让 Baseline 与
Judge Prompt 明确绑定 `ruleset_id`、Data Dragon 版本和知识截止日；当前内嵌 Prompt
尚未完成这项适配。

## 3. 数据流

```mermaid
flowchart LR

上述结构是历史 Baseline v1 契约，多轮 fixed-KB 开发实验依赖它，因此保留用于复现，
不静默覆盖。项目已经接受新的
[Lineup Analysis Output Schema v2](LINEUP_ANALYSIS_OUTPUT_SCHEMA.md)：第一阶段只输出
双方阵容画像、3～5 条决定性交互、相对强势期与交战条件、地图资源影响、双方制胜条件
及不确定性，不再要求完整四路打法，也不输出 `cot_reasoning`。

机器可读文件为 `schemas/lineup_analysis_output_v2.schema.json`。当前只完成契约、示例
和回归测试；Baseline 推理、指标、Judge 与人工审核工具仍未迁移。因此现在运行旧命令
只会产生 v1 输出，不能标记为正式 v2 Baseline。
    A["冻结测试集<br/>50 条"] --> B["Qwen2.5-7B-Instruct<br/>Zero-shot / Greedy"]
    B --> C["experiments/EXP-0001/model_outputs.jsonl"]
    C --> D["程序指标"]
    A --> E["按 sample_id 关联"]
    C --> E
    E --> F["LLM Judge"]
    A --> G["分层抽取"]
    C --> G
    G --> H["人工盲审"]
```

推理结果中的每条记录保存：

- `sample_id`
- `scenario_type`
- `input_scenario`
- `input_prompt`
- `is_valid_json`
- `y_base_raw_output`
- 非法 JSON 时的 `original_uncleaned_output`

## 4. 程序指标

`src/baseline/calculate_baseline_metrics.py` 全量计算：

- JSON 格式合法率。
- 完整 Schema 合法率。
- 数值幻觉触发率。

Schema 校验递归覆盖根节点、全局分析和四个分路的所有子字段，并拒绝：

- 缺失字段。
- 未声明字段。
- 错误对象类型。
- 空字符串叶子。

程序指标只判断协议和硬约束，不判断英雄机制是否正确。

## 5. 语义能力与 LLM Judge

正式报告使用[能力分类体系](CAPABILITY_TAXONOMY.md)中的五个一级维度组织结果，
逐项计分、封顶、`NA` 和汇总规则以
[Evaluation Rubric v1.0](EVALUATION_RUBRIC.md)为准：

1. `E1` 输入与输出契约。
2. `E2` 机制事实准确性。
3. `E3` 阵容交互推理。
4. `E4` 阵容整体推演。
5. `E5` 制胜条件与因果。

19 个二级标签只用于旁路错误诊断，不要求分别形成稳定总分。EXP-0001 以 Data Dragon
16.16.1 及截至 2026-08-21 的官方修正作为 E2 的事实与规则目标；缺少该 ruleset 的
可靠依据或确有版本争议的检查项记 `NA`。
E2 主要用于形成未来知识库的事实缺口清单，`E3`～`E5` 是判断 SFT 数据方向的重点。

正式 closed-book 脚本 `run_llm_judge.py` 仍只输出下面两个旧聚合维度，旧分数不能
冒充正式 E1～E5 结果。fixed-KB 开发实验已新增 `run_kb_judge.py`、版本化 Prompt、
五维 Schema 和汇总器，用于对现有 18 份成对输出评分；该开发管线不等于 EXP-0001
的正式 Judge 和人工审核已经完成迁移。

`src/baseline/run_llm_judge.py` 通过 `sample_id` 将 baseline 输出与
canonical 测试样本重新关联，评分：

- 事实与机制准确度：0～5。
- 战术因果自洽性：0～5。

错误处理规则：

- API、响应解析、样本关联或 baseline 输出错误统一写入
  `evaluation_error`。
- 错误记录不得伪造成 0 分。
- 只有存在有效 `judge_evaluation` 且没有 `evaluation_error` 的记录
  才进入均值。
- 运行时若没有 `OPENAI_API_KEY`，脚本拒绝覆盖已有结果。

## 6. 人工抽查

`src/baseline/human_review.py` 可以按照 `scenario_type` 固定种子
分层抽取，默认抽取 12 条，并隐藏 LLM Judge 分数以减少锚定偏差。

当前工具仍提供旧的事实分、自洽分、关键错误、备注和是否通过字段，尚未适配已经
冻结的[人工盲审协议 v1.0](EVALUATION_RUBRIC.md#10-人工盲审协议-v10)。正式审核要求：

- 12 条按 `scenario_type` 分层抽样。
- 至少两名领域审核者独立、盲法、逐检查项评分并引用原文证据。
- 报告线性加权 Cohen's kappa 和平均绝对分差。
- 不把“审核者更喜欢另一种打法”判为事实错误。

## 7. 当前状态

| 项目 | 状态 |
|---|---|
| 50 条测试输入 | 已冻结 |
| 推理脚本修正 | 已完成 |
| Judge 关联与错误统计修正 | 已完成 |
| fixed-KB 开发 E1～E5 Judge | DEV-KB-0002 已完成 18/18 有效评分 |
| 完整 Schema 校验 | 已完成 |
| 人工抽查工具 | 已完成旧版，Rubric 已冻结、代码待适配 |
| E1～E5 Rubric | 已冻结；开发 Judge 已适配，正式 Judge/人工仍待统一 |
| 本地单元测试 | 全项目 47/47 通过 |
| 修正后的 baseline 推理 | 未运行 |
| Lineup Analysis Output Schema v2 | 已接受；机器 Schema、示例和测试已完成 |
| Baseline Prompt/校验器迁移到 v2 | 未完成 |
| 修正后的 LLM Judge | 未运行 |
| 正式人工抽查 | 未运行 |

`experiments/LEGACY-0001/model_outputs.jsonl` 和
`judge_results.jsonl` 生成时间早于修正代码，是历史产物。旧 Judge
没有获得真实阵容输入，不能作为正式 baseline 分数。

## 8. 正式运行顺序

当前暂不运行。历史结果已归档到 `experiments/LEGACY-0001/`，修正后的
默认实验目录是 `experiments/EXP-0001/`。脚本拒绝覆盖已有结果；新实验
应设置新的 `LOL_EXPERIMENT_ID`。以下命令仍对应历史 v1 输出，在完成 v2 迁移前只供
工程参考，不得据此生成正式结果。

```bash
cd /root/autodl-tmp/lol-draft-alignment

export LOL_EXPERIMENT_ID="EXP-0001"
# 可选：export LOL_MODEL_PATH="/absolute/model/path"

python src/baseline/run_baseline_eval.py
python src/baseline/calculate_baseline_metrics.py
python src/baseline/run_llm_judge.py
python src/baseline/human_review.py prepare
```

人工填写完成后：

```bash
python src/baseline/human_review.py summarize
```

## 9. Baseline 完成标准

只有同时满足以下条件，Baseline v1 才能标记为完成：

- 50 条确定性推理全部生成并保存真实输入。
- 程序指标完成。
- Judge 对所有成功请求完成有效评分，失败项单独报告。
- 完成人工抽查或明确记录为何暂不进行。
- Judge、人工审核与汇总结果符合 Evaluation Rubric v1.0；旧两个聚合分数不能替代。
- 将模型、数据哈希、Prompt、解码参数、代码状态、指标和结果路径追加到
  `EXPERIMENT_LOG.md`。

由于正式任务范围已经收窄，下一次正式运行改用输出契约 v2；必须额外满足 Prompt、
程序校验、Judge 和人工审核都读取同一份 v2 定义。历史 v1 完成标准仅供追溯。

## 10. 已知局限

- 测试集只有 50 条，置信区间和类别细分能力有限。
- 16.16.1 ruleset 是事后绑定的评估目标，原测试阵容的创作版本未知，不能据此宣称其代表对应版本的 meta。
- `scenario_description` 提供了阵容意图提示，不是纯阵容盲测。
- 任务没有专家参考答案，Judge 和人工审核只能评估合理性而非唯一正确性。
- 输出契约 v2 已移除 `cot_reasoning`，但当前运行代码尚未迁移。
- Prompt 和大部分实验参数仍在代码里；路径与实验 ID 已集中管理，完整配置版本化尚未完成。
- 当前是 closed-book 诊断，机制错误会同时包含“缺知识”和“不会推理”两种原因。

## 11. 未来 Fixed-KB Baseline

知识库实现后建立独立的 open-book / fixed-KB 实验，不覆盖当前 baseline：

| 实验 | 目的 |
|---|---|
| A. 基座模型，无知识库 | 测量原始知识与推理能力 |
| B. 基座模型 + 固定知识快照 | 测量知识库与知识使用带来的提升 |
| C. SFT 模型 + 同一固定知识快照 | 测量微调带来的推理提升 |

SFT 的主要有效性比较是 B 与 C。B、C 必须使用相同测试输入、输出协议、检索逻辑、
`ruleset_id`、`ddragon_version`、`ruleset_as_of` 和 `knowledge_snapshot_id`。

Fixed-KB 实验除五个一级维度外，新增检索完整性、版本一致性、知识忠实度和无依据
扩写检查。生产知识库可以动态更新，但正式实验必须固定快照以保证可复现。


### 开发验证结果（非正式）

2026-08-24 使用同一 9 条分层样本完成 `DEV-KB-0001` 与 `DEV-KB-0002`。两轮均使用
Qwen2.5-7B-Instruct、greedy、相同输出 Schema 和固定知识快照；第二轮额外显式绑定
阵营、位置、输入称号与标准名。

- closed-book 的 JSON/Schema 均为 9/9。
- fixed-KB 两轮均为 8/9；失败均是尾逗号，不当作语义 0 分。
- 隐藏条件单审核者总体偏好：第一轮 closed-book 7、fixed-KB 2；第二轮 6:3。
- 第二轮 fixed-KB 平均输入 6,179.667 tokens，较闭卷增加 5,267.556；平均推理延迟
  增加 7.308 秒。
- 单审核者观察到的主要问题不是检索缺失，而是模型在十张长卡片中发生跨英雄、跨位置和技能槽位错配。

E1～E5 Judge API 对 `DEV-KB-0002` 的 18 份输出全部有效评分：closed-book 6 胜、
fixed-KB 3 胜，语义综合分均值 1.894 对 1.699；fixed-KB 知识忠实度均值仅 1.167/5，
跨实体混淆为 5/9，无依据机制断言 50 条，均差于 closed-book 的 4/9 与 30 条。

因此当前完整十卡 Prompt 暂不进入正式 50 条实验。该结果仍只有 9 条开发样本、单个
LLM Judge 且未经专家盲审校准；下一步测试压缩后的关键机制上下文。
