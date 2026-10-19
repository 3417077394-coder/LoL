#!/usr/bin/env python3
"""Build the full source-grounded LoL 16.16.1 Chinese champion knowledge base."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from jsonschema import Draft202012Validator, FormatChecker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas/champion_knowledge_card_v2.schema.json"
DDRAGON_VERSION = "16.16.1"
CDRAGON_VERSION = "16.16"
PUBLIC_PATCH_ALIAS = "26.16"
AS_OF = "2026-08-21"
RULESET_ID = "lol-pc-ddragon-16.16.1-asof-2026-08-21"
REGION_SCOPE = "global_pc"
SOURCE_SNAPSHOT_ID = "sources-lol-pc-16.16.1-asof-2026-08-21-v1"
KNOWLEDGE_SNAPSHOT_ID = "kb-lol-pc-16.16.1-zh-CN-v1"
BUILDER_VERSION = "full-kb-builder-v1"
SOURCE_ROOT = PROJECT_ROOT / "data/knowledge/source_snapshots" / SOURCE_SNAPSHOT_ID
SOURCE_MANIFEST_PATH = SOURCE_ROOT / "manifest.json"
SNAPSHOT_ROOT = PROJECT_ROOT / "data/knowledge/snapshots" / KNOWLEDGE_SNAPSHOT_ID
CARDS_ROOT = SNAPSHOT_ROOT / "cards"
CONTEXT_ROOT = SNAPSHOT_ROOT / "contexts"
DDRAGON_BASE = "https://ddragon.leagueoflegends.com"
CDRAGON_BASE = "https://raw.communitydragon.org"
RIOT_SITE_BASE = "https://www.leagueoflegends.com"
WIKI_API = "https://wiki.leagueoflegends.com/en-us/api.php"
PATCH_NOTES_URL = (
    "https://www.leagueoflegends.com/en-gb/news/game-updates/"
    "league-of-legends-patch-26-16-notes/"
)
USER_AGENT = "lol-draft-alignment-source-builder/1.0"
SLOTS = ("passive", "q", "w", "e", "r")
WIKI_BATCH_SIZE = 35
ROLE_ZH = {
    "assassin": "刺客", "fighter": "战士", "mage": "法师", "marksman": "射手",
    "support": "辅助", "tank": "坦克",
}
ATTACK_TYPE_ZH = {"melee": "近战", "ranged": "远程", "mixed": "可切换", "unknown": "未知"}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def project_relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def clean_plain_text(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return " ".join(value.split())


def clean_client_detail(value: str) -> tuple[str, bool]:
    had_placeholders = bool(re.search(r"@[^@]+@|\{\{[^{}]+\}\}", value))
    value = re.sub(r"@SpellModifierDescriptionAppend@", "", value)
    value = re.sub(r"@[^@]+@", "【数值】", value)
    value = re.sub(r"\{\{[^{}]+\}\}", "【依当前形态或武器而定】", value)
    return clean_plain_text(value), not had_placeholders


def slug_for_champion(stable_id: str) -> str:
    return stable_id.lower()


def wiki_page_name(stable_id: str, english_name: str) -> str:
    return "Nunu" if stable_id == "Nunu" else english_name


def spec(path: str, url: str, *, media_type: str) -> dict[str, Any]:
    return {"relative_path": path, "url": url, "media_type": media_type}


def initial_specs() -> list[dict[str, Any]]:
    return [
        spec("ddragon/versions.json", f"{DDRAGON_BASE}/api/versions.json", media_type="application/json"),
        spec("ddragon/realms/na.json", f"{DDRAGON_BASE}/realms/na.json", media_type="application/json"),
        spec("ddragon/zh_CN/champion.json", f"{DDRAGON_BASE}/cdn/{DDRAGON_VERSION}/data/zh_CN/champion.json", media_type="application/json"),
        spec("ddragon/en_US/champion.json", f"{DDRAGON_BASE}/cdn/{DDRAGON_VERSION}/data/en_US/champion.json", media_type="application/json"),
        spec("riot/champions-index.html", f"{RIOT_SITE_BASE}/en-us/champions/", media_type="text/html"),
        spec("riot/patch-26.16-notes.html", PATCH_NOTES_URL, media_type="text/html"),
    ]


def individual_specs(roster: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for hero_id, row in roster.items():
        for locale in ("zh_CN", "en_US"):
            output.append(spec(
                f"ddragon/{locale}/champion/{hero_id}.json",
                f"{DDRAGON_BASE}/cdn/{DDRAGON_VERSION}/data/{locale}/champion/{hero_id}.json",
                media_type="application/json",
            ))
        key = row["key"]
        output.append(spec(
            f"communitydragon/zh_cn/champions/{key}.json",
            f"{CDRAGON_BASE}/{CDRAGON_VERSION}/plugins/rcp-be-lol-game-data/global/zh_cn/v1/champions/{key}.json",
            media_type="application/json",
        ))
        slug = slug_for_champion(hero_id)
        output.append(spec(
            f"riot/champions/{slug}.html",
            f"{RIOT_SITE_BASE}/en-us/champions/{slug}/",
            media_type="text/html",
        ))
    return output


def make_wiki_query_url(titles: list[str]) -> str:
    params = {
        "action": "query", "titles": "|".join(titles), "redirects": "1",
        "prop": "revisions", "rvprop": "ids|timestamp|content", "rvslots": "main",
        "format": "json", "formatversion": "2",
    }
    return f"{WIKI_API}?{urlencode(params)}"


def wiki_batch_specs(kind: str, titles: list[str]) -> list[dict[str, Any]]:
    batches = []
    for index in range(0, len(titles), WIKI_BATCH_SIZE):
        batch_titles = titles[index:index + WIKI_BATCH_SIZE]
        item = spec(
            f"wiki/{kind}/batch-{index // WIKI_BATCH_SIZE + 1:03d}.json",
            make_wiki_query_url(batch_titles), media_type="application/json",
        )
        item["titles"] = batch_titles
        batches.append(item)
    return batches


def request_bytes(url: str, timeout: float) -> bytes:
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            response.raise_for_status()
            return response.content
        except (requests.RequestException, TimeoutError) as error:
            last_error = error
            if attempt < 3:
                time.sleep(0.5 * (2 ** attempt))
    assert last_error is not None
    raise last_error


def download_one(item: dict[str, Any], timeout: float) -> dict[str, Any]:
    path = SOURCE_ROOT / item["relative_path"]
    if path.exists():
        payload = path.read_bytes()
    else:
        payload = request_bytes(item["url"], timeout)
        if item["media_type"] == "application/json":
            json.loads(payload)
        atomic_write(path, payload)
    result = {key: item[key] for key in ("relative_path", "url", "media_type")}
    result.update({"sha256": sha256_bytes(payload), "bytes": len(payload)})
    return result


def download_many(specs: list[dict[str, Any]], *, timeout: float, workers: int, label: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download_one, item, timeout): item for item in specs}
        completed = 0
        for future in as_completed(futures):
            results.append(future.result())
            completed += 1
            if completed % 50 == 0 or completed == len(specs):
                print(f"{label}: {completed}/{len(specs)}", flush=True)
    return sorted(results, key=lambda item: item["relative_path"])


def ddragon_roster() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    zh = load_json(SOURCE_ROOT / "ddragon/zh_CN/champion.json")
    en = load_json(SOURCE_ROOT / "ddragon/en_US/champion.json")
    if zh.get("version") != DDRAGON_VERSION or en.get("version") != DDRAGON_VERSION:
        raise ValueError("Data Dragon summary version mismatch")
    if set(zh["data"]) != set(en["data"]):
        raise ValueError("Data Dragon zh_CN and en_US rosters differ")
    return zh["data"], en["data"]


def validate_core_sources() -> None:
    versions = load_json(SOURCE_ROOT / "ddragon/versions.json")
    realm = load_json(SOURCE_ROOT / "ddragon/realms/na.json")
    if DDRAGON_VERSION not in versions:
        raise ValueError(f"{DDRAGON_VERSION} is missing from the official version catalog")
    if realm.get("n", {}).get("champion") != DDRAGON_VERSION:
        raise ValueError("NA realm champion build does not match the pinned Data Dragon build")
    zh, _ = ddragon_roster()
    if len(zh) != 173:
        raise ValueError(f"Expected 173 standard champions, found {len(zh)}")
    index = (SOURCE_ROOT / "riot/champions-index.html").read_text(encoding="utf-8")
    hrefs = {
        anchor.get("href") for anchor in BeautifulSoup(index, "html.parser").find_all("a")
        if anchor.get("href") and re.fullmatch(r"/en-us/champions/[^/]+/", anchor.get("href"))
    }
    expected = {f"/en-us/champions/{slug_for_champion(hero_id)}/" for hero_id in zh}
    if hrefs != expected:
        raise ValueError(f"Riot champion index mismatch: missing={sorted(expected-hrefs)}, extra={sorted(hrefs-expected)}")


def query_pages_from_batches(batch_specs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for item in batch_specs:
        raw_path = SOURCE_ROOT / item["relative_path"]
        query = load_json(raw_path).get("query", {})
        aliases = {title: title for title in item["titles"]}
        for normalization in query.get("normalized", []):
            aliases[normalization["from"]] = normalization["to"]
        redirects = {entry["from"]: entry["to"] for entry in query.get("redirects", [])}
        pages = {page["title"]: page for page in query.get("pages", [])}
        for requested in item["titles"]:
            title = aliases.get(requested, requested)
            seen = set()
            while title in redirects and title not in seen:
                seen.add(title)
                title = redirects[title]
            page = pages.get(title)
            if page is None:
                page = next((value for key, value in pages.items() if key.casefold() == title.casefold()), None)
            resolved[requested] = {
                "requested_title": requested, "resolved_title": title,
                "page": page, "raw_path": raw_path,
            }
    return resolved


def revision_record(query_record: dict[str, Any]) -> dict[str, Any] | None:
    page = query_record.get("page")
    if not page or page.get("missing"):
        return None
    revisions = page.get("revisions", [])
    if not revisions:
        return None
    revision = revisions[0]
    return {
        "title": page["title"], "page_id": page["pageid"], "revision_id": revision["revid"],
        "revision_timestamp": revision["timestamp"], "content": revision["slots"]["main"]["content"],
        "raw_path": query_record["raw_path"].relative_to(SOURCE_ROOT).as_posix(),
    }


ABILITY_TEMPLATE_RE = re.compile(
    r"\{\{\s*Data\s+([^/|{}]+?)/([^|{}]+?)\|\s*Ability\b", re.IGNORECASE
)


def extract_ability_template_titles(page_content: str) -> list[str]:
    return unique(
        f"Template:Data {champion.strip()}/{ability.strip()}"
        for champion, ability in ABILITY_TEMPLATE_RE.findall(page_content)
    )


def slot_from_template(title: str, content: str = "") -> str | None:
    skill_match = re.search(r"^\s*\|\s*skill\s*=\s*([A-Z]+)", content, re.I | re.M)
    first = (skill_match.group(1) if skill_match else title.rsplit("/", 1)[-1]).strip().lower()[:1]
    return {"i": "passive", "p": "passive", "q": "q", "w": "w", "e": "e", "r": "r"}.get(first)


def build_wiki_index(roster_en: dict[str, dict[str, Any]], main_batches: list[dict[str, Any]], ability_batches: list[dict[str, Any]]) -> dict[str, Any]:
    main_queries = query_pages_from_batches(main_batches)
    ability_queries = query_pages_from_batches(ability_batches)
    champions: dict[str, Any] = {}
    for hero_id, row in roster_en.items():
        page_name = wiki_page_name(hero_id, row["name"])
        main = revision_record(main_queries[page_name])
        ability_sources = {slot: [] for slot in SLOTS}
        if main:
            for requested_title in extract_ability_template_titles(main["content"]):
                query = ability_queries.get(requested_title)
                record = revision_record(query) if query else None
                slot = slot_from_template(requested_title, record["content"] if record else "")
                if slot and record:
                    record = {key: value for key, value in record.items() if key != "content"}
                    record["requested_title"] = requested_title
                    ability_sources[slot].append(record)
        champions[hero_id] = {
            "page": None if not main else {key: value for key, value in main.items() if key != "content"},
            "abilities": ability_sources,
        }
    return {"schema_version": "wiki-source-index-v1", "retrieved_for_ruleset": RULESET_ID, "champions": champions}


def extract_patch_changes(html_text: str, champion_names: set[str]) -> dict[str, str]:
    soup = BeautifulSoup(html_text, "html.parser")
    headings = soup.find_all(["h2", "h3"])
    in_champions = False
    changes: dict[str, str] = {}
    for heading in headings:
        text = clean_plain_text(heading.get_text(" ", strip=True))
        if heading.name == "h2":
            if in_champions:
                break
            in_champions = text == "Champions"
            continue
        if not in_champions or text not in champion_names:
            continue
        pieces: list[str] = []
        for element in heading.next_elements:
            if isinstance(element, Tag) and element is not heading and element.name in {"h2", "h3"}:
                break
            if isinstance(element, NavigableString):
                value = " ".join(str(element).split())
                if value:
                    pieces.append(value)
        changes[text] = " ".join(pieces)
    return changes


def tags_and_status_terms(raw_detail: str) -> tuple[list[str], list[str]]:
    tags = unique(match.lower() for match in re.findall(r"<([A-Za-z][A-Za-z0-9]*)\b", raw_detail))
    terms = unique(clean_plain_text(value) for value in re.findall(r"<status>(.*?)</status>", raw_detail, re.I | re.S))
    return tags, terms


def damage_types(raw_detail: str, rendered_detail: str) -> list[str]:
    lower = raw_detail.lower()
    found = []
    for tag, value in (("physicaldamage", "physical"), ("magicdamage", "magic"), ("truedamage", "true")):
        if f"<{tag}" in lower:
            found.append(value)
    if found:
        return found
    return ["unknown"] if "伤害" in rendered_detail else ["none"]


def source_entry_by_path(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["relative_path"]: entry for entry in manifest["files"]}


def source_record(*, source_ref_id: str, source_type: str, publisher: str, title: str,
                  version_namespace: str, source_version: str, raw_path: Path,
                  manifest: dict[str, Any], url: str | None = None,
                  revision_id: int | None = None, revision_timestamp: str | None = None) -> dict[str, Any]:
    relative = raw_path.relative_to(SOURCE_ROOT).as_posix()
    entry = source_entry_by_path(manifest)[relative]
    return {
        "source_ref_id": source_ref_id, "source_type": source_type, "publisher": publisher,
        "title": title, "url": url or entry["url"], "version_namespace": version_namespace,
        "source_version": source_version, "retrieved_at": manifest["retrieved_at"],
        "content_hash": f"sha256:{entry['sha256']}", "raw_snapshot_path": project_relative(raw_path),
        "revision_id": revision_id, "revision_timestamp": revision_timestamp,
    }


def wiki_source_record(record: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    ref_id = f"source:wiki:{record['page_id']}:{record['revision_id']}"
    url_title = quote(record["title"].replace(" ", "_"), safe="/:!")
    return source_record(
        source_ref_id=ref_id, source_type="official_wiki_community_maintained",
        publisher="League of Legends Wiki community (Riot-supported)", title=record["title"],
        version_namespace="wiki_revision", source_version=f"revision:{record['revision_id']}",
        raw_path=SOURCE_ROOT / record["raw_path"], manifest=manifest,
        url=f"https://wiki.leagueoflegends.com/en-us/{url_title}",
        revision_id=record["revision_id"], revision_timestamp=record["revision_timestamp"],
    )


def cdragon_attack_type(value: Any) -> str:
    normalized = str(value or "").lower().removeprefix("k")
    return normalized if normalized in {"melee", "ranged", "mixed"} else "unknown"


def build_card(hero_id: str, zh_summary: dict[str, Any], en_summary: dict[str, Any],
               wiki_data: dict[str, Any], patch_changes: dict[str, str], manifest: dict[str, Any]) -> dict[str, Any]:
    zh_path = SOURCE_ROOT / f"ddragon/zh_CN/champion/{hero_id}.json"
    en_path = SOURCE_ROOT / f"ddragon/en_US/champion/{hero_id}.json"
    cdragon_path = SOURCE_ROOT / f"communitydragon/zh_cn/champions/{zh_summary['key']}.json"
    riot_page_path = SOURCE_ROOT / f"riot/champions/{slug_for_champion(hero_id)}.html"
    patch_path = SOURCE_ROOT / "riot/patch-26.16-notes.html"
    zh = load_json(zh_path)["data"][hero_id]
    en = load_json(en_path)["data"][hero_id]
    client = load_json(cdragon_path)
    official_name_zh, title_zh = zh["title"], zh["name"]
    ddragon_zh_ref = f"source:ddragon:{DDRAGON_VERSION}:zh_CN:{hero_id}"
    ddragon_en_ref = f"source:ddragon:{DDRAGON_VERSION}:en_US:{hero_id}"
    cdragon_ref = f"source:communitydragon:{CDRAGON_VERSION}:zh_cn:{hero_id}"
    riot_page_ref = f"source:riot-champion-page:{hero_id}:asof-{AS_OF}"
    patch_ref = f"source:riot-patch-notes:{PUBLIC_PATCH_ALIAS}"
    sources = [
        source_record(source_ref_id=ddragon_zh_ref, source_type="riot_ddragon", publisher="Riot Games",
                      title=f"Data Dragon {DDRAGON_VERSION} zh_CN: {official_name_zh}", version_namespace="ddragon",
                      source_version=DDRAGON_VERSION, raw_path=zh_path, manifest=manifest),
        source_record(source_ref_id=ddragon_en_ref, source_type="riot_ddragon", publisher="Riot Games",
                      title=f"Data Dragon {DDRAGON_VERSION} en_US: {en['name']}", version_namespace="ddragon",
                      source_version=DDRAGON_VERSION, raw_path=en_path, manifest=manifest),
        source_record(source_ref_id=cdragon_ref, source_type="communitydragon_client_extract", publisher="CommunityDragon",
                      title=f"LoL client game-data {CDRAGON_VERSION} zh_cn: {official_name_zh}", version_namespace="communitydragon_patch",
                      source_version=CDRAGON_VERSION, raw_path=cdragon_path, manifest=manifest),
        source_record(source_ref_id=riot_page_ref, source_type="riot_champion_page", publisher="Riot Games",
                      title=f"Riot champion page: {en['name']}", version_namespace="live_as_of", source_version=AS_OF,
                      raw_path=riot_page_path, manifest=manifest),
        source_record(source_ref_id=patch_ref, source_type="riot_patch_notes", publisher="Riot Games",
                      title=f"League of Legends Patch {PUBLIC_PATCH_ALIAS} Notes", version_namespace="public_patch",
                      source_version=PUBLIC_PATCH_ALIAS, raw_path=patch_path, manifest=manifest),
    ]
    wiki_refs_by_slot: dict[str, list[str]] = {slot: [] for slot in SLOTS}
    for slot in SLOTS:
        for record in wiki_data["abilities"][slot]:
            wiki_source = wiki_source_record(record, manifest)
            if wiki_source["source_ref_id"] not in {item["source_ref_id"] for item in sources}:
                sources.append(wiki_source)
            wiki_refs_by_slot[slot].append(wiki_source["source_ref_id"])
    raw_zh = [zh["passive"], *zh["spells"]]
    raw_en = [en["passive"], *en["spells"]]
    client_by_slot = {spell["spellKey"].lower(): spell for spell in client["spells"]}
    abilities = []
    for slot, official_zh, official_en in zip(SLOTS, raw_zh, raw_en, strict=True):
        if slot == "passive":
            client_ability = client["passive"]
            raw_detail = client_ability.get("description") or official_zh["description"]
        else:
            client_ability = client_by_slot[slot]
            dynamic = client_ability.get("dynamicDescription") or ""
            usable_dynamic = clean_plain_text(dynamic.replace("@SpellModifierDescriptionAppend@", ""))
            raw_detail = dynamic if usable_dynamic else client_ability["description"]
        rendered_detail, exact_numbers_preserved = clean_client_detail(raw_detail)
        markup_tags, status_terms = tags_and_status_terms(raw_detail)
        ability_source_refs = [ddragon_zh_ref, ddragon_en_ref, cdragon_ref, *wiki_refs_by_slot[slot]]
        abilities.append({
            "ability_id": f"ability:{hero_id}:{slot}:ddragon-{DDRAGON_VERSION}", "slot": slot,
            "name_zh": clean_plain_text(official_zh["name"]), "name_en": clean_plain_text(official_en["name"]),
            "summary_zh": clean_plain_text(official_zh["description"]), "summary_en": clean_plain_text(official_en["description"]),
            "detailed_description_zh": rendered_detail, "damage_types": damage_types(raw_detail, rendered_detail),
            "status_terms_zh": status_terms, "markup_tags": markup_tags,
            "mechanism_critical_numbers_preserved": exact_numbers_preserved,
            "field_sources": {
                "name_zh": [ddragon_zh_ref], "name_en": [ddragon_en_ref],
                "summary_zh": [ddragon_zh_ref], "summary_en": [ddragon_en_ref],
                "detailed_description_zh": [cdragon_ref], "deterministic_hints": [cdragon_ref],
                "wiki_supplement": wiki_refs_by_slot[slot],
            },
            "source_ref_ids": unique(ability_source_refs), "wiki_source_ref_ids": wiki_refs_by_slot[slot],
            "extraction": {
                "method": "deterministic_client_markup_v1", "status": "source_grounded" if rendered_detail else "partial",
                "notes": [
                    "详细中文机制来自固定 CommunityDragon 客户端数据；数值占位符统一显示为【数值】。",
                    "伤害类型和状态词只从客户端标记确定性提取，不由模型补写。",
                ],
            },
        })
    tactical = client.get("tacticalInfo", {})
    playstyle = client.get("playstyleInfo", {})
    wiki_gap_slots = [slot for slot, refs in wiki_refs_by_slot.items() if not refs]
    total_wiki_abilities = sum(len(refs) for refs in wiki_refs_by_slot.values())
    quality_flags = []
    if wiki_gap_slots:
        quality_flags.append("wiki_ability_gap:" + ",".join(wiki_gap_slots))
    if total_wiki_abilities > 5 or any("/" in ability["name_en"] for ability in abilities):
        quality_flags.append("complex_ability_structure")
    if any(not ability["mechanism_critical_numbers_preserved"] for ability in abilities):
        quality_flags.append("exact_values_omitted_from_context")
    patch_text = patch_changes.get(en["name"])
    return {
        "schema_version": "champion-knowledge-card-v2",
        "card_id": f"champion:{hero_id}:ddragon-{DDRAGON_VERSION}:zh-CN:v2",
        "knowledge_snapshot_id": KNOWLEDGE_SNAPSHOT_ID,
        "ruleset": {"ruleset_id": RULESET_ID, "ddragon_version": DDRAGON_VERSION,
                    "public_patch_alias": PUBLIC_PATCH_ALIAS, "as_of": AS_OF, "region_scope": REGION_SCOPE},
        "locale": "zh-CN",
        "champion": {"stable_id": hero_id, "numeric_key": zh["key"], "official_name_zh": official_name_zh,
                     "official_name_en": en["name"], "title_zh": title_zh, "aliases": unique([en["name"], hero_id]),
                     "resource_type_zh": zh["partype"] or "无", "source_ref_ids": [ddragon_zh_ref, ddragon_en_ref, cdragon_ref, riot_page_ref]},
        "client_classification": {
            "roles": unique(client.get("roles", [])), "attack_type": cdragon_attack_type(tactical.get("attackType")),
            "difficulty": tactical.get("difficulty"),
            "playstyle": {"damage": playstyle.get("damage"), "durability": playstyle.get("durability"),
                          "crowd_control": playstyle.get("crowdControl"), "mobility": playstyle.get("mobility"),
                          "utility": playstyle.get("utility")}, "source_ref_ids": [cdragon_ref],
        },
        "abilities": abilities,
        "patch_change": {"status": "listed" if patch_text else "not_listed", "text_en": patch_text, "source_ref_id": patch_ref},
        "provenance": {"sources": sources, "generated_at": manifest["retrieved_at"], "builder_version": BUILDER_VERSION,
                       "input_hashes": unique(source["content_hash"] for source in sources)},
        "quality": {
            "status": "source_grounded_auto", "human_reviewed": False,
            "source_coverage": {"ddragon": True, "communitydragon": True, "riot_champion_page": True,
                                "official_wiki": total_wiki_abilities > 0, "patch_notes": True},
            "quality_flags": quality_flags,
            "usage_policy": "可用于来源约束的中文 RAG；自动提示不等同于人工专家结论。",
        },
    }


def validate_card_semantics(card: dict[str, Any]) -> None:
    hero_id = card["champion"]["stable_id"]
    if [ability["slot"] for ability in card["abilities"]] != list(SLOTS):
        raise ValueError(f"{hero_id}: abilities are not passive/Q/W/E/R")
    source_ids = {source["source_ref_id"] for source in card["provenance"]["sources"]}
    if len(source_ids) != len(card["provenance"]["sources"]):
        raise ValueError(f"{hero_id}: duplicate source_ref_id")
    for source_ref in card["champion"]["source_ref_ids"]:
        if source_ref not in source_ids:
            raise ValueError(f"{hero_id}: champion references missing source {source_ref}")
    for ability in card["abilities"]:
        missing = set(ability["source_ref_ids"]) - source_ids
        if missing:
            raise ValueError(f"{hero_id}/{ability['slot']}: missing sources {sorted(missing)}")
        field_missing = {
            source_ref
            for refs in ability["field_sources"].values()
            for source_ref in refs
            if source_ref not in source_ids
        }
        if field_missing:
            raise ValueError(
                f"{hero_id}/{ability['slot']}: field_sources reference missing sources {sorted(field_missing)}"
            )


def render_context_zh(card: dict[str, Any]) -> str:
    champion = card["champion"]
    classification = card["client_classification"]
    roles = "、".join(ROLE_ZH.get(role, role) for role in classification["roles"]) or "未标注"
    lines = [
        f"英雄：{champion['official_name_zh']}（{champion['title_zh']}）",
        f"版本：Data Dragon {DDRAGON_VERSION}；公开补丁 {PUBLIC_PATCH_ALIAS}；知识截止 {AS_OF}",
        f"基础：{ATTACK_TYPE_ZH[classification['attack_type']]}；资源：{champion['resource_type_zh']}；官方角色：{roles}",
        "技能机制：",
    ]
    labels = {"passive": "被动", "q": "Q", "w": "W", "e": "E", "r": "R"}
    for ability in card["abilities"]:
        description = ability["detailed_description_zh"]
        if "/" in ability["name_zh"] and ability["summary_zh"] != description:
            description = f"{ability['summary_zh']} 客户端详细展开：{description}"
        lines.append(f"- {labels[ability['slot']]} {ability['name_zh']}：{description}")
    lines.extend([
        "说明：文中的【数值】表示客户端原始描述中的版本化数值占位符；本上下文保留机制，不展开伤害成长数值。",
        f"追溯：{card['card_id']}",
    ])
    return "\n".join(lines) + "\n"


def verify_source_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("source_snapshot_id") != SOURCE_SNAPSHOT_ID:
        raise ValueError("Source snapshot ID mismatch")
    for entry in manifest.get("files", []):
        path = SOURCE_ROOT / entry["relative_path"]
        if not path.is_file() or sha256_bytes(path.read_bytes()) != entry["sha256"]:
            raise ValueError(f"Source snapshot hash mismatch: {path}")


def build_source_snapshot(*, timeout: float, workers: int) -> tuple[dict[str, Any], dict[str, Any]]:
    if SOURCE_MANIFEST_PATH.exists():
        manifest = load_json(SOURCE_MANIFEST_PATH)
        verify_source_manifest(manifest)
        return manifest, load_json(SOURCE_ROOT / "indexes/wiki-abilities.json")
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    core_specs = initial_specs()
    core_entries = download_many(core_specs, timeout=timeout, workers=min(workers, 6), label="core sources")
    validate_core_sources()
    roster_zh, roster_en = ddragon_roster()
    detail_specs = individual_specs(roster_zh)
    detail_entries = download_many(detail_specs, timeout=timeout, workers=workers, label="champion sources")
    main_titles = [wiki_page_name(hero_id, roster_en[hero_id]["name"]) for hero_id in roster_en]
    main_batches = wiki_batch_specs("champions", main_titles)
    main_entries = download_many(main_batches, timeout=timeout, workers=min(workers, 4), label="wiki champion pages")
    main_queries = query_pages_from_batches(main_batches)
    template_titles = sorted({
        template for title in main_titles for main in [revision_record(main_queries[title])] if main
        for template in extract_ability_template_titles(main["content"])
    })
    ability_batches = wiki_batch_specs("abilities", template_titles)
    ability_entries = download_many(ability_batches, timeout=timeout, workers=min(workers, 4), label="wiki ability templates")
    wiki_index = build_wiki_index(roster_en, main_batches, ability_batches)
    atomic_write(SOURCE_ROOT / "indexes/wiki-abilities.json", canonical_json_bytes(wiki_index))
    all_entries = sorted(core_entries + detail_entries + main_entries + ability_entries, key=lambda item: item["relative_path"])
    manifest = {
        "schema_version": "knowledge-source-manifest-v1", "source_snapshot_id": SOURCE_SNAPSHOT_ID,
        "ruleset_id": RULESET_ID, "ddragon_version": DDRAGON_VERSION, "communitydragon_version": CDRAGON_VERSION,
        "public_patch_alias": PUBLIC_PATCH_ALIAS, "as_of": AS_OF, "retrieved_at": retrieved_at,
        "roster_size": len(roster_zh), "wiki_template_count": len(template_titles), "files": all_entries,
    }
    atomic_write(SOURCE_MANIFEST_PATH, canonical_json_bytes(manifest))
    verify_source_manifest(manifest)
    return manifest, wiki_index


def build_knowledge_snapshot(manifest: dict[str, Any], wiki_index: dict[str, Any]) -> dict[str, Any]:
    schema = load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    roster_zh, roster_en = ddragon_roster()
    patch_changes = extract_patch_changes(
        (SOURCE_ROOT / "riot/patch-26.16-notes.html").read_text(encoding="utf-8"),
        {row["name"] for row in roster_en.values()},
    )
    card_records = []
    alias_index: dict[str, str] = {}
    contexts_jsonl = []
    for hero_id in sorted(roster_zh):
        card = build_card(hero_id, roster_zh[hero_id], roster_en[hero_id], wiki_index["champions"][hero_id], patch_changes, manifest)
        errors = sorted(validator.iter_errors(card), key=lambda error: list(error.path))
        if errors:
            message = "; ".join(f"{list(error.path)}: {error.message}" for error in errors[:8])
            raise ValueError(f"{hero_id} failed v2 schema: {message}")
        validate_card_semantics(card)
        card_path = CARDS_ROOT / f"{hero_id}.json"
        card_payload = canonical_json_bytes(card)
        atomic_write(card_path, card_payload)
        context = render_context_zh(card)
        context_path = CONTEXT_ROOT / f"{hero_id}.md"
        atomic_write(context_path, context.encode("utf-8"))
        contexts_jsonl.append(json.dumps(
            {"champion_id": hero_id, "card_id": card["card_id"], "context_zh": context},
            ensure_ascii=False, sort_keys=True,
        ))
        for alias in unique([
            hero_id,
            card["champion"]["official_name_zh"],
            card["champion"]["official_name_en"],
            card["champion"]["title_zh"],
            *card["champion"]["aliases"],
        ]):
            previous = alias_index.setdefault(alias.casefold(), hero_id)
            if previous != hero_id:
                raise ValueError(f"Alias collision: {alias!r} maps to {previous} and {hero_id}")
        card_records.append({
            "champion_id": hero_id, "official_name_zh": card["champion"]["official_name_zh"],
            "card_path": project_relative(card_path), "card_sha256": sha256_bytes(card_payload),
            "context_path": project_relative(context_path), "context_sha256": sha256_bytes(context.encode("utf-8")),
            "quality_flags": card["quality"]["quality_flags"], "patch_change_status": card["patch_change"]["status"],
        })
    atomic_write(SNAPSHOT_ROOT / "aliases.json", canonical_json_bytes(alias_index))
    atomic_write(SNAPSHOT_ROOT / "contexts.jsonl", ("\n".join(contexts_jsonl) + "\n").encode("utf-8"))
    snapshot_manifest = {
        "schema_version": "knowledge-snapshot-manifest-v1", "knowledge_snapshot_id": KNOWLEDGE_SNAPSHOT_ID,
        "source_snapshot_id": SOURCE_SNAPSHOT_ID, "ruleset_id": RULESET_ID, "ddragon_version": DDRAGON_VERSION,
        "public_patch_alias": PUBLIC_PATCH_ALIAS, "as_of": AS_OF, "locale": "zh-CN", "builder_version": BUILDER_VERSION,
        "generated_at": manifest["retrieved_at"], "card_count": len(card_records), "human_reviewed_count": 0,
        "source_grounded_auto_count": len(card_records),
        "source_file_count": len(manifest["files"]),
        "wiki_ability_slot_covered": sum(
            bool(refs)
            for champion in wiki_index["champions"].values()
            for refs in champion["abilities"].values()
        ),
        "wiki_ability_slot_total": len(card_records) * len(SLOTS),
        "patch_changed_champion_count": sum(item["patch_change_status"] == "listed" for item in card_records),
        "cards": card_records,
    }
    atomic_write(SNAPSHOT_ROOT / "manifest.json", canonical_json_bytes(snapshot_manifest))
    return snapshot_manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--sources-only", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.workers < 1 or args.workers > 16:
        raise ValueError("--workers must be between 1 and 16")
    if args.sources_only and args.build_only:
        raise ValueError("--sources-only and --build-only are mutually exclusive")
    if args.build_only:
        manifest = load_json(SOURCE_MANIFEST_PATH)
        verify_source_manifest(manifest)
        wiki_index = load_json(SOURCE_ROOT / "indexes/wiki-abilities.json")
    else:
        manifest, wiki_index = build_source_snapshot(timeout=args.timeout, workers=args.workers)
    if not args.sources_only:
        snapshot = build_knowledge_snapshot(manifest, wiki_index)
        print(
            f"Built {snapshot['card_count']} source-grounded cards in {SNAPSHOT_ROOT}; "
            f"patch-listed champions: {snapshot['patch_changed_champion_count']}", flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
