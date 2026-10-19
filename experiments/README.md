# Experiments

每个正式实验使用独立目录，不覆盖历史结果。

- `LEGACY-0001/`：迁移前的历史 baseline 产物，只供追溯。
- `EXP-0001/`：修正后的正式 zero-shot baseline，尚未运行。
- `DEV-KB-0001/`：9 条闭卷 vs 完整十英雄知识卡开发对照，已完成，非正式。
- `DEV-KB-0002/`：加入阵营/位置实体映射的第二轮开发对照，已完成，非正式。

Baseline 脚本默认读取 `LOL_EXPERIMENT_ID=EXP-0001`，并拒绝覆盖已经存在
的输出文件。完整实验规则见 `../docs/EXPERIMENT_LOG.md`。
