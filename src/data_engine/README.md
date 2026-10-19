# Data engine commands

- `validator.py`：校验 `data/raw/baseline_test_set.jsonl`，输出候选到
  `data/processed/clean_baseline_candidate.jsonl` 并刷新缺口报告。
- `generator.py`：根据 `data/reports/gap_report.json` 生成补丁到
  `data/patches/patch_baseline.jsonl`。
- `legacy/`：只供追溯。

冻结测试集位于 `data/eval/`，数据引擎不得直接覆盖它。
