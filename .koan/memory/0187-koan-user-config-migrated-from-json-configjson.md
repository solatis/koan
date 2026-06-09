---
title: koan user config migrated from JSON (config.json, camelCase) to YAML (~/.koan/config.yaml,
  snake_case) via pyyaml; YAML chosen over TOML
type: decision
created: '2026-06-08T08:26:06Z'
modified: '2026-06-08T08:26:06Z'
related:
- 0178
- '0155'
- '0014'
---

koan's user-settings file (loaded/saved exclusively by `koan/config.py` through `load_koan_config` / `save_koan_config`) was converted from JSON at `~/.koan/config.json` to YAML at `~/.koan/config.yaml`, with on-disk keys renamed from camelCase to snake_case. Leon decided this on 2026-06-08 after an intake interview about configuration-format philosophy. YAML was chosen over TOML because `pyyaml` is already a direct dependency, is load-bearing for memory-entry frontmatter (`koan/memory/writer.py`, `koan/memory/parser.py`), and is transitively required by `uvicorn`/`huggingface-hub`/`langchain-core` -- so YAML adds zero dependencies, whereas TOML would need a new writer dependency (`tomli-w`; stdlib `tomllib` reads but cannot write). YAML also unifies koan's human-facing structured data, since memory frontmatter is already YAML. snake_case was adopted because the on-disk camelCase was a TypeScript-heritage artifact fully decoupled from the UI: the in-memory dataclasses in `koan/types.py` (`ProviderAuth.env_keys`, `ModelSpec.context_window`, etc.) are already snake_case, and the camelCase the frontend consumes is produced independently at two boundaries -- the HTTP settings API in `koan/web/app.py` and the SSE projection in `koan/projections.py` (Pydantic `alias_generator=to_camel` + `model_dump(by_alias=True)`). `koan/config.py` is the sole translator between disk keys and dataclass fields, so changing the disk casing touched only `config.py` plus tests asserting on the saved file, leaving the wire/API camelCase unchanged. Rejected alternatives: TOML (Leon's stated explicit-and-minimal format philosophy favored it, but dependency-minimalism and memory-format consistency outweighed it once `pyyaml` was confirmed load-bearing rather than vestigial); keeping camelCase on disk (a pointless mismatch with the Python dataclasses for a file now meant to be hand-editable). The change was a hard cutover with no migration. Earlier memory entries describing credential storage and provider config still cite "config.json" as the path; the file is now `config.yaml`.
