#!/usr/bin/env python3
"""Build a deterministic compact mechanics view from Champion Knowledge Card v2."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ID = "kb-lol-pc-16.16.1-zh-CN-v1"
SNAPSHOT_ROOT = PROJECT_ROOT / "data/knowledge/snapshots" / SNAPSHOT_ID
CARDS_ROOT = SNAPSHOT_ROOT / "cards"
CONTEXT_VIEW_ID = "compact-mechanics-v2"
VIEW_ROOT = PROJECT_ROOT / "data/knowledge/context_views" / SNAPSHOT_ID / CONTEXT_VIEW_ID
CONTEXT_ROOT = VIEW_ROOT / "contexts"
MANIFEST_PATH = VIEW_ROOT / "manifest.json"
RENDERER_VERSION = "deterministic-compact-mechanics-v2"

SLOT_LABELS = {"passive": "被动", "q": "Q", "w": "W", "e": "E", "r": "R"}
SLOT_ORDER = {slot: index for index, slot in enumerate(SLOT_LABELS)}
ATTACK_TYPE_ZH = {"melee": "近战", "ranged": "远程", "unknown": "未标注"}
ROLE_ZH = {
    "assassin": "刺客",
    "fighter": "战士",
    "mage": "法师",
    "marksman": "射手",
    "support": "辅助",
    "tank": "坦克",
}
DAMAGE_TYPE_ZH = {"physical": "物理", "magic": "魔法", "true": "真实"}

# Only direct client markup is displayed; no derived tactical labels are added.
DIRECT_MARKER_ZH = {
    "shield": "护盾",
    "healing": "治疗/回复",
    "speed": "移速变化",
    "attackspeed": "攻速变化",
    "keywordstealth": "隐身/潜行",
    "recast": "再次施放",
    "charge": "蓄力",
    "release": "蓄力释放",
    "onhit": "攻击特效",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_status_terms(values: list[str]) -> list[str]:
    """Drop leaked template variables while preserving short source terms."""
    result: list[str] = []
    for value in values:
        term = clean_text(value)
        if not term or "@" in term or len(term) > 12:
            continue
        if term not in result:
            result.append(term)
    return result


def ability_signals(ability: dict[str, Any]) -> dict[str, Any]:
    summary = clean_text(ability["summary_zh"])
    markup_tags = set(ability.get("markup_tags", []))
    markers = [tag for tag in DIRECT_MARKER_ZH if tag in markup_tags]
    damage_types = [
        damage_type
        for damage_type in ability.get("damage_types", [])
        if damage_type in DAMAGE_TYPE_ZH
    ]
    return {
        "summary": summary,
        "markers": markers,
        "damage_types": damage_types,
        "status_terms": clean_status_terms(ability.get("status_terms_zh", [])),
    }


def select_abilities(card: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep all Passive/Q/W/E/R slots; compactness must not drop abilities."""
    abilities = card["abilities"]
    actual_slots = [ability["slot"] for ability in abilities]
    expected_slots = list(SLOT_LABELS)
    if len(actual_slots) != len(set(actual_slots)):
        raise ValueError(
            f"{card['champion']['stable_id']}: 技能槽位重复：{actual_slots}"
        )
    if set(actual_slots) != set(expected_slots):
        raise ValueError(
            f"{card['champion']['stable_id']}: 必须完整包含 Passive/Q/W/E/R；"
            f"实际槽位={actual_slots}"
        )
    return sorted(abilities, key=lambda ability: SLOT_ORDER[ability["slot"]])


def direct_mechanism_index(card: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {
        "damage_types": [],
        "status_terms": [],
        "client_markers": [],
    }
    for ability in card["abilities"]:
        signals = ability_signals(ability)
        for damage_type in signals["damage_types"]:
            label = DAMAGE_TYPE_ZH[damage_type]
            if label not in result["damage_types"]:
                result["damage_types"].append(label)
        for term in signals["status_terms"]:
            if term not in result["status_terms"]:
                result["status_terms"].append(term)
        for marker in signals["markers"]:
            label = DIRECT_MARKER_ZH[marker]
            if label not in result["client_markers"]:
                result["client_markers"].append(label)
    return result


def render_compact_context(card: dict[str, Any]) -> tuple[str, list[str]]:
    champion = card["champion"]
    classification = card["client_classification"]
    roles = "、".join(
        ROLE_ZH.get(role.casefold(), role) for role in classification.get("roles", [])
    ) or "未标注"
    index = direct_mechanism_index(card)
    selected = select_abilities(card)
    index_parts = []
    if index["damage_types"]:
        index_parts.append("伤害=" + "/".join(index["damage_types"]))
    if index["status_terms"]:
        index_parts.append("控制=" + "/".join(index["status_terms"]))
    if index["client_markers"]:
        index_parts.append("标记=" + "/".join(index["client_markers"]))
    if not index_parts:
        index_parts.append("客户端未提供可直接提取的机制标记")

    lines = [
        f"英雄：{champion['official_name_zh']}（{champion['official_name_en']}；ID={champion['stable_id']}）",
        "基础："
        f"{ATTACK_TYPE_ZH.get(classification['attack_type'], '未标注')}；"
        f"资源={champion['resource_type_zh']}；官方角色={roles}",
        "确定性索引：" + "；".join(index_parts),
        "关键机制（技能槽位与英雄严格对应）：",
    ]
    for ability in selected:
        lines.append(
            f"- {SLOT_LABELS[ability['slot']]} {ability['name_zh']}："
            f"{clean_text(ability['summary_zh'])}"
        )
    lines.append(f"追溯：{card['card_id']}；上下文视图={CONTEXT_VIEW_ID}")
    return "\n".join(lines) + "\n", [ability["slot"] for ability in selected]


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def build_context_view() -> dict[str, Any]:
    snapshot_manifest = load_json(SNAPSHOT_ROOT / "manifest.json")
    card_manifest = {item["champion_id"]: item for item in snapshot_manifest["cards"]}
    records = []
    jsonl_records = []
    total_compact_chars = 0
    total_full_chars = 0
    for card_path in sorted(CARDS_ROOT.glob("*.json")):
        card = load_json(card_path)
        champion_id = card["champion"]["stable_id"]
        context, selected_slots = render_compact_context(card)
        context_payload = context.encode("utf-8")
        output_path = CONTEXT_ROOT / f"{champion_id}.md"
        atomic_write(output_path, context_payload)
        full_context = (SNAPSHOT_ROOT / "contexts" / f"{champion_id}.md").read_text(
            encoding="utf-8"
        )
        total_compact_chars += len(context)
        total_full_chars += len(full_context)
        jsonl_records.append(
            json.dumps(
                {
                    "champion_id": champion_id,
                    "card_id": card["card_id"],
                    "context_view_id": CONTEXT_VIEW_ID,
                    "selected_ability_slots": selected_slots,
                    "context_zh": context,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        records.append(
            {
                "champion_id": champion_id,
                "card_id": card["card_id"],
                "source_card_sha256": card_manifest[champion_id]["card_sha256"],
                "context_path": output_path.relative_to(PROJECT_ROOT).as_posix(),
                "context_sha256": sha256_bytes(context_payload),
                "context_char_count": len(context),
                "selected_ability_slots": selected_slots,
            }
        )

    contexts_payload = ("\n".join(jsonl_records) + "\n").encode("utf-8")
    atomic_write(VIEW_ROOT / "contexts.jsonl", contexts_payload)
    manifest = {
        "schema_version": "knowledge-context-view-manifest-v1",
        "context_view_id": CONTEXT_VIEW_ID,
        "renderer_version": RENDERER_VERSION,
        "knowledge_snapshot_id": SNAPSHOT_ID,
        "knowledge_manifest_sha256": sha256_bytes(
            (SNAPSHOT_ROOT / "manifest.json").read_bytes()
        ),
        "source_card_count": snapshot_manifest["card_count"],
        "context_count": len(records),
        "selection_policy": {
            "ordinary_max_abilities": 4,
            "complex_max_abilities": 5,
            "summary_source": "Champion Knowledge Card v2 summary_zh",
            "displayed_indexes": "direct client damage/status/markup only",
            "llm_generated_fields": False,
        },
        "aggregate": {
            "compact_char_count": total_compact_chars,
            "full_char_count": total_full_chars,
            "char_ratio": round(total_compact_chars / total_full_chars, 4),
        },
        "contexts_jsonl_sha256": sha256_bytes(contexts_payload),
        "contexts": records,
    }
    atomic_write(
        MANIFEST_PATH,
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build", action="store_true", help="从冻结知识卡重建 compact-mechanics-v2"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.build:
        raise ValueError("当前命令只支持 --build；查询请使用 query_kb.py --context-view")
    manifest = build_context_view()
    print(
        json.dumps(
            {
                "context_view_id": manifest["context_view_id"],
                "context_count": manifest["context_count"],
                "char_ratio": manifest["aggregate"]["char_ratio"],
                "manifest": str(MANIFEST_PATH.relative_to(PROJECT_ROOT)),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

