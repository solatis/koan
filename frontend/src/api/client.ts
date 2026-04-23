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
): Promise<StartRunResult> {
  const body: Record<string, unknown> = { task, profile }
  if (installations && Object.keys(installations).length > 0) {
    body['installations'] = installations
  }
  if (workflow) {
    body['workflow'] = workflow
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

export async function sendChatMessage(message: string) {
  return post<{ ok: boolean; error?: string }>('/api/chat', { message })
}

// -- Artifact review ---------------------------------------------------------

export interface ArtifactReviewComment {
  blockIndex: number
  text: string
  blockPreview: string
}

export interface ArtifactReviewPayload {
  summary: string
  comments: ArtifactReviewComment[]
}

export async function submitArtifactReview(
  path: string,
  payload: ArtifactReviewPayload,
) {
  return post<{ ok: boolean; error?: string }>(
    '/api/artifact-review',
    { path, payload },
  )
}

// -- Probe -------------------------------------------------------------------

export interface ModelInfo {
  alias: string
  display_name: string
  thinking_modes: string[]
  tier_hint: string
}

export interface RunnerInfo {
  runner_type: string
  available: boolean
  binary_path: string | null
  version: string | null
  models: ModelInfo[]
}

export async function getProbeInfo(): Promise<{ runners: RunnerInfo[] }> {
  return get('/api/probe')
}

// -- Profiles ----------------------------------------------------------------

export async function createProfile(
  name: string,
  tiers: Record<string, { runner_type: string; model: string; thinking: string }>,
) {
  return post<{ ok: boolean; message?: string }>('/api/profiles', { name, tiers })
}

export async function updateProfile(
  name: string,
  tiers: Record<string, { runner_type: string; model: string; thinking: string }>,
) {
  return put<{ ok: boolean; message?: string }>(`/api/profiles/${encodeURIComponent(name)}`, { tiers })
}

export async function deleteProfile(name: string) {
  return del<{ ok: boolean; message?: string }>(`/api/profiles/${encodeURIComponent(name)}`)
}

// -- Agent installations -----------------------------------------------------

export async function createAgent(params: {
  alias: string
  runner_type: string
  binary: string
  extra_args: string[]
}) {
  return post<{ ok: boolean; message?: string }>('/api/agents', params)
}

export async function updateAgent(
  alias: string,
  params: Partial<{ runner_type: string; binary: string; extra_args: string[] }>,
) {
  return put<{ ok: boolean; message?: string }>(`/api/agents/${encodeURIComponent(alias)}`, params)
}

export async function deleteAgent(alias: string) {
  return del<{ ok: boolean; message?: string }>(`/api/agents/${encodeURIComponent(alias)}`)
}

export async function detectAgent(runner_type: string): Promise<{ path: string | null }> {
  return get(`/api/agents/detect?runner_type=${encodeURIComponent(runner_type)}`)
}

// -- Settings ----------------------------------------------------------------

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
