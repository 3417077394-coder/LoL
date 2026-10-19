# LEGACY-0001

状态：历史无效语义评估，只供追溯。

文件：

- `input_snapshot.jsonl`：迁移前 baseline 目录中的测试集副本。
- `model_outputs.jsonl`：旧的采样推理结果。
- `judge_results.jsonl`：旧 Judge 结果。

已知问题见 `../../docs/EXPERIMENT_LOG.md`。输入快照与
`../../data/eval/baseline-test-v1.jsonl` 的 SHA-256 相同，但不是新的
canonical 数据源。
