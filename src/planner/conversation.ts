// Export the parent session conversation to a JSONL file in the epic directory.
//
// The output is raw pi SessionManager entries — NOT a plain-text transcript.
// Each line is a JSON-serialized session entry (header first, then branch entries).
//
// Agents reading this file should look for entries with type "message" and
// role "user" or "assistant" for conversation content. Entries with type
// "compaction" contain synthesized summaries of earlier context. Internal
// session management entries should be ignored.
//
// The file is write-once from the driver's perspective — planning phases read it.

import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { ExtensionContext } from "@mariozechner/pi-coding-agent";

// Export the current conversation branch as a JSONL file.
// Returns the absolute path to the written file.
export async function exportConversation(
  sessionManager: ExtensionContext["sessionManager"],
  planDir: string,
): Promise<string> {
  const filePath = path.join(planDir, "conversation.jsonl");

  const header = sessionManager.getHeader();
  const branch = sessionManager.getBranch();

  const lines: string[] = [];
  if (header) lines.push(JSON.stringify(header));
  for (const entry of branch) lines.push(JSON.stringify(entry));

  await fs.writeFile(filePath, `${lines.join("\n")}\n`, "utf8");
  return filePath;
}
