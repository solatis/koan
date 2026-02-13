export type QRSeverity = "MUST" | "SHOULD" | "COULD";
export type QRItemStatus = "TODO" | "PASS" | "FAIL";

export interface QRItem {
  id: string;
  scope: string;
  check: string;
  status: QRItemStatus;
  version: number;
  finding: string | null;
  parent_id: string | null;
  group_id: string | null;
  severity: QRSeverity;
}

export interface QRFile {
  phase: string;
  iteration: number;
  items: QRItem[];
}
