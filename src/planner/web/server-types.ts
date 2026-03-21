// Shared types for the koan web UI: WebServerHandle interface, SSE event
// types, result types, and ask model types relocated from ask-logic.ts.

import type { LogLine } from "../lib/audit.js";
import type { EpicPhase, StoryStatus } from "../types.js";

export type { LogLine, EpicPhase, StoryStatus };

// ---------------------------------------------------------------------------
// Ask model types (relocated from ui/ask/ask-logic.ts)
// ---------------------------------------------------------------------------

export const OTHER_OPTION = "Other (type your own)";
const RECOMMENDED_OPTION_TAG = " (Recommended)";

export interface AskOption {
  label: string;
}

export interface AskQuestion {
  id: string;
  question: string;
  context?: string;
  options: AskOption[];
  multi?: boolean;
  recommended?: number;
}

export interface AskSelection {
  selectedOptions: string[];
  customInput?: string;
}

export function appendRecommendedTagToOptionLabels(
  optionLabels: string[],
  recommendedOptionIndex?: number,
): string[] {
  if (
    recommendedOptionIndex == null ||
    recommendedOptionIndex < 0 ||
    recommendedOptionIndex >= optionLabels.length
  ) {
    return optionLabels;
  }
  return optionLabels.map((label, idx) => {
    if (idx !== recommendedOptionIndex) return label;
    if (label.endsWith(RECOMMENDED_OPTION_TAG)) return label;
    return `${label}${RECOMMENDED_OPTION_TAG}`;
  });
}

function removeRecommendedTag(label: string): string {
  if (!label.endsWith(RECOMMENDED_OPTION_TAG)) return label;
  return label.slice(0, -RECOMMENDED_OPTION_TAG.length);
}

export function buildSingleSelectionResult(selectedOptionLabel: string, note?: string): AskSelection {
  const normalized = removeRecommendedTag(selectedOptionLabel);
  const trimmedNote = note?.trim();
  if (normalized === OTHER_OPTION) {
    return trimmedNote ? { selectedOptions: [], customInput: trimmedNote } : { selectedOptions: [] };
  }
  if (trimmedNote) {
    return { selectedOptions: [`${normalized} - ${trimmedNote}`] };
  }
  return { selectedOptions: [normalized] };
}

export function buildMultiSelectionResult(
  optionLabels: string[],
  selectedOptionIndexes: number[],
  optionNotes: string[],
  otherOptionIndex: number,
): AskSelection {
  const selected = new Set(selectedOptionIndexes);
  const selectedOptions: string[] = [];
  let customInput: string | undefined;

  for (let i = 0; i < optionLabels.length; i++) {
    if (!selected.has(i)) continue;
    const label = removeRecommendedTag(optionLabels[i]);
    const note = optionNotes[i]?.trim();
    if (i === otherOptionIndex) {
      if (note) customInput = note;
      continue;
    }
    selectedOptions.push(note ? `${label} - ${note}` : label);
  }

  return customInput ? { selectedOptions, customInput } : { selectedOptions };
}

// ---------------------------------------------------------------------------
// Result types
// ---------------------------------------------------------------------------

export interface ReviewStory {
  storyId: string;
  title: string;
  content: string;
}

export interface ReviewResult {
  approved: string[];
  skipped: string[];
}

export type AnswerElement = AskSelection & { questionId: string };

export interface AnswerResult {
  cancelled: boolean;
  answer: AnswerElement;
}

// ---------------------------------------------------------------------------
// SSE event payload types (server → browser)
// ---------------------------------------------------------------------------

export interface AvailableModel {
  id: string;
  name: string;
  provider: string;
}

export interface InitEvent {
  availableModels: AvailableModel[];
}

export interface PhaseEvent {
  phase: EpicPhase;
}

export interface StoriesEvent {
  stories: Array<{ storyId: string; status: StoryStatus }>;
}

export interface SubagentEvent {
  role: string;
  storyId?: string;
  step: number;
  totalSteps: number;
  stepName: string;
  startedAt: number;
}

export interface SubagentIdleEvent {}

export interface LogsEvent {
  lines: LogLine[];
}

export interface NotificationEvent {
  message: string;
  level: "info" | "warning" | "error";
}

export interface AskEvent {
  requestId: string;
  question: AskQuestion;
}

export interface ReviewEvent {
  requestId: string;
  stories: ReviewStory[];
}

export interface AskCancelledEvent {
  requestId: string;
}

export interface PipelineEndEvent {
  success: boolean;
  summary: string;
}

// Confidence level type for the intake confidence loop.
export type IntakeConfidenceLevel = "exploring" | "low" | "medium" | "high" | "certain" | null;

export interface IntakeProgressEvent {
  subPhase: string | null;
  intakeDone: boolean;
  // The most recent confidence level declared by koan_set_confidence.
  // Null before the first Reflect step completes.
  confidence: IntakeConfidenceLevel;
  // The current loop iteration (1-based). Zero before the loop begins.
  iteration: number;
}

export interface ScoutState {
  id: string;
  role: string;
  status: "running" | "completed" | "failed" | null;
  lastAction: string | null;
  eventCount: number;
  model: string | null;
  completionSummary: string | null;
  tokensSent: number;
  tokensReceived: number;
}

export interface ScoutsEvent {
  scouts: ScoutState[];
}

export interface AgentEntry {
  id: string;
  name: string;
  role: string;
  model: string | null;
  parent: string | null;
  status: "running" | "completed" | "failed" | null;
  tokensSent: number;
  tokensReceived: number;
  recentActions: Array<{ tool: string; summary: string; inFlight: boolean; ts?: string }>;
  subPhase: string | null;
}

export interface AgentsEvent {
  agents: AgentEntry[];
}

export interface ModelConfigEvent {
  requestId: string;
  tiers: Record<string, string> | null;
  availableModels: AvailableModel[];
}

// ---------------------------------------------------------------------------
// WebServerHandle interface
// ---------------------------------------------------------------------------

export interface WebServerHandle {
  readonly url: string;
  readonly port: number;

  // ---------------------------------------------------------------------------
  // Concern 1 -- Push / SSE (fire-and-forget, no response expected)
  //   pushPhase, pushStories, pushLogs, pushNotification
  //
  // Concern 2 -- Agent lifecycle / observation
  //   registerAgent, startAgent, completeAgent, trackSubagent, clearSubagent
  //
  // Concern 3 -- Blocking human input (returns a Promise that resolves when the
  //             user responds; must be called with an AbortSignal for cancellation)
  //   requestReview, requestAnswer, requestModelConfig
  //
  // Note: this interface conflates three unrelated responsibilities. A future
  // split into three narrower interfaces (PushHandle, AgentHandle, InputHandle)
  // would allow callers to depend only on what they use. The split is deferred
  // because it requires updating all call sites in driver.ts and koan.ts.
  // ---------------------------------------------------------------------------

  // Concern 1 -- Push / SSE
  pushPhase(phase: EpicPhase): void;
  pushStories(stories: Array<{ storyId: string; status: StoryStatus }>): void;
  pushLogs(lines: LogLine[], currentToolCallId?: string | null): void;
  pushNotification(message: string, level: "info" | "warning" | "error"): void;

  // Concern 2 -- Agent lifecycle / observation
  registerAgent(info: {
    id: string;
    name: string;
    dir: string;
    role: string;
    model: string | null;
    parent: string | null;
    status?: "running" | null;
  }): void;
  startAgent(id: string): void;
  completeAgent(id: string): void;
  trackSubagent(dir: string, role: string, storyId?: string): void;
  clearSubagent(): void;

  // Concern 3 -- Blocking human input
  requestReview(stories: ReviewStory[], signal?: AbortSignal): Promise<ReviewResult>;
  requestAnswer(question: AskQuestion, signal: AbortSignal): Promise<AnswerResult>;
  requestModelConfig(): Promise<void>;

  close(): void;
}
