# 实验账本

最后更新：2026-08-26

## 1. 使用规则

本文件是正式实验的追加式账本：

- 只记录实际运行过的实验；计划不能伪装成结果。
- 已完成实验不静默修改。发现错误时追加“更正”并说明影响。
- 每个实验使用唯一 ID。
- 正式结果应保存到独立目录，不能反复覆盖同名文件。
- 必须记录失败请求数和排除规则，不能只记录平均分。
- 结果必须能够追溯到模型、数据、Prompt、代码和运行配置。

建议实验 ID：

- `EXP-0001`：正式实验。
- `DEV-xxxx`：开发验证，不进入正式结论。
- `LEGACY-xxxx`：文档系统建立前的历史产物。

## 2. 当前实验索引

| ID | 类型 | 状态 | 是否可作正式对照 | 说明 |
|---|---|---|---:|---|
| LEGACY-0001 | Zero-shot baseline | 历史产物 | 否 | Judge 未获得真实阵容，且包含 API 失败伪 0 分问题 |
| EXP-0001 | 修正后的 Zero-shot baseline | 计划中，未运行 | 否 | 先完成 Evaluation Rubric v1.0 的代码适配与实验冻结 |
| DEV-KB-0001 | Closed-book vs 完整十卡 KB | 已完成 | 否 | 无阵营/位置卡头；closed-book 隐藏条件偏好 7:2 |
| DEV-KB-0002 | Closed-book vs 位置绑定十卡 KB | 已完成 | 否 | 隐藏偏好与 Judge API 均为 closed-book 6:3 |
| DEV-KB-0003 | Closed-book vs 紧凑机制 KB | 已完成 | 否 | 格式 9/9；closed-book 隐藏条件偏好 7:2；未调用 Judge API |
| DEV-KB-0004 | Closed-book vs 五技能紧凑 KB | 已完成 | 否 | 槽位 450/450；fixed-KB 机制接受度 0/9 完全通过；未调用 Judge API |
| DEV-KB-0005 | GPT-5.6-sol fixed-KB 容量对照 | 已完成 | 否 | 相同9个Prompt；相对KB 6/9、端到端5/9完全通过；未自评 |

当前没有可用于 few-shot/SFT 对比的正式 baseline 数字。

## 2.1 Fixed-KB 开发验证摘要

前四个 fixed-KB 开发实验均使用 Qwen2.5-7B-Instruct、9 条固定种子分层样本
`[1,4,10,15,19,20,21,27,36]`、greedy、`max_new_tokens=2048` 和知识快照
`kb-lol-pc-16.16.1-zh-CN-v1`。只有 `DEV-KB-0002` 已调用 E1～E5 Judge API；
四个实验都没有正式双人盲审；只有 `DEV-KB-0002` 调用了 Judge API。

第五个实验用 GPT-5.6-sol 仅生成同一批 fixed-KB Prompt，作为知识使用容量对照。

| 指标 | DEV-KB-0001 closed / KB | DEV-KB-0002 closed / KB | DEV-KB-0003 closed / KB | DEV-KB-0004 closed / KB |
|---|---:|---:|---:|---:|
| JSON 与完整 Schema | 9/9 / 8/9 | 9/9 / 8/9 | 9/9 / 9/9 | 9/9 / 9/9 |
| 平均输入 tokens | 875.111 / 5,821.000 | 912.111 / 6,179.667 | 912.111 / 4,426.889 | 912.111 / 4,818.222 |
| 平均输出 tokens | 687.111 / 683.556 | 645.556 / 797.778 | 645.556 / 745.667 | 645.556 / 751.556 |
| 平均延迟（秒） | 13.527 / 16.805 | 12.707 / 20.015 | 12.855 / 17.027 | 12.714 / 17.439 |
| 隐藏条件单审核者总体偏好 | 7 / 2 | 6 / 3 | 7 / 2 | 未执行 |

前三轮语义比较均在看条件密钥前冻结逐样本判断；第四轮改为专门检查 fixed-KB 是否忠实
使用已注入技能，未做隐藏偏好。审核者仍是执行任务的同一 AI 助手，因此都只作为开发
诊断。完整和紧凑上下文均未解决跨英雄、跨位置与槽位错配，当前结果不支持扩到正式
50 条 fixed-KB。

## 2.2 DEV-KB-0002：E1～E5 Judge API 结果

Judge 使用 `gpt-5.6-sol`、`prompts/kb_judge_e1_e5_v1.txt` 和同一份 16.16.1
十英雄参考知识评价两种条件；只有 fixed-KB 额外计算 KB1～KB5。E1.1/E1.2 来自程序
检查。最终 18/18 份评分有效，错误数为 0。

| 指标 | closed-book | fixed-KB | fixed-KB - closed |
|---|---:|---:|---:|
| E1 | 4.444 | 3.944 | -0.500 |
| E2 | 1.722 | 1.500 | -0.222 |
| E3 | 2.056 | 1.944 | -0.112 |
| E4 | 2.222 | 2.056 | -0.166 |
| E5 | 1.611 | 1.333 | -0.278 |
| 语义综合分 | 1.894 | 1.699 | -0.196 |
| 知识忠实度 | NA | 1.167 | NA |
| 跨实体混淆样本 | 4/9 | 5/9 | +1 |
| 无依据机制断言 | 30 | 50 | +20 |

成对结果为 closed-book 6 胜、fixed-KB 3 胜、无平局；fixed-KB 的逐样本差值为
`[+0.30, -0.07, -0.83, -0.47, +0.20, -0.70, -0.55, -0.37, +0.73]`。
9 条样本不足以作显著性或正式泛化结论，但与隐藏条件单审核者 6:3 的方向一致。

成功评分记录的 API 用量为 prompt 155,003、completion 92,865、合计 247,868 tokens。
首次 smoke 的两个请求因 `max_tokens` 不兼容返回 HTTP 400；第二次 smoke 收到两个
完整响应，但因让 Judge 自填固定 `capability_id` 而未通过协议，且当时未保存 usage，
所以失败 smoke 可能产生的用量不在上述合计中。修复后由程序确定性归一化标签，第三次
smoke 成功并复用到最终 18 份结果。

追溯信息：

- 成对输入 SHA-256：`794db6fbc2fe6dfd72f32fd2e92dce2477cdf4981cb663ddee0d782e1bde7593`
- Judge Prompt SHA-256：`a18111c0018d7a84c227e45a206133616ddca30af42876d34f3b40edfe601cc3`
- Judge Schema SHA-256：`3a6e834c54ae5c437d2de4b074b2a3f010dac80e8074c86fe50c22f988806a6d`
- 最终结果 SHA-256：`51be66a19a13fdfb8d5bbae14d24fde45f83b539fd8947b824b692075ef76155`
- 结果：`experiments/DEV-KB-0002/judge_results_e1_e5.jsonl`
- 汇总：`experiments/DEV-KB-0002/judge_summary_e1_e5.json`
- 合并配置：`experiments/DEV-KB-0002/judge_results_e1_e5.config.json`

结论：完整十英雄技能卡没有改善该 9 条开发样本，且模型对注入知识的实体绑定和忠实
使用很弱。下一实验应只改变上下文模板，改为位置绑定的关键机制摘要；不能把本结果
解释为知识库本身无效或正式 50 条 Baseline 结论。

## 2.3 DEV-KB-0003：紧凑机制上下文结果

`DEV-KB-0003` 只把 fixed-KB 的 context view 从完整十卡切换为
`compact-mechanics-v1`；closed-book 输出与 `DEV-KB-0002` 逐字一致。紧凑 fixed-KB
相较完整 fixed-KB 的平均输入减少 28.36%、平均输出减少 6.53%、平均延迟减少 14.93%，
并把 JSON/Schema 合法率从 8/9 恢复到 9/9。

隐藏条件单审核者比较为 closed-book 7 胜、fixed-KB 2 胜，fixed-KB 只在 sample 4 和
36 获胜。七个失利样本仍出现跨英雄复用控制/护盾/突进、技能槽位错配、遗漏辅助交互
和非常规分路实体错误。结果说明压缩改善工程成本，不足以让当前 7B 模型忠实使用知识。

本实验没有调用 Judge API；不能把隐藏单审核者结论当作正式统计或专家共识。

2026-08-25 更正：事后审核发现 `compact-mechanics-v1` 对 159/173 名普通英雄只保留
五个技能槽位中的四个，七个失利样本中确有亚索 W、莎弥拉 W、克格莫 W 等关键漏项。
因此本实验比较的不只是表达压缩，还改变了知识覆盖率；结果不能用于判断“完整技能知识
下的紧凑 RAG 是否有效”。历史产物和哈希保持不变。修复版 `compact-mechanics-v2`
当时已生成但尚未运行模型；随后以新 ID `DEV-KB-0004` 完成验证，不修改本实验产物。

追溯信息：

- 成对输出 SHA-256：`37156298148bcdc73a3ad16fea37c6de648b8e8894f320822184035ba892b96f`
- 自动汇总 SHA-256：`835265c3e2a575544381b7815ddc9765a1ce74b090ab449c0fa9b5676cfadae2`
- 隐藏比较 SHA-256：`a006f510016d74d5912917a23d0d16a09a83c9b6d72eebb2256b1ce3d77ee57b`
- 结果目录：`experiments/DEV-KB-0003/`

结论：不扩到正式 50 条。下一步先用失利样本区分读取、实体绑定与战术聚合错误，再测试
无 Q/W/E/R 槽位文字的原子事实或显式事实 ID 引用；若仍失败，转向知识使用 SFT pilot。


## 2.4 DEV-KB-0004：五技能知识接受度验证

`DEV-KB-0004` 使用同一模型、同一 9 条样本、greedy 和相同输出 Schema，将 fixed-KB
视图改为 `compact-mechanics-v2`。本轮两种条件都重新推理，不复用旧输出。

程序确认 9 个 fixed-KB Prompt 均含 10 名英雄，每名 Passive/Q/W/E/R，技能槽位覆盖
450/450。自动结果如下：

| 指标 | closed-book | 五技能 fixed-KB |
|---|---:|---:|
| JSON / Schema | 9/9 | 9/9 |
| 平均输入 tokens | 912.111 | 4818.222 |
| 平均输出 tokens | 645.556 | 751.556 |
| 平均延迟（秒） | 12.714 | 17.439 |

带证据的技能接受度审核判定 fixed-KB 0/9 完全通过，其中 7 条严重、2 条中等，共保存
27 条代表性错误。五技能有局部收益：sample 27 正确使用恢复注入的艾翁 W，卡特琳娜与
锐雯的旧错误减少；sample 20 不再出现卡尔玛 Q、蛮王 Q 晕眩。但主要问题仍存在：

- sample 10 把兰博的危险温度/技能模板复制给卢锡安和维迦；
- sample 15 已收到亚索 W 与莎弥拉 W，却不使用，并继续把辅助阿木木写成中野对手；
- sample 19 把“Q 隐身、E 突袭、R 控制”模板跨多个英雄复用；
- sample 36 把艾翁的草丛模板复制给乌迪尔，把卡尔玛式护盾模板复制给亚索。

结论：完整五技能已经排除“核心技能没有进入 Prompt”这一混杂因素，但当前 7B 仍不能
稳定读取和绑定十英雄技能事实。下一步不继续增加长度，而是验证逐技能结构化事实、
显式 fact ID 引用和阵营/位置/槽位确定性校验；方向改善前不扩正式 50 条。

本轮没有调用 Judge API，也没有独立专家盲审。机制审核是助手按输出原文与固定 KB
证据做的开发诊断，不是正式统计。

追溯信息：

- 成对输出 SHA-256：`b44ed1c86e80ef08534d5fc5142ea1d1eb8b65c3e1083c38951d854952c72a5f`
- 自动指标 SHA-256：`a9cf311e8a8a35854374be489ec3b6e500ab931fd668644705f9ea9e8df7c03c`
- 机制审核 JSONL SHA-256：`a4d89e60702212cf531e0381be5c28c023a4aae41433598494e5f3201028e095`
- 结果目录：`experiments/DEV-KB-0004/`

## 2.5 DEV-KB-0005：GPT-5.6-sol fixed-KB 容量对照

本实验只改变生成模型：使用 GPT-5.6-sol API 生成与 `DEV-KB-0004` 哈希逐条一致的
9 个 fixed-KB Prompt，不额外重跑 GPT closed-book，也不让 GPT-5.6-sol 给自己的输出
打 Judge 分。API 为兼容推理模型省略 temperature，且不支持本地 Transformers 的
repetition_penalty，因此不宣称逐解码参数完全等价。

自动结果：

- API 成功 9/9，失败 0；
- JSON 9/9、完整 Schema 9/9、数值硬约束触发 0/9；
- 平均延迟 39.836 秒（含网络）；
- API 用量为 prompt 50,757、completion 17,768、total 68,525 tokens，其中 reasoning
  tokens 为 643。

带证据开发审核显示：相对模型实际收到的 KB，6/9 完全通过、2 条中等、1 条严重；
若按真实游戏机制端到端检查，则为 5/9 完全通过，因为 sample 36 暴露了卡莉丝塔 R
誓约者条件没有进入紧凑 KB。模型自身的代表性错误为：

- sample 10 把兰博 W 的移速泛化为“位移”；
- sample 19 把奎因与萨科、阿克尚一起概括为“隐身”；
- sample 27 给莫甘娜虚构沉默，并让德莱文打断同队锐雯。

相比 `DEV-KB-0004` 的 Qwen2.5-7B 0/9 完全通过、7 条严重，GPT 显著减少大规模
模板复制、技能槽位错绑和辅助遗漏。这支持模型容量/知识绑定能力是 7B 失败的重要因素，
但 GPT 仍有孤立错误，且更强模型会暴露 KB 自身漏项，所以不取消结构化事实、条件字段
和确定性校验方向。

追溯信息：

- 输出 SHA-256：`fc7001d19d5476bab2913ac490de08b7695bdbf2f646f6abe8574288b5362b15`
- 结果目录：`experiments/DEV-KB-0005/`
- 完整配置：`experiments/DEV-KB-0005/config.json`
- 带证据审核：`experiments/DEV-KB-0005/mechanism_acceptance_audit.md`

本实验是方向性容量对照，不是正式 Baseline、SFT 结果或独立专家共识。

## 3. 历史产物：LEGACY-0001

- 输入快照：`experiments/LEGACY-0001/input_snapshot.jsonl`
- 推理结果：`experiments/LEGACY-0001/model_outputs.jsonl`
- Judge 结果：`experiments/LEGACY-0001/judge_results.jsonl`
- 推理结果生成时间：早于 2026-08-14 baseline 修正。
- Judge 结果生成时间：早于 2026-08-14 baseline 修正。
- 已知问题：
  - 推理记录没有保存 `input_prompt`。
  - Judge 从结果读取不存在的 `input_prompt`，实际得到“无对局特征”。
  - API 失败被写成 0 分并计入均值。
  - 推理使用采样而非当前冻结的 greedy 配置。
- 结论：只供错误分析和代码兼容性测试，不报告为正式 baseline。

旧结果上的程序格式指标曾为 JSON 100%、完整 Schema 100%、数值触发 0%。
这些数字只说明旧输出符合协议，不能修复语义评分的无效性。

## 4. 计划实验：EXP-0001

目标：生成可作为后续对照的 Baseline v1。

冻结条件：

- 模型：Qwen2.5-7B-Instruct。
- 数据：baseline-test-v1，50 条，哈希见 `DATA_DESIGN.md`。
- 评估 ruleset：Data Dragon 16.16.1，官方补丁别名 26.16，知识截止日 2026-08-21；
  绑定见 `data/eval/baseline-test-v1.metadata.json`。
- 限制：测试阵容的原始创作版本未知，不能声称代表该 ruleset 的 meta。
- 推理：zero-shot、greedy、`do_sample=false`。
- 输出协议：Baseline v1 Schema。
- Judge：按 `sample_id` 回连 canonical 测试集。
- 人工审核：按 Evaluation Rubric v1.0 分层盲审。
- 评估协议：Evaluation Rubric v1.0；Judge、人工审核和汇总代码适配后方可正式运行。
- 当前状态：未运行。
- 运行时机：评估代码、版本化配置/Prompt 和代码版本冻结，并获得用户明确运行授权后。

历史结果已归档到 `experiments/LEGACY-0001/`。正式输出将写入
`experiments/EXP-0001/`；脚本拒绝覆盖已有文件。新实验通过
`LOL_EXPERIMENT_ID` 使用新的独立目录。

## 5. 正式实验模板

复制以下模板并追加到文件末尾：

```markdown
## EXP-XXXX：实验名称

### 目标

本实验只验证什么假设？

### 冻结输入

- 日期：
- 模型及权重/adapter：
- 数据集版本：
- 数据集路径：
- 数据集 SHA-256：
- ruleset ID：
- Data Dragon 版本：
- 公开补丁别名：
- ruleset 知识截止日：
- 知识快照 ID（如适用）：
- Prompt 版本或完整路径：
- 输出 Schema 版本：
- 代码版本或文件哈希：

### 推理配置

- do_sample：
- temperature：
- top_p：
- max_new_tokens：
- repetition_penalty：
- seed：
- 其他：

### 评估配置

- 程序指标版本：
- Judge 模型：
- Judge Prompt 版本：
- Evaluation Rubric 版本：
- 五维评估 Schema 版本：
- 人工审核协议版本：
- 失败与缺失值处理：

### 结果

- 总样本数：
- JSON 合法率：
- 完整 Schema 合法率：
- 数值幻觉触发率：
- Judge 成功/失败数：
- Judge E1/E2/E3/E4/E5：
- Judge 语义综合分（辅助）：
- 各检查项 1/0.5/0/NA 分布：
- 二级标签与严重错误分布：
- 语义不可评率：
- 人工抽查样本数与审核者数：
- 人工 E1/E2/E3/E4/E5：
- 人工一致性（加权 kappa / 平均绝对分差）：
- 其他：

### 产物

- 完整配置：
- 原始输出：
- Judge 输出：
- 人工审核：
- 汇总报告：

### 结论

是否支持实验假设？主要错误类型是什么？下一步只改变哪个变量？

### 限制或异常

记录 OOM、API 失败、数据缺失、运行中断和任何事后修正。
```

## 6. 更正规则

如果历史实验后来被发现无效：

1. 不删除原条目。
2. 在索引中把状态改为“无效”或“部分有效”。
3. 追加一节说明发现日期、原因和受影响指标。
4. 分配新实验 ID 重新运行。
5. 不能复用旧 ID 覆盖原结果。
