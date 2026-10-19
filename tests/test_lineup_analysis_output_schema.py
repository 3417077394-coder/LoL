import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "lineup_analysis_output_v2.schema.json"
EXAMPLE_PATH = (
    PROJECT_ROOT
    / "schemas"
    / "examples"
    / "lineup_analysis_output_v2.example.json"
)


class LineupAnalysisOutputSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)
        cls.example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    def validation_errors(self, payload):
        return sorted(
            self.validator.iter_errors(payload),
            key=lambda error: list(error.absolute_path),
        )

    def test_example_is_valid(self):
        self.assertEqual(self.validation_errors(self.example), [])

    def test_unknown_archetype_tag_is_rejected(self):
        payload = copy.deepcopy(self.example)
        payload["team_profiles"]["blue_team"]["archetype_tags"] = ["万能阵容"]
        self.assertTrue(self.validation_errors(payload))

    def test_fewer_than_three_decisive_interactions_is_rejected(self):
        payload = copy.deepcopy(self.example)
        payload["decisive_interactions"] = payload["decisive_interactions"][:2]
        self.assertTrue(self.validation_errors(payload))

    def test_undeclared_lane_strategy_is_rejected(self):
        payload = copy.deepcopy(self.example)
        payload["positional_strategies"] = {"top_lane": "不属于v2范围"}
        self.assertTrue(self.validation_errors(payload))

    def test_win_condition_requires_failure_risk(self):
        payload = copy.deepcopy(self.example)
        del payload["win_conditions"]["blue_team"][0]["failure_risk"]
        self.assertTrue(self.validation_errors(payload))


if __name__ == "__main__":
    unittest.main()
