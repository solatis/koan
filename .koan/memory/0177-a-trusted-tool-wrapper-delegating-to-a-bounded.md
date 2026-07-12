---
title: A trusted tool wrapper delegating to a bounded primitive must thread the size-limit
  bypass explicitly, or it silently inherits the bound
type: lesson
created: '2026-06-07T04:04:08Z'
modified: '2026-07-10T08:20:57Z'
related:
- 0173-three-class-tool-trust-taxonomy-untrusted-built.md
- 0174-untrusted-built-in-tool-output-readgrepglobbash.md
---

When koan's `koan_artifact_read` was made a trusted command exempt from the untrusted output cap, it was implemented as a wrapper delegating to the same built-in `read_tool` that enforces that cap (`koan/tools/koan_tools.py`, `koan/tools/builtin_tools.py`). The reference patch the work was based on gave `read_tool` no bypass parameter, so following it literally would have silently re-limited the trusted artifact reader — review phases reading large artifacts would have hit the cap despite being declared exempt. Root cause: a trusted path that delegates to a bounded primitive inherits the primitive's bound unless the exemption is threaded through explicitly. Prevention applied: `read_tool` accepts `limit: int | None = DEFAULT_LIMIT`; `artifact_read_core` and the model-facing `_koan_artifact_read` wrapper both pass `limit=None` to return full content. The parameter is deliberately kept as an integer (`limit: int = DEFAULT_LIMIT`) on the model-facing `_read` wrapper so the model cannot pass `None` to un-limit a raw untrusted read. Both directions of the seam are hazards: silently re-limiting the trusted reader, and silently un-limiting raw reads. The hazard re-surfaced when the pre-emptive limiting redesign changed the bypass from `enforce_limits=False` to `limit=None`: the model-facing `_koan_artifact_read` wrapper initially kept its default at `2000`, which would have passed `2000` to `read_tool` — slicing every artifact read to 2000 lines via `render_anchored` and silently re-bounding the trusted reader despite the `limit=None` core default. The fix changed the wrapper's default to `None`. The general rule: when a trusted/exempt wrapper sits over a bounded/untrusted primitive, make the exemption an explicit internal-only parameter and verify both directions — especially when the bypass mechanism changes, every wrapper default must be re-checked.
