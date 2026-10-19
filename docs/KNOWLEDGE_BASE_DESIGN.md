# 版本化英雄知识库设计

状态：Knowledge Base Design v2.2（全英雄快照与五技能紧凑上下文 v2 已生成）  
最后更新：2026-08-26

## 1. 目标与边界

知识库为阵容分析模型提供指定版本下可追溯的英雄机制事实，减少新英雄、重做和版本变化
对推理评估的混杂。它负责“英雄能做什么”，模型负责推导“十名英雄组合后会发生什么”。

首个 ruleset：

- Data Dragon：`16.16.1`
- 公开补丁别名：`26.16`
- 知识截止：`2026-08-21`
- 区域：`global_pc`
- 快照：`kb-lol-pc-16.16.1-zh-CN-v1`

知识库不保存英雄克制、阵容协同结论、制胜条件、胜率、出装、职业赛 Meta 或
`engage=high` 一类主观战术评级。这些是推理结果或动态数据，不是稳定英雄事实。

## 2. 当前架构

```text
固定来源 URL / Wiki revision
        ↓ 保存原始响应、时间和 SHA-256
source snapshot（728 份）
        ↓ 确定性字段读取与客户端标记解析
Champion Knowledge Card v2（173 张，事实母版）
        ↓ 确定性渲染
full context / compact-mechanics-v2（五技能当前视图）
                    / compact-mechanics-v1（历史有损视图，只供复现）
        ↓ 别名精确解析、1～10 名英雄查询、显式选择 context view
Base / Few-shot / SFT 模型
```

阵容输入已经明确给出英雄，因此第一版不需要向量检索。稳定 ID + 固定快照的精确查询
更可复现，也不会召回同名的 Wild Rift、TFT 或历史页面。

## 3. 来源层级

| 来源 | 用途 | 版本记录 | 注意事项 |
|---|---|---|---|
| Riot Data Dragon | ID、中英文名、技能名、官方概述、资源 | `ddragon/16.16.1` | 全量事实主干 |
| CommunityDragon 客户端数据 | 中文详细技能描述、标记、角色、近远程和客户端五维 | `communitydragon_patch/16.16` | 社区提供的客户端提取，不是 Riot 正式支持 API |
| Riot 英雄页 | 卡级官方页面交叉来源 | `live_as_of/2026-08-21` | 内容按知识截止日冻结 |
| Riot 26.16 补丁说明 | 公开补丁别名与本版改动 | `public_patch/26.16` | 自动识别到 7 名召唤师峡谷改动英雄 |
| LoL 官方 Wiki | 技能模板、复杂交互和修订追踪 | `wiki_revision/<revision_id>` | Riot 支持、社区维护；严格使用 PC 主命名空间 |

Wiki 共冻结 860 个技能模板，Passive/Q/W/E/R 槽位覆盖 831/865。剩余 34 个槽位主要由
组合、强化或二段技能模板组织方式导致，卡片已显式记录 `wiki_ability_gap`；这些槽位仍有
Data Dragon、中文客户端数据和 Riot 英雄页来源，不是主事实缺失。

批量重新分发来源内容前需另行检查各来源当时的许可与署名要求。本项目当前保存这些快照
用于内部研究的复现和出处追踪。

## 4. Champion Knowledge Card v2

机器契约：`schemas/champion_knowledge_card_v2.schema.json`。

每张卡只包含五类内容：

1. 身份与版本：稳定 ID、中英文名称、称号、别名、资源、ruleset。
2. 客户端分类：官方角色、默认近远程、难度和客户端 playstyle 数值。
3. Passive/Q/W/E/R：中英文技能名、官方概述、中文详细描述。
4. 确定性提示：从客户端 HTML-like 标记提取的伤害类型、状态词和原始 markup tag。
5. 来源与质量：每个来源 URL、版本命名空间、抓取时间、原始路径、哈希和 Wiki 修订。

v2 不让 LLM 补写技能事实。若客户端没有明确标记，字段保留 `unknown` 或依赖原文，不凭
模型参数记忆猜测。复杂形态的完整概述优先保留 Data Dragon 合并描述，客户端展开作为
补充。例如杰斯上下文同时包含锤/炮概述与客户端当前展开。

## 5. 数值策略

原始响应完整保留精确数值、变量和系数；中文 RAG 上下文不展开普通伤害成长数值。
CommunityDragon 的模板变量统一渲染为 `【数值】`，保留以下信息：

- 伤害类型和是否造成伤害；
- 控制、位移、防御和功能效果；
- 触发条件、目标限制和形态差异；
- “随蓄力/距离/已损失生命变化”等机制关系。

若后续任务需要精确数值计算，应单独实现变量解析器并创建新 context template，不能把
当前 `【数值】` 当成精确数据。

## 6. 质量状态

当前卡片状态统一为 `source_grounded_auto`：

- 原始来源已冻结并校验哈希；
- 卡片通过 JSON Schema、版本、引用、别名和 Passive/Q/W/E/R 完整性校验；
- 结构化提示由确定性解析产生；
- 没有逐英雄人工专家审核；
- 不声称是专家战术真值。

它可以进入“来源约束的 fixed-KB”实验，因为模型看到的是来源事实，而不是未经审核的
主观战术标签。实验报告必须记录 snapshot ID、卡片/上下文哈希与质量状态。若任务升级到
精确数值计算或高风险生产决策，再针对相关字段增加人工或规则复核。

## 7. 精确上下文

`src/knowledge_base/query_kb.py` 接受 1～10 个常用中文名、官方中文称号、英文名或稳定 ID，
并通过 `--context-view` 显式选择完整或紧凑视图：

```bash
python src/knowledge_base/query_kb.py 波比 Camille 杰斯
python src/knowledge_base/query_kb.py --context-view compact-mechanics-v2 波比 Camille 杰斯
```

处理规则：

1. 通过冻结 `aliases.json` 精确映射到稳定 ID；冻结测试集使用的官方称号已全部覆盖。
2. 未知名称、未知视图、别名冲突和重复英雄 fail closed。
3. `full` 保留知识快照中的完整机制上下文；`compact-mechanics-v2` 是当前可重建派生
   视图，不修改 Champion Knowledge Card 事实母版。
4. v2 强制每名英雄完整包含 Passive/Q/W/E/R，任一槽位缺失或重复时构建失败；不再进行
   top-k 技能选择。紧凑化只能压缩表达，不能删除完整技能槽位。
5. `compact-mechanics-v1` 对 159 名英雄有损保留四个槽位，已弃用且只用于复现
   `DEV-KB-0003`，不得作为新实验默认视图。
6. 蓝红方、位置、输入称号、标准名和 stable ID 由 fixed-KB 实验脚本显式绑定。
7. 实验记录 snapshot ID、context view ID、清单哈希和拼装后上下文哈希，供 Judge
   重建完全相同的参考知识。

## 8. 数据与实现

- 完整卡构建器：`src/knowledge_base/full_kb_builder.py`
- 紧凑视图生成器：`src/knowledge_base/compact_context.py`
- 查询器：`src/knowledge_base/query_kb.py`
- 来源快照：`data/knowledge/source_snapshots/sources-lol-pc-16.16.1-asof-2026-08-21-v1/`
- 知识快照：`data/knowledge/snapshots/kb-lol-pc-16.16.1-zh-CN-v1/`
- v2 Schema：`schemas/champion_knowledge_card_v2.schema.json`
- 全量验证：`tests/test_full_knowledge_base.py`

当前统计：728 份冻结来源，约 45 MB；173 张卡；完整、v1 和 v2 视图各 173 份中文
上下文；7 名 26.16 改动英雄；42 个项目测试全部通过。v2 的 173 名英雄均为
Passive/Q/W/E/R 五槽，覆盖 865/865，全库字符数为完整视图的 72.36%。v1 的 64.26%
和 `DEV-KB-0003` 结果仅作为历史有损方案记录。`DEV-KB-0004` 已使用 v2 运行同一
9 条：Prompt 覆盖 450/450 槽位、JSON/Schema 9/9，但机制接受度审核 0/9 完全通过；
未调用 Judge API。`DEV-KB-0005` 的强模型容量对照相对注入 KB 为 6/9 完全通过，
同时发现卡莉丝塔 R 的紧凑描述遗漏“只能作用于预先绑定的誓约者”条件。当前冻结快照
不原地修补；该漏项标记为已确认限制，后续通过新 snapshot ID 修正。

## 9. 版本更新策略

- 当前 source snapshot 和 knowledge snapshot 只读，不原地刷新线上页面。
- 新 Data Dragon 构建或新的知识截止日创建新的 snapshot ID。
- 先比较来源哈希和补丁变化，只重建受影响英雄；未变化卡可按内容哈希复用。
- Wiki 必须记录具体 revision ID，不能只保存“当前页面”链接。
- 实验不得使用 `latest` URL 或无版本的动态上下文。

## 10. v1 Pilot 的定位

`ddragon_importer.py`、`pilot_annotations.py`、`normalized/16.16.1/zh-CN/` 和
Champion Knowledge Card v1 是五卡 Schema 原型。它包含模型候选战术画像，未人工审核，
现已被 v2 全量来源约束设计取代；数据继续保留以追溯设计演进，但不进入当前快照。

## 11. 下一步

四个 Qwen2.5-7B 的 9 条开发实验都不支持把当前 fixed-KB Prompt 扩到正式 50 条：
完整上下文的 `DEV-KB-0001/0002` 分别只胜 2/9、3/9；四技能紧凑上下文的
`DEV-KB-0003` 只胜 2/9；五技能 `DEV-KB-0004` 的机制接受度为 0/9 完全通过。
紧凑视图解决了 token、延迟和 JSON 合法率，但没有解决 7B 知识使用错误。常见失败包括：

- 把某英雄的突进、护盾或控制模板复用给同阵容其他英雄；
- 即使上下文提供正确槽位，输出仍把机制绑定到错误的 Q/W/E/R；
- 分路策略只谈 ADC，遗漏双方辅助及真实双人路交互；
- 非常规分路中重新排列或遗漏输入英雄。

`DEV-KB-0005` 用 GPT-5.6-sol 生成相同 9 个 fixed-KB Prompt，相对注入 KB 为 6/9
完全通过、端到端真实机制为 5/9；说明更强模型能显著改善绑定，但仍不能替代知识条件
完整性和确定性校验。

下一步不再只做长度压缩，而是进行以下最小验证：

1. 基于冻结来源建立后继知识快照，补充卡莉丝塔 R 的誓约者等关键触发条件；不原地修改
   已用于实验的 `kb-lol-pc-16.16.1-zh-CN-v1`。
2. 将下一候选改为逐技能原子事实和显式 fact ID 引用，并在生成战术文案前校验阵营、
   位置、英雄与槽位；不再继续增加上下文长度。
3. 若事实引用与确定性校验后仍跨实体，再停止 Prompt 工程，转向知识使用 SFT pilot。
4. 强模型输出可作为教师候选，但必须通过同一事实校验，不能因为模型更强而直接当真值。

正式 closed-book 与 fixed-KB Baseline 均未重新运行。
