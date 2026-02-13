import type { QRFile, QRItem, QRSeverity, QRItemStatus } from "./types.js";

function pad3(n: number): string {
  return String(n).padStart(3, "0");
}

function nextQRId(qr: QRFile): string {
  return `QR-${qr.phase}-${pad3(qr.items.length + 1)}`;
}

export function addQRItem(
  qr: QRFile,
  data: { scope: string; check: string; severity?: QRSeverity },
): { qr: QRFile; id: string } {
  const id = nextQRId(qr);
  const item: QRItem = {
    id,
    scope: data.scope,
    check: data.check,
    status: "TODO",
    version: 1,
    finding: null,
    parent_id: null,
    group_id: null,
    severity: data.severity ?? "MUST",
  };
  return {
    qr: {
      ...qr,
      items: [...qr.items, item],
    },
    id,
  };
}

// PASS is terminal: cannot transition from PASS to FAIL.
// FAIL requires finding (explains what failed).
// PASS forbids finding.
export function setQRItem(
  qr: QRFile,
  id: string,
  data: {
    status?: QRItemStatus;
    finding?: string;
    check?: string;
    severity?: QRSeverity;
  },
): QRFile {
  const idx = qr.items.findIndex((i) => i.id === id);
  if (idx === -1) throw new Error(`qr_item ${id} not found`);

  const item = qr.items[idx];

  if (item.status === "PASS" && data.status === "FAIL") {
    throw new Error(`cannot transition ${id} from PASS to FAIL (PASS is terminal)`);
  }

  const status = data.status ?? item.status;
  const finding = data.finding ?? item.finding;

  if (status === "FAIL" && !finding) {
    throw new Error(`FAIL status requires finding for ${id}`);
  }

  if (status === "PASS" && finding) {
    throw new Error(`PASS status forbids finding for ${id}`);
  }

  const updated: QRItem = {
    ...item,
    version: item.version + 1,
    status,
    finding,
    check: data.check ?? item.check,
    severity: data.severity ?? item.severity,
  };

  const items = [...qr.items];
  items[idx] = updated;

  return { ...qr, items };
}

// Does not increment version (grouping is metadata).
export function assignGroup(qr: QRFile, ids: string[], groupId: string): QRFile {
  const idSet = new Set(ids);
  const items = qr.items.map((item) =>
    idSet.has(item.id) ? { ...item, group_id: groupId } : item,
  );
  return { ...qr, items };
}
