# Knowledge Data

状态：LoL PC 16.16.1 全英雄来源约束知识快照已建立。

```text
data/knowledge/
├── source_snapshots/
│   └── sources-lol-pc-16.16.1-asof-2026-08-21-v1/
│       ├── ddragon/             # Riot Data Dragon 16.16.1 中英文数据
│       ├── communitydragon/     # 16.16 中文客户端结构化数据
│       ├── riot/                # Riot 英雄页与 26.16 补丁说明
│       ├── wiki/                # LoL 官方 Wiki 页面与技能模板修订
│       ├── indexes/             # Wiki 修订到英雄/技能槽的派生索引
│       └── manifest.json        # 728 份原始来源的 URL、版本和 SHA-256
├── snapshots/
│   └── kb-lol-pc-16.16.1-zh-CN-v1/
│       ├── cards/               # 173 张 Champion Knowledge Card v2
│       ├── contexts/            # 每英雄中文 RAG 上下文
│       ├── aliases.json         # 中英文名与稳定 ID 精确映射
│       ├── contexts.jsonl       # 聚合上下文
│       └── manifest.json        # 卡片与上下文哈希
├── raw/                         # 历史五卡 pilot 原始数据
├── normalized/                  # 历史五卡 v1 候选
├── context_views/
│   └── kb-lol-pc-16.16.1-zh-CN-v1/
│       └── compact-mechanics-v1/ # 173 份可重建的紧凑派生上下文
│           ├── contexts/
│           └── manifest.json     # 来源卡与派生上下文哈希
└── reports/                     # 历史 pilot 报告
```

当前正式机器契约：`../../schemas/champion_knowledge_card_v2.schema.json`。  
构建与查询说明：`../../src/knowledge_base/README.md`。  
设计边界：`../../docs/KNOWLEDGE_BASE_DESIGN.md`。

当前 173 张卡均为 `source_grounded_auto`：内容来自冻结来源并经过确定性转换，适合
来源约束的中文 RAG，但不声称经过逐英雄专家审核。v1 的 5 张 `generated` 卡保留为
历史原型，不进入当前快照。

`context_views/` 不是真实事实的第二份手工维护副本；它由冻结卡片确定性生成。当前
`compact-mechanics-v1` 的字符数为完整上下文的 64.26%，只用于后续开发对照，尚未证明
模型语义表现提升。
