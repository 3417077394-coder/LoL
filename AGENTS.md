# AGENTS.md

本文件适用于 `/root/autodl-tmp/lol-draft-alignment` 及其全部子目录。

## 1. 开始工作前

任何协作者或 AI 在修改项目前，按顺序阅读：

1. `README.md`
2. `docs/PROJECT_DESIGN.md`
3. 与任务相关的模块文档：
   - Baseline：`docs/BASELINE_DESIGN.md`、`docs/EVALUATION_RUBRIC.md`
   - 数据：`docs/DATA_DESIGN.md`、`docs/CAPABILITY_TAXONOMY.md`、
     `docs/DATA_REQUIREMENTS_MATRIX.md`、`docs/KNOWLEDGE_BASE_DESIGN.md`
   - 实验：`docs/EXPERIMENT_LOG.md`
4. `docs/DECISIONS.md`
5. 目标目录下更具体的 README 或 AGENTS.md（如果存在）

聊天记录不作为项目事实来源。若用户提供的新要求与文档冲突，以用户当前
要求为准，并在同一次修改中更新文档和决策记录。

## 2. 当前项目事实

截至 2026-08-26：

- 当前阶段是固化 closed-book / model-only zero-shot baseline。
- Baseline、知识库和紧凑上下文开发对照代码已修正；47 个本地单元测试全部通过。
- E1～E5 的 Evaluation Rubric v1.0 已冻结；fixed-KB 开发 Judge、评估 Schema 和
  汇总代码已完成 18/18 有效 API 评分。正式旧 Judge 与人工审核仍待统一适配。
- 修正后的 baseline 尚未重新运行。
- `Lineup Analysis Output Schema v2` 已接受并完成机器 Schema、说明性示例和回归测试；
  第一阶段只做匹配位置的静态阵容分析，不要求逐路操作教学。当前 Baseline Prompt、
  指标、Judge 和人工审核仍使用或兼容历史 v1，尚未迁移，也没有运行 v2 实验。
- 现有 baseline 和 Judge JSONL 是历史产物，不能作为正式基线。
- 当前 50 条测试集属于冻结测试集，禁止进入训练或 few-shot 示例。
- EXP-0001 的工程 ruleset 已冻结为 Data Dragon 16.16.1、官方补丁别名 26.16、
  知识截止日 2026-08-21；测试集原始创作版本未知，不能把 `scenario_type` 当作该
  ruleset 的专家竞技结论。
- Champion Knowledge Card v2 全量快照 `kb-lol-pc-16.16.1-zh-CN-v1` 已完成，覆盖
  173 名英雄和中文精确查询；官方称号别名已覆盖冻结测试集 50/50 条阵容；状态为
  `source_grounded_auto`，不是人工专家战术真值。
- 历史 `compact-mechanics-v1` 只用于复现 `DEV-KB-0003`。五技能
  `compact-mechanics-v2` 已用于 `DEV-KB-0004`：Prompt 槽位覆盖 450/450、JSON/Schema
  9/9，但机制接受度审核 0/9 完全通过（7 条严重、2 条中等）；未调用 Judge API。
- `DEV-KB-0005` 使用 GPT-5.6-sol 生成与 `DEV-KB-0004` 哈希逐条一致的 9 个 fixed-KB
  Prompt：API/JSON/Schema 9/9；相对注入 KB 6/9 完全通过，端到端真实机制 5/9。
  它是强模型容量对照，不是 Judge 自评、正式 Baseline 或 SFT 结果。
- `DEV-KB-0001/0002/0003` 均为同一 9 条开发验证，不是正式 Baseline。fixed-KB 的隐藏
  条件胜场依次为 2/9、3/9、2/9；`DEV-KB-0002` 的 E1～E5 Judge API 同样仅胜 3/9，
  `DEV-KB-0003` 未调用 Judge API。当前不得扩到正式 50 条 fixed-KB。
- 下一步先把 Baseline Prompt、程序校验、Judge 和人工审核迁移到输出契约 v2；KB 条件
  漏项和知识使用验证保留为后续工作。迁移完成前不得运行正式 Baseline，也不得直接扩到
  50 条 fixed-KB。
- 人工审核协议 v1.0 已冻结，但实现代码尚未适配。
- fixed-KB 开发 Judge API 已运行；最终 18 份评分全部有效。正式 closed-book baseline、
  正式 Judge 和双人专家审核仍未运行。

每次开始任务都应重新核对这些状态是否已被后续文档更新。

## 3. 文档同步规则

不是所有修改都更新所有文档，只更新受影响的部分：

| 修改类型 | 必须检查或更新 |
|---|---|
| 项目目标、范围、阶段 | README、PROJECT_DESIGN、DECISIONS |
| Baseline Prompt、解码、Schema、指标 | BASELINE_DESIGN、DECISIONS |
| E1～E5 评分项、封顶、汇总、人工盲审协议 | EVALUATION_RUBRIC、BASELINE_DESIGN、DECISIONS |
| 数据 Schema、切分、版本、用途 | DATA_DESIGN、DECISIONS |
| 阵容分析输出字段、枚举和任务边界 | LINEUP_ANALYSIS_OUTPUT_SCHEMA、BASELINE_DESIGN、DECISIONS |
| 能力标签、采集优先级、SFT 覆盖目标 | CAPABILITY_TAXONOMY、DATA_REQUIREMENTS_MATRIX、DATA_DESIGN、DECISIONS |
| 知识卡 Schema、事实边界、快照与上下文生成 | KNOWLEDGE_BASE_DESIGN、DATA_DESIGN、README、DECISIONS |
| 正式运行实验 | EXPERIMENT_LOG、README 当前状态 |
| 重要设计取舍 | DECISIONS |
| 纯格式、注释或内部重构 | 通常无需设计文档；若行为变化则必须更新 |

修改文档时：

- 使用明确状态：已完成、进行中、计划中、无效。
- 不把计划写成已完成。
- 不把结构清洗数据称为专家语义黄金答案。
- 更新“最后更新”日期。
- 保持 README 简短，把细节放在对应设计文档。

## 4. 实验和结果规则

- 冻结测试集不得进入训练、few-shot 或偏好数据。
- 正式实验必须使用唯一 ID。
- 不静默覆盖正式实验产物。
- API 失败、解析失败和缺失值单独统计，不伪造成模型低分。
- 实验记录必须包含模型、数据版本/哈希、Prompt、解码、Judge 和结果路径。
- 文档、重构或测试任务不得顺带调用付费 API。
- 长时间 GPU 运行或外部 Judge 调用必须在任务授权范围内。
- 开发测试不能冒充正式实验。

## 5. 修改代码时

- 先阅读相关实现和当前文档，确认是否存在用户改动。
- 保持改动范围最小，不覆盖无关文件。
- 为关键数据关联、错误处理和 Schema 规则补测试。
- 代码与文档发生冲突时，明确指出并修复，不能默默选择一个版本。
- 项目根目录使用 Git 记录代码与文档；模型权重和运行缓存保持在项目外。
- 即使有 Git，也不得静默覆盖正式实验结果。

## 6. 完成任务时

交付说明至少包含：

- 实际完成的结果。
- 修改的代码和文档。
- 执行的验证及结果。
- 没有执行但用户可能误以为已执行的步骤。
- 当前项目状态和下一安全步骤。

如果本次修改改变了正式设计，应同时更新 `docs/DECISIONS.md`；如果只提出
建议但未获确认，应标记为 Proposed，不能写成 Accepted。
