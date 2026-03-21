// Phase dispatch: routes a SubagentTask to the appropriate phase class.
//
// Called from koan.ts after readTaskFile() resolves the task manifest.
// There is no flag-parsing here — all task parameters come from task.json.

import * as path from "node:path";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { createLogger, type Logger } from "../../utils/logger.js";
import type { RuntimeContext } from "../lib/runtime-context.js";
import type { EventLog } from "../lib/audit.js";
import type { SubagentTask } from "../lib/task.js";
import { IntakePhase, type ConfidenceRef } from "./intake/phase.js";
import { ScoutPhase } from "./scout/phase.js";
import { DecomposerPhase } from "./decomposer/phase.js";
import { BriefWriterPhase } from "./brief-writer/phase.js";
import { OrchestratorPhase } from "./orchestrator/phase.js";
import { PlannerPhase } from "./planner/phase.js";
import { ExecutorPhase } from "./executor/phase.js";

export async function dispatchPhase(
  pi: ExtensionAPI,
  task: SubagentTask,
  ctx: RuntimeContext,
  log?: Logger,
  eventLog?: EventLog,
  onConfidenceRef?: (ref: ConfidenceRef) => void,
): Promise<void> {
  const logger = log ?? createLogger("Dispatch");

  switch (task.role) {
    case "intake": {
      const phase = new IntakePhase(pi, ctx, logger, eventLog);
      onConfidenceRef?.(phase.confidenceRef);
      await phase.begin();
      break;
    }

    case "scout": {
      // outputFile is relative to subagentDir in the task manifest.
      // ScoutPhase receives the resolved absolute path.
      const phase = new ScoutPhase(pi, {
        question: task.question,
        outputFile: path.join(ctx.subagentDir!, task.outputFile),
        investigatorRole: task.investigatorRole,
      }, ctx, logger, eventLog);
      await phase.begin();
      break;
    }

    case "decomposer": {
      const phase = new DecomposerPhase(pi, ctx, logger, eventLog);
      await phase.begin();
      break;
    }

    case "brief-writer": {
      const phase = new BriefWriterPhase(pi, ctx, logger, eventLog);
      await phase.begin();
      break;
    }

    case "orchestrator": {
      const phase = new OrchestratorPhase(
        pi,
        { epicDir: task.epicDir, stepSequence: task.stepSequence, storyId: task.storyId },
        ctx, logger, eventLog,
      );
      await phase.begin();
      break;
    }

    case "planner": {
      const phase = new PlannerPhase(
        pi,
        { epicDir: task.epicDir, storyId: task.storyId },
        ctx, logger, eventLog,
      );
      await phase.begin();
      break;
    }

    case "executor": {
      const phase = new ExecutorPhase(
        pi,
        { epicDir: task.epicDir, storyId: task.storyId, retryContext: task.retryContext },
        ctx, logger, eventLog,
      );
      await phase.begin();
      break;
    }

    default: {
      // TypeScript narrows task to `never` here — this branch is unreachable
      // when all roles are covered above.
      const exhaustive: never = task;
      logger("Unrecognized role in task manifest", { role: (exhaustive as { role: string }).role });
      break;
    }
  }
}
