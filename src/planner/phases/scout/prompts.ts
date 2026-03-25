// Scout phase prompts — 3-step investigation workflow:
//   Step 1: Investigate (find entry points AND read/trace code — combined for speed)
//   Step 2: Verify      (spot-check critical claims with targeted tool calls)
//   Step 3: Report      (write findings.md with verified facts)
//
// The system prompt establishes the investigator identity but contains no task
// details — a scout doesn't know its question until koan_complete_step returns
// step 1 guidance. This is intentional: including the question in the system
// prompt or spawn prompt would front-load instructions before the tool-call
// pattern is established, causing weaker models to answer inline and exit.
//
// Speed design: scouts are optimized for breadth and speed. They use cheap
// models for narrow codebase investigation. The system prompt explicitly
// instructs batching tool calls (reading multiple files per turn, running
// multiple grep/find commands simultaneously). The original 4-step design
// (Orient → Investigate → Verify → Report) was reduced to 3 steps by merging
// Orient into Investigate — separating "find files" from "read files" was an
// artificial split that wasted a full round trip.
//
// The verification step (2) uses targeted spot-checks (grep for a function
// name, read a specific line range) rather than re-reading every cited file.
// Full re-reads are an intrinsic self-correction anti-pattern that doubles
// I/O with marginal accuracy gain for narrow investigation tasks.

import type { StepGuidance } from "../../lib/step.js";

export const SCOUT_STEP_NAMES: Record<number, string> = {
  1: "Investigate",
  2: "Verify",
  3: "Report",
};

export function scoutSystemPrompt(): string {
  return `You are a codebase investigator. You are assigned one narrow, specific question about a codebase. Your job is to methodically explore the relevant code, verify your findings, and write a grounded report.

## Your role

You find facts. You do NOT interpret, recommend, or opine.

## Speed principles

You are optimized for speed and breadth. Cast a wide net quickly.

- Call MULTIPLE tools simultaneously. Read 3–5 files in one turn, not one at a time.
- Combine search strategies: run grep, find, and read calls together in a single turn.
- Use bash for broad sweeps: \`grep -rn\` across directories, \`find\` with multiple patterns.
- Do NOT be overly cautious or sequential. Explore aggressively, discard irrelevant results.
- Maximize work per turn. Each tool-call turn should accomplish as much as possible.

## Strict rules

- MUST answer only the assigned question. Do not expand scope.
- MUST write only factual observations: what the code does, what files exist, what patterns are present.
- MUST NOT produce recommendations or suggestions of any kind.
- MUST NOT express opinions about code quality.
- MUST NOT produce implementation plans or design ideas.
- MUST include file paths and line numbers when referencing code.
- MUST include relevant code excerpts (verbatim) to support each finding.
- SHOULD be thorough within the question scope: follow references, check related files.
- SHOULD note explicitly when something is NOT present (e.g., "No tests found for this module").

## Output file

You write a single markdown file with your findings. The file location and format are provided in your final step.

## Tools available

- All read tools (read, bash, grep, glob, find, ls) — for reading the codebase.
- \`write\` / \`edit\` — for writing the output file only.
- \`koan_complete_step\` — to advance to the next workflow step.`;
}

export function scoutStepGuidance(
  step: number,
  question: string,
  outputFile: string,
  investigatorRole: string,
): StepGuidance {
  switch (step) {
    case 1:
      return {
        title: SCOUT_STEP_NAMES[1],
        instructions: [
          "Find and read the relevant code to answer the question.",
          "",
          "## Your Assignment",
          "",
          ...(question ? [`**Question:** ${question}`] : []),
          ...(investigatorRole ? [`**Your investigator role:** ${investigatorRole}`] : []),
          "",
          "## Actions",
          "",
          "1. Parse the question: what exactly are you being asked to find?",
          "2. Cast a wide net: run grep, find, or glob to locate candidate files. Run multiple searches simultaneously.",
          "3. Read the most promising files immediately — do not wait for a separate step. Read 3–5 files at once.",
          "4. Follow imports, cross-references, and call chains to related files. Read follow-up files in batches.",
          "5. For each relevant finding, note the file path, line numbers, and a verbatim code excerpt.",
          "6. Be thorough but fast: if a file is irrelevant, move on immediately.",
        ],
      };

    case 2:
      return {
        title: SCOUT_STEP_NAMES[2],
        instructions: [
          "Spot-check your key findings before reporting.",
          "",
          "## Actions",
          "",
          "1. Pick the 2–3 most critical claims from your investigation.",
          "2. Verify each with a targeted tool call: grep for a function name, read a specific line range, ls to confirm a path exists.",
          "3. If you find a discrepancy, correct it. If a file does not exist, drop the reference.",
          "4. Organize your verified findings into a clear answer to the original question.",
          "5. Identify any gaps — things you could not determine or areas you could not access.",
          "6. Note anything that is explicitly NOT present (missing tests, missing config, etc.).",
        ],
      };

    case 3:
      return {
        title: SCOUT_STEP_NAMES[3],
        instructions: [
          "Write your findings to the output file.",
          "",
          `**Output file:** ${outputFile}`,
          "",
          "Write a markdown file with these exact sections:",
          "",
          "## Question",
          "Restate the assigned question verbatim.",
          "",
          "## Findings",
          "Factual observations that answer the question. Use sub-sections if the answer has multiple parts.",
          "Cite file paths and line numbers for every claim. Include code snippets where relevant.",
          "Every finding must be backed by a file you actually read — no inferred claims.",
          "",
          "## Files Examined",
          "List every file you read during this investigation.",
          "",
          "## Gaps",
          "Note anything you could not determine. If no gaps, write: (none)",
        ],
      };

    default:
      return {
        title: `Step ${step}`,
        instructions: [`Execute step ${step}.`],
      };
  }
}
