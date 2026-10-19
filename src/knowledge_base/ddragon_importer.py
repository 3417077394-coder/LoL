#!/usr/bin/env python3
"""Download fixed Data Dragon sources and build review-required pilot cards.

The importer intentionally has no "latest" mode. Every URL, version label and
output directory is pinned so a later Data Dragon release cannot silently alter
an experiment input.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from jsonschema import Draft202012Validator, FormatChecker

try:
    from .pilot_annotations import PILOT_ANNOTATIONS, PILOT_HERO_IDS
except ImportError:  # Support direct execution from the repository root.
    from pilot_annotations import PILOT_ANNOTATIONS, PILOT_HERO_IDS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas/champion_knowledge_card_v1.schema.json"
RAW_ROOT = PROJECT_ROOT / "data/knowledge/raw/16.16.1"
NORMALIZED_ROOT = PROJECT_ROOT / "data/knowledge/normalized/16.16.1/zh-CN"
REPORT_PATH = PROJECT_ROOT / "data/knowledge/reports/pilot-16.16.1-report.json"

DDRAGON_VERSION = "16.16.1"
PUBLIC_PATCH_ALIAS = "26.16"
RULESET_AS_OF = "2026-08-21"
RULESET_ID = "lol-pc-ddragon-16.16.1-asof-2026-08-21"
KNOWLEDGE_SNAPSHOT_ID = "kb-ddragon-16.16.1-pilot-v1"
REGION_SCOPE = "global_pc"
CARD_LOCALE = "zh-CN"
DDRAGON_LOCALES = ("zh_CN", "en_US")
SCRIPT_VERSION = "ddragon-importer-v1"
BASE_URL = "https://ddragon.leagueoflegends.com"

SLOT_ORDER = ("passive", "q", "w", "e", "r")
BLOCKING_FLAGS = {
    "missing_source",
    "version_conflict",
    "manual_review_required",
    "source_license_pending",
    "outdated_source",
}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def clean_text(value: str) -> str:
    """Turn Data Dragon's small HTML fragments into stable plain text."""

    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return " ".join(value.split())


def project_relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def source_specs() -> list[dict[str, str]]:
    specs = [
        {"path": "versions.json", "url": f"{BASE_URL}/api/versions.json"},
        {"path": "realms/na.json", "url": f"{BASE_URL}/realms/na.json"},
    ]
    for locale in DDRAGON_LOCALES:
        prefix = f"cdn/{DDRAGON_VERSION}/data/{locale}"
        specs.append(
            {
                "path": f"{locale}/champion.json",
                "url": f"{BASE_URL}/{prefix}/champion.json",
            }
        )
        specs.extend(
            {
                "path": f"{locale}/champion/{hero_id}.json",
                "url": f"{BASE_URL}/{prefix}/champion/{hero_id}.json",
            }
            for hero_id in PILOT_HERO_IDS
        )
    return specs


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_downloaded_sources() -> None:
    versions = load_json(RAW_ROOT / "versions.json")
    if DDRAGON_VERSION not in versions:
        raise ValueError(f"Data Dragon version catalog does not contain {DDRAGON_VERSION}")

    realm = load_json(RAW_ROOT / "realms/na.json")
    realm_champion_version = realm.get("n", {}).get("champion")
    if realm_champion_version != DDRAGON_VERSION:
        raise ValueError(
            f"Realm champion version is {realm_champion_version!r}, expected {DDRAGON_VERSION!r}"
        )

    for locale in DDRAGON_LOCALES:
        summary = load_json(RAW_ROOT / locale / "champion.json")
        if summary.get("version") != DDRAGON_VERSION:
            raise ValueError(f"{locale} champion summary has wrong version")
        missing = set(PILOT_HERO_IDS) - set(summary.get("data", {}))
        if missing:
            raise ValueError(f"{locale} champion summary is missing: {sorted(missing)}")
        for hero_id in PILOT_HERO_IDS:
            payload = load_json(RAW_ROOT / locale / "champion" / f"{hero_id}.json")
            row = payload.get("data", {}).get(hero_id)
            if not row or row.get("id") != hero_id:
                raise ValueError(f"Invalid {locale} individual payload for {hero_id}")
            if len(row.get("spells", [])) != 4 or not row.get("passive"):
                raise ValueError(f"Expected passive and four spell slots for {locale}/{hero_id}")


def verify_manifest(manifest: dict[str, Any]) -> None:
    expected = {
        "ruleset_id": RULESET_ID,
        "ddragon_version": DDRAGON_VERSION,
        "public_patch_alias": PUBLIC_PATCH_ALIAS,
        "as_of": RULESET_AS_OF,
        "region_scope": REGION_SCOPE,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ValueError(f"Raw manifest {field}={manifest.get(field)!r}, expected {value!r}")

    expected_paths = {spec["path"] for spec in source_specs()}
    actual_paths = {entry["relative_path"] for entry in manifest.get("files", [])}
    if actual_paths != expected_paths:
        raise ValueError("Raw manifest file set differs from the pinned importer source set")
    for entry in manifest["files"]:
        path = RAW_ROOT / entry["relative_path"]
        if not path.is_file():
            raise FileNotFoundError(f"Manifest source is missing: {path}")
        digest = sha256_bytes(path.read_bytes())
        if digest != entry["sha256"]:
            raise ValueError(f"Raw source hash mismatch: {path}")


def download_sources(timeout: float = 30.0) -> dict[str, Any]:
    """Fetch and freeze exact official inputs, or verify an existing freeze."""

    manifest_path = RAW_ROOT / "manifest.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        verify_manifest(manifest)
        validate_downloaded_sources()
        return manifest

    session = requests.Session()
    session.headers.update({"User-Agent": "lol-draft-alignment-ddragon-importer/1.0"})
    entries: list[dict[str, Any]] = []
    for spec in source_specs():
        response = session.get(spec["url"], timeout=timeout)
        response.raise_for_status()
        payload = response.content
        json.loads(payload)
        path = RAW_ROOT / spec["path"]
        if path.exists() and path.read_bytes() != payload:
            raise FileExistsError(f"Refusing to overwrite differing immutable raw source: {path}")
        if not path.exists():
            atomic_write(path, payload)
        entries.append(
            {
                "relative_path": spec["path"],
                "url": spec["url"],
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "media_type": response.headers.get("Content-Type", "application/json").split(";")[0],
            }
        )

    manifest = {
        "schema_version": "ddragon-raw-manifest-v1",
        "ruleset_id": RULESET_ID,
        "ddragon_version": DDRAGON_VERSION,
        "public_patch_alias": PUBLIC_PATCH_ALIAS,
        "as_of": RULESET_AS_OF,
        "region_scope": REGION_SCOPE,
        "card_locale": CARD_LOCALE,
        "ddragon_locales": list(DDRAGON_LOCALES),
        "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": entries,
    }
    validate_downloaded_sources()
    atomic_write(manifest_path, canonical_json_bytes(manifest))
    return manifest


def manifest_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["relative_path"]: entry for entry in manifest["files"]}


def make_source_reference(
    *, hero_id: str, locale: str, localized_name: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    relative_path = f"{locale}/champion/{hero_id}.json"
    entry = manifest_entries(manifest)[relative_path]
    return {
        "source_ref_id": f"source:ddragon:{DDRAGON_VERSION}:{locale}:{hero_id}",
        "source_type": "official_structured",
        "title": f"Data Dragon {DDRAGON_VERSION} {locale} champion data: {localized_name}",
        "publisher": "Riot Games",
        "version_namespace": "ddragon",
        "source_version": DDRAGON_VERSION,
        "url": entry["url"],
        "retrieved_at": manifest["retrieved_at"],
        "content_hash": f"sha256:{entry['sha256']}",
        "usage_basis": "official_public",
    }


def fact_id(hero_id: str, slot: str, form_id: str) -> str:
    return f"fact:{hero_id}:{slot}:{form_id}:ddragon-{DDRAGON_VERSION}"


def zh_champion_identity(row: dict[str, Any]) -> tuple[str, str]:
    """Return common champion name and epithet from zh_CN Data Dragon.

    Unlike en_US, Riot's zh_CN payload uses ``title`` for the common champion
    name (for example, 波比) and ``name`` for the epithet (圣锤之毅).
    """

    return row["title"], row["name"]


def build_card(hero_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    annotation = PILOT_ANNOTATIONS[hero_id]
    form_id = str(annotation["form_id"])
    zh_path = RAW_ROOT / "zh_CN/champion" / f"{hero_id}.json"
    en_path = RAW_ROOT / "en_US/champion" / f"{hero_id}.json"
    zh_row = load_json(zh_path)["data"][hero_id]
    en_row = load_json(en_path)["data"][hero_id]
    official_name, champion_title = zh_champion_identity(zh_row)

    zh_source_id = f"source:ddragon:{DDRAGON_VERSION}:zh_CN:{hero_id}"
    en_source_id = f"source:ddragon:{DDRAGON_VERSION}:en_US:{hero_id}"
    source_ids = [zh_source_id, en_source_id]
    raw_abilities = [zh_row["passive"], *zh_row["spells"]]

    ability_facts: list[dict[str, Any]] = []
    ability_mechanics: list[dict[str, Any]] = []
    for slot, raw_ability in zip(SLOT_ORDER, raw_abilities, strict=True):
        candidate = annotation["abilities"][slot]
        current_fact_id = fact_id(hero_id, slot, form_id)
        ability_facts.append(
            {
                "fact_id": current_fact_id,
                "slot": slot,
                "form_id": form_id,
                "official_name": clean_text(raw_ability["name"]),
                "official_description": clean_text(raw_ability["description"]),
                "mechanics_summary": candidate["summary"],
                "effective_ddragon_version": DDRAGON_VERSION,
                "effective_public_patch_alias": PUBLIC_PATCH_ALIAS,
                "source_ref_ids": source_ids,
                "raw_payload_path": project_relative(zh_path),
            }
        )
        ability_mechanics.append(
            {
                "mechanic_id": f"mechanic:{hero_id}:{slot}:{form_id}:v1",
                "ability_fact_id": current_fact_id,
                "damage_types": candidate["damage_types"],
                "targeting_types": candidate["targeting_types"],
                "control_types": candidate["control_types"],
                "mobility_types": candidate["mobility_types"],
                "defense_types": candidate["defense_types"],
                "conditions": candidate["conditions"],
                "limitations": candidate["limitations"],
                "source_fact_ids": [current_fact_id],
                "normalization_method": "llm_candidate",
                "normalization_status": "generated",
            }
        )

    attributes = []
    for category, rating, summary, basis_slots in annotation["attributes"]:
        attributes.append(
            {
                "attribute_id": f"attribute:{hero_id}:{category}:v1",
                "category": category,
                "rating": rating,
                "summary": summary,
                "conditions": [],
                "basis_fact_ids": [fact_id(hero_id, slot, form_id) for slot in basis_slots],
                "derivation_method": "llm_candidate",
                "review_status": "generated",
            }
        )

    limitations = []
    for suffix, summary, basis_slots in annotation["limitations"]:
        limitations.append(
            {
                "limitation_id": f"limitation:{hero_id}:{suffix}:v1",
                "summary": summary,
                "conditions": [],
                "basis_fact_ids": [fact_id(hero_id, slot, form_id) for slot in basis_slots],
                "review_status": "generated",
            }
        )

    quality_flags = ["manual_review_required"]
    if hero_id in {"Jayce", "Aphelios"}:
        quality_flags.append("complex_form")

    entries = manifest_entries(manifest)
    input_hashes = [
        f"sha256:{entries[f'{locale}/champion/{hero_id}.json']['sha256']}"
        for locale in DDRAGON_LOCALES
    ]
    aliases = [en_row["name"]] if en_row["name"] != zh_row["name"] else []
    return {
        "schema_version": "champion-knowledge-card-v1",
        "card_id": f"champion:{hero_id}:ddragon-{DDRAGON_VERSION}:{CARD_LOCALE}",
        "knowledge_snapshot_id": KNOWLEDGE_SNAPSHOT_ID,
        "ruleset_id": RULESET_ID,
        "ddragon_version": DDRAGON_VERSION,
        "public_patch_alias": PUBLIC_PATCH_ALIAS,
        "as_of": RULESET_AS_OF,
        "region_scope": REGION_SCOPE,
        "locale": CARD_LOCALE,
        "champion": {
            "stable_id": hero_id,
            "numeric_key": zh_row["key"],
            "official_name": official_name,
            "title": champion_title,
            "aliases": aliases,
            "resource_type": zh_row["partype"],
            "source_ref_ids": source_ids,
        },
        "source_facts": {"ability_facts": ability_facts},
        "normalized_mechanics": {"ability_mechanics": ability_mechanics},
        "tactical_profile": {
            "positions": [],
            "attributes": attributes,
            "limitations": limitations,
        },
        "provenance": {
            "sources": [
                make_source_reference(
                    hero_id=hero_id,
                    locale="zh_CN",
                    localized_name=official_name,
                    manifest=manifest,
                ),
                make_source_reference(
                    hero_id=hero_id,
                    locale="en_US",
                    localized_name=en_row["name"],
                    manifest=manifest,
                ),
            ],
            "generation": {
                "ingest_method": "semi_automatic",
                "script_version": SCRIPT_VERSION,
                "input_hashes": input_hashes,
                "generated_at": manifest["retrieved_at"],
            },
        },
        "review": {
            "status": "generated",
            "reviewer_ids": [],
            "reviewed_at": None,
            "quality_flags": quality_flags,
            "notes": [
                "官方名称与技能描述来自固定 Data Dragon 原始响应。",
                "机制摘要、标准化枚举与战术画像为待人工核验的模型候选，不得用于正式 fixed-KB 实验。",
            ],
        },
    }


def validate_semantics(card: dict[str, Any]) -> None:
    hero_id = card["champion"]["stable_id"]
    facts = card["source_facts"]["ability_facts"]
    mechanics = card["normalized_mechanics"]["ability_mechanics"]
    sources = card["provenance"]["sources"]
    fact_ids = {fact["fact_id"] for fact in facts}
    source_ids = {source["source_ref_id"] for source in sources}

    if [fact["slot"] for fact in facts] != list(SLOT_ORDER):
        raise ValueError(f"{hero_id}: pilot card must preserve passive/Q/W/E/R order")
    if len(fact_ids) != len(facts):
        raise ValueError(f"{hero_id}: duplicate fact IDs")
    for fact in facts:
        if not set(fact["source_ref_ids"]).issubset(source_ids):
            raise ValueError(f"{hero_id}: fact references an unknown source")
        if fact["effective_ddragon_version"] != card["ddragon_version"]:
            raise ValueError(f"{hero_id}: fact/card version mismatch")
    for mechanic in mechanics:
        if not set(mechanic["source_fact_ids"]).issubset(fact_ids):
            raise ValueError(f"{hero_id}: mechanic references an unknown fact")
    for collection in (card["tactical_profile"]["attributes"], card["tactical_profile"]["limitations"]):
        for item in collection:
            if not set(item["basis_fact_ids"]).issubset(fact_ids):
                raise ValueError(f"{hero_id}: tactical item references an unknown fact")
    if card["review"]["status"] == "approved" and BLOCKING_FLAGS.intersection(
        card["review"]["quality_flags"]
    ):
        raise ValueError(f"{hero_id}: approved card contains a blocking quality flag")


def validator() -> Draft202012Validator:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def build_cards(manifest: dict[str, Any], *, replace_generated: bool = False) -> list[dict[str, Any]]:
    verify_manifest(manifest)
    validate_downloaded_sources()
    schema_validator = validator()
    results: list[dict[str, Any]] = []
    report_cards: list[dict[str, Any]] = []

    for hero_id in PILOT_HERO_IDS:
        card = build_card(hero_id, manifest)
        errors = sorted(schema_validator.iter_errors(card), key=lambda error: list(error.path))
        if errors:
            details = "; ".join(f"{list(error.path)}: {error.message}" for error in errors)
            raise ValueError(f"{hero_id} failed JSON Schema validation: {details}")
        validate_semantics(card)
        output_path = NORMALIZED_ROOT / f"{hero_id}.json"
        payload = canonical_json_bytes(card)
        if output_path.exists() and output_path.read_bytes() != payload and not replace_generated:
            raise FileExistsError(
                f"Refusing to overwrite changed generated card without --replace-generated: {output_path}"
            )
        if not output_path.exists() or output_path.read_bytes() != payload:
            atomic_write(output_path, payload)
        digest = sha256_bytes(payload)
        results.append(card)
        report_cards.append(
            {
                "champion_id": hero_id,
                "card_id": card["card_id"],
                "path": project_relative(output_path),
                "sha256": digest,
                "review_status": card["review"]["status"],
                "quality_flags": card["review"]["quality_flags"],
            }
        )

    report = {
        "schema_version": "knowledge-pilot-report-v1",
        "knowledge_snapshot_id": KNOWLEDGE_SNAPSHOT_ID,
        "ruleset_id": RULESET_ID,
        "generated_at": manifest["retrieved_at"],
        "card_count": len(report_cards),
        "approved_count": sum(item["review_status"] == "approved" for item in report_cards),
        "cards": report_cards,
    }
    atomic_write(REPORT_PATH, canonical_json_bytes(report))
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true", help="freeze raw official sources only")
    mode.add_argument("--build-only", action="store_true", help="build from an existing raw manifest")
    parser.add_argument(
        "--replace-generated",
        action="store_true",
        help="replace differing generated cards; never replaces immutable raw sources",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = RAW_ROOT / "manifest.json"
    if args.build_only:
        if not manifest_path.exists():
            raise FileNotFoundError("Raw manifest does not exist; run without --build-only first")
        manifest = load_json(manifest_path)
    else:
        manifest = download_sources(timeout=args.timeout)

    if not args.download_only:
        cards = build_cards(manifest, replace_generated=args.replace_generated)
        print(f"Generated and validated {len(cards)} cards in {NORMALIZED_ROOT}")
        print(f"Report: {REPORT_PATH}")
    else:
        print(f"Downloaded and verified {len(manifest['files'])} raw files in {RAW_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
