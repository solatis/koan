import { Type } from "@sinclair/typebox";

const NonEmptyStringArray = Type.Array(Type.String({ minLength: 1 }), { minItems: 1 });

export const ContextStoreSchema = Type.Object({
  task_spec: NonEmptyStringArray,
  constraints: NonEmptyStringArray,
  entry_points: NonEmptyStringArray,
  rejected_alternatives: NonEmptyStringArray,
  current_understanding: NonEmptyStringArray,
  assumptions: NonEmptyStringArray,
  invisible_knowledge: NonEmptyStringArray,
  reference_docs: NonEmptyStringArray,
}, {
  description: [
    "Structured planning context. All fields are string arrays.",
    "task_spec: subject, scope, out-of-scope items.",
    "constraints: 'MUST/SHOULD/MUST-NOT: rule (source)' or 'none confirmed'.",
    "entry_points: 'file:symbol - why relevant' or 'greenfield'.",
    "rejected_alternatives: 'approach - why dismissed' or 'none discussed'.",
    "current_understanding: how the system works, relevant behavior.",
    "assumptions: 'claim (H/M/L confidence)' or 'none'.",
    "invisible_knowledge: design rationale, invariants, accepted tradeoffs.",
    "reference_docs: 'path - what it covers' or 'none'.",
  ].join(" "),
});

export interface ContextToolResult {
  ok: boolean;
  message: string;
  errors?: string[];
}

export type ContextToolHandler = (payload: unknown, ctx: unknown) => Promise<ContextToolResult>;
