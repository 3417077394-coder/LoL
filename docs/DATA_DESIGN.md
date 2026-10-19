# 数据设计

状态：Data Design v0.1  
最后更新：2026-08-25

## 1. 目标

建立清晰的数据生命周期和隔离边界，使测试输入、few-shot 示例、SFT
数据、偏好数据和模型输出不会互相污染，并让每个正式实验可以追溯到确切
数据版本。

## 2. 当前数据资产

### 测试数据引擎

代码目录：`src/data_engine/`

- `data/raw/`：生成模型的原始输入候选，允许包含失败样本。
- `data/processed/`：结构清洗后的候选，不能自动替换冻结 eval。
- `data/patches/`：针对类别缺口生成的补丁。
- `data/reports/`：缺口和校验报告。
- `data/reference/`：英雄名称等本地参考快照。
- `data/knowledge/`：版本化英雄知识卡、审核中间态、固定快照与校验报告。
- `src/data_engine/legacy/`：只供追溯。

### Baseline 冻结测试集

唯一 Canonical 文件：

`data/eval/baseline-test-v1.jsonl`

历史输入快照：

`experiments/LEGACY-0001/input_snapshot.jsonl`

版本元数据 sidecar：

`data/eval/baseline-test-v1.metadata.json`

截至 2026-08-21：

- Canonical 与历史快照均为 50 条。
- SHA-256 均为
  `e5b4e0d0a590ae64bad31ed7be272f3d7acb919441f1a2ff0b9f9671832e5682`。
- `standard_meta: 20`。
- `extreme_comps: 15`。
- `off_meta: 15`。

历史快照只用于复现实验，不是第二个 canonical 数据源。processed 候选
只说明结构清洗完成，不代表存在专家标准答案。

## 3. 当前测试样本 Schema

每条测试样本包含：

```json
{
  "scenario_type": "standard_meta | extreme_comps | off_meta",
  "scenario_description": "阵容意图的一句话描述",
  "draft_phase_lineup": {
    "blue_team": {
      "top": "英雄官方中文全称",
      "jungle": "英雄官方中文全称",
      "mid": "英雄官方中文全称",
      "bottom": "英雄官方中文全称",
      "support": "英雄官方中文全称"
    },
    "red_team": {
      "top": "英雄官方中文全称",
      "jungle": "英雄官方中文全称",
      "mid": "英雄官方中文全称",
      "bottom": "英雄官方中文全称",
      "support": "英雄官方中文全称"
    }
  }
}
```

当前缺少但未来正式数据应补充的元数据：

- `dataset_version`
- `ruleset_id`、`ddragon_version`、`public_patch_alias` 和 `ruleset_as_of`
  （Canonical 行内缺少；EXP-0001 通过 sidecar 事后绑定）
- `source`
- `created_at`
- `review_status`
- `reviewer_ids`
- `quality_flags`

## 4. 数据类别和允许用途

| 数据类别 | 允许训练 | 允许做 few-shot | 允许评估 |
|---|---:|---:|---:|
| 冻结 baseline 测试集 | 否 | 否 | 是 |
| Baseline 测试集上的模型输出 | 否 | 否 | 仅评估与误差分析 |
| 独立专家示例 | 是 | 是 | 只能进入独立验证集时评估 |
| 教师模型合成候选 | 审核后 | 审核后 | 不直接作为黄金评估 |
| SFT 训练集 | 是 | 可选 | 否 |
| SFT 验证集 | 否 | 否 | 是 |
| 偏好对 | 偏好训练 | 否 | 否 |
| 人工盲审记录 | 否 | 否 | 是 |

## 5. 防泄漏规则

冻结测试集建立后遵循：

1. 不把测试样本及其模型答案放入 SFT 或偏好训练。
2. 不把测试样本用作 few-shot 示例。
3. 不根据测试样本的 Judge 批注直接改写同一测试样本后加入训练。
4. 合成训练数据生成后，检查完整阵容重复和蓝红换边重复。
5. 在条件允许时，进一步检查英雄组合、关键对线和阵容原型的近似重复。
6. 测试集只用于阶段性评估，不能在每个小改动后反复人工挑选最优配置。
7. 若未来扩大或重建测试集，旧版本继续保留并分配新版本号，不能静默替换。

当前 50 条数量较少，仅按完整阵容去重仍可能存在组合层面的信息泄漏。
正式 SFT 前需要实现更严格的相似度或组合重合检查。

## 6. Future SFT 数据 Schema

建议使用标准聊天格式，并把实验需要的元数据与消息分开：

```json
{
  "messages": [
    {
      "role": "system",
      "content": "版本化的系统提示词"
    },
    {
      "role": "user",
      "content": "阵容和任务输入"
    },
    {
      "role": "assistant",
      "content": "经过审核的结构化答案"
    }
  ],
  "metadata": {
    "sample_id": "sft-v1-000001",
    "dataset_version": "sft-v1",
    "scenario_type": "standard_meta",
    "primary_dimension_id": "E5",
    "capability_ids": ["R02", "C01", "P01", "P04", "Q02"],
    "ruleset_id": "lol-pc-ddragon-16.16.1-asof-2026-08-21",
    "ddragon_version": "16.16.1",
    "public_patch_alias": "26.16",
    "ruleset_as_of": "2026-08-21",
    "knowledge_snapshot_id": "kb-lol-pc-16.16.1-zh-CN-v1",
    "retrieved_fact_ids": [],
    "source": "expert | synthetic_reviewed",
    "review_status": "approved"
  }
}
```

训练时只对 assistant token 计算损失。未来样本应把固定知识上下文作为输入的一部分，
让模型学习依据证据进行推理，而不是背诵版本事实。是否保留 `cot_reasoning` 作为训练
目标尚未决定；在决定前不得批量生成正式 SFT 数据。

## 7. 合成数据质量分级

教师模型输出不能直接称为黄金数据，建议按以下状态流转：

```text
generated
    ↓ 结构和实体校验
schema_valid
    ↓ 英雄机制事实检查
fact_checked
    ↓ 战术因果审核
reviewed
    ↓ 去重和泄漏检查
approved
```

只有 `approved` 数据可以进入正式 SFT 数据集。任何自动审核都应保留错误
原因，不能只保留一个总分。任务答案使用
[Evaluation Rubric v1.0](EVALUATION_RUBRIC.md)逐检查项审核；正式入库阈值需在
baseline 与专家种子试标后另行冻结。

## 8. 切分原则

SFT pilot 建议先构建独立训练集和验证集，现有 50 条保持外部冻结测试集。

切分时不能只做随机逐条切分，应尽量按以下维度分组：

- 完整阵容和蓝红换边。
- 高重合英雄组合。
- 关键对线组合。
- 阵容原型，例如开团、Poke、冲阵、分带和四保一。
- 常规、极端和非主流场景。

目标是让验证集检查泛化，而不是记忆相似阵容。

## 9. 数据版本规则

建议命名：

- `baseline-test-v1`
- `fewshot-seed-v1`
- `sft-pilot-v1`
- `preference-v1`

每个版本至少记录：

- 文件路径和 SHA-256。
- 条数和类别分布。
- `ruleset_id`、Data Dragon 构建、公开补丁别名和知识截止日。
- 生成来源与审核状态。
- 创建脚本版本。
- 与其他数据集的重复检查结果。

正式实验引用版本号和哈希，不只引用“最新数据”。

## 10. 能力驱动的数据采集

训练数据不按“是否属于英雄联盟内容”来决定是否收集，而由两类证据共同决定：

1. [阵容分析能力分类体系](CAPABILITY_TAXONOMY.md)定义任务需要哪些可观察能力。
2. 修正后的 baseline 错误标注说明当前模型在哪些能力上实际失败。

[数据需求矩阵](DATA_REQUIREMENTS_MATRIX.md)把能力映射到知识库、SFT、程序约束、
来源和入库门槛。矩阵不在正式 baseline 错误标注前设置逐类精确条数。原始教学视频、
解说或文章属于 `SOURCE`，不是 SFT 数据；
只有完成授权记录、片段抽取、任务化、事实/因果审核和防泄漏检查后才可进入训练候选。

Baseline 能力与错误标签采用 sidecar，通过 `sample_id` 关联，不能给冻结测试集本体
追加训练导向字段。机器可读目录和错误标注 Schema 位于 `schemas/`。

## 11. 版本化知识库边界

英雄技能、定位和游戏规则等可能随游戏版本变化的事实，优先存入外部知识库；SFT 主要
训练模型如何忠实使用这些事实完成交互、阵容聚合和制胜条件推演。

- 生产知识库可以动态更新。
- 首个实验主版本固定为 Data Dragon 16.16.1，官方补丁别名为 26.16，知识截止日为
  2026-08-21；Baseline、few-shot 和 SFT 实验必须绑定固定 `ruleset_id`、
  `ddragon_version`、`ruleset_as_of` 与 `knowledge_snapshot_id`。
- 结构化英雄事实优先按稳定 ID 和版本精确查询；主观战术结论不得写成知识库事实。
- Fixed-KB 结果还需记录检索事实 ID，以便检查完整性、版本一致性和知识忠实度。
- Champion Knowledge Card v2、728 份来源快照、173 张 `source_grounded_auto` 卡和
  中文精确查询已经实现；官方称号、蓝红方和位置的开发版 Prompt 拼装也已实现。详细边界
  见[知识库设计](KNOWLEDGE_BASE_DESIGN.md)。历史四技能视图已弃用；五技能
  `compact-mechanics-v2` 强制 865/865 槽位覆盖。`DEV-KB-0004` 的 9 条开发审核仍显示
  知识绑定失败，因此 fixed-KB 正式实验没有运行。

## 12. 待决问题

- 后续跨 Data Dragon 构建时，测试集、知识快照和训练数据如何共同版本化。
- 是否建立一个不含 `scenario_description` 的独立纯阵容测试集。
- `DEV-KB-0003` 使用的 `compact-mechanics-v1` 有损删除普通英雄一个技能槽位，结果只用于
  记录该历史方案失败。五技能 `compact-mechanics-v2` 已在同一 9 条完成验证，但仍有
  9/9 机制/实体错误；下一候选应增加原子事实 ID 和确定性校验，再决定知识使用 SFT。
- 人工审核所需的最小专家人数和一致率阈值。
- 训练/验证切分的组合相似度定义。
