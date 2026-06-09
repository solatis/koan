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

export async function startRun(
  task: string,
  profile: string,
  installations?: Record<string, string>,
  workflow?: string,
  attachments?: string[],
): Promise<StartRunResult> {
  const body: Record<string, unknown> = { task, profile }
  if (installations && Object.keys(installations).length > 0) {
    body['installations'] = installations
  }
  if (workflow) {
    body['workflow'] = workflow
  }
  if (attachments && attachments.length > 0) {
    body['attachments'] = attachments
  }
  return post('/api/start-run', body)
}

export async function clearRun(): Promise<{ ok: boolean }> {
  return post('/api/run/clear', {})
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

// -- Profiles ----------------------------------------------------------------

/**
 * Create a new user profile.
 * tiers: M3 shape -- {tier_name: {provider, model, thinking}}.
 */
export async function createProfile(
  name: string,
  tiers: Record<string, { provider: string; model: string; thinking: string }>,
) {
  return post<{ ok: boolean; message?: string }>('/api/profiles', { name, tiers })
}

/**
 * Update the tiers of an existing user profile.
 * tiers: M3 shape -- {tier_name: {provider, model, thinking}}.
 */
export async function updateProfile(
  name: string,
  tiers: Record<string, { provider: string; model: string; thinking: string }>,
) {
  return put<{ ok: boolean; message?: string }>(`/api/profiles/${encodeURIComponent(name)}`, { tiers })
}

export async function deleteProfile(name: string) {
  return del<{ ok: boolean; message?: string }>(`/api/profiles/${encodeURIComponent(name)}`)
}

// -- Settings ----------------------------------------------------------------

/**
 * Stores the encrypted API key and/or non-secret region/base_url for a
 * provider. Omitting `secret` leaves the stored key unchanged, so an empty
 * form submit never overwrites an existing key.
 */
export interface ProviderConfigBody {
  secret?: string
  region?: string
  baseUrl?: string
}

export async function setProviderConfig(
  provider: string,
  body: ProviderConfigBody,
): Promise<{ ok: boolean; error?: string; message?: string }> {
  return post('/api/settings/provider', { provider, ...body })
}

/**
 * Clears both the encrypted credential and the non-secret config
 * (region, base_url) for a provider. Idempotent.
 */
export async function deleteProviderConfig(
  provider: string,
): Promise<{ ok: boolean; error?: string; message?: string }> {
  return del(`/api/settings/provider/${encodeURIComponent(provider)}`)
}

/**
 * Test connectivity and model listing for a provider using candidate values.
 * Candidate values from the form (pre-save) are used when present; stored values
 * are the fallback. Always returns HTTP 200 -- never throws on a listing failure.
 *
 * On success: {ok: true, count: N, models: string[]}.
 * On failure: {ok: false, message: string}.
 */
export async function testProviderConfig(
  provider: string,
  body: ProviderConfigBody,
): Promise<{ ok: boolean; count?: number; models?: string[]; message?: string }> {
  return post('/api/settings/provider/test', { provider, ...body })
}

export async function saveScoutConcurrency(value: number) {
  return put<{ ok: boolean; message?: string }>('/api/settings/scout-concurrency', {
    scout_concurrency: value,
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

export interface CurationDecision {
  proposal_id: string
  decision: 'approved' | 'rejected'
  feedback: string
  attachments?: string[]
}

export async function submitMemoryCuration(batch_id: string, decisions: CurationDecision[]) {
  return post<{ ok: boolean; error?: string }>(
    '/api/memory/curation',
    { batch_id, decisions },
  )
}

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
