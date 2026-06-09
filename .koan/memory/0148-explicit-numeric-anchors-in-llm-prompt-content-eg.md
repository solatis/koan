---
title: Explicit numeric anchors in LLM prompt content (e.g. "100-500 tokens") bias
  generation toward the stated number
type: lesson
created: '2026-05-12T03:15:03Z'
modified: '2026-05-12T03:15:03Z'
---

The koan curation prompt at `koan/phases/curation.py` previously included the guidance "Every entry is 100-500 tokens of temporally grounded, attributed, event-style prose." On 2026-05-11, the user identified that this explicit range was biasing the LLM toward generating entries near the upper bound: the 137 entries written under the v4 discipline (2026-04-16 onward) averaged roughly 500 tokens each, at the high end of the stated range.

Root cause: explicit numeric guidance in prompt content acts as an anchor for LLM generation, regardless of whether the prompt frames the number as a minimum, maximum, or range. The LLM treats the stated value as a target. The user's exact wording: "there is a real potential that *because* we say '100 - 500 tokens', the LLM is heavily biased towards 500 tokens. what we really need is not token limits (maybe we shouldn't even mention that at all, and let the LLM decide this by rules / process, not arbitrary limits)."

Prevention: when writing prompt content meant to constrain LLM output, do not include explicit numeric ranges or quantitative size bounds. Describe the required content (what the output must carry) and let length follow from the content; see the paired procedure entry covering this rule generally.

Concrete consequence in the koan codebase: the 2026-05-11 writing-discipline retune removed the "100-500 tokens" guidance from both `docs/memory-system.md` and `koan/phases/curation.py`. Replacement is per-type content guidelines (decisions bundle choice + rationale + rejected alternatives; lessons carry event + root cause + prevention; procedures carry trigger + rule + consequence; contexts carry stable fact + why it matters) without size bounds.
