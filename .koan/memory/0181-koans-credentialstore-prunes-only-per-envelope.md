---
title: koan's CredentialStore prunes only per-envelope-undecryptable secrets; a systemic
  master-key failure leaves all envelopes intact
type: decision
created: '2026-06-07T14:24:28Z'
modified: '2026-06-07T14:24:28Z'
related:
- 0178-koan-provider-api-keys-stored-in-an-encrypted.md
---

koan's encrypted credential store (`koan/credentials.py:CredentialStore`) loads at construction by decrypting every `~/.koan/config.json` envelope into an in-memory cache, and `_load_cache` now prunes an individually-undecryptable envelope -- removing the dead `{"scheme":"fernet","ciphertext":...}` entry and setting a read-only `pruned` flag -- instead of merely logging-and-skipping it. The two boot entrypoints that build the store, `koan/cli/run.py` and `koan/cli/memory.py`, then persist the cleaned `config.json` when `seed_from_env()` imported something OR `store.pruned` is set. The load-bearing safety rule, flagged by the change's adversarial plan-review: `_load_cache` validates the master key exactly once up front (`Fernet(self._backend.load_key())`) and, on failure, logs and returns leaving every envelope intact; only a genuine per-envelope decrypt failure prunes that single entry. Rationale: `decrypt_secret` loads the master key internally, so a systemic key failure -- an unreadable or malformed `~/.koan/master.key`, which makes `Fernet(key)` raise for every envelope -- would, under a naive prune-on-broad-`except`, prune and persist ALL credentials at once and irreversibly wipe them, because the stored ciphertext is the only copy. Alternative rejected: pruning inside a broad `except` around the whole decrypt, which cannot tell per-envelope corruption from a systemic key failure (a data-loss footgun). The intended payoff: an envelope orphaned under a now-lost master key self-heals on the next boot -- it is pruned, a fresh `master.key` is minted, and `seed_from_env` re-imports that provider from its environment variable when present.
