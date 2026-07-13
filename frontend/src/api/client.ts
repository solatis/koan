// -- Helpers -----------------------------------------------------------------

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json() as Promise<T>
}

async function put<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return res.json() as Promise<T>
}

async function del<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'DELETE' })
  return res.json() as Promise<T>
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  return res.json() as Promise<T>
}

// -- Run ---------------------------------------------------------------------

export interface StartRunResult {
  ok: boolean
  run_dir?: string
  error?: string
  message?: string
}

/**
 * Start a run on the backend active preset ($last). The backend resolves cfg.active.
 *
 * @param task - The task description.
 * @param workflow - Optional workflow name (default: 'plan').
 * @param attachments - Optional upload IDs to attach at run start.
 * @param overrides - Optional per-run model overrides applied to the $last preset.
 *   Each role key (strong/standard/cheap) may carry {connection_id, model_id, thinking}.
 *   Roles not included fall back to their persisted slot assignment.
 *   Overrides affect only the frozen run snapshot; ~/.koan/config.yaml is untouched.
 *
 * M4: installations param removed -- agent installation concept deleted.
 * M5: profile param removed -- /api/start-run no longer reads a posted profile.
 */
export async function startRun(
  task: string,
  workflow?: string,
  attachments?: string[],
  overrides?: Partial<Record<'strong' | 'standard' | 'cheap', {
    connection_id: string
    model_id: string
    thinking: string
  }>>,
): Promise<StartRunResult> {
  const body: Record<string, unknown> = { task }
  if (workflow) {
    body['workflow'] = workflow
  }
  if (attachments && attachments.length > 0) {
    body['attachments'] = attachments
  }
  if (overrides && Object.keys(overrides).length > 0) {
    body['overrides'] = overrides
  }
  return post('/api/start-run', body)
}

// clearRun removed: run clearing is server-authoritative at workflow end; the
// backend emits run_cleared at done-receipt / failure exit.

/**
 * Mechanical phase transition (including 'done'). Only valid while the workflow
 * is parked at a yield -- the server rejects with 409 otherwise.
 * @param phase - The target phase name, or 'done' to end the workflow.
 */
export async function setPhase(phase: string): Promise<{ ok: boolean; error?: string; message?: string; phase?: string }> {
  return post('/api/phase', { phase })
}

// -- Interactions ------------------------------------------------------------

export async function submitAnswer(answers: unknown[], token: string) {
  return post<{ ok: boolean; message?: string }>('/api/answer', { answers, token })
}

// -- Chat --------------------------------------------------------------------

export async function sendChatMessage(message: string, attachments?: string[]) {
  const body: Record<string, unknown> = { message }
  if (attachments && attachments.length > 0) {
    body['attachments'] = attachments
  }
  return post<{ ok: boolean; error?: string }>('/api/chat', body)
}

// -- Artifact comment ---------------------------------------------------------
// M5 replaced /api/artifact-review with /api/artifact-comment (flat schema).
// submitArtifactReview and the multi-block payload types are deleted.

export async function submitArtifactComment(
  path: string,
  comment: string,
  attachments: string[] = [],
): Promise<{ ok: boolean; error?: string }> {
  return post<{ ok: boolean; error?: string }>(
    '/api/artifact-comment',
    { path, comment, attachments },
  )
}

// M5: profile endpoints removed -- /api/profiles deleted on the backend.
// Dead /api/settings/provider* methods removed (M5; routes deleted in M5; HTTP 404).

// -- Settings ----------------------------------------------------------------

// -- /api/config/* methods (M6) -----------------------------------------------

export interface ConfigApiResult {
  ok: boolean
  error?: string
  message?: string
  /** Returned by setConfiguredModel / setMemoryBinding when a LanceDB vector index
   *  rebuild was triggered but failed.  The save itself succeeded; only the rebuild
   *  failed.  Present only when the rebuild was attempted and errored. */
  rebuild_error?: string
  count?: number
  models?: string[]
}

export interface ConnectionBody {
  id: string
  type: string
  base_url?: string
  locality?: string
  azure_deployment?: string
  api_version?: string
  timeout?: number
  /** Plaintext secret; encrypted on the backend before storage. */
  secret?: string
}

export interface ConfiguredModelBody {
  id: string
  connection_id: string
  model_id: string
  resolved_from?: string
  /** Selected Voyage output dimension; omitted or null means use the catalog default. */
  embedding_dim?: number | null
}

export interface SlotBody {
  configured_model_id: string
  thinking?: string
}

/**
 * Upsert a connection (POST /api/config/connections).
 * If 'secret' is present it is stored encrypted; omitting it leaves any
 * existing credential unchanged. Pushes settings_listed (full snapshot).
 * When base_url is omitted on edit, the backend preserves the existing value.
 */
export async function setConnection(body: ConnectionBody): Promise<ConfigApiResult> {
  return post('/api/config/connections', body)
}

/**
 * Delete a connection by id (DELETE /api/config/connections/{id}).
 * Removes the connection and its credential envelope. Idempotent.
 */
export async function deleteConnection(id: string): Promise<ConfigApiResult> {
  return del(`/api/config/connections/${encodeURIComponent(id)}`)
}

/**
 * Trigger a live model listing for a connection (POST /api/config/connections/{id}/list-models).
 * On success: {ok: true, count: N, models: string[]}.
 * On failure: {ok: false, message: string}.
 */
export async function listConnectionModels(id: string): Promise<ConfigApiResult> {
  return post(`/api/config/connections/${encodeURIComponent(id)}/list-models`, {})
}

/**
 * Upsert a configured model (POST /api/config/models).
 * A configured model is a (connection, model-id) pair; the id is caller-assigned
 * and conventionally '<connectionId>:<modelId>' for auto-created entries.
 * This is a full upsert -- all fields (including resolved_from) must be preserved.
 */
export async function setConfiguredModel(body: ConfiguredModelBody): Promise<ConfigApiResult> {
  return post('/api/config/models', body)
}

/**
 * Delete a configured model by id (DELETE /api/config/models/{id}).
 * Idempotent; also removes any slot/memory references in the config.
 */
export async function deleteConfiguredModel(id: string): Promise<ConfigApiResult> {
  return del(`/api/config/models/${encodeURIComponent(id)}`)
}

/**
 * Assign a role slot in the active preset (PUT /api/config/slots/{slot}).
 * slot is one of 'strong', 'standard', 'cheap'.
 */
export async function setSlot(slot: string, body: SlotBody): Promise<ConfigApiResult> {
  return put(`/api/config/slots/${encodeURIComponent(slot)}`, body)
}

/**
 * Assign a memory binding (PUT /api/config/memory/{kind}).
 * kind must be 'embedding'; memory_llm and reflect_llm are no longer valid API kinds.
 */
export async function setMemoryBinding(kind: string, body: SlotBody): Promise<ConfigApiResult> {
  return put(`/api/config/memory/${encodeURIComponent(kind)}`, body)
}

export async function saveScoutConcurrency(value: number) {
  return put<{ ok: boolean; message?: string }>('/api/settings/scout-concurrency', {
    scout_concurrency: value,
  })
}

export async function saveRetrySettings(maxRetryAttempts: number, maxRetryWaitSeconds: number) {
  return put<{ ok: boolean; message?: string }>('/api/settings/retry', {
    max_retry_attempts: maxRetryAttempts,
    max_retry_wait_seconds: maxRetryWaitSeconds,
  })
}

// -- Initial prompt ----------------------------------------------------------

export async function getInitialPrompt(): Promise<{ prompt: string; project_dir?: string }> {
  return get('/api/initial-prompt')
}

// -- Artifacts ---------------------------------------------------------------

export async function getArtifactContent(
  path: string,
): Promise<{ content: string; displayPath: string }> {
  return get(`/api/artifacts/${encodeURIComponent(path)}`)
}

// -- Sessions ----------------------------------------------------------------

export interface Session {
  run_id: string
  task: string
  workflow: string
  created_at: number
  project_dir: string
}

export async function listSessions(): Promise<{ sessions: Session[] }> {
  return get('/api/sessions')
}

export async function deleteSession(run_id: string): Promise<{ ok: boolean; error?: string; message?: string }> {
  return del(`/api/sessions/${encodeURIComponent(run_id)}`)
}

// -- Memory ------------------------------------------------------------------

import type { MemoryType } from '../store/index'

export interface MemoryEntryWire {
  seq: string
  type: MemoryType
  title: string
  createdMs: number
  modifiedMs: number
}

export async function listMemoryEntries(
  params?: { q?: string; type?: string },
): Promise<{ entries: MemoryEntryWire[] }> {
  // Build query string only when there are non-empty values to avoid
  // sending spurious params that change backend behaviour.
  const parts: string[] = []
  if (params?.q) parts.push(`q=${encodeURIComponent(params.q)}`)
  if (params?.type && params.type !== 'all') parts.push(`type=${encodeURIComponent(params.type)}`)
  const qs = parts.length ? `?${parts.join('&')}` : ''
  return get(`/api/memory/entries${qs}`)
}

export interface MemoryRelationWire {
  seq: string
  type: MemoryType
  title: string
  age: string
}

export interface MemoryEntryDetailWire {
  entry: {
    seq: string
    type: MemoryType
    title: string
    body: string
    createdMs: number
    modifiedMs: number
    filename: string
    related: string[]
  }
  relations: { outgoing: MemoryRelationWire[]; incoming: MemoryRelationWire[] }
}

export async function getMemoryEntry(seq: string): Promise<MemoryEntryDetailWire> {
  return get(`/api/memory/entries/${encodeURIComponent(seq)}`)
}

export async function getMemorySummary(): Promise<{ summary: string }> {
  return get('/api/memory/summary')
}

export async function startReflect(question: string, context?: string) {
  return post<{ ok: boolean; session_id: string; error?: string }>(
    '/api/memory/reflect',
    { question, context },
  )
}

export async function cancelReflect() {
  return del<{ ok: boolean; error?: string }>('/api/memory/reflect')
}

// CurationDecision and submitMemoryCuration removed in M7: koan_memory_propose
// gate retired; the /api/memory/curation endpoint no longer exists.

// -- File uploads -------------------------------------------------------------

export interface UploadedFile {
  id: string
  filename: string
  size: number
  content_type: string
}

export async function uploadFile(file: File): Promise<UploadedFile> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/upload', { method: 'POST', body: form })
  return res.json() as Promise<UploadedFile>
}
