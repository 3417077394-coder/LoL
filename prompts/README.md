# Prompts

正式 closed-book Baseline System Prompt 和旧 Judge Prompt 目前仍分别内嵌在：

- `src/baseline/run_baseline_eval.py`
- `src/baseline/run_llm_judge.py`

迁移目录时不外置 Prompt，是为了避免在正式 baseline 重跑前同时改变实验语义。

`kb_judge_e1_e5_v1.txt` 是 fixed-KB 开发实验使用的版本化 Judge Prompt，已覆盖
E1～E5、KB1～KB5、证据和封顶规则；运行配置会保存其 SHA-256。它不代表正式
EXP-0001 的旧 Judge 已完成迁移，正式实验仍需统一 Prompt 和人工审核协议。
