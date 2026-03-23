// Epic artifact I/O -- list, read, and write markdown artifacts within an epic directory.
// All writes use atomic tmp+rename to prevent partial reads during concurrent access.
// Artifacts are .md files in the epic root and under stories/ (excluding subagents/).

import { promises as fs } from "node:fs";
import * as path from "node:path";

// -- Types --

export interface ArtifactEntry {
  path: string;
  size: number;
  modifiedAt: string;
}

// -- Scope --

export function isArtifactInScope(relativePath: string): boolean {
  const norm = path.normalize(relativePath);
  if (!norm.endsWith(".md")) return false;
  const segments = norm.split(path.sep);
  if (segments.includes("subagents")) return false;
  // Must be root-level or under stories/
  return segments.length === 1 || segments[0] === "stories";
}

// -- List --

export async function listArtifacts(epicDir: string): Promise<ArtifactEntry[]> {
  const results: ArtifactEntry[] = [];

  // Pass 1: epic root .md files
  const rootEntries = await fs.readdir(epicDir, { withFileTypes: true });
  for (const e of rootEntries) {
    if (!e.isFile() || !isArtifactInScope(e.name)) continue;
    const abs = path.join(epicDir, e.name);
    const stat = await fs.stat(abs);
    results.push({
      path: e.name,
      size: stat.size,
      modifiedAt: stat.mtime.toISOString(),
    });
  }

  // Pass 2: stories/ recursive scan
  const storiesDir = path.join(epicDir, "stories");
  try {
    const entries = await fs.readdir(storiesDir, { withFileTypes: true, recursive: true });
    for (const e of entries) {
      if (!e.isFile()) continue;
      const parent = (e as any).parentPath ?? (e as any).path ?? storiesDir;
      const abs = path.join(parent, e.name);
      const rel = path.relative(epicDir, abs);
      if (!isArtifactInScope(rel)) continue;
      const stat = await fs.stat(abs);
      results.push({
        path: rel,
        size: stat.size,
        modifiedAt: stat.mtime.toISOString(),
      });
    }
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
  }

  results.sort((a, b) => a.path.localeCompare(b.path));
  return results;
}

// -- Read --

export async function readArtifact(epicDir: string, relativePath: string): Promise<string> {
  const abs = path.resolve(epicDir, relativePath);
  const root = path.resolve(epicDir);
  const rel = path.relative(root, abs);
  if (rel !== "" && (rel.startsWith("..") || path.isAbsolute(rel))) {
    throw new Error(`Path "${relativePath}" escapes the epic directory.`);
  }
  if (!isArtifactInScope(rel)) {
    throw new Error(`Path "${relativePath}" is outside artifact scope.`);
  }
  return fs.readFile(abs, "utf8");
}

// -- Display helpers --

export function formatArtifactSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

export function artifactDisplayPath(relativePath: string): string {
  const norm = path.posix.normalize(relativePath.replace(/\\/g, "/"));
  const segments = norm.split("/");
  if (segments.length === 1) return "epic root / " + segments[0];
  return segments.join(" / ");
}

// -- Write --

export async function writeArtifact(epicDir: string, relativePath: string, content: string): Promise<void> {
  const abs = path.resolve(epicDir, relativePath);
  const tmp = `${abs}.tmp`;
  await fs.writeFile(tmp, content, "utf8");
  await fs.rename(tmp, abs);
}
