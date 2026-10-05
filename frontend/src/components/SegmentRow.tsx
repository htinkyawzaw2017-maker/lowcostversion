import { useEffect, useState } from 'react'
import { api, fmtTime, type Segment } from '../lib/api'

const EMOTIONS = ['neutral', 'sad', 'tense', 'warm', 'angry', 'urgent', 'playful', 'fearful']
const VOICES: Record<string, string[]> = {
  my: ['default', 'mya_female_1', 'mya_male_1', 'mya_narrator'],
  en: ['default', 'en_US-amy-medium', 'en_US-ryan-high', 'af_heart'],
}

function fitBadge(s: Segment) {
  if (s.fit === 'unknown') return <span className="badge">no audio</span>
  const cls = s.fit === 'ok' ? 'ok' : s.fit === 'long' ? 'bad' : 'warn'
  return (
    <span className={`badge ${cls}`}>
      {s.drift > 0 ? '+' : ''}
      {s.drift.toFixed(2)}s {s.fit}
    </span>
  )
}

export default function SegmentRow({
  seg,
  lang,
  onChange,
  onNotify,
}: {
  seg: Segment
  lang: string
  onChange: (s: Segment) => void
  onNotify: (m: string, err?: boolean) => void
}) {
  const [draft, setDraft] = useState(seg)
  const [saving, setSaving] = useState(false)

  useEffect(() => setDraft(seg), [seg])

  const dirty =
    draft.dub_text !== seg.dub_text ||
    draft.start !== seg.start ||
    draft.end !== seg.end ||
    draft.voice !== seg.voice ||
    draft.speed !== seg.speed ||
    draft.emotion !== seg.emotion

  async function save(andResynth = false) {
    setSaving(true)
    try {
      const updated = await api.updateSegment(seg.id, {
        dub_text: draft.dub_text,
        start: draft.start,
        end: draft.end,
        voice: draft.voice,
        speed: draft.speed,
        emotion: draft.emotion,
      })
      onChange(updated)
      if (andResynth) {
        await api.resynthesize(seg.id)
        onNotify(`Segment ${seg.index + 1} queued for re-synthesis`)
      }
    } catch (e) {
      onNotify(String(e), true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <tr>
      <td className="mono" style={{ whiteSpace: 'nowrap' }}>
        <div>#{seg.index + 1}</div>
        <div className="muted">{seg.speaker}</div>
        {seg.locked && <span className="badge accent">edited</span>}
      </td>

      <td style={{ width: 150 }}>
        <div className="row" style={{ gap: 5, flexWrap: 'nowrap' }}>
          <input
            className="mono"
            type="number"
            step="0.05"
            value={draft.start}
            onChange={(e) => setDraft({ ...draft, start: Number(e.target.value) })}
          />
          <input
            className="mono"
            type="number"
            step="0.05"
            value={draft.end}
            onChange={(e) => setDraft({ ...draft, end: Number(e.target.value) })}
          />
        </div>
        <div className="muted mono" style={{ marginTop: 4 }}>
          slot {fmtTime(draft.end - draft.start)}
        </div>
      </td>

      <td style={{ maxWidth: 260 }}>
        <div className="muted" style={{ fontSize: 12.5 }}>
          {seg.source_text}
        </div>
      </td>

      <td style={{ minWidth: 280 }}>
        <textarea
          className="seg-text"
          value={draft.dub_text}
          onChange={(e) => setDraft({ ...draft, dub_text: e.target.value })}
          placeholder="Dubbing line…"
        />
        {seg.translated_text && seg.translated_text !== seg.dub_text && (
          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
            literal: {seg.translated_text}
          </div>
        )}
      </td>

      <td style={{ width: 190 }}>
        <select value={draft.voice} onChange={(e) => setDraft({ ...draft, voice: e.target.value })}>
          {VOICES[lang]?.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <select
          style={{ marginTop: 5 }}
          value={draft.emotion}
          onChange={(e) => setDraft({ ...draft, emotion: e.target.value })}
        >
          {EMOTIONS.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
        <div className="row" style={{ gap: 6, marginTop: 5, flexWrap: 'nowrap' }}>
          <input
            type="range"
            min={0.5}
            max={2}
            step={0.05}
            value={draft.speed}
            onChange={(e) => setDraft({ ...draft, speed: Number(e.target.value) })}
          />
          <span className="mono muted">{draft.speed.toFixed(2)}×</span>
        </div>
      </td>

      <td style={{ width: 200 }}>
        <div>{fitBadge(seg)}</div>
        <div className="muted mono" style={{ marginTop: 3 }}>
          {seg.audio_duration ? `${seg.audio_duration.toFixed(2)}s / ${seg.target_duration.toFixed(2)}s` : '—'}
        </div>
        {seg.tts_provider && <div className="muted mono">{seg.tts_provider}</div>}
        {seg.audio_url && <audio controls preload="none" src={seg.audio_url} />}
      </td>

      <td className="right" style={{ width: 120 }}>
        <button className="sm" disabled={!dirty || saving} onClick={() => save(false)}>
          Save
        </button>
        <button
          className="primary sm"
          style={{ marginTop: 5 }}
          disabled={saving}
          onClick={() => save(true)}
        >
          Re-voice
        </button>
      </td>
    </tr>
  )
}
