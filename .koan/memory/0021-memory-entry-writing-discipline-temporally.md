---
title: 'Koan memory writing discipline: per-type content guidelines, no token cap,
  frontmatter for temporal context (2026-05-11 revision)'
type: procedure
created: '2026-04-16T09:02:41Z'
modified: '2026-05-12T03:14:44Z'
---

The koan memory system stores entries in `.koan/memory/NNNN-*.md` and applies a writing discipline rendered both in `docs/memory-system.md` and in the curation prompt at `koan/phases/curation.py`. On 2026-05-11, the user retuned the discipline from the earlier 2026-04-16 v4 form (five uniform rules including "every statement includes a date" plus a "100-500 tokens" length range) to a per-type content-driven form.

Current rules: (1) situate the entry for retrieval with concrete subsystem / file / decision names; (2) attribute when the source affects trust calibration -- not categorical; (3) no forward-looking language -- entries record what has happened; (4) name things concretely (versions, file paths, environment variables); (5) each entry stands alone. There is no token range and no length target.

Each memory type has a characteristic content shape, defined in `docs/memory-system.md`: decisions bundle choice + rationale + rejected alternatives + surfacing context (the neo-Davidsonian "must stay bundled" principle, narrowed from the earlier uniform-rule framing); contexts carry the specific fact + why it matters; lessons carry event + root cause + prevention; procedures carry trigger + rule + consequence + counter-frame. Procedure entries are the shape closest to a sharp factual rule. Titles read as factual headlines that name a subsystem + claim, not as topic labels; they participate in the embedding text (`# {title}\ntype: {type}\n\n{body}` per `koan/memory/retrieval/index.py`).

Temporal context lives in the frontmatter `created` and `modified` fields. Dates may appear in body prose when a specific date is itself part of the rationale or a load-bearing fact, but embedding a date in every claim is no longer required.

The 2026-05-11 retune was forward-only: existing entries written under the v4 discipline were not rewritten.
