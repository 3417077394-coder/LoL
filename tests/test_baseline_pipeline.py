import json
import sys
import tempfile
import unittest
from pathlib import Path

BASELINE_SOURCE = Path(__file__).resolve().parents[1] / "src" / "baseline"
sys.path.insert(0, str(BASELINE_SOURCE))

import calculate_baseline_metrics as metrics
import human_review
import project_paths
import run_kb_ablation as kb_ablation
import run_llm_judge as judge
import summarize_kb_ablation as kb_summary


def valid_model_output():
    return {
        "cot_reasoning": "双方阵容机制分析。",
        "global_analysis": {
            "blue_team_win_condition": "蓝方条件",
            "red_team_win_condition": "红方条件",
            "power_spike_comparison": "强势期比较",
        },
        "positional_strategies": {
            "top_lane": {
                "matchup_analysis": "上路分析",
                "blue_top_strategy": "蓝方上路策略",
                "red_top_strategy": "红方上路策略",
            },
            "jungle": {
                "matchup_analysis": "野区分析",
                "blue_jungle_strategy": "蓝方打野策略",
                "red_jungle_strategy": "红方打野策略",
            },
            "mid_lane": {
                "matchup_analysis": "中路分析",
                "blue_mid_strategy": "蓝方中路策略",
                "red_mid_strategy": "红方中路策略",
            },
            "bottom_lane": {
                "matchup_analysis": "下路分析",
                "blue_bottom_strategy": "蓝方下路策略",
                "red_bottom_strategy": "红方下路策略",
            },
        },
    }


class ProjectPathTests(unittest.TestCase):
    def test_canonical_dataset_uses_new_project_layout(self):
        self.assertEqual(project_paths.PROJECT_ROOT.name, "lol-draft-alignment")
        self.assertEqual(
            project_paths.TEST_SET_FILE.relative_to(project_paths.PROJECT_ROOT),
            Path("data/eval/baseline-test-v1.jsonl"),
        )
        self.assertTrue(project_paths.TEST_SET_FILE.is_file())

    def test_default_outputs_are_isolated_by_experiment(self):
        self.assertEqual(project_paths.EXPERIMENT_ID, "EXP-0001")
        self.assertEqual(
            project_paths.MODEL_OUTPUT_FILE.relative_to(
                project_paths.PROJECT_ROOT
            ),
            Path("experiments/EXP-0001/model_outputs.jsonl"),
        )


class SchemaTests(unittest.TestCase):
    def test_complete_schema_passes(self):
        self.assertEqual(
            metrics.validate_schema_integrity(valid_model_output()),
            [],
        )

    def test_every_lane_is_checked(self):
        output = valid_model_output()
        del output["positional_strategies"]["bottom_lane"][
            "red_bottom_strategy"
        ]
        errors = metrics.validate_schema_integrity(output)
        self.assertTrue(
            any("red_bottom_strategy 缺失" in error for error in errors)
        )

    def test_extra_and_empty_fields_fail(self):
        output = valid_model_output()
        output["global_analysis"]["extra"] = "x"
        output["positional_strategies"]["jungle"][
            "blue_jungle_strategy"
        ] = " "
        errors = metrics.validate_schema_integrity(output)
        self.assertTrue(any("未声明字段" in error for error in errors))
        self.assertTrue(any("非空字符串" in error for error in errors))


class JudgeTests(unittest.TestCase):
    def test_load_scenarios_uses_one_based_sample_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "test.jsonl"
            path.write_text(
                '{"scenario_type":"a"}\n{"scenario_type":"b"}\n',
                encoding="utf-8",
            )
            scenarios = judge.load_scenarios(path)
        self.assertEqual(scenarios[1]["scenario_type"], "a")
        self.assertEqual(scenarios[2]["scenario_type"], "b")

    def test_judge_response_validation(self):
        result = judge.extract_json(
            '{"judge_reasoning":"合理","factual_score":4,'
            '"consistency_score":3}'
        )
        self.assertEqual(result["factual_score"], 4)
        with self.assertRaises(ValueError):
            judge.extract_json(
                '{"judge_reasoning":"失败","factual_score":9,'
                '"consistency_score":3}'
            )

    def test_evaluation_error_has_no_fake_scores(self):
        error = judge.make_evaluation_error(
            RuntimeError("temporary failure"),
            stage="judge_api_or_response",
        )
        self.assertEqual(error["stage"], "judge_api_or_response")
        self.assertNotIn("factual_score", error)
        self.assertNotIn("consistency_score", error)

    def test_evaluation_errors_are_excluded_from_averages(self):
        good = {
            "judge_evaluation": {
                "judge_reasoning": "ok",
                "factual_score": 4,
                "consistency_score": 3,
            }
        }
        failed = {
            "evaluation_error": {"stage": "judge_api_or_response"},
        }
        contradictory = {
            "judge_evaluation": {
                "judge_reasoning": "must be ignored",
                "factual_score": 0,
                "consistency_score": 0,
            },
            "evaluation_error": {"stage": "judge_api_or_response"},
        }
        self.assertEqual(
            judge.collect_successful_evaluations(
                [good, failed, contradictory]
            ),
            [good["judge_evaluation"]],
        )


class HumanReviewTests(unittest.TestCase):
    def test_stratified_sampling_is_balanced_and_reproducible(self):
        records = [
            {"sample_id": index, "scenario_type": scenario_type}
            for index, scenario_type in enumerate(
                ["a"] * 6 + ["b"] * 6 + ["c"] * 6,
                start=1,
            )
        ]
        first = human_review.select_stratified(records, 9, seed=42)
        second = human_review.select_stratified(records, 9, seed=42)
        self.assertEqual(first, second)
        counts = {
            name: sum(item["scenario_type"] == name for item in first)
            for name in ("a", "b", "c")
        }
        self.assertEqual(counts, {"a": 3, "b": 3, "c": 3})



class KnowledgeAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = json.loads(
            project_paths.TEST_SET_FILE.read_text(encoding="utf-8").splitlines()[0]
        )

    def test_lineup_order_is_blue_then_red_by_position(self):
        names = kb_ablation.lineup_names(self.row)
        self.assertEqual(names[:2], ["山隐之焰", "德玛西亚皇子"])
        self.assertEqual(names[5:7], ["荒漠屠夫", "盲僧"])
        self.assertEqual(len(names), 10)

    def test_conditions_share_entities_but_only_kb_prompt_has_cards(self):
        closed_ids, closed_context, closed_prompt = kb_ablation.build_condition_prompt(
            self.row, "closed_book"
        )
        kb_ids, kb_context, kb_prompt = kb_ablation.build_condition_prompt(
            self.row, "fixed_kb"
        )
        self.assertEqual(closed_ids, kb_ids)
        self.assertEqual(closed_context, kb_context)
        self.assertEqual(len(kb_ids), 10)
        self.assertIn("蓝方 / 上路 | 输入称号：山隐之焰 | 标准名：奥恩", kb_context)
        self.assertIn("红方 / 辅助 | 输入称号：曙光女神 | 标准名：蕾欧娜", kb_context)
        self.assertIn("本条件不提供外部英雄机制知识", closed_prompt)
        self.assertNotIn("英雄：奥恩", closed_prompt)
        self.assertIn("英雄：奥恩", kb_prompt)

    def test_automatic_summary_does_not_claim_semantic_quality(self):
        output = valid_model_output()
        record = {
            "sample_id": 1,
            "conditions": {
                condition: {
                    "input_token_count": 100,
                    "output_token_count": 20,
                    "latency_seconds": 1.0,
                    "model_output": json.dumps(output, ensure_ascii=False),
                }
                for condition in kb_summary.CONDITIONS
            },
        }
        summary = kb_summary.summarize_records([record])
        self.assertEqual(summary["knowledge_context_view"], "full")
        self.assertEqual(summary["conditions"]["fixed_kb"]["valid_schema_count"], 1)
        self.assertIn("不能单独证明", summary["interpretation_boundary"])


if __name__ == "__main__":
    unittest.main()
