---
title: A trusted tool wrapper delegating to a bounded primitive must thread the size-limit
  bypass explicitly, or it silently inherits the bound
type: lesson
created: '2026-06-07T04:04:08Z'
modified: '2026-06-07T04:04:08Z'
related:
- 0173-three-class-tool-trust-taxonomy-untrusted-built.md
- 0174-untrusted-built-in-tool-output-readgrepglobbash.md
---

When koan's `koan_artifact_read` was made a trusted command exempt from the untrusted-output reject ceiling, it was implemented as a wrapper delegating to the same built-in `read_tool` that ENFORCES that ceiling (`koan/tools/koan_tools.py`, `koan/tools/builtin_tools.py`). The reference patch the work was based on gave `read_tool` no bypass parameter, so following it literally would have silently re-limited the trusted artifact reader -- review phases reading large artifacts would have hit the 500-line / 10 KB reject despite being declared exempt. Root cause: a trusted path that delegates to a bounded primitive inherits the primitive's bound unless the exemption is threaded through explicitly. Prevention applied: `read_tool` gained an `enforce_limits: bool = True` parameter, `artifact_read_core` calls `read_tool(..., enforce_limits=False)`, and the parameter is deliberately kept OUT of the model-facing `_read` tool signature so the model cannot un-limit a raw untrusted read by passing the flag itself. Both directions of the seam are hazards: silently re-limiting the trusted reader, and silently un-limiting raw reads. The general rule: when a trusted/exempt wrapper sits over a bounded/untrusted primitive, make the exemption an explicit internal-only parameter and verify both directions.
