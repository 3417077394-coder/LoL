import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_SOURCE = PROJECT_ROOT / "src" / "baseline"
sys.path.insert(0, str(BASELINE_SOURCE))

import run_kb_api_generation as api_generation


class ApiGenerationTests(unittest.TestCase):
    def test_default_run_targets_fixed_kb_five_skill_view(self):
        args = api_generation.parse_args(["--experiment-id", "DEV-KB-TEST"])
        self.assertEqual(args.sample_ids, list(api_generation.DEFAULT_SAMPLE_IDS))
        self.assertEqual(
            args.knowledge_context_view, api_generation.COMPACT_CONTEXT_VIEW_ID
        )
        self.assertEqual(args.model, "gpt-5.6-sol")

    def test_api_call_omits_sampling_parameters(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=None,
        )
        raw, usage = api_generation.call_generator(
            client,
            model="gpt-5.6-sol",
            system_prompt="system",
            user_prompt="user",
            max_completion_tokens=6000,
        )
        self.assertEqual(raw, "{}")
        self.assertIsNone(usage)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["max_completion_tokens"], 6000)
        self.assertNotIn("temperature", kwargs)
        self.assertNotIn("top_p", kwargs)
        self.assertNotIn("repetition_penalty", kwargs)


if __name__ == "__main__":
    unittest.main()

