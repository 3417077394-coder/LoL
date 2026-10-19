import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_SOURCE = PROJECT_ROOT / "src" / "baseline"
sys.path.insert(0, str(BASELINE_SOURCE))

import run_kb_judge as judge
import summarize_kb_judge as summary


def program_checks(valid=True):
    return {
        "is_valid_json": valid,
        "is_valid_schema": valid,
        "schema_errors": [],
        "numerical_trigger": False,
        "E1.1_score": 1 if valid else 0,
        "E1.2_score": 1 if valid else 0,
    }


def valid_payload(condition="closed_book", valid=True):
    criteria = []
    for criterion_id, capability_id in judge.CAPABILITY_BY_CRITERION.items():
        score = 1
        if criterion_id in {"E1.1", "E1.2"} and not valid:
            score = 0
        criteria.append({
            "criterion_id": criterion_id,
            "score": score,
            "evidence_quote": "",
            "explanation": "测试说明",
            "capability_id": capability_id,
            "severity": "none" if score == 1 else "major",
            "confidence": "high",
        })
    kb_score = "NA" if condition == "closed_book" else 1
    return {
        "judge_summary": "测试裁判结论",
        "criterion_results": criteria,
        "kb_criterion_results": [
            {
                "criterion_id": criterion_id,
                "score": kb_score,
                "evidence_quote": "",
                "explanation": "测试说明",
                "severity": "none",
                "confidence": "high",
            }
            for criterion_id in judge.KB_CRITERIA
        ],
        "applied_caps": [],
        "cross_entity_confusion": False,
        "unsupported_mechanism_claims": [],
    }


class JudgeValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads(judge.SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema)

    def test_complete_closed_book_payload_scores_five(self):
        payload = valid_payload()
        payload["criterion_results"][2]["capability_id"] = "Q03"
        result = judge.validate_and_enrich(
            payload,
            condition="closed_book",
            program_checks=program_checks(),
            validator=self.validator,
        )
        self.assertEqual(result["dimension_scores"], {dimension: 5.0 for dimension in judge.DIMENSIONS})
        self.assertEqual(result["semantic_score"], 5.0)
        self.assertIsNone(result["knowledge_faithfulness_score"])
        self.assertEqual(result["criterion_results"][2]["capability_id"], "B01")
        self.assertEqual(len(result["capability_id_corrections"]), 1)

    def test_invalid_json_forces_e1_to_zero(self):
        result = judge.validate_and_enrich(
            valid_payload(valid=False),
            condition="closed_book",
            program_checks=program_checks(valid=False),
            validator=self.validator,
        )
        self.assertEqual(result["dimension_scores"]["E1"], 0.0)
        self.assertEqual(result["dimension_scores"]["E2"], 5.0)

    def test_fixed_kb_requires_numeric_kb_scores(self):
        with self.assertRaises(ValueError):
            judge.validate_and_enrich(
                valid_payload(condition="closed_book"),
                condition="fixed_kb",
                program_checks=program_checks(),
                validator=self.validator,
            )

    def test_missing_criterion_fails(self):
        payload = valid_payload()
        payload["criterion_results"].pop()
        with self.assertRaises(ValueError):
            judge.validate_and_enrich(
                payload,
                condition="closed_book",
                program_checks=program_checks(),
                validator=self.validator,
            )


    def test_project_env_loads_only_allowed_missing_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "OPENAI_API_KEY=test-key\nUNRELATED_SECRET=ignore-me\n",
                encoding="utf-8",
            )
            original = judge.os.environ.pop("OPENAI_API_KEY", None)
            try:
                judge.load_project_env(env_path)
                self.assertEqual(judge.os.environ["OPENAI_API_KEY"], "test-key")
                self.assertNotIn("UNRELATED_SECRET", judge.os.environ)
            finally:
                judge.os.environ.pop("OPENAI_API_KEY", None)
                if original is not None:
                    judge.os.environ["OPENAI_API_KEY"] = original

    def test_api_call_uses_completion_token_parameter_without_temperature(self):
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=None,
        )
        judge.call_judge(
            client,
            model="judge-model",
            system_prompt="system",
            user_prompt="user",
            max_completion_tokens=1234,
        )
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["max_completion_tokens"], 1234)
        self.assertNotIn("max_tokens", kwargs)
        self.assertNotIn("temperature", kwargs)


class JudgeSummaryTests(unittest.TestCase):
    def test_pair_comparison_uses_semantic_score(self):
        def record(condition, semantic):
            return {
                "sample_id": 1,
                "condition": condition,
                "judge_evaluation": {
                    "dimension_scores": {dimension: semantic for dimension in judge.DIMENSIONS},
                    "semantic_score": semantic,
                    "knowledge_faithfulness_score": None if condition == "closed_book" else 3.0,
                    "criterion_results": valid_payload(condition)["criterion_results"],
                    "kb_criterion_results": valid_payload(condition)["kb_criterion_results"],
                    "cross_entity_confusion": False,
                    "unsupported_mechanism_claims": [],
                },
            }
        result = summary.summarize([
            record("closed_book", 3.0),
            record("fixed_kb", 4.0),
        ])
        self.assertEqual(result["knowledge_context_view"], "full")
        self.assertEqual(
            result["paired_semantic_comparison"]["winner_counts"],
            {"fixed_kb": 1},
        )


if __name__ == "__main__":
    unittest.main()
