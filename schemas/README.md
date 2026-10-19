# Schemas

Baseline v1 输出契约目前由以下两处共同描述：

- `docs/BASELINE_DESIGN.md`
- `src/baseline/calculate_baseline_metrics.py` 中的 `EXPECTED_SCHEMA`

正式 SFT 数据生成前，应把输出契约固化为机器可读 Schema，并让评估代码
从该文件加载，避免文档和代码漂移。

当前已有：

- `capability_catalog_v1.json`：五个一级评估维度与 19 个二级诊断标签的机器可读目录。
- `baseline_error_annotation_v1.schema.json`：通过 `sample_id` 关联 baseline
  输出的旁路原子错误标注契约。
- `champion_knowledge_card_v1.schema.json`：以 Data Dragon 构建为工程主版本的英雄
  知识卡契约，区分公开补丁别名、知识截止日、来源事实、规范化机制、战术属性、出处
  与审核状态。
- `examples/champion_knowledge_card_v1.example.json`：仅用于结构校验的合成样例，
  明确禁止作为真实英雄事实入库。
- `champion_knowledge_card_v2.schema.json`：当前全量来源约束英雄卡契约；移除主观战术
  画像，保留中英文事实、中文客户端详细机制、确定性标记、逐来源哈希与 Wiki 修订。
- `kb_judge_evaluation_v1.schema.json`：fixed-KB 开发实验的 E1～E5 与 KB1～KB5
  Judge 契约，包含证据、严重度、置信度和封顶记录。
- `lineup_analysis_output_v2.schema.json`：第一阶段静态阵容分析的目标输出契约；使用
  受控阵容类型和交战条件标签，同时保留自由解释、决定性交互和双向制胜条件。
- `examples/lineup_analysis_output_v2.example.json`：仅用于说明字段和回归测试的输出
  示例，不是专家黄金答案，也不得进入训练或 few-shot。

输出契约 v2 已接受，但 Baseline Prompt、指标、Judge 和人工审核尚未迁移。现有
`EXPECTED_SCHEMA` 仍表示历史 Baseline v1，不得将两者的格式率或语义分数直接比较。

开发用五维 Judge Schema 已实现；正式 EXP-0001 前仍需统一 closed-book Judge、
人工审核和正式汇总代码使用的协议，避免再次出现协议漂移。

能力目录与人类可读定义必须同步维护；权威解释见
`docs/CAPABILITY_TAXONOMY.md`。错误标注文件不得写回冻结测试集，也不得进入
few-shot 或训练数据。
