# Processed candidates

数据引擎的校验结果写入本目录，默认文件为
`clean_baseline_candidate.jsonl`。

这里的数据仍是候选数据，不能自动替换 `../eval/` 中的冻结测试集。只有
在语义审核、版本命名、重复检查和文档更新完成后，才能晋升为新的 eval
版本。
