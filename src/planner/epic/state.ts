// Epic and story state I/O — read/write JSON state files for driver routing.
// All JSON writes use atomic tmp+rename to prevent partial reads during concurrent access.
// Paths follow: ~/.koan/state/epics/{epic-id}/...
//
// The driver reads and writes .json files only — never .md files. This is the
// core invariant (AGENTS.md): LLMs read/write markdown; the driver reads/writes
// JSON; tool code bridges both. Putting writeStatusMarkdown here would violate the
// invariant boundary and make the module responsible for two communication channels.
// status.md writes belong exclusively in tools/orchestrator.ts.
//
// discoverStoryIds scans the filesystem instead of reading a driver-maintained
// list because the decomposer LLM writes story.md files using the Write tool —
// it has no reason to know the JSON state format, and requiring it to update
// epic-state.json would force an LLM to write JSON, violating the core invariant
// (§10.2). The driver discovers what the LLM created by scanning stories/*/story.md,
// then populates the JSON story list itself.

import { promises as fs } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

import {
  createInitialEpicState,
  createInitialStoryState,
  type EpicInfo,
  type EpicState,
  type StoryState,
} from "./types.js";

export const KOAN_HOME = path.join(os.homedir(), ".koan");
export const EPICS_HOME = path.join(KOAN_HOME, "state", "epics");

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

function epicStatePath(epicDir: string): string {
  return path.join(epicDir, "epic-state.json");
}

function storyStatePath(epicDir: string, storyId: string): string {
  return path.join(epicDir, "stories", storyId, "state.json");
}

// ---------------------------------------------------------------------------
// Atomic JSON write
// ---------------------------------------------------------------------------

// Writes to a .tmp file first, then renames — preventing partial reads.
async function atomicWriteJson(filePath: string, value: unknown): Promise<void> {
  const tmpPath = `${filePath}.tmp`;
  await fs.writeFile(tmpPath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await fs.rename(tmpPath, filePath);
}

// ---------------------------------------------------------------------------
// ID generation
// ---------------------------------------------------------------------------

function slugify(input: string): string {
  const base = input
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48);
  return base.length > 0 ? base : "epic";
}

export function generateEpicId(description: string, now: Date): string {
  const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
  const slug = slugify(description);
  return `${timestamp}-${slug}`;
}

async function ensureEpicDirectoryUnique(baseId: string): Promise<{ id: string; directory: string }> {
  let suffix = 0;
  while (true) {
    const candidateId = suffix === 0 ? baseId : `${baseId}-${suffix}`;
    const directory = path.join(EPICS_HOME, candidateId);
    try {
      await fs.mkdir(directory, { recursive: false });
      return { id: candidateId, directory };
    } catch (error) {
      const err = error as NodeJS.ErrnoException;
      if (err.code === "EEXIST") {
        suffix += 1;
        continue;
      }
      throw error;
    }
  }
}

// ---------------------------------------------------------------------------
// Epic directory creation
// ---------------------------------------------------------------------------

// Creates the epic directory with standard subdirectories.
// Creates only 'stories/' and 'subagents/' — no 'scouts/' directory.
// Scout output lives in per-scout subagent directories under subagents/.
export async function createEpicDirectory(description: string, _cwd: string, now = new Date()): Promise<EpicInfo> {
  await fs.mkdir(EPICS_HOME, { recursive: true });

  const baseId = generateEpicId(description, now);
  const { id, directory } = await ensureEpicDirectoryUnique(baseId);

  await Promise.all([
    fs.mkdir(path.join(directory, "stories"), { recursive: true }),
    fs.mkdir(path.join(directory, "subagents"), { recursive: true }),
  ]);

  const epicState = createInitialEpicState(id);
  await atomicWriteJson(epicStatePath(directory), epicState);

  return { id, directory, createdAt: epicState.createdAt };
}

// ---------------------------------------------------------------------------
// Epic state I/O
// ---------------------------------------------------------------------------

export async function loadEpicState(epicDir: string): Promise<EpicState> {
  const raw = await fs.readFile(epicStatePath(epicDir), "utf8");
  return JSON.parse(raw) as EpicState;
}

export async function saveEpicState(epicDir: string, state: EpicState): Promise<void> {
  await atomicWriteJson(epicStatePath(epicDir), state);
}

// ---------------------------------------------------------------------------
// Story state I/O
// ---------------------------------------------------------------------------

export async function loadStoryState(epicDir: string, storyId: string): Promise<StoryState> {
  const raw = await fs.readFile(storyStatePath(epicDir, storyId), "utf8");
  return JSON.parse(raw) as StoryState;
}

export async function saveStoryState(epicDir: string, storyId: string, state: StoryState): Promise<void> {
  await atomicWriteJson(storyStatePath(epicDir, storyId), state);
}

export async function loadAllStoryStates(epicDir: string): Promise<StoryState[]> {
  const epicState = await loadEpicState(epicDir);
  return Promise.all(epicState.stories.map((id) => loadStoryState(epicDir, id)));
}

// ---------------------------------------------------------------------------
// Directory provisioning
// ---------------------------------------------------------------------------

// Ensures the story directory and plan subdirectory exist, and that state.json
// is initialized if not already present.
export async function ensureStoryDirectory(epicDir: string, storyId: string): Promise<string> {
  const storyDir = path.join(epicDir, "stories", storyId);
  await fs.mkdir(path.join(storyDir, "plan"), { recursive: true });

  const statePath = storyStatePath(epicDir, storyId);
  try {
    await fs.access(statePath);
  } catch {
    const initialState = createInitialStoryState(storyId);
    await atomicWriteJson(statePath, initialState);
  }

  return storyDir;
}

// Ensures a uniquely labeled subagent directory exists under {epicDir}/subagents/.
// The label should be descriptive (e.g., "intake-20260313T105232" or "scout-task1-1741830752000").
export async function ensureSubagentDirectory(epicDir: string, label: string): Promise<string> {
  const subagentDir = path.join(epicDir, "subagents", label);
  await fs.mkdir(subagentDir, { recursive: true });
  return subagentDir;
}

// ---------------------------------------------------------------------------
// Story discovery
// ---------------------------------------------------------------------------

// Scans {epicDir}/stories/ for subdirectories and returns their names sorted.
// This is the authoritative discovery mechanism after decomposition.
// The driver calls this after the decomposer LLM creates stories/*/story.md files.
// Never reads epic-state.json.stories — that list is populated by the driver AFTER
// discovery, not by the LLM.
export async function discoverStoryIds(epicDir: string): Promise<string[]> {
  const storiesDir = path.join(epicDir, "stories");
  try {
    const entries = await fs.readdir(storiesDir, { withFileTypes: true });
    return entries
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .sort();
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
}
