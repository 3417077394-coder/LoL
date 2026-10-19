import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_SOURCE = PROJECT_ROOT / "src" / "knowledge_base"
sys.path.insert(0, str(KNOWLEDGE_SOURCE))

import compact_context
import full_kb_builder as builder
import query_kb


class FullKnowledgeBaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source_manifest = builder.load_json(builder.SOURCE_MANIFEST_PATH)
        cls.snapshot_manifest = builder.load_json(builder.SNAPSHOT_ROOT / "manifest.json")
        schema = builder.load_json(builder.SCHEMA_PATH)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())
        cls.cards = {
            path.stem: builder.load_json(path)
            for path in sorted(builder.CARDS_ROOT.glob("*.json"))
        }

    def test_snapshot_covers_exactly_173_standard_champions(self):
        self.assertEqual(self.snapshot_manifest["card_count"], 173)
        self.assertEqual(len(self.cards), 173)
        self.assertNotIn("Jade", self.cards)
        self.assertEqual(len({card["champion"]["numeric_key"] for card in self.cards.values()}), 173)
        self.assertEqual(len({card["champion"]["official_name_zh"] for card in self.cards.values()}), 173)

    def test_all_cards_pass_schema_and_reference_validation(self):
        source_entries = {
            entry["relative_path"]: entry for entry in self.source_manifest["files"]
        }
        wiki_covered_slots = 0
        for hero_id, card in self.cards.items():
            with self.subTest(hero_id=hero_id):
                self.validator.validate(card)
                builder.validate_card_semantics(card)
                self.assertNotIn("tactical_profile", card)
                self.assertEqual(card["ruleset"]["ddragon_version"], "16.16.1")
                self.assertEqual(card["quality"]["status"], "source_grounded_auto")
                for source in card["provenance"]["sources"]:
                    raw_path = Path(source["raw_snapshot_path"])
                    relative = raw_path.relative_to(builder.SOURCE_ROOT.relative_to(PROJECT_ROOT)).as_posix()
                    self.assertEqual(source["content_hash"], f"sha256:{source_entries[relative]['sha256']}")
                for ability in card["abilities"]:
                    self.assertEqual(
                        ability["field_sources"]["detailed_description_zh"],
                        [f"source:communitydragon:16.16:zh_cn:{hero_id}"],
                    )
                wiki_covered_slots += sum(bool(ability["wiki_source_ref_ids"]) for ability in card["abilities"])
        self.assertGreaterEqual(wiki_covered_slots, 825)

    def test_every_frozen_source_matches_manifest_hash(self):
        self.assertEqual(len(self.source_manifest["files"]), 728)
        for entry in self.source_manifest["files"]:
            payload = (builder.SOURCE_ROOT / entry["relative_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])

    def test_patch_notes_identify_the_seven_summoners_rift_champions(self):
        listed = {
            card["champion"]["official_name_en"]
            for card in self.cards.values()
            if card["patch_change"]["status"] == "listed"
        }
        self.assertEqual(
            listed,
            {"Azir", "Bel'Veth", "Camille", "Gwen", "Kennen", "Nasus", "Poppy"},
        )

    def test_complex_chinese_context_keeps_both_jayce_forms(self):
        context = (builder.CONTEXT_ROOT / "Jayce.md").read_text(encoding="utf-8")
        self.assertIn("锤形态", context)
        self.assertIn("炮形态", context)
        self.assertIn("加速之门", context)

    def test_all_chinese_contexts_are_compact_and_have_no_raw_markup(self):
        for hero_id in self.cards:
            with self.subTest(hero_id=hero_id):
                context = (builder.CONTEXT_ROOT / f"{hero_id}.md").read_text(encoding="utf-8")
                self.assertLess(len(context), 1200)
                self.assertIsNone(re.search(r"<[^>]+>|@[^@]+@|\{\{", context))

    def test_alias_query_is_exact_and_fail_closed(self):
        with self.assertRaises(ValueError):
            query_kb.assemble_context(["波比"], context_view="unknown-view")
        champion_ids, context = query_kb.assemble_context(["波比", "Camille"])
        self.assertEqual(champion_ids, ["Poppy", "Camille"])
        self.assertIn("英雄：波比", context)
        self.assertIn("英雄：卡蜜尔", context)
        with self.assertRaises(KeyError):
            query_kb.assemble_context(["不存在的英雄"])
        with self.assertRaises(ValueError):
            query_kb.assemble_context(["波比", "Poppy"])


    def test_compact_context_view_is_complete_and_reproducible(self):
        manifest = builder.load_json(compact_context.MANIFEST_PATH)
        source_cards = {
            item["champion_id"]: item
            for item in self.snapshot_manifest["cards"]
        }
        self.assertEqual(manifest["context_view_id"], compact_context.CONTEXT_VIEW_ID)
        self.assertEqual(manifest["knowledge_snapshot_id"], compact_context.SNAPSHOT_ID)
        self.assertEqual(manifest["source_card_count"], 173)
        self.assertEqual(manifest["context_count"], 173)
        self.assertEqual(len(manifest["contexts"]), 173)
        self.assertGreater(manifest["aggregate"]["char_ratio"], 0.4)
        self.assertLess(manifest["aggregate"]["char_ratio"], 0.8)

        for record in manifest["contexts"]:
            hero_id = record["champion_id"]
            with self.subTest(hero_id=hero_id):
                context_path = PROJECT_ROOT / record["context_path"]
                context = context_path.read_text(encoding="utf-8")
                rendered, selected_slots = compact_context.render_compact_context(
                    self.cards[hero_id]
                )
                self.assertEqual(context, rendered)
                self.assertEqual(record["selected_ability_slots"], selected_slots)
                self.assertEqual(
                    record["source_card_sha256"], source_cards[hero_id]["card_sha256"]
                )
                self.assertEqual(
                    hashlib.sha256(context.encode("utf-8")).hexdigest(),
                    record["context_sha256"],
                )
                self.assertIsNone(re.search(r"<[^>]+>|@[^@]+@|\{\{", context))
                self.assertEqual(
                    selected_slots, ["passive", "q", "w", "e", "r"]
                )


    def test_compact_context_requires_all_five_ability_slots(self):
        yasuo = json.loads(json.dumps(self.cards["Yasuo"]))
        yasuo["abilities"] = [
            ability for ability in yasuo["abilities"] if ability["slot"] != "w"
        ]
        with self.assertRaisesRegex(ValueError, "Passive/Q/W/E/R"):
            compact_context.render_compact_context(yasuo)

        _, context = query_kb.assemble_context(
            ["疾风剑豪"], context_view=compact_context.CONTEXT_VIEW_ID
        )
        self.assertIn("- 被动 浪客之道：", context)
        self.assertIn("- Q 斩钢闪：", context)
        self.assertIn("- W 风之障壁：", context)
        self.assertIn("- E 踏前斩：", context)
        self.assertIn("- R 狂风绝息斩：", context)

    def test_compact_context_preserves_critical_complex_mechanics(self):
        _, context = query_kb.assemble_context(
            ["波比", "Camille", "杰斯", "厄斐琉斯"],
            context_view=compact_context.CONTEXT_VIEW_ID,
        )
        for expected in (
            "中断附近敌人的突进",
            "拉向一个墙体",
            "锤形态",
            "炮形态",
            "加速之门",
            "武器队列系统",
        ):
            self.assertIn(expected, context)

    def test_compact_context_reduces_all_frozen_eval_lineups_in_aggregate(self):
        eval_path = PROJECT_ROOT / "data/eval/baseline-test-v1.jsonl"
        positions = ("top", "jungle", "mid", "bottom", "support")
        full_chars = 0
        compact_chars = 0
        for line in eval_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            names = [
                row["draft_phase_lineup"][team][position]
                for team in ("blue_team", "red_team")
                for position in positions
            ]
            _, full = query_kb.assemble_context(names, context_view="full")
            _, compact = query_kb.assemble_context(
                names, context_view=compact_context.CONTEXT_VIEW_ID
            )
            full_chars += len(full)
            compact_chars += len(compact)
        self.assertLess(compact_chars / full_chars, 0.8)

    def test_all_frozen_eval_lineups_resolve_by_official_title(self):
        eval_path = PROJECT_ROOT / "data/eval/baseline-test-v1.jsonl"
        positions = ("top", "jungle", "mid", "bottom", "support")
        for sample_id, line in enumerate(
            eval_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            row = json.loads(line)
            names = [
                row["draft_phase_lineup"][team][position]
                for team in ("blue_team", "red_team")
                for position in positions
            ]
            with self.subTest(sample_id=sample_id):
                champion_ids, _ = query_kb.assemble_context(names)
                self.assertEqual(len(champion_ids), 10)


if __name__ == "__main__":
    unittest.main()
