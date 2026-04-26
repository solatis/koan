---
title: Remove UI attachment affordances from frontend surfaces that no backend path
  can deliver the files from
type: procedure
created: '2026-04-24T16:40:02Z'
modified: '2026-04-24T16:40:02Z'
---

This entry records a frontend discipline rule established during the file-attachment initiative (M5) in koan's React SPA (`frontend/src/components/`). On 2026-04-24, during M5 plan-spec, the orchestrator noted that `frontend/src/components/organisms/MemoryOverviewPage.tsx` had been refactored in the pre-M1 design phase to include a paperclip icon, drag-and-drop handlers, and a file-chip row on the reflect question textarea via `useFileAttachment`, but the `POST /api/memory/reflect` HTTP endpoint did not accept `attachments` (it was not one of the four attachment-accepting endpoints in scope for M3: `/api/chat`, `/api/answer`, `/api/artifact-review`, `/api/memory/curation`). Leaving the UI affordance would have silently discarded user-uploaded file IDs after reflect was submitted, producing a dead-end interaction the user could not diagnose. On 2026-04-24, during M5 execute, the executor removed the `useFileAttachment` import, the paperclip button, the file-input element, the drop overlay, and the `FileChip` row from `MemoryOverviewPage.tsx`, and changed the `onAsk(value, ids)` callback to `onAsk(value)` to match. The general rule Leon confirmed for future frontend UI work in koan: if a visual attachment affordance cannot deliver uploaded files through an existing backend endpoint that accepts an `attachments` field, remove the affordance rather than let IDs drop on the floor; extending the backend to accept attachments on that endpoint is a separate initiative, not a silent add.
