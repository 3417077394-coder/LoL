# Baseline commands

共享路径由 `project_paths.py` 管理：

- 冻结测试集：`data/eval/baseline-test-v1.jsonl`
- 默认实验：`experiments/EXP-0001/`
- 模型：项目外的 AutoDL 模型目录，或 `LOL_MODEL_PATH`
- 实验 ID：`LOL_EXPERIMENT_ID`

运行命令见 `../../docs/BASELINE_DESIGN.md`。任何正式输出都不得静默覆盖。


Fixed-KB 开发对照使用独立脚本，实验 ID 必填：

```bash
python src/baseline/run_kb_ablation.py --experiment-id DEV-KB-XXXX
python src/baseline/summarize_kb_ablation.py --experiment-id DEV-KB-XXXX

# 紧凑上下文开发对照（下一次使用 DEV-KB-0003）
python src/baseline/run_kb_ablation.py \
  --experiment-id DEV-KB-0003 \
  --knowledge-context-view compact-mechanics-v1
```

脚本默认使用 9 条固定种子分层样本，同时运行 closed-book 与 fixed-KB。自动汇总只判断
格式、硬约束和成本，不能替代语义 Judge 或人工审核。
`--knowledge-context-view` 默认为 `full`，以兼容历史实验；新产物会保存视图 ID、派生清单
哈希和最终上下文哈希。Judge 从产物读取该字段并重建同一视图，旧产物没有字段时仍按
`full` 处理。

对现有成对输出调用 E1～E5 Judge：

```bash
cp .env.example .env
# 在本地 .env 填写 OPENAI_API_KEY；不要把密钥提交到 Git 或粘贴进实验产物。
python src/baseline/run_kb_judge.py --experiment-id DEV-KB-0002
python src/baseline/summarize_kb_judge.py --experiment-id DEV-KB-0002
```

`.env` 已被 Git 忽略。Judge 对 closed-book 和 fixed-KB 都读取同一份参考知识以校验
事实；只有 fixed-KB 额外计算 KB1～KB5 知识忠实度。API、解析或关联失败写入
`evaluation_error`，不按 0 分计入平均值。

用同一批 fixed-KB Prompt 测试 API 强模型的知识使用容量：

```bash
python src/baseline/run_kb_api_generation.py \
  --experiment-id DEV-KB-XXXX \
  --model gpt-5.6-sol
```

该命令默认只生成 9 份 `fixed_kb` 输出，不额外运行 closed-book，也不调用该模型给
自己的输出评分。API 不支持本地 Transformers 的 `repetition_penalty`，并为兼容推理
模型省略 `temperature`；因此这是 Prompt 和数据相同的容量对照，不宣称逐参数完全等价。

