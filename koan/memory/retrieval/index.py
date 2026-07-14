from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

import lancedb
import pyarrow as pa
import voyageai
from lancedb.index import FTS

from ..parser import parse_entry

from ...types import ModelSpec
TABLE_NAME = "entries"
_ENTRY_PATTERN = re.compile(r"^(\d{4})-.*\.md$")


def _content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entry_id_from_name(name: str) -> int | None:
    m = _ENTRY_PATTERN.match(name)
    if m is None:
        return None
    return int(m.group(1))


async def _embed_texts(texts: list[str], input_type: str, model: ModelSpec) -> list[list[float]]:
    """Embed texts using the voyage provider via the explicit embedding ModelSpec.

    The embedding model/key arrive via the explicit model parameter; no module
    global is read. The binding must point at a voyage connection;
    embeddings are voyage-only (brief D9).
    Raises RuntimeError when the provider is not voyage.
    """
    if model.provider != "voyage":
        raise RuntimeError(
            f"Memory embedding binding must use a voyage connection; "
            f"got provider={model.provider!r}."
        )
    client = voyageai.AsyncClient(api_key=model.api_key)
    result = await client.embed(
        texts, model=model.model, input_type=input_type,
        output_dimension=model.embedding_dim,
    )
    return result.embeddings


async def _embed_query(text: str, model: ModelSpec) -> list[float]:
    """Embed a single query text via the explicit embedding ModelSpec."""
    result = await _embed_texts([text], "query", model)
    return result[0]


def _lancedb_schema(dim: int) -> pa.Schema:
    """Build the LanceDB schema parameterized by embedding dimension.

    dim is the resolved output dimension for the active Voyage binding.
    A dimension change requires dropping and recreating the table because
    the vector column width is fixed at creation time (exist_ok=True on
    create_table ignores the schema argument on an existing table).
    """
    return pa.schema([
        pa.field("entry_id", pa.int32()),
        pa.field("file_path", pa.utf8()),
        pa.field("title", pa.utf8()),
        pa.field("type", pa.utf8()),
        pa.field("created", pa.utf8()),
        pa.field("modified", pa.utf8()),
        pa.field("body", pa.utf8()),
        pa.field("content_hash", pa.utf8()),
        pa.field("vector", pa.list_(pa.float32(), dim)),
    ])


class RetrievalIndex:
    def __init__(self, memory_dir: Path) -> None:
        self._memory_dir = memory_dir
        self._index_path = memory_dir / ".index"
        self._lock: asyncio.Lock = asyncio.Lock()
        self._synced: bool = False

    async def ensure_synced(self, model: ModelSpec) -> None:
        """Ensure the vector index is up to date using the explicit embedding model."""
        async with self._lock:
            await self._sync(model)
            self._synced = True

    async def _existing_table_dim(self, conn) -> int | None:
        """Return the vector-column dimension of the live LanceDB table, or None.

        Returns None when the table does not exist, so callers can treat
        None as "needs creation" without a separate existence check.
        Uses lancedb async API: list_tables() returns a ListTablesResponse
        with a .tables attribute; tbl.schema() is an async call.
        """
        tables = await conn.list_tables()
        if TABLE_NAME not in tables.tables:
            return None
        tbl = await conn.open_table(TABLE_NAME)
        schema = await tbl.schema()
        # Locate the 'vector' field and read the fixed-list size.
        for field in schema:
            if field.name == "vector" and hasattr(field.type, "list_size"):
                return field.type.list_size
        return None

    async def _sync(self, model: ModelSpec) -> None:
        """Sync on-disk memory entries into the LanceDB vector index.

        Uses the explicit embedding model for dimension and embedding calls;
        no module global is read. When the existing table was built at a
        different dimension, it is dropped and recreated so the schema is
        consistent with the current binding. After a drop, all stored entries
        are re-embedded from scratch.

        Re-embed failure (e.g. Voyage unreachable) leaves a newly created
        empty table; the next ensure_synced() call re-embeds, self-healing.
        """
        conn = await lancedb.connect_async(str(self._index_path))

        # dim drives both the schema and the embed call.
        dim = model.embedding_dim

        # Self-heal: if the existing table dimension does not match the
        # current binding's dimension, drop it so it is recreated below.
        existing_dim = await self._existing_table_dim(conn)
        if existing_dim is not None and existing_dim != dim:
            await conn.drop_table(TABLE_NAME)

        table = await conn.create_table(TABLE_NAME, schema=_lancedb_schema(dim), exist_ok=True)

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
            vectors = await _embed_texts(texts, "document", model)

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

    async def rebuild(self, model: ModelSpec) -> None:
        """Force-rebuild the vector index: drop the existing table and re-embed all entries.

        Acquires the non-reentrant self._lock and calls _sync() directly (NOT
        ensure_synced()) so the lock is not re-acquired inside.  Calling
        ensure_synced() here would deadlock because asyncio.Lock is
        non-reentrant.  _sync() with a dropped table acts as a full rebuild:
        stored hashes are empty so every on-disk entry is re-embedded with
        the explicit model.
        """
        async with self._lock:
            conn = await lancedb.connect_async(str(self._index_path))
            # Drop the existing table; _sync below recreates it at the current dim.
            tables = await conn.list_tables()
            if TABLE_NAME in tables.tables:
                await conn.drop_table(TABLE_NAME)
            await self._sync(model)

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
