// Mechanical renderer: plan.json -> plan.md.
// The plan JSON is the source of truth; this file provides a deterministic
// markdown projection for human/manual review between planning and execution.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { Plan, Milestone, DiagramGraph } from "./types.js";
import { loadPlan } from "./serialize.js";

function escCell(text: string): string {
  return text.replace(/\|/g, "\\|").replace(/\n/g, " ").trim();
}

function pushList(lines: string[], title: string, values: string[]): void {
  if (values.length === 0) return;
  lines.push(title, "");
  for (const value of values) lines.push(`- ${value}`);
  lines.push("");
}

function pushScopedDiagrams(lines: string[], diagrams: DiagramGraph[], scope: string): void {
  const scoped = diagrams.filter((d) => d.scope === scope);
  for (const diagram of scoped) {
    lines.push(`### ${diagram.title}`, "");
    if (diagram.ascii_render && diagram.ascii_render.trim().length > 0) {
      lines.push("```", diagram.ascii_render, "```", "");
    } else {
      lines.push(`[Diagram pending rendering: ${diagram.id}]`, "");
    }
  }
}

function pushMilestone(lines: string[], milestone: Milestone, diagrams: DiagramGraph[]): void {
  lines.push(`### ${milestone.id}: ${milestone.name}`, "");

  pushScopedDiagrams(lines, diagrams, `milestone:${milestone.id}`);

  if (milestone.files.length > 0) {
    lines.push(`**Files**: ${milestone.files.join(", ")}`, "");
  }

  pushList(lines, "**Requirements**", milestone.requirements);
  pushList(lines, "**Acceptance Criteria**", milestone.acceptance_criteria);
  pushList(lines, "**Tests**", milestone.tests);

  if (milestone.code_intents.length > 0) {
    lines.push("#### Code Intents", "");
    for (const intent of milestone.code_intents) {
      const fn = intent.function ? `::${intent.function}` : "";
      const refs = intent.decision_refs.length > 0 ? ` (refs: ${intent.decision_refs.join(", ")})` : "";
      lines.push(`- **${intent.id}** \`${intent.file}${fn}\`: ${intent.behavior}${refs}`);
    }
    lines.push("");
  }

  if (milestone.code_changes.length > 0) {
    lines.push("#### Code Changes", "");
    for (const change of milestone.code_changes) {
      const intentRef = change.intent_ref ? ` - implements ${change.intent_ref}` : "";
      lines.push(`**${change.id}** (${change.file})${intentRef}`, "");

      if (change.diff.trim().length > 0) {
        lines.push("**Code Diff**", "", "```diff", change.diff, "```", "");
      }

      if (change.doc_diff.trim().length > 0) {
        lines.push("**Documentation Diff**", "", "```diff", change.doc_diff, "```", "");
      }

      if (change.comments.trim().length > 0) {
        lines.push(`> ${change.comments}`, "");
      }
    }
  }
}

export function renderPlanMarkdown(plan: Plan): string {
  const lines: string[] = ["# Plan", "", "## Overview", "", plan.overview.problem || "(empty)", ""];

  if (plan.overview.approach.trim().length > 0) {
    lines.push(`**Approach**: ${plan.overview.approach}`, "");
  }

  pushScopedDiagrams(lines, plan.diagram_graphs, "overview");

  if (plan.planning_context.decision_log.length > 0) {
    lines.push("## Planning Context", "", "### Decision Log", "", "| ID | Decision | Reasoning Chain |", "|---|---|---|");
    for (const d of plan.planning_context.decision_log) {
      lines.push(`| ${d.id} | ${escCell(d.decision)} | ${escCell(d.reasoning_chain)} |`);
    }
    lines.push("");
  }

  if (plan.planning_context.rejected_alternatives.length > 0) {
    lines.push("### Rejected Alternatives", "", "| Alternative | Why Rejected |", "|---|---|");
    for (const r of plan.planning_context.rejected_alternatives) {
      lines.push(`| ${escCell(r.alternative)} | ${escCell(r.rejection_reason)} (ref: ${r.decision_ref}) |`);
    }
    lines.push("");
  }

  pushList(lines, "### Constraints", plan.planning_context.constraints);

  if (plan.planning_context.known_risks.length > 0) {
    lines.push("### Known Risks", "");
    for (const risk of plan.planning_context.known_risks) {
      lines.push(`- **${risk.risk}**: ${risk.mitigation}`);
    }
    lines.push("");
  }

  const ik = plan.invisible_knowledge;
  if (ik.system.trim().length > 0 || ik.invariants.length > 0 || ik.tradeoffs.length > 0) {
    lines.push("## Invisible Knowledge", "");
    if (ik.system.trim().length > 0) {
      lines.push("### System", "", ik.system, "");
    }
    pushList(lines, "### Invariants", ik.invariants);
    pushList(lines, "### Tradeoffs", ik.tradeoffs);
    pushScopedDiagrams(lines, plan.diagram_graphs, "invisible_knowledge");
  }

  lines.push("## Milestones", "");
  for (const milestone of plan.milestones) {
    pushMilestone(lines, milestone, plan.diagram_graphs);
  }

  if (plan.readme_entries.length > 0) {
    lines.push("## README Entries", "");
    for (const entry of plan.readme_entries) {
      lines.push(`### ${entry.path}`, "", entry.content, "");
    }
  }

  if (plan.waves.length > 0) {
    lines.push("## Execution Waves", "");
    for (const wave of plan.waves) {
      lines.push(`- ${wave.id}: ${wave.milestones.join(", ")}`);
    }
    lines.push("");
  }

  return `${lines.join("\n").trimEnd()}\n`;
}

export async function renderPlanMarkdownToFile(planDir: string): Promise<string> {
  const plan = await loadPlan(planDir);
  const markdown = renderPlanMarkdown(plan);
  const outputPath = path.join(planDir, "plan.md");
  const tmpPath = path.join(planDir, ".plan.md.tmp");
  await fs.writeFile(tmpPath, markdown, "utf8");
  await fs.rename(tmpPath, outputPath);
  return outputPath;
}
