# Knowledge Base

当前正式实现是一个固定、全量、来源可追溯的 LoL PC 16.16.1 中文英雄机制知识库。
精确查询同时支持常用中文名、官方中文称号、英文名和 stable ID；冻结测试集 50/50 条
阵容已通过十英雄解析回归测试。

## 当前快照

- ruleset：`lol-pc-ddragon-16.16.1-asof-2026-08-21`
- 知识快照：`kb-lol-pc-16.16.1-zh-CN-v1`
- 覆盖：173 名标准英雄，每名 Passive/Q/W/E/R
- 状态：173 张 `source_grounded_auto`，0 张人工专家审核
- 边界：只保存英雄事实与客户端结构化提示，不保存克制、阵容结论、胜率、出装或主观战术评级

来源包括固定 Data Dragon 16.16.1 中英文数据、CommunityDragon 16.16 中文客户端数据、
Riot 英雄页、26.16 官方补丁说明和 LoL 官方 Wiki 的具体修订。每个来源保存 URL、
抓取时间、版本命名空间、原始路径和 SHA-256。

## 构建

首次冻结来源并生成全部卡片：

```bash
python src/knowledge_base/full_kb_builder.py
```

从已冻结来源离线重建完整事实快照，再生成当前五技能紧凑派生视图：

```bash
python src/knowledge_base/full_kb_builder.py --build-only
python src/knowledge_base/compact_context.py --build
```

构建器没有 `latest` 模式。来源 manifest 存在后只校验本地内容哈希，不会静默刷新。
新版本必须使用新的 source snapshot 与 knowledge snapshot ID。

## 精确查询

按中文名、英文名或稳定 ID 查询 1～10 名英雄：

```bash
python src/knowledge_base/query_kb.py 波比 Camille 杰斯
python src/knowledge_base/query_kb.py --context-view compact-mechanics-v2 波比 Camille 杰斯
```

默认视图是 `full`；需要结构化输出时增加 `--json`。未知视图、未知名称和重复英雄都会
fail closed。当前 `compact-mechanics-v2` 从完整知识卡确定性生成，并强制每名英雄完整
保留 Passive/Q/W/E/R；历史 `compact-mechanics-v1` 因有损删除技能槽位而弃用，只保留
用于复现 `DEV-KB-0003`。派生视图都不会反向修改事实母版。

## 文件入口

- v2 Schema：`schemas/champion_knowledge_card_v2.schema.json`
- 来源 manifest：`data/knowledge/source_snapshots/sources-lol-pc-16.16.1-asof-2026-08-21-v1/manifest.json`
- 快照 manifest：`data/knowledge/snapshots/kb-lol-pc-16.16.1-zh-CN-v1/manifest.json`
- 卡片：`data/knowledge/snapshots/kb-lol-pc-16.16.1-zh-CN-v1/cards/`
- 中文上下文：`data/knowledge/snapshots/kb-lol-pc-16.16.1-zh-CN-v1/contexts/`
- 完整聚合上下文：`data/knowledge/snapshots/kb-lol-pc-16.16.1-zh-CN-v1/contexts.jsonl`
- 当前五技能紧凑视图：`data/knowledge/context_views/kb-lol-pc-16.16.1-zh-CN-v1/compact-mechanics-v2/`
- 历史有损视图：`data/knowledge/context_views/kb-lol-pc-16.16.1-zh-CN-v1/compact-mechanics-v1/`

客户端详细描述中的版本化数值变量渲染为 `【数值】`。这保留了机制、条件与效果类型，
避免把未解析的模板变量或无关伤害成长塞进 RAG。双形态技能同时保留 Data Dragon
合并概述和客户端当前形态的详细展开。

`ddragon_importer.py` 与 v1 五卡数据是早期 Schema/pilot 原型，只供追溯，不是当前
全量知识快照。
