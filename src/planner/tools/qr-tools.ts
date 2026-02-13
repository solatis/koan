import { Type } from "@sinclair/typebox";
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { promises as fs } from "node:fs";
import * as path from "node:path";

import type { PlanRef } from "./dispatch.js";
import type { QRFile, QRSeverity, QRItemStatus } from "../qr/types.js";
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
      const p = params as {
        phase: string;
        scope: string;
        check: string;
        severity?: QRSeverity;
      };
      const qr = await loadQR(planRef.dir, p.phase);
      const r = addQRItem(qr, p);
      await saveQR(r.qr, planRef.dir, p.phase);
      return {
        content: [{ type: "text" as const, text: `Added QR item ${r.id}` }],
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
      const p = params as {
        phase: string;
        id: string;
        status?: QRItemStatus;
        finding?: string;
        check?: string;
        severity?: QRSeverity;
      };
      const qr = await loadQR(planRef.dir, p.phase);
      const updated = setQRItem(qr, p.id, p);
      await saveQR(updated, planRef.dir, p.phase);
      return {
        content: [{ type: "text" as const, text: `Updated QR item ${p.id}` }],
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
      const p = params as {
        phase: string;
        ids: string[];
        group_id: string;
      };
      const qr = await loadQR(planRef.dir, p.phase);
      const updated = assignGroup(qr, p.ids, p.group_id);
      await saveQR(updated, planRef.dir, p.phase);
      return {
        content: [
          {
            type: "text" as const,
            text: `Assigned ${p.ids.length} items to group ${p.group_id}`,
          },
        ],
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
      const p = params as { phase: string; id: string };
      const qr = await loadQR(planRef.dir, p.phase);
      const item = qr.items.find((x) => x.id === p.id);
      if (!item) throw new Error(`QR item ${p.id} not found`);
      return {
        content: [{ type: "text" as const, text: JSON.stringify(item, null, 2) }],
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
      const p = params as { phase: string; status?: QRItemStatus };
      const qr = await loadQR(planRef.dir, p.phase);
      const filtered = p.status
        ? qr.items.filter((item) => item.status === p.status)
        : qr.items;
      return {
        content: [
          { type: "text" as const, text: JSON.stringify(filtered, null, 2) },
        ],
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
      const p = params as { phase: string };
      const qr = await loadQR(planRef.dir, p.phase);

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
      };
    },
  });
}
