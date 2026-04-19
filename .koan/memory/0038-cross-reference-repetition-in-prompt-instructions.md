---
title: Cross-reference repetition in prompt instructions aids LLM instruction following
type: procedure
created: '2026-04-17T04:22:19Z'
modified: '2026-04-17T04:22:19Z'
---

The koan phase prompt system (`koan/phases/*.py`) was confirmed on 2026-04-17 to follow a cross-reference repetition principle for LLM instruction following. When the plan proposed adding the COMMENT classification to step 2 substep E's "Apply" list (even though COMMENT was already defined in the classification schema earlier in the prompt), the user confirmed this was correct, stating "these type of cross-references and repetitions work well" for optimizing instruction following. The user described this as fitting koan's existing conventions. The rule: when writing phase prompt instructions, repeat classifications, rules, and categories at each point of use rather than referencing earlier definitions once. The model recognizes the repeated information from earlier context, and the repetition reinforces the expected behavior at the moment of action.
