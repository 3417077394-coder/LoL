import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_SOURCE = PROJECT_ROOT / "src" / "baseline"
sys.path.insert(0, str(BASELINE_SOURCE))

import run_kb_ablation as ablation


class KnowledgeContextAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = json.loads(
            ablation.TEST_SET_FILE.read_text(encoding="utf-8").splitlines()[0]
        )

    def test_compact_view_keeps_entity_mapping_and_reduces_context(self):
        full_ids, full_context = ablation.build_positioned_knowledge_context(
            self.row, knowledge_context_view="full"
        )
        compact_ids, compact_context = ablation.build_positioned_knowledge_context(
            self.row, knowledge_context_view=ablation.COMPACT_CONTEXT_VIEW_ID
        )
        self.assertEqual(full_ids, compact_ids)
        self.assertEqual(len(compact_ids), 10)
        self.assertIn(f"上下文视图：{ablation.COMPACT_CONTEXT_VIEW_ID}", compact_context)
        self.assertLess(len(compact_context), len(full_context))

    def test_prompt_and_cli_record_explicit_context_view(self):
        _, _, prompt = ablation.build_condition_prompt(
            self.row, "fixed_kb", knowledge_context_view=ablation.COMPACT_CONTEXT_VIEW_ID
        )
        self.assertIn(f"上下文视图：{ablation.COMPACT_CONTEXT_VIEW_ID}", prompt)
        args = ablation.parse_args([
            "--experiment-id",
            "DEV-KB-TEST",
            "--knowledge-context-view",
            ablation.COMPACT_CONTEXT_VIEW_ID,
        ])
        self.assertEqual(args.knowledge_context_view, ablation.COMPACT_CONTEXT_VIEW_ID)

        legacy_args = ablation.parse_args([
            "--experiment-id",
            "DEV-KB-LEGACY-TEST",
            "--knowledge-context-view",
            ablation.LEGACY_COMPACT_CONTEXT_VIEW_ID,
        ])
        self.assertEqual(
            legacy_args.knowledge_context_view,
            ablation.LEGACY_COMPACT_CONTEXT_VIEW_ID,
        )


if __name__ == "__main__":
    unittest.main()
