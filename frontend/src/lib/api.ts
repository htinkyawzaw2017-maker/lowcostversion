// All calls are relative -> proxied to FastAPI. No API keys ever live here.
export type Fit = 'ok' | 'long' | 'short' | 'unknown'

export interface Segment {
  id: string
  index: number
  start: number
  end: number
  speaker: string
  source_text: string
  translated_text: string
  dub_text: string
  emotion: string
  voice: string
  speed: number
  locked: boolean
  audio_url: string | null
  audio_duration: number
  target_duration: number
  drift: number
  fit: Fit
  tts_provider: string | null
}

export interface Job {
  id: string
  project_id: string
  kind: string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'
  progress: number
  stage: string
  error: string | null
  logs: string[]
  attempts: number
  created_at: string
  updated_at: string
}

export interface Artifact {
  kind: string
  bytes: number
  meta: Record<string, unknown>
  url: string
}

export interface Project {
  id: string
  title: string
  source_lang: string
  target_lang: string
  status: string
  duration_sec: number
  settings: Record<string, unknown>
  segment_count: number
  has_source: boolean
  created_at: string
  artifacts: Artifact[]
  segments?: Segment[]
  jobs?: Job[]
  upload?: { url: string; method: string; key: string; headers: Record<string, string> }
}

export interface AppConfig {
  app_name: string
  providers: Record<string, { configured: string; active?: string; beta?: boolean }>
  secrets: { gemini_api_key_configured: boolean }
  lipsync: { beta: boolean; max_clip_seconds: number }
  storage: string
  mock_mode: boolean
}

const TOKEN = localStorage.getItem('dub_token') || ''

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      ...(init.headers || {}),
    },
  })
  if (!res.ok) throw new Error((await res.text()) || res.statusText)
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const api = {
  config: () => req<AppConfig>('/config'),
  listProjects: () => req<Project[]>('/projects'),
  getProject: (id: string) => req<Project>(`/projects/${id}`),
  createProject: (body: {
    title: string
    source_lang: string
    target_lang: string
    filename?: string
    content_type?: string
  }) => req<Project>('/projects', { method: 'POST', body: JSON.stringify(body) }),
  updateProject: (id: string, body: Record<string, unknown>) =>
    req<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteProject: (id: string) => req<void>(`/projects/${id}`, { method: 'DELETE' }),
  uploadComplete: (id: string) => req<Project>(`/projects/${id}/upload-complete`, { method: 'POST' }),
  updateSegment: (sid: string, body: Partial<Segment>) =>
    req<Segment>(`/segments/${sid}`, { method: 'PATCH', body: JSON.stringify(body) }),
  resynthesize: (sid: string) => req<Job>(`/segments/${sid}/resynthesize`, { method: 'POST' }),
  startJob: (pid: string, kind: string, params: Record<string, unknown> = {}) =>
    req<Job>(`/projects/${pid}/jobs`, { method: 'POST', body: JSON.stringify({ kind, params }) }),
  getJob: (jid: string) => req<Job>(`/jobs/${jid}`),
}

/** Browser -> S3 directly, using a short-lived presigned URL from the backend. */
export async function uploadToPresigned(
  upload: NonNullable<Project['upload']>,
  file: File,
  onProgress: (pct: number) => void,
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open(upload.method, upload.url)
    Object.entries(upload.headers || {}).forEach(([k, v]) => xhr.setRequestHeader(k, v))
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => (xhr.status < 400 ? resolve() : reject(new Error(`upload failed ${xhr.status}`)))
    xhr.onerror = () => reject(new Error('network error during upload'))
    xhr.send(file)
  })
}

export const fmtTime = (s: number) => {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = (s % 60).toFixed(2).padStart(5, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}
