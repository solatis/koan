---
title: Opus 4.7+ requires --thinking-display summarized to restore thinking tokens
  in Claude CLI stream-json
type: context
created: '2026-04-19T06:21:20Z'
modified: '2026-04-19T06:21:20Z'
---

This entry records the addition of `--thinking-display summarized` to Claude launch arguments in koan. On 2026-04-19, Leon reported that Anthropic's Opus 4.7 release changed Claude Code CLI behavior: the default thinking-display mode changed to "off", omitting thinking tokens from the stream-json output entirely unless the consumer opts in via the undocumented `--thinking-display` flag. In response, Leon directed that the Claude runner in `koan/runners/claude.py` append `--thinking-display summarized` to the command whenever the selected model alias contained "opus" (case-insensitive substring match, inserted between `--model X` and the `installation.extra_args` spread). The `summarized` value produced condensed reasoning summaries suitable for the projection store's thinking-block rendering path, while the Opus 4.7+ default produced no thinking content at all. Leon chose substring matching over exact or prefix matching on the rationale that users were assumed to run the latest Opus model; earlier Opus releases (4.6 and prior) accepted the flag as a no-op, so the substring match was safe across versions. The flag was not present in Claude Code's published CLI reference at that date; Leon discovered it empirically after the 4.7 upgrade broke thinking-block visibility in the koan frontend.
