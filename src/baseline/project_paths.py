"""Shared paths for baseline commands after the project migration."""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID = os.environ.get("LOL_EXPERIMENT_ID", "EXP-0001")

if Path(EXPERIMENT_ID).name != EXPERIMENT_ID or EXPERIMENT_ID in {"", ".", ".."}:
    raise ValueError("LOL_EXPERIMENT_ID 必须是单个安全目录名")

EXPERIMENT_DIR = PROJECT_ROOT / "experiments" / EXPERIMENT_ID
TEST_SET_FILE = PROJECT_ROOT / "data" / "eval" / "baseline-test-v1.jsonl"
MODEL_OUTPUT_FILE = EXPERIMENT_DIR / "model_outputs.jsonl"
JUDGE_OUTPUT_FILE = EXPERIMENT_DIR / "judge_results.jsonl"
HUMAN_REVIEW_FILE = EXPERIMENT_DIR / "human_review_sample.jsonl"

DEFAULT_MODEL_PATH = (
    PROJECT_ROOT.parent
    / "models"
    / "models"
    / "Qwen--Qwen2.5-7B-Instruct"
    / "snapshots"
    / "master"
)
MODEL_PATH = Path(
    os.environ.get("LOL_MODEL_PATH", str(DEFAULT_MODEL_PATH))
).expanduser()
