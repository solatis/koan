from __future__ import annotations

import asyncio
import hashlib
import os
import re
from pathlib import Path

import lancedb
import pyarrow as pa
import voyageai
from lancedb.index import FTS

from ..parser import parse_entry

VOYAGE_MODEL = "voyage-4-large"
VOYAGE_DIM = 1024
TABLE_NAME = "entries"
_ENTRY_PATTERN = re.compile(r"^(\d{4})-.*\.md$")


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry_id_from_name(name: str) -> int | None:
    m = _ENTRY_PATTERN.match(name)
    if m is None:
        return None
    return int(m.group(1))


def _voyage_api_key() -> str:
    key = os.environ.get("VOYAGE_API_KEY") or ""
    if not key:
        raise RuntimeError("VOYAGE_API_KEY environment variable is required")
    return key


async def _embed_texts(texts: list[str], input_type: str) -> list[list[float]]:
    client = voyageai.AsyncClient(api_key=_voyage_api_key())
    result = await client.embed(texts, model=VOYAGE_MODEL, input_type=input_type)
    return result.embeddings


async def _embed_query(text: str) -> list[float]:
    result = await _embed_texts([text], "query")
    return result[0]


def _lancedb_schema() -> pa.Schema:
    return pa.schema([
        pa.field("entry_id", pa.int32()),
        pa.field("file_path", pa.utf8()),
        pa.field("title", pa.utf8()),
        pa.field("type", pa.utf8()),
        pa.field("created", pa.utf8()),
        pa.field("modified", pa.utf8()),
        pa.field("body", pa.utf8()),
        pa.field("content_hash", pa.utf8()),
        pa.field("vector", pa.list_(pa.float32(), VOYAGE_DIM)),
    ])


class RetrievalIndex:
    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._index_path = memory_dir / ".index"
        self._lock: asyncio.Lock = asyncio.Lock()
        self._synced: bool = False

    async def ensure_synced(self) -> None:
        async with self._lock:
            await self._sync()
            self._synced = True

    async def _sync(self) -> None:
        conn = await lancedb.connect_async(str(self._index_path))

        # Create-or-open: exist_ok=True returns existing table without overwriting data
        table = await conn.create_table(TABLE_NAME, schema=_lancedb_schema(), exist_ok=True)

        # Load existing hashes: entry_id -> content_hash
        rows = await table.query().select(["entry_id", "content_hash"]).to_list()
        stored: dict[int, str] = {r["entry_id"]: r["content_hash"] for r in rows}

        # Scan memory_dir for NNNN-*.md files (excluding summary.md)
        disk: dict[int, Path] = {}
        if self._memory_dir.is_dir():
            for p in self._memory_dir.iterdir():
                if p.name == "summary.md":
                    continue
                eid = _entry_id_from_name(p.name)
                if eid is not None:
                    disk[eid] = p

        # Find changed or new files
        to_embed: list[tuple[int, Path]] = []
        for eid, path in disk.items():
            h = _content_hash(path)
            if stored.get(eid) != h:
                to_embed.append((eid, path))

        if to_embed:
            entries = [parse_entry(path) for _, path in to_embed]
            texts = [
                f"# {e.title}\ntype: {e.type}\n\n{e.body}"
                for e in entries
            ]
            vectors = await _embed_texts(texts, "document")

            records = []
            for (eid, path), entry, vector in zip(to_embed, entries, vectors):
                records.append({
                    "entry_id": eid,
                    "file_path": str(path),
                    "title": entry.title,
                    "type": entry.type,
                    "created": entry.created,
                    "modified": entry.modified,
                    "body": entry.body,
                    "content_hash": _content_hash(path),
                    "vector": vector,
                })

            # Upsert: delete existing rows for these entry_ids, then add new
            existing_eids = [eid for eid, _ in to_embed if eid in stored]
            if existing_eids:
                ids_str = ", ".join(str(e) for e in existing_eids)
                await table.delete(f"entry_id IN ({ids_str})")

            if records:
                await table.add(records)

        # Delete rows for files that no longer exist on disk
        deleted_eids = [eid for eid in stored if eid not in disk]
        if deleted_eids:
            ids_str = ", ".join(str(e) for e in deleted_eids)
            await table.delete(f"entry_id IN ({ids_str})")

        # Ensure FTS index exists (idempotent) -- only if the table has rows
        all_rows = await table.query().select(["entry_id"]).to_list()
        if all_rows:
            await table.create_index("body", config=FTS(), replace=True)
            await table.create_index("title", config=FTS(), replace=True)

    async def dense_search(self, query_vector: list[float], n: int = 20) -> list[dict]:
        conn = await lancedb.connect_async(str(self._index_path))
        table = await conn.open_table(TABLE_NAME)
        builder = await table.search(query_vector)
        return await builder.limit(n).to_list()

    async def fts_search(self, query: str, n: int = 20) -> list[dict]:
        conn = await lancedb.connect_async(str(self._index_path))
        table = await conn.open_table(TABLE_NAME)
        builder = await table.search(query, query_type="fts")
        return await builder.limit(n).to_list()
