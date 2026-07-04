# CLI handlers for `koan memory` subcommands.

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..config import load_koan_config, save_koan_config
from ..credentials import CredentialStore, get_key_backend
from ..memory.bindings import build_memory_models, require_memory_model
from ..memory import ops
from ..memory.retrieval import RetrievalIndex, search as retrieval_search, inject as rag_inject
from ..memory.retrieval import (
    IterationCapExceeded,
    ReflectTraceEvent,
    run_reflect_agent,
)
from ..memory.store import MemoryStore


def _make_store() -> MemoryStore:
    store = MemoryStore(Path.cwd())
    store.init()
    return store


def _make_index(store: MemoryStore) -> RetrievalIndex:
    return RetrievalIndex(store._memory_dir)


def _resolve_tier_model(
    config: "KoanConfig",
    credential_store: "CredentialStore",
    tier: str,
) -> "ModelSpec | None":
    """Resolve a ModelSpec for a tier slot from the active preset.

    Returns None when the preset, slot, configured model, or connection is
    missing rather than raising — callers check for None and report the gap.
    Mirrors AgentRegistry.resolve_model_spec but keyed by tier name (not role),
    as directed by the remove-memory-LLM-bindings initiative.
    """
    from ..agents.registry import build_resolved_model
    try:
        preset = config.presets.get(config.active)
        if preset is None:
            return None
        slot = preset.slots.get(tier)
        if slot is None:
            return None
        cm = next(
            (m for m in config.configured_models if m.id == slot.configured_model_id), None
        )
        conn = (
            next((c for c in config.connections if c.id == cm.connection_id), None)
            if cm else None
        )
        if cm is None or conn is None:
            return None
        api_key = credential_store.resolve(conn.id) if credential_store and conn.id else None
        return build_resolved_model(
            conn, cm, slot.thinking, slot.caching, cm.embedding_dim, api_key,
            cache_tier="short",
        )
    except Exception:
        return None



def _die(msg: str) -> None:
    print(json.dumps({"error": msg}), file=sys.stderr)
    sys.exit(1)


def _has_cheap_model(cheap_spec: "ModelSpec | None") -> bool:
    """True when a cheap ModelSpec has been resolved (cheap slot is configured).

    Does not check whether api_key is non-None; keyless providers are valid.
    """
    return cheap_spec is not None


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


def cmd_status(args: argparse.Namespace, cheap_spec: "ModelSpec | None") -> None:
    """Print memory status. Skips regeneration when the cheap model spec is not
    resolved (cheap slot not configured in the active preset)."""
    store = _make_store()
    if store.summary_is_stale() and not _has_cheap_model(cheap_spec):
        print(
            "koan status: summary is stale but 'cheap' slot is not configured in the active preset"
            " -- cannot regenerate",
            file=sys.stderr,
        )
        sys.exit(1)
    result = asyncio.run(ops.status(store, model=cheap_spec, type=getattr(args, "type", None)))
    if getattr(args, "json_output", False):
        print(json.dumps(result))
    else:
        _print_human_readable(result)
    if result.get("regenerated"):
        print("(summary regenerated)", file=sys.stderr)


def cmd_search(args: argparse.Namespace, models: MemoryModels) -> None:
    """Search memory entries. Requires the embedding binding to be configured."""
    store = _make_store()
    index = _make_index(store)
    type_filter = getattr(args, "type", None)
    k = getattr(args, "k", 5)
    json_output = getattr(args, "json_output", False)
    try:
        embed = require_memory_model(models.embedding, "embedding")
        results = asyncio.run(retrieval_search(index, args.query, embed, k=k, type_filter=type_filter))
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


def cmd_rag(args: argparse.Namespace, embed_spec: "ModelSpec", cheap_spec: "ModelSpec") -> None:
    """Run the RAG injection pipeline. Requires resolved embed and cheap ModelSpecs."""
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
        results = asyncio.run(rag_inject(index, embed_spec, cheap_spec, directive, anchor, k=k))
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


def cmd_reflect(args: argparse.Namespace, embed_spec: "ModelSpec", standard_spec: "ModelSpec") -> None:
    """Run the reflection loop. Requires resolved embed and standard ModelSpecs."""
    store = _make_store()
    index = _make_index(store)
    json_output = getattr(args, "json_output", False)
    show_trace = getattr(args, "show_trace", False)

    def on_trace(event: ReflectTraceEvent) -> None:
        if event.kind == "search":
            q = event.query
            tf = event.type_filter or None
            rc = event.result_count if event.result_count is not None else "?"
            tag = f" type={tf}" if tf else ""
            print(
                f"[iter {event.iteration}] search({q!r}{tag}) -> {rc} results",
                file=sys.stderr,
            )
        elif event.kind == "done":
            print(f"[iter {event.iteration}] done", file=sys.stderr)

    try:
        result = asyncio.run(run_reflect_agent(
            index,
            model=standard_spec,
            embed=embed_spec,
            question=args.question,
            context=getattr(args, "context", None),
            on_trace=on_trace if show_trace else None,
        ))
    except IterationCapExceeded as e:
        _die(f"iteration_cap_exceeded after {e.iterations} iterations")
        return
    except RuntimeError as e:
        _die(str(e))
        return

    if json_output:
        out = {
            "answer": result.answer,
            "citations": [{"id": c.id, "title": c.title} for c in result.citations],
            "iterations": result.iterations,
        }
        print(json.dumps(out))
    else:
        print("# Briefing")
        print(result.answer)
        print()
        print("# Citations")
        if not result.citations:
            print("(none)")
        else:
            for c in result.citations:
                print(f"- [{c.id:04d}] {c.title}")
        print()
        print(f"(iterations: {result.iterations})", file=sys.stderr)


def cmd_memory(args: argparse.Namespace) -> None:
    """Dispatch koan memory subcommands.

    Threads args.koan_home (resolved in main()) into the config loader/saver
    and key backend.  The memory store remains project-rooted at cwd and is
    not affected by --home.

    cheap and standard specs are resolved from the active preset's slot
    assignments and threaded explicitly to sub-commands that need them.
    """
    config = asyncio.run(load_koan_config(args.koan_home))
    store = CredentialStore(config, get_key_backend(args.koan_home))
    if store.pruned:
        asyncio.run(save_koan_config(config, args.koan_home))
    models = build_memory_models(config, store)
    cheap_spec = _resolve_tier_model(config, store, "cheap")
    standard_spec = _resolve_tier_model(config, store, "standard")

    cmd = getattr(args, "memory_command", None)
    if cmd == "memorize":
        cmd_memorize(args)
    elif cmd == "forget":
        cmd_forget(args)
    elif cmd == "status":
        cmd_status(args, cheap_spec)
    elif cmd == "search":
        cmd_search(args, models)
    elif cmd == "rag":
        embed = models.embedding
        if embed is None:
            _die("embedding binding is not configured")
            return
        if cheap_spec is None:
            _die("'cheap' slot is not configured in the active preset")
            return
        cmd_rag(args, embed, cheap_spec)
    elif cmd == "reflect":
        embed = models.embedding
        if embed is None:
            _die("embedding binding is not configured")
            return
        if standard_spec is None:
            _die("'standard' slot is not configured in the active preset")
            return
        cmd_reflect(args, embed, standard_spec)
    else:
        mem_parser = getattr(args, "_mem_parser", None)
        if mem_parser is not None:
            mem_parser.print_help()
        sys.exit(1)
