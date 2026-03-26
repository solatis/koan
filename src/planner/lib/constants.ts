// Shared constants for use across both the extension entry-point and the
// subagent spawn infrastructure. Keeping the flag name here prevents string
// drift between registerFlag() and the child-process args construction.

export const KOAN_DEBUG_FLAG = "koan-debug" as const;
