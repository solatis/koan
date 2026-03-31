import { Installation } from '../store/index'

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
  epic_dir?: string
  error?: string
  message?: string
}

export async function startRun(
  task: string,
  profile: string,
  scoutConcurrency?: number,
  installations?: Record<string, string>,
): Promise<StartRunResult> {
  const body: Record<string, unknown> = { task, profile }
  if (scoutConcurrency !== undefined) {
    body['scout_concurrency'] = scoutConcurrency
  }
  if (installations && Object.keys(installations).length > 0) {
    body['installations'] = installations
  }
  return post('/api/start-run', body)
}

// -- Start-run preflight -----------------------------------------------------

export interface PreflightInstallation {
  alias: string
  binary: string
  binary_valid: boolean
  extra_args: string[]
}

export interface StartRunPreflight {
  profile: string
  required_runner_types: string[]
  installations: Record<string, PreflightInstallation[]>
}

export async function getStartRunPreflight(profile: string): Promise<StartRunPreflight> {
  return get(`/api/start-run/preflight?profile=${encodeURIComponent(profile)}`)
}

// -- Interactions ------------------------------------------------------------

export async function submitAnswer(answers: unknown[], token: string) {
  return post<{ ok: boolean; message?: string }>('/api/answer', { answers, token })
}

export async function submitArtifactReview(
  response: string,
  accepted: boolean,
  token: string,
) {
  return post<{ ok: boolean; message?: string }>('/api/artifact-review', {
    response,
    accepted,
    token,
  })
}

export async function submitWorkflowDecision(
  phase: string,
  context: string,
  token: string,
) {
  return post<{ ok: boolean; message?: string }>('/api/workflow-decision', {
    phase,
    context,
    token,
  })
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

export async function getAgents(): Promise<{
  installations: Installation[]
}> {
  return get('/api/agents')
}

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

export async function getInitialPrompt(): Promise<{ prompt: string }> {
  return get('/api/initial-prompt')
}

// -- Artifacts ---------------------------------------------------------------

export async function getArtifactContent(
  path: string,
): Promise<{ content: string; displayPath: string }> {
  return get(`/api/artifacts/${encodeURIComponent(path)}`)
}
