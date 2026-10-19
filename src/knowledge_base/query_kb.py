#!/usr/bin/env python3
"""Resolve champion aliases and assemble Chinese context from the fixed snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_ID = "kb-lol-pc-16.16.1-zh-CN-v1"
SNAPSHOT_ROOT = PROJECT_ROOT / "data/knowledge/snapshots" / SNAPSHOT_ID
LEGACY_COMPACT_CONTEXT_VIEW_ID = "compact-mechanics-v1"
COMPACT_CONTEXT_VIEW_ID = "compact-mechanics-v2"
CONTEXT_VIEW_ROOTS = {
    "full": SNAPSHOT_ROOT / "contexts",
    LEGACY_COMPACT_CONTEXT_VIEW_ID: (
        PROJECT_ROOT
        / "data/knowledge/context_views"
        / SNAPSHOT_ID
        / LEGACY_COMPACT_CONTEXT_VIEW_ID
        / "contexts"
    ),
    COMPACT_CONTEXT_VIEW_ID: (
        PROJECT_ROOT
        / "data/knowledge/context_views"
        / SNAPSHOT_ID
        / COMPACT_CONTEXT_VIEW_ID
        / "contexts"
    ),
}


def load_aliases() -> dict[str, str]:
    return json.loads((SNAPSHOT_ROOT / "aliases.json").read_text(encoding="utf-8"))


def resolve_champion(name: str, aliases: dict[str, str] | None = None) -> str:
    aliases = aliases or load_aliases()
    normalized = name.strip().casefold()
    if not normalized or normalized not in aliases:
        raise KeyError(f"知识快照中没有英雄名称或别名：{name!r}")
    return aliases[normalized]


def assemble_context(
    names: list[str], context_view: str = "full"
) -> tuple[list[str], str]:
    if not names or len(names) > 10:
        raise ValueError("一次必须查询 1～10 名英雄")
    if context_view not in CONTEXT_VIEW_ROOTS:
        raise ValueError(
            f"未知上下文视图：{context_view!r}；可选值：{sorted(CONTEXT_VIEW_ROOTS)}"
        )
    aliases = load_aliases()
    champion_ids = [resolve_champion(name, aliases) for name in names]
    if len(set(champion_ids)) != len(champion_ids):
        raise ValueError("同一英雄不能在一次上下文中重复出现")
    context_root = CONTEXT_VIEW_ROOTS[context_view]
    if not context_root.is_dir():
        raise FileNotFoundError(
            f"上下文视图尚未生成：{context_root}；"
            "紧凑视图请先运行 compact_context.py --build"
        )
    contexts = [
        (context_root / f"{champion_id}.md").read_text(encoding="utf-8").strip()
        for champion_id in champion_ids
    ]
    header = (
        f"知识快照：{SNAPSHOT_ID}\n"
        f"上下文视图：{context_view}\n"
        "规则：以下内容是来源约束的英雄机制事实，不包含阵容结论；请仅基于给定阵容进行推导。"
    )
    return champion_ids, header + "\n\n" + "\n\n---\n\n".join(contexts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("champions", nargs="+", help="1～10 个中文名、英文名或稳定 ID")
    parser.add_argument("--json", action="store_true", help="输出带 champion_ids 的 JSON")
    parser.add_argument(
        "--context-view",
        choices=sorted(CONTEXT_VIEW_ROOTS),
        default="full",
        help="选择完整或紧凑的确定性上下文视图",
    )
    args = parser.parse_args(argv)
    champion_ids, context = assemble_context(args.champions, args.context_view)
    if args.json:
        print(json.dumps({"snapshot_id": SNAPSHOT_ID, "context_view": args.context_view, "champion_ids": champion_ids, "context_zh": context}, ensure_ascii=False, indent=2))
    else:
        print(context, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
