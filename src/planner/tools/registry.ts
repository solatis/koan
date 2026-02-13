// Default-deny permissions. Read tools bypass this map. Write tools
// (edit/write) always blocked during planning. The map defines OUTER
// boundaries; phase handlers narrow further.

const READ_TOOLS = new Set(["read", "bash", "grep", "glob", "find", "ls"]);
const WRITE_TOOLS = new Set(["edit", "write"]);

const PLAN_GETTER_TOOLS_LIST = [
  "koan_get_plan",
  "koan_get_milestone",
  "koan_get_decision",
  "koan_get_intent",
  "koan_get_change",
];

const PLAN_SETTER_TOOLS_LIST = [
  "koan_set_overview",
  "koan_set_constraints",
  "koan_set_invisible_knowledge",
];

const PLAN_DECISION_TOOLS_LIST = ["koan_add_decision", "koan_set_decision"];

const PLAN_REJECTED_ALT_TOOLS_LIST = [
  "koan_add_rejected_alternative",
  "koan_set_rejected_alternative",
];

const PLAN_RISK_TOOLS_LIST = ["koan_add_risk", "koan_set_risk"];

const PLAN_MILESTONE_TOOLS_LIST = [
  "koan_add_milestone",
  "koan_set_milestone_name",
  "koan_set_milestone_files",
  "koan_set_milestone_flags",
  "koan_set_milestone_requirements",
  "koan_set_milestone_acceptance_criteria",
  "koan_set_milestone_tests",
];

const PLAN_INTENT_TOOLS_LIST = ["koan_add_intent", "koan_set_intent"];

const PLAN_CHANGE_TOOLS_LIST = [
  "koan_add_change",
  "koan_set_change_diff",
  "koan_set_change_doc_diff",
  "koan_set_change_comments",
  "koan_set_change_file",
  "koan_set_change_intent_ref",
];

const PLAN_WAVE_TOOLS_LIST = ["koan_add_wave", "koan_set_wave_milestones"];

const PLAN_DIAGRAM_TOOLS_LIST = [
  "koan_add_diagram",
  "koan_set_diagram",
  "koan_add_diagram_node",
  "koan_add_diagram_edge",
];

const PLAN_README_TOOLS_LIST = ["koan_set_readme_entry"];

const QR_TOOLS_LIST = [
  "koan_qr_add_item",
  "koan_qr_set_item",
  "koan_qr_assign_group",
  "koan_qr_get_item",
  "koan_qr_list_items",
  "koan_qr_summary",
];

const ALL_PLAN_ENTITY_TOOLS = [
  ...PLAN_DECISION_TOOLS_LIST,
  ...PLAN_REJECTED_ALT_TOOLS_LIST,
  ...PLAN_RISK_TOOLS_LIST,
  ...PLAN_MILESTONE_TOOLS_LIST,
  ...PLAN_INTENT_TOOLS_LIST,
  ...PLAN_WAVE_TOOLS_LIST,
  ...PLAN_DIAGRAM_TOOLS_LIST,
  ...PLAN_README_TOOLS_LIST,
];

const PLAN_DESIGN_ENTITY_TOOLS = ALL_PLAN_ENTITY_TOOLS.filter(
  (t) => !PLAN_CHANGE_TOOLS_LIST.includes(t),
);

export const PLAN_GETTER_TOOLS: ReadonlySet<string> = new Set(
  PLAN_GETTER_TOOLS_LIST,
);

export const PLAN_MUTATION_TOOLS: ReadonlySet<string> = new Set([
  ...PLAN_SETTER_TOOLS_LIST,
  ...ALL_PLAN_ENTITY_TOOLS,
  ...PLAN_CHANGE_TOOLS_LIST,
]);

// Missing phase keys are blocked (default-deny extends to unknown phases).
// Prevents security boundary breach when a new phase is added without
// updating the permissions map.
export const PHASE_PERMISSIONS: ReadonlyMap<string, ReadonlySet<string>> =
  new Map([
    ["context-capture", new Set(["koan_store_context", "koan_complete_step"])],
    [
      "plan-design",
      new Set([
        "koan_complete_step",
        ...PLAN_GETTER_TOOLS_LIST,
        ...PLAN_SETTER_TOOLS_LIST,
        ...PLAN_DESIGN_ENTITY_TOOLS,
      ]),
    ],
    [
      "plan-code",
      new Set([
        "koan_complete_step",
        ...PLAN_GETTER_TOOLS_LIST,
        ...PLAN_CHANGE_TOOLS_LIST,
        "koan_set_intent",
      ]),
    ],
    [
      "plan-docs",
      new Set([
        "koan_complete_step",
        ...PLAN_GETTER_TOOLS_LIST,
        "koan_set_change_doc_diff",
        "koan_set_change_comments",
        "koan_set_readme_entry",
        "koan_set_diagram",
      ]),
    ],
    [
      "qr-plan-design",
      new Set(["koan_complete_step", ...PLAN_GETTER_TOOLS_LIST, ...QR_TOOLS_LIST]),
    ],
    [
      "qr-plan-code",
      new Set([
        "koan_complete_step",
        "koan_get_plan",
        "koan_get_milestone",
        "koan_get_intent",
        "koan_get_change",
        ...QR_TOOLS_LIST,
      ]),
    ],
    [
      "qr-plan-docs",
      new Set([
        "koan_complete_step",
        "koan_get_plan",
        "koan_get_milestone",
        "koan_get_change",
        ...QR_TOOLS_LIST,
      ]),
    ],
  ]);

export function checkPermission(
  phaseKey: string,
  toolName: string,
): { allowed: boolean; reason?: string } {
  if (READ_TOOLS.has(toolName)) {
    return { allowed: true };
  }

  if (WRITE_TOOLS.has(toolName)) {
    return {
      allowed: false,
      reason: "Edit/write tools blocked during planning.",
    };
  }

  if (!PHASE_PERMISSIONS.has(phaseKey)) {
    return {
      allowed: false,
      reason: `Unknown phase: ${phaseKey}`,
    };
  }

  const allowed = PHASE_PERMISSIONS.get(phaseKey)!;
  if (!allowed.has(toolName)) {
    return {
      allowed: false,
      reason: `${toolName} is not available in phase ${phaseKey}`,
    };
  }

  return { allowed: true };
}
