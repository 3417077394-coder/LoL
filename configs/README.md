# Configs

Baseline 迁移后使用两个环境变量控制本地路径：

- `LOL_EXPERIMENT_ID`：实验目录名，默认 `EXP-0001`。
- `LOL_MODEL_PATH`：模型权重目录；默认指向项目外的
  `../models/models/Qwen--Qwen2.5-7B-Instruct/snapshots/master`。

共享路径定义位于 `src/baseline/project_paths.py`。正式 baseline 配置
Schema 尚未冻结，因此目前没有创建会与代码重复的 YAML。待 DEC-0008
Accepted 后，再把模型、解码、Prompt 和 Judge 参数整体迁移到版本化配置。
