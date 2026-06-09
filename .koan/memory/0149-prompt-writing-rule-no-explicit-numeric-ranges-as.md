---
title: 'Prompt-writing rule: no explicit numeric ranges as content guidance; describe
  required content and let length follow'
type: procedure
created: '2026-05-12T03:15:09Z'
modified: '2026-05-12T03:15:09Z'
---

On 2026-05-11, during a koan plan workflow that retuned the memory writing discipline, the user established a general prompt-engineering rule applicable to any koan agent or maintainer writing prompt content for an LLM (phase modules in `koan/phases/`, agent-type system prompts in `koan/prompts/`, MCP tool descriptions, content-generation directives).

The rule: when prompt content is meant to constrain the shape of LLM output, do NOT include explicit numeric ranges, quantitative size bounds, or anchor phrases like "approximately N tokens", "1-3 paragraphs", "100-500 words", "between X and Y items". The LLM treats stated numeric values as targets regardless of whether they are framed as minimums, maximums, ranges, or rough guidance. Output drifts toward the stated number.

Replacement pattern: enumerate the content the output must carry; length emerges from the content. The koan memory writing discipline (revised 2026-05-11) applied this rule when it replaced "100-500 tokens" with per-type content guidelines (decisions bundle rationale + rejected alternatives + surfacing context; lessons carry event + root cause + prevention; procedures carry trigger + rule + consequence; contexts carry stable fact + why it matters). The LLM sees what to include but no target length.

Avoid replacement phrasings that imply a target without naming a number. "Concise", "brief", "short", "as short as possible" all force the LLM to guess at a target. "Long enough but not too long" is the same anti-pattern in different prose. Process-driven rules (what to include) are the only safe formulation.

The rule applies to all prompt surfaces, not only memory writing. Any place koan instructs an LLM "how much" to produce is subject to anchoring; the safe pattern is "what to include" instead.

Violating this rule produces LLM outputs that cluster at the stated number, regardless of whether that number is appropriate for the specific instance being generated.
