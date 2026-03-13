// Epic and story state types — JSON structures for driver consumption.
// Persisted as .json files under ~/.koan/state/epics/{epic-id}/.
// Per AGENTS.md invariant: LLMs write markdown only; driver reads JSON only.
// LLMs never read these files directly — they read the corresponding .md files.

import type { EpicPhase, StoryStatus } from "../types.js";

// Persisted at {epic-dir}/epic-state.json
export interface EpicState {
  epicId: string;
  createdAt: string;
  phase: EpicPhase;
  stories: string[];  // Story IDs in declaration order
}

// Persisted at {epic-dir}/stories/{story-id}/state.json
// Note: no `escalation` field — escalation is handled via koan_ask_question,
// not a separate status or state field.
export interface StoryState {
  storyId: string;
  status: StoryStatus;
  updatedAt: string;
  retryCount: number;
  maxRetries: number;
  failureSummary?: string;  // Set by koan_retry_story; used as retry context for executor
  skipReason?: string;      // Set by koan_skip_story or driver on budget exhaustion
}

// Metadata about an epic directory — returned by createEpicDirectory.
export interface EpicInfo {
  id: string;
  directory: string;
  createdAt: string;
}

// Default retry budget per story.
export const DEFAULT_MAX_RETRIES = 2;

export function createInitialStoryState(storyId: string, maxRetries = DEFAULT_MAX_RETRIES): StoryState {
  return {
    storyId,
    status: "pending",
    updatedAt: new Date().toISOString(),
    retryCount: 0,
    maxRetries,
  };
}

export function createInitialEpicState(epicId: string, stories: string[] = []): EpicState {
  return {
    epicId,
    createdAt: new Date().toISOString(),
    phase: "intake",
    stories,
  };
}
