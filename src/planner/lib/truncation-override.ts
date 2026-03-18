// Raises the effective truncation limit for bash tool output in koan subagents.
//
// Pi's built-in bash tool truncates output to 50KB / 2000 lines. When the
// prompt-engineer skill (or any skill that concatenates large reference files
// to stdout) runs via bash, the LLM loses critical context mid-output.
//
// Instead of replacing the built-in bash tool, we intercept the tool_result
// event. When truncation occurred, the bash tool has already saved the full
// output to a temp file. We re-read that file and apply truncateTail with
// higher limits, then return the replacement content. This is surgical —
// it only activates when truncation actually happened and a temp file exists.
//
// Why tool_result interception rather than registering a replacement bash tool:
// - No duplication of the bash tool implementation (exec, streaming, exit codes)
// - The bash tool's temp file mechanism is the key enabler — the full output
//   is already on disk before the event fires
// - Zero cost when output fits within the default limits (handler exits early)
//
// Registration is unconditional (not gated on subagent mode) because both
// parent sessions running skills directly and spawned subagent processes
// benefit from higher limits. The truncation guard makes it a no-op for
// outputs that fit within pi's defaults.
//
// Audit handler ordering: the audit tool_result handler (registered inside
// before_agent_start, after this one) records the ORIGINAL event content
// because it does not return a modified result — it only appends to the log.
// Pi runs handlers in registration order; each handler receives the event
// state as modified by prior handlers. Since the audit handler returns nothing,
// it never sees our replacement content, and since we don't touch the audit
// log, the two handlers are fully independent.

import { readFileSync } from "node:fs";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { truncateTail, formatSize, isBashToolResult } from "@mariozechner/pi-coding-agent";

// 4x the pi defaults (50KB / 2000 lines). Sized for the prompt-engineer skill,
// which concatenates ~100-150KB of technique reference files into a single bash
// call. 200KB gives comfortable headroom; 5000 lines is proportional (2.5x).
const KOAN_MAX_BYTES = 200 * 1024;
const KOAN_MAX_LINES = 5000;

export function registerTruncationOverride(pi: ExtensionAPI): void {
  pi.on("tool_result", (event) => {
    if (!isBashToolResult(event)) return;
    if (!event.details?.truncation?.truncated) return;
    if (!event.details?.fullOutputPath) return;

    const fullOutputPath = event.details.fullOutputPath;

    // readFileSync is fine here — the runner awaits handlers so async would
    // also work, but there's no benefit for a single temp file read.
    //
    // Timing note: the bash tool calls tempFileStream.end() then immediately
    // resolves. On local filesystems the OS write completes before the
    // microtask chain reaches this handler. If this ever causes incomplete
    // reads on network filesystems, switch to async readFile with a small
    // retry delay.
    let fullContent: string;
    try {
      fullContent = readFileSync(fullOutputPath, "utf8");
    } catch {
      // Temp file gone (race condition) — leave the result unchanged.
      return undefined;
    }

    const truncation = truncateTail(fullContent, { maxLines: KOAN_MAX_LINES, maxBytes: KOAN_MAX_BYTES });
    let outputText = truncation.content || "(no output)";

    if (truncation.truncated) {
      // Mirror the bash tool's notice format exactly. The LLM's tool description
      // says output is truncated to specific limits and references the full output
      // path — a divergent format would confuse the LLM about how to recover the rest.
      const startLine = truncation.totalLines - truncation.outputLines + 1;
      const endLine = truncation.totalLines;

      if (truncation.lastLinePartial) {
        const lines = fullContent.split("\n");
        const lastLine = lines[lines.length - 1] ?? "";
        const lastLineSize = Buffer.byteLength(lastLine, "utf8");
        outputText += `\n\n[Showing last ${formatSize(truncation.outputBytes)} of line ${endLine} (line is ${formatSize(lastLineSize)}). Full output: ${fullOutputPath}]`;
      } else if (truncation.truncatedBy === "lines") {
        outputText += `\n\n[Showing lines ${startLine}-${endLine} of ${truncation.totalLines}. Full output: ${fullOutputPath}]`;
      } else {
        outputText += `\n\n[Showing lines ${startLine}-${endLine} of ${truncation.totalLines} (${formatSize(KOAN_MAX_BYTES)} limit). Full output: ${fullOutputPath}]`;
      }
    }

    return { content: [{ type: "text" as const, text: outputText }] };
  });
}
