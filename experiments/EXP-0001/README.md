# EXP-0001

状态：计划中，未运行；Evaluation Rubric v1.0 已冻结，评估代码待适配。

目标：生成修正后的 Baseline v1。

预期产物：

- `model_outputs.jsonl`
- `judge_results.jsonl`
- `human_review_sample.jsonl`
- `evaluation_summary.json`
- 后续补充的配置、Prompt、Rubric 与 Schema 快照

脚本会拒绝覆盖已经存在的结果。正式运行前必须完成五维评估 Schema、Judge、人工
审核和汇总代码适配，并再次核对 `../../docs/BASELINE_DESIGN.md` 与
`../../docs/EVALUATION_RUBRIC.md`。
