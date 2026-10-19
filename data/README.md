# Data lifecycle

- `eval/`：冻结、版本化的评测集；不得被生成器直接覆盖。
- `raw/`：原始模型输出或生成候选，允许包含失败样本。
- `processed/`：通过结构和实体校验的候选，尚未自动晋升为评测集。
- `patches/`：缺口驱动生成器产生的活动补丁。
- `patches/archive/`：已合并的历史补丁，禁止再次并入 raw。
- `reports/`：机器可读的 ETL 状态与缺口报告。
- `reference/`：DDragon 等外部参考快照，不替代正式版本元数据。

当前冻结测试集：

- 文件：`eval/baseline-test-v1.jsonl`
- 条数：50
- SHA-256：
  `e5b4e0d0a590ae64bad31ed7be272f3d7acb919441f1a2ff0b9f9671832e5682`

详细用途和防泄漏规则见 `../docs/DATA_DESIGN.md`。
