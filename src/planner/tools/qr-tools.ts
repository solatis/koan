import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { PlanRef } from "./dispatch.js";
import type { QRFile } from "../qr/types.js";
import { addQRItem, setQRItem, assignGroup } from "../qr/mutate.js";

function createEmptyQRFile(phase: string): QRFile {
  return {
    phase,
    iteration: 1,
    items: [],
  };
}

async function loadQR(dir: string, phase: string): Promise<QRFile> {
  const qrPath = path.join(dir, `qr-${phase}.json`);
  try {
    const content = await fs.readFile(qrPath, "utf8");
    return JSON.parse(content) as QRFile;
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return createEmptyQRFile(phase);
    }
    throw err;
  }
}

async function saveQR(qr: QRFile, dir: string, phase: string): Promise<void> {
  const qrPath = path.join(dir, `qr-${phase}.json`);
  const tmpPath = path.join(dir, `.qr-${phase}.json.tmp`);
  const content = `${JSON.stringify(qr, null, 2)}\n`;
  await fs.writeFile(tmpPath, content, "utf8");
  await fs.rename(tmpPath, qrPath);
}

export function registerQRTools(pi: ExtensionAPI, planRef: PlanRef): void {
  pi.registerTool({
    name: "koan_qr_add_item",
    label: "Add QR item",
    description: "Add quality review item.",
    parameters: Type.Object({
      phase: Type.String(),
      scope: Type.String(),
      check: Type.String(),
      severity: Type.Optional(
        Type.Union([
          Type.Literal("MUST"),
          Type.Literal("SHOULD"),
          Type.Literal("COULD"),
        ]),
      ),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const qr = await loadQR(planRef.dir, params.phase);
      const r = addQRItem(qr, params);
      await saveQR(r.qr, planRef.dir, params.phase);
      return {
        content: [{ type: "text" as const, text: `Added QR item ${r.id}` }],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_qr_set_item",
    label: "Update QR item",
    description: "Update QR item status or finding.",
    parameters: Type.Object({
      phase: Type.String(),
      id: Type.String(),
      status: Type.Optional(
        Type.Union([
          Type.Literal("TODO"),
          Type.Literal("PASS"),
          Type.Literal("FAIL"),
        ]),
      ),
      finding: Type.Optional(Type.String()),
      check: Type.Optional(Type.String()),
      severity: Type.Optional(
        Type.Union([
          Type.Literal("MUST"),
          Type.Literal("SHOULD"),
          Type.Literal("COULD"),
        ]),
      ),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const qr = await loadQR(planRef.dir, params.phase);
      const updated = setQRItem(qr, params.id, params);
      await saveQR(updated, planRef.dir, params.phase);
      return {
        content: [{ type: "text" as const, text: `Updated QR item ${params.id}` }],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_qr_assign_group",
    label: "Assign QR group",
    description: "Assign group ID to QR items.",
    parameters: Type.Object({
      phase: Type.String(),
      ids: Type.Array(Type.String()),
      group_id: Type.String(),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const qr = await loadQR(planRef.dir, params.phase);
      const updated = assignGroup(qr, params.ids, params.group_id);
      await saveQR(updated, planRef.dir, params.phase);
      return {
        content: [
          {
            type: "text" as const,
            text: `Assigned ${params.ids.length} items to group ${params.group_id}`,
          },
        ],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_qr_get_item",
    label: "Get QR item",
    description: "Get QR item by ID.",
    parameters: Type.Object({
      phase: Type.String(),
      id: Type.String(),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const qr = await loadQR(planRef.dir, params.phase);
      const item = qr.items.find((x) => x.id === params.id);
      if (!item) throw new Error(`QR item ${params.id} not found`);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(item, null, 2) }],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_qr_list_items",
    label: "List QR items",
    description: "List QR items, optionally filtered by status.",
    parameters: Type.Object({
      phase: Type.String(),
      status: Type.Optional(
        Type.Union([
          Type.Literal("TODO"),
          Type.Literal("PASS"),
          Type.Literal("FAIL"),
        ]),
      ),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const qr = await loadQR(planRef.dir, params.phase);
      const filtered = params.status
        ? qr.items.filter((item) => item.status === params.status)
        : qr.items;
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(filtered, null, 2) },
        ],
        details: undefined,
      };
    },
  });

  pi.registerTool({
    name: "koan_qr_summary",
    label: "QR summary",
    description: "Get QR summary with counts by status and severity.",
    parameters: Type.Object({
      phase: Type.String(),
    }),
    async execute(_toolCallId, params) {
      if (!planRef.dir) throw new Error("No plan directory is active.");
      const qr = await loadQR(planRef.dir, params.phase);

      const byStatus = {
        TODO: qr.items.filter((x) => x.status === "TODO").length,
        PASS: qr.items.filter((x) => x.status === "PASS").length,
        FAIL: qr.items.filter((x) => x.status === "FAIL").length,
      };

      const bySeverity = {
        MUST: qr.items.filter((x) => x.severity === "MUST").length,
        SHOULD: qr.items.filter((x) => x.severity === "SHOULD").length,
        COULD: qr.items.filter((x) => x.severity === "COULD").length,
      };

      const summary = {
        total: qr.items.length,
        by_status: byStatus,
        by_severity: bySeverity,
      };

      return {
        content: [
          { type: "text" as const, text: JSON.stringify(summary, null, 2) },
        ],
        details: undefined,
      };
    },
  });
}
