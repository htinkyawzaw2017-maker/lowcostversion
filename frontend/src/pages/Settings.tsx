import type { AppConfig } from '../lib/api'

const DESC: Record<string, string> = {
  transcription: 'Timestamped transcription — faster-whisper runs locally, no per-minute cost.',
  translation: 'Gemini via the backend: translation, dub rewrite, recap, emotion, shortening.',
  tts_my: 'Burmese speech — local MMS-TTS first.',
  tts_en: 'English speech — local Piper/Kokoro first.',
  tts_fallback: 'Optional fallback only, used when the local engine is unavailable.',
  lipsync: 'Beta. Separate GPU worker, short single-speaker clips.',
  render: 'FFmpeg: extraction, segment mixing, subtitles, final mux.',
  storage: 'S3 presigned uploads, or local disk for development.',
}

export default function SettingsPage({ config }: { config: AppConfig | null }) {
  if (!config) return <div className="page empty">Loading…</div>
  return (
    <div className="page">
      <div className="card">
        <h2>Provider modules</h2>
        <p className="sub">
          Every stage is a replaceable module bound by configuration. Start fully mocked, then swap
          one stage at a time without touching the rest of the app.
        </p>
        <table>
          <thead>
            <tr>
              <th>Stage</th>
              <th>Configured</th>
              <th>Active implementation</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(config.providers).map(([k, v]) => (
              <tr key={k}>
                <td>
                  <strong>{k}</strong>
                  {v.beta && <span className="badge warn" style={{ marginLeft: 6 }}>beta</span>}
                </td>
                <td className="mono">{v.configured}</td>
                <td className="mono">
                  <span className={`badge ${v.active?.startsWith('mock') ? 'warn' : 'ok'}`}>
                    {v.active ?? '—'}
                  </span>
                </td>
                <td className="muted">{DESC[k]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Secrets</h2>
        <p className="sub">
          The Gemini API key lives in AWS Secrets Manager and is read server-side only. It is never
          sent to the browser and no endpoint can return it — this page only shows whether it
          resolves.
        </p>
        <span className={`badge ${config.secrets.gemini_api_key_configured ? 'ok' : 'bad'}`}>
          Gemini API key {config.secrets.gemini_api_key_configured ? 'resolved' : 'not configured'}
        </span>
      </div>
    </div>
  )
}
