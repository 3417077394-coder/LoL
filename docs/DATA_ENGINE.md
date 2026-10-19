# LoL 测试数据引擎

该模块用于生成、校验和清洗英雄联盟 BP 阶段的结构化阵容输入。

## 目录

- 代码：`src/data_engine/`
- 原始数据：`data/raw/`
- 清洗候选：`data/processed/`
- 冻结评测集：`data/eval/`
- 补丁：`data/patches/`
- 缺口报告：`data/reports/`
- 英雄参考快照：`data/reference/`
- 旧版代码：`src/data_engine/legacy/`

## 安装

```bash
python -m pip install -r requirements.txt
export OPENAI_API_KEY="你的密钥"
export OPENAI_BASE_URL="你的兼容端点"
```

不要将真实密钥写入脚本或提交到版本控制。

## 工作流

1. 校验 raw 数据并生成候选：

```bash
python src/data_engine/validator.py
```

输出：

- `data/processed/clean_baseline_candidate.jsonl`
- `data/reports/gap_report.json`

2. 若缺口非零，生成候选补丁：

```bash
python src/data_engine/generator.py
```

输出：`data/patches/patch_baseline.jsonl`。

3. 人工检查补丁后再合并到 raw 数据，并重新运行校验器。

4. 候选数据只有经过语义审核、版本命名、重复检查和文档更新后，才可以
晋升为新的 `data/eval/` 版本。

## 重要边界

`data/eval/baseline-test-v1.jsonl` 是冻结测试集。数据引擎不能直接覆盖
它，结构校验通过也不等于获得专家语义背书。
