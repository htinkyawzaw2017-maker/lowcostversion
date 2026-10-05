import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, uploadToPresigned, type Project } from '../lib/api'
import { useToast } from '../lib/useToast'

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [title, setTitle] = useState('')
  const [sourceLang, setSourceLang] = useState('en')
  const [targetLang, setTargetLang] = useState('my')
  const [file, setFile] = useState<File | null>(null)
  const [pct, setPct] = useState<number | null>(null)
  const [over, setOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const nav = useNavigate()
  const toast = useToast()

  const refresh = useCallback(() => {
    api.listProjects().then(setProjects).catch((e) => toast(String(e), true))
  }, [toast])

  useEffect(refresh, [refresh])

  const pick = (f: File | null) => {
    if (!f) return
    setFile(f)
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ''))
  }

  async function create(startNow: boolean) {
    if (!title.trim()) return toast('Give the project a title', true)
    try {
      setPct(file ? 0 : null)
      const p = await api.createProject({
        title: title.trim(),
        source_lang: sourceLang,
        target_lang: targetLang,
        filename: file?.name,
        content_type: file?.type || 'video/mp4',
      })
      if (file && p.upload) {
        await uploadToPresigned(p.upload, file, setPct)
        await api.uploadComplete(p.id)
      }
      if (startNow) await api.startJob(p.id, 'pipeline')
      toast(startNow ? 'Pipeline queued — it keeps running if you close the browser' : 'Project created')
      nav(`/projects/${p.id}`)
    } catch (e) {
      toast(String(e), true)
    } finally {
      setPct(null)
    }
  }

  return (
    <div className="page">
      <div className="card">
        <h2>New dubbing project</h2>
        <p className="sub">
          The video is uploaded straight to S3 with a short-lived presigned URL — it never passes
          through the API server.
        </p>
        <div className="grid3" style={{ marginBottom: 12 }}>
          <div className="field">
            <label>Title</label>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Film title" />
          </div>
          <div className="field">
            <label>Source language</label>
            <select value={sourceLang} onChange={(e) => setSourceLang(e.target.value)}>
              <option value="en">English</option>
              <option value="my">Burmese</option>
            </select>
          </div>
          <div className="field">
            <label>Dub into</label>
            <select value={targetLang} onChange={(e) => setTargetLang(e.target.value)}>
              <option value="my">Burmese</option>
              <option value="en">English</option>
            </select>
          </div>
        </div>

        <div
          className="drop"
          data-over={over}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => {
            e.preventDefault()
            setOver(true)
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            pick(e.dataTransfer.files?.[0] ?? null)
          }}
        >
          {file ? (
            <>
              <strong>{file.name}</strong>
              <div className="muted">{(file.size / 1e6).toFixed(1)} MB — click to change</div>
            </>
          ) : (
            <>Drop a video here, or click to browse (optional in mock mode)</>
          )}
          <input
            ref={inputRef}
            type="file"
            accept="video/*"
            hidden
            onChange={(e) => pick(e.target.files?.[0] ?? null)}
          />
        </div>

        {pct !== null && (
          <div style={{ marginTop: 12 }}>
            <div className="progress">
              <div style={{ width: `${Math.round(pct * 100)}%` }} />
            </div>
            <div className="muted" style={{ marginTop: 5 }}>
              Uploading {Math.round(pct * 100)}%
            </div>
          </div>
        )}

        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" disabled={pct !== null} onClick={() => create(true)}>
            Create &amp; run pipeline
          </button>
          <button disabled={pct !== null} onClick={() => create(false)}>
            Create only
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Projects</h2>
        {projects.length === 0 ? (
          <div className="empty">No projects yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Languages</th>
                <th>Status</th>
                <th>Segments</th>
                <th>Exports</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td>
                    <a href={`/projects/${p.id}`} onClick={(e) => { e.preventDefault(); nav(`/projects/${p.id}`) }}>
                      {p.title}
                    </a>
                    <div className="muted mono">{new Date(p.created_at).toLocaleString()}</div>
                  </td>
                  <td className="mono">{p.source_lang} → {p.target_lang}</td>
                  <td>
                    <span className={`badge ${p.status === 'failed' ? 'bad' : p.status === 'completed' || p.status === 'needs_review' ? 'ok' : ''}`}>
                      {p.status}
                    </span>
                  </td>
                  <td>{p.segment_count}</td>
                  <td>
                    <div className="chips">
                      {p.artifacts.map((a) => (
                        <span key={a.kind} className="badge accent">{a.kind}</span>
                      ))}
                    </div>
                  </td>
                  <td className="right">
                    <button
                      className="danger sm"
                      onClick={async () => {
                        await api.deleteProject(p.id)
                        refresh()
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
