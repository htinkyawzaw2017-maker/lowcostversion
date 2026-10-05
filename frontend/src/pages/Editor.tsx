import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type AppConfig, type Job, type Project, type Segment } from '../lib/api'
import { useToast } from '../lib/useToast'
import SegmentRow from '../components/SegmentRow'

type Tab = 'script' | 'jobs' | 'export' | 'extras'

const EXPORTS: { kind: string; label: string; note: string }[] = [
  { kind: 'mp4', label: 'MP4 (dubbed video)', note: 'Original video + mixed dub track' },
  { kind: 'mp4_lipsync', label: 'MP4 (lip-sync beta)', note: 'Only present if the GPU worker succeeded' },
  { kind: 'wav', label: 'WAV (dub mix)', note: 'Lossless full-length dubbed audio' },
  { kind: 'mp3', label: 'MP3 (dub mix)', note: '192 kbps' },
  { kind: 'srt', label: 'SRT subtitles', note: 'Dubbed script with timings' },
  { kind: 'vtt', label: 'VTT subtitles', note: 'For web players' },
  { kind: 'recap', label: 'Recap script', note: 'Gemini-generated voiceover recap' },
]

export default function EditorPage({ config }: { config: AppConfig | null }) {
  const { id = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [tab, setTab] = useState<Tab>('script')
  const [filter, setFilter] = useState<'all' | 'long' | 'edited'>('all')
  const [recapMinutes, setRecapMinutes] = useState(3)
  const toast = useToast()
  const timer = useRef<number | null>(null)

  const load = useCallback(async () => {
    try {
      setProject(await api.getProject(id))
    } catch (e) {
      toast(String(e), true)
    }
  }, [id, toast])

  useEffect(() => {
    load()
  }, [load])

  // Poll while anything is in flight. Work continues server-side regardless.
  const active = (project?.jobs || []).some((j) => j.status === 'pending' || j.status === 'running')
  useEffect(() => {
    if (!active) return
    timer.current = window.setInterval(load, 2000)
    return () => {
      if (timer.current) window.clearInterval(timer.current)
    }
  }, [active, load])

  if (!project) return <div className="page empty">Loading…</div>

  const segments = project.segments || []
  const shown = segments.filter((s) =>
    filter === 'all' ? true : filter === 'long' ? s.fit === 'long' : s.locked,
  )
  const overBudget = segments.filter((s) => s.fit === 'long').length
  const voiced = segments.filter((s) => s.audio_url).length
  const latest = project.jobs?.[project.jobs.length - 1]

  const patchSeg = (s: Segment) =>
    setProject((p) => (p ? { ...p, segments: (p.segments || []).map((x) => (x.id === s.id ? s : x)) } : p))

  async function run(kind: string, params: Record<string, unknown> = {}, msg?: string) {
    try {
      await api.startJob(project!.id, kind, params)
      toast(msg || `${kind} queued — safe to close the browser`)
      load()
    } catch (e) {
      toast(String(e), true)
    }
  }

  return (
    <div className="page">
      <div className="card">
        <div className="row">
          <div>
            <h2>{project.title}</h2>
            <div className="muted mono">
              {project.source_lang} → {project.target_lang} · {segments.length} segments · {voiced} voiced
            </div>
          </div>
          <span className="spacer" />
          <span className={`badge ${project.status === 'failed' ? 'bad' : 'ok'}`}>{project.status}</span>
          {overBudget > 0 && <span className="badge bad">{overBudget} over their slot</span>}
          <button className="primary" onClick={() => run('pipeline', {}, 'Full pipeline queued')}>
            Run pipeline
          </button>
          <button onClick={() => run('tts', {}, 'Re-synthesising all segments')}>Re-voice all</button>
          <button onClick={() => run('render', {}, 'Re-rendering exports')}>Re-render</button>
        </div>

        {latest && (latest.status === 'running' || latest.status === 'pending') && (
          <div style={{ marginTop: 14 }}>
            <div className="progress">
              <div style={{ width: `${Math.round(latest.progress * 100)}%` }} />
            </div>
            <div className="muted mono" style={{ marginTop: 5 }}>
              {latest.kind} · {latest.stage} · {Math.round(latest.progress * 100)}%
            </div>
          </div>
        )}
      </div>

      <div className="tabs">
        {(['script', 'jobs', 'export', 'extras'] as Tab[]).map((t) => (
          <button key={t} data-active={tab === t} onClick={() => setTab(t)}>
            {t === 'script' ? 'Script & voices' : t === 'extras' ? 'Recap & lip-sync' : t}
          </button>
        ))}
      </div>

      {tab === 'script' && (
        <div className="card">
          <div className="row" style={{ marginBottom: 10 }}>
            <h3 style={{ margin: 0 }}>Editable dubbing script</h3>
            <span className="spacer" />
            {(['all', 'long', 'edited'] as const).map((f) => (
              <button key={f} className="sm" data-active={filter === f} onClick={() => setFilter(f)}>
                {f === 'long' ? `over budget (${overBudget})` : f}
              </button>
            ))}
          </div>
          <p className="sub">
            Edit text, timing, voice, emotion and speed. Generated duration is compared against the
            original dialogue slot — red means the take runs longer than the gap.
          </p>
          {shown.length === 0 ? (
            <div className="empty">No segments. Run the pipeline to transcribe.</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Start / End</th>
                  <th>Source</th>
                  <th>Dub line</th>
                  <th>Voice / tone / speed</th>
                  <th>Duration fit</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {shown.map((s) => (
                  <SegmentRow
                    key={s.id}
                    seg={s}
                    lang={project.target_lang}
                    onChange={patchSeg}
                    onNotify={toast}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'jobs' && (
        <div className="card">
          <h3>Background jobs</h3>
          <p className="sub">
            Jobs are stored in the database and executed by a worker process — closing this tab does
            not stop or cancel anything.
          </p>
          {(project.jobs || []).length === 0 && <div className="empty">No jobs yet.</div>}
          {[...(project.jobs || [])].reverse().map((j: Job) => (
            <div key={j.id} style={{ marginBottom: 14 }}>
              <div className="row">
                <strong>{j.kind}</strong>
                <span
                  className={`badge ${
                    j.status === 'failed' ? 'bad' : j.status === 'succeeded' ? 'ok' : 'warn'
                  }`}
                >
                  {j.status}
                </span>
                <span className="muted mono">{j.stage}</span>
                <span className="spacer" />
                <span className="muted mono">{new Date(j.updated_at).toLocaleTimeString()}</span>
              </div>
              <div className="progress" style={{ margin: '6px 0' }}>
                <div style={{ width: `${Math.round(j.progress * 100)}%` }} />
              </div>
              {j.error && <div className="badge bad">{j.error.split('\n')[0]}</div>}
              {j.logs.length > 0 && <div className="logs">{j.logs.join('\n')}</div>}
            </div>
          ))}
        </div>
      )}

      {tab === 'export' && (
        <div className="card">
          <h3>Exports</h3>
          <p className="sub">
            The audio-only dubbed outputs (MP4 / WAV / MP3 / SRT / VTT) are always produced, even if
            the optional lip-sync beta fails.
          </p>
          <table>
            <tbody>
              {EXPORTS.map((e) => {
                const a = project.artifacts.find((x) => x.kind === e.kind)
                return (
                  <tr key={e.kind}>
                    <td>
                      <strong>{e.label}</strong>
                      <div className="muted">{e.note}</div>
                    </td>
                    <td className="mono muted">{a ? `${(a.bytes / 1024).toFixed(0)} KB` : 'not ready'}</td>
                    <td className="right">
                      <a href={a?.url ?? '#'} download>
                        <button className="sm" disabled={!a}>
                          Download
                        </button>
                      </a>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <div className="row" style={{ marginTop: 14 }}>
            <a href={`/api/projects/${project.id}/subtitles.srt`} target="_blank" rel="noreferrer">
              Preview SRT
            </a>
            <a href={`/api/projects/${project.id}/subtitles.vtt`} target="_blank" rel="noreferrer">
              Preview VTT
            </a>
            <span className="spacer" />
            <label className="row" style={{ gap: 6 }}>
              <input
                type="checkbox"
                style={{ width: 16 }}
                checked={Boolean(project.settings.burn_subtitles)}
                onChange={async (e) => {
                  await api.updateProject(project.id, { settings: { burn_subtitles: e.target.checked } })
                  load()
                }}
              />
              <span className="muted">Burn subtitles into MP4 on next render</span>
            </label>
          </div>
        </div>
      )}

      {tab === 'extras' && (
        <>
          <div className="card">
            <h3>Recap script (Gemini)</h3>
            <p className="sub">Generates a timed voiceover recap from the transcript.</p>
            <div className="row">
              <div className="field" style={{ width: 160 }}>
                <label>Target minutes</label>
                <input
                  type="number"
                  min={1}
                  max={15}
                  value={recapMinutes}
                  onChange={(e) => setRecapMinutes(Number(e.target.value))}
                />
              </div>
              <button
                onClick={() => run('recap', { minutes: recapMinutes, lang: project.target_lang })}
                disabled={segments.length === 0}
              >
                Generate recap
              </button>
              {project.artifacts.some((a) => a.kind === 'recap') && (
                <a href={`/api/projects/${project.id}/artifacts/recap`} target="_blank" rel="noreferrer">
                  View latest recap
                </a>
              )}
            </div>
          </div>

          <div className="card">
            <h3>
              Lip-sync <span className="badge warn">beta</span>
            </h3>
            <p className="sub">
              Runs on a separate GPU worker. Short clips only (≤{' '}
              {config?.lipsync.max_clip_seconds ?? 20}s) and one front-facing speaker. If it fails,
              your audio-only dubbed output stays untouched and downloadable.
            </p>
            <div className="row">
              <button
                onClick={() => run('lipsync', { max_clips: 3 }, 'Lip-sync beta queued on the GPU worker')}
                disabled={voiced === 0}
              >
                Try lip-sync on 3 short clips
              </button>
              <span className="muted">worker: {config?.providers.lipsync?.active ?? 'unknown'}</span>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
