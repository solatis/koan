# CLI handlers for `koan memory` subcommands.

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from ..memory import ops
from ..memory.retrieval import RetrievalIndex, search as retrieval_search, inject as rag_inject
from ..memory.store import MemoryStore


def _make_store() -> MemoryStore:
    store = MemoryStore(Path.cwd())
    store.init()
    return store


def _make_index(store: MemoryStore) -> RetrievalIndex:
    return RetrievalIndex(store._memory_dir)


def _die(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def _has_api_key() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))


def _print_human_readable(result: dict) -> None:
    summary = result.get("summary") or ""
    print("# Summary")
    print(summary if summary else "(none)")
    print()

    entries = result.get("entries") or []
    if not entries:
        print("No entries.")
        return

    col_id = 8
    col_type = 10
    header = f"{'entry_id':<{col_id}}  {'type':<{col_type}}  title"
    print(header)
    print("-" * len(header))
    for e in entries:
        entry_id = str(e.get("entry_id", ""))
        etype = str(e.get("type", ""))
        title = str(e.get("title", ""))
        print(f"{entry_id:<{col_id}}  {etype:<{col_type}}  {title}")


def cmd_memorize(args: argparse.Namespace) -> None:
    store = _make_store()
    body = args.body if args.body is not None else sys.stdin.read()
    try:
        result = ops.memorize(
            store,
            args.type,
            args.title,
            body,
            related=args.related or None,
            entry_id=args.entry_id,
        )
    except ValueError as e:
        _die(str(e))
        return
    print(json.dumps(result))


def cmd_forget(args: argparse.Namespace) -> None:
    store = _make_store()
    try:
        result = ops.forget(store, args.entry_id, type=args.type)
    except ValueError as e:
        _die(str(e))
        return
    print(json.dumps(result))


def cmd_status(args: argparse.Namespace) -> None:
    store = _make_store()
    if store.summary_is_stale() and not _has_api_key():
        print(
            "koan status: summary is stale but GEMINI_API_KEY is not set"
            " -- cannot regenerate",
            file=sys.stderr,
        )
        sys.exit(1)
    result = asyncio.run(ops.status(store, type=getattr(args, "type", None)))
    if getattr(args, "json_output", False):
        print(json.dumps(result))
    else:
        _print_human_readable(result)
    if result.get("regenerated"):
        print("(summary regenerated)", file=sys.stderr)


def cmd_search(args: argparse.Namespace) -> None:
    store = _make_store()
    index = _make_index(store)
    type_filter = getattr(args, "type", None)
    k = getattr(args, "k", 5)
    json_output = getattr(args, "json_output", False)
    try:
        results = asyncio.run(retrieval_search(index, args.query, k=k, type_filter=type_filter))
    except RuntimeError as e:
        _die(str(e))
        return
    if json_output:
        out = {
            "results": [
                {
                    "entry_id": r.entry_id,
                    "title": r.entry.title,
                    "type": r.entry.type,
                    "score": r.score,
                    "created": r.entry.created,
                    "modified": r.entry.modified,
                    "body": r.entry.body,
                }
                for r in results
            ]
        }
        print(json.dumps(out))
    else:
        sep = "-" * 60
        for r in results:
            print(f"[{r.entry_id:04d}] {r.entry.title}  type={r.entry.type}  score={r.score:.4f}")
            preview = r.entry.body[:200].replace("\n", " ")
            print(f"  {preview}...")
            print(sep)


def cmd_rag(args: argparse.Namespace) -> None:
    store = _make_store()
    index = _make_index(store)
    directive = args.directive
    anchor_raw = args.anchor
    k = getattr(args, "k", 5)
    json_output = getattr(args, "json_output", False)

    if anchor_raw.startswith("@"):
        anchor_path = Path(anchor_raw[1:])
        if not anchor_path.exists():
            _die(f"anchor file not found: {anchor_path}")
            return
        anchor = anchor_path.read_text(encoding="utf-8")
    else:
        anchor = anchor_raw

    try:
        results = asyncio.run(rag_inject(index, directive, anchor, k=k))
    except RuntimeError as e:
        _die(str(e))
        return

    if json_output:
        out = {
            "results": [
                {
                    "entry_id": r.entry_id,
                    "title": r.entry.title,
                    "type": r.entry.type,
                    "score": r.score,
                    "created": r.entry.created,
                    "modified": r.entry.modified,
                    "body": r.entry.body,
                }
                for r in results
            ]
        }
        print(json.dumps(out))
    else:
        sep = "-" * 60
        for r in results:
            print(f"[{r.entry_id:04d}] {r.entry.title}  type={r.entry.type}  score={r.score:.4f}")
            preview = r.entry.body[:200].replace("\n", " ")
            print(f"  {preview}...")
            print(sep)


def cmd_memory(args: argparse.Namespace) -> None:
    cmd = getattr(args, "memory_command", None)
    if cmd == "memorize":
        cmd_memorize(args)
    elif cmd == "forget":
        cmd_forget(args)
    elif cmd == "status":
        cmd_status(args)
    elif cmd == "search":
        cmd_search(args)
    elif cmd == "rag":
        cmd_rag(args)
    elif cmd == "reflect":
        print("koan memory reflect: not yet implemented", file=sys.stderr)
        sys.exit(1)
    else:
        mem_parser = getattr(args, "_mem_parser", None)
        if mem_parser is not None:
            mem_parser.print_help()
        sys.exit(1)
