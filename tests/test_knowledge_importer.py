import hashlib
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_SOURCE = PROJECT_ROOT / "src" / "knowledge_base"
sys.path.insert(0, str(KNOWLEDGE_SOURCE))

import ddragon_importer as importer


EXPECTED_NAMES = {
    "Poppy": "波比",
    "Camille": "卡蜜尔",
    "Jayce": "杰斯",
    "Aphelios": "厄斐琉斯",
    "Lulu": "璐璐",
}


class KnowledgeImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = importer.load_json(importer.RAW_ROOT / "manifest.json")
        schema = importer.load_json(importer.SCHEMA_PATH)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def test_raw_manifest_is_complete_and_content_addressed(self):
        expected_paths = {spec["path"] for spec in importer.source_specs()}
        actual_paths = {entry["relative_path"] for entry in self.manifest["files"]}
        self.assertEqual(actual_paths, expected_paths)
        self.assertEqual(len(actual_paths), 14)
        for entry in self.manifest["files"]:
            payload = (importer.RAW_ROOT / entry["relative_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])

    def test_all_five_cards_pass_schema_and_semantic_validation(self):
        for hero_id in EXPECTED_NAMES:
            with self.subTest(hero_id=hero_id):
                card = importer.load_json(importer.NORMALIZED_ROOT / f"{hero_id}.json")
                self.validator.validate(card)
                importer.validate_semantics(card)
                self.assertEqual(card["ddragon_version"], "16.16.1")
                self.assertEqual(card["public_patch_alias"], "26.16")
                self.assertEqual(card["review"]["status"], "generated")
                self.assertIn("manual_review_required", card["review"]["quality_flags"])
                self.assertEqual(
                    [fact["slot"] for fact in card["source_facts"]["ability_facts"]],
                    list(importer.SLOT_ORDER),
                )

    def test_zh_cn_common_names_are_not_epithets(self):
        for hero_id, expected_name in EXPECTED_NAMES.items():
            with self.subTest(hero_id=hero_id):
                card = importer.load_json(importer.NORMALIZED_ROOT / f"{hero_id}.json")
                self.assertEqual(card["champion"]["official_name"], expected_name)
                self.assertNotEqual(card["champion"]["official_name"], card["champion"]["title"])

    def test_only_complex_pilot_cards_have_complex_form_flag(self):
        for hero_id in EXPECTED_NAMES:
            card = importer.load_json(importer.NORMALIZED_ROOT / f"{hero_id}.json")
            has_flag = "complex_form" in card["review"]["quality_flags"]
            self.assertEqual(has_flag, hero_id in {"Jayce", "Aphelios"})

    def test_provenance_hashes_resolve_to_frozen_raw_files(self):
        entries_by_url = {entry["url"]: entry for entry in self.manifest["files"]}
        for hero_id in EXPECTED_NAMES:
            card = importer.load_json(importer.NORMALIZED_ROOT / f"{hero_id}.json")
            for source in card["provenance"]["sources"]:
                entry = entries_by_url[source["url"]]
                self.assertEqual(source["content_hash"], f"sha256:{entry['sha256']}")
                self.assertEqual(source["source_version"], card["ddragon_version"])

    def test_report_never_presents_candidates_as_approved(self):
        report = importer.load_json(importer.REPORT_PATH)
        self.assertEqual(report["card_count"], 5)
        self.assertEqual(report["approved_count"], 0)
        self.assertTrue(all(item["review_status"] == "generated" for item in report["cards"]))


if __name__ == "__main__":
    unittest.main()
