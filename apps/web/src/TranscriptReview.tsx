import CutReview from './CutReview.js';
import { useCallback, useEffect, useRef, useState } from 'react';
import { CaptionOverlay, CaptionStatus, useCaptionPlan, useEmphasisPlan } from './CaptionPreview.js';
import { activeSegment, seekVideo, timedWords } from './transcript.js';
import type { Review, Segment } from './transcript.js';

const API = 'http://127.0.0.1:8000';

export function SegmentText({ segment, seek }: { segment: Segment; seek: (time: number) => void }) {
  const words = timedWords(segment);
  const wordButtons = words.map((word, index) => <button type="button" className="word" key={index}
    title={`Seek to ${word.start.toFixed(2)}s${word.confidence !== null && word.confidence < .5 ? ' · Low ASR probability' : ''}`}
    onClick={() => seek(word.start)}>{word.text}</button>);
  // Even unedited ASR segment text can differ from concatenated word text.
  const exactWords = words.map(w => w.text).join('') === segment.text;
  return <>
    <p className="transcript">{!segment.edited && exactWords && words.length ? wordButtons
      : <button type="button" className="segment-text" onClick={() => seek(segment.start)}>{segment.text || '(Empty text)'}</button>}</p>
    {(segment.edited || (words.length > 0 && !exactWords)) && <details>
      <summary>Original ASR text{words.length > 0 ? ' and timed words' : ''}</summary>
      <p className="transcript">{segment.raw_text || '(Empty text)'}</p>
      {words.length > 0 && <p className="transcript">{wordButtons}</p>}
    </details>}
  </>;
}

export default function TranscriptReview({ projectId, revision, busy }: {
  projectId: string; revision: string; busy: boolean;
}) {
  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [time, setTime] = useState(0);
  const [reload, setReload] = useState(0);
  const [cutRevision, setCutRevision] = useState(0);
  const cutsChanged = useCallback(() => setCutRevision(n => n + 1), []);
  const captionState = useCaptionPlan(projectId, JSON.stringify([revision, review, cutRevision, saving, reload]));
  const emphasisPlan = useEmphasisPlan(projectId, JSON.stringify([revision, review, cutRevision, saving, reload]));
  const video = useRef<HTMLVideoElement>(null);
  const generation = useRef(0);
  const savingRef = useRef(false);
  const base = `${API}/projects/${projectId}/transcript`;

  useEffect(() => {
    const controller = new AbortController();
    const current = ++generation.current;
    const timeout = setTimeout(() => controller.abort(), 15000);
    setLoading(true); setError(''); setEditId(null);
    async function load() {
      try {
        const response = await fetch(`${base}/review`, { signal: controller.signal, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error?.message ?? 'Transcript could not be loaded.');
        if (generation.current === current) setReview(body as Review);
      } catch (failure) {
        if (generation.current === current) {
          setReview(null);
          setError(controller.signal.aborted ? 'Transcript request timed out. Try Reload transcript.'
            : failure instanceof Error ? failure.message : 'Transcript could not be loaded.');
        }
      } finally {
        clearTimeout(timeout);
        if (generation.current === current) setLoading(false);
      }
    }
    void load();
    return () => { clearTimeout(timeout); controller.abort(); generation.current++; };
  }, [base, revision, reload]);

  async function change(action: 'save' | 'reset' | 'reset-all', segmentId?: string) {
    if (!review || savingRef.current || busy || loading) return;
    savingRef.current = true; setSaving(true); setError('');
    const current = ++generation.current;
    const endpoint = action === 'reset-all' ? '/overrides/reset'
      : `/overrides/${segmentId}${action === 'reset' ? '/reset' : ''}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(base + endpoint, {
        method: action === 'save' ? 'PUT' : 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-Media-Import': '1' },
        body: JSON.stringify({ source_transcript_checksum: review.source_transcript_checksum,
          ...(action === 'save' ? { text: draft } : {}) }),
      });
      const body = await response.json();
      if (!response.ok) {
        if (response.status === 409 && body.error?.code !== 'job_busy') setReload(r => r + 1);
        throw new Error(body.error?.message ?? 'Corrections could not be saved.');
      }
      if (generation.current === current) { setReview(body as Review); setEditId(null); }
    } catch (failure) {
      if (generation.current === current) setError(controller.signal.aborted
        ? 'Save timed out. Reload transcript to check whether it was saved.'
        : failure instanceof Error ? failure.message : 'Save failed. Reload to verify saved state.');
    } finally {
      clearTimeout(timeout); savingRef.current = false; setSaving(false);
    }
  }

  function seek(seconds: number) {
    seekVideo(video.current, seconds);
    if (video.current) setTime(video.current.currentTime);
  }
  const active = activeSegment(review?.segments ?? [], time);
  const blocked = loading || saving || busy;
  const invalid = review?.override_state === 'stale' || review?.override_state === 'invalid';

  return <div className="review-layout">
    <div className="proxy-preview">
    <div className="proxy-frame">
    <video ref={video} controls preload="metadata" src={`${API}/projects/${projectId}/proxy`}
      onTimeUpdate={event => setTime(event.currentTarget.currentTime)}
      onSeeking={event => setTime(event.currentTarget.currentTime)}
      onSeeked={event => setTime(event.currentTarget.currentTime)} />
    <CaptionOverlay plan={saving || loading || busy ? null : captionState.plan} emphasis={emphasisPlan} time={time} />
    </div>
    <CaptionStatus {...captionState} />
    </div>
    <section className="transcript-panel" aria-label="Transcript review">
      <h2>Transcript review</h2>
      <button disabled={loading || saving} onClick={() => setReload(r => r + 1)}>Reload transcript</button>
      {loading && <p role="status">Loading transcript…</p>}
      {error && <p role="alert">{error}</p>}
      {review && <>
        <p>Detected language: {review.language}</p>
        <p className="diagnostic">Timing: {review.timing_quality.replaceAll('_', ' ')}. Seeking is approximate.</p>
        {review.override_message && <p role="alert">{review.override_message}</p>}
        <button disabled={blocked || (!invalid && !review.segments.some(s => s.edited))}
          onClick={() => void change('reset-all')}>Reset All Corrections</button>
        {!review.segments.length && <p>No speech detected.</p>}
        <ol className="segments">
          {review.segments.map(segment => <li key={segment.segment_id}
            className={active === segment.segment_id ? 'segment active' : 'segment'}
            aria-current={active === segment.segment_id ? 'true' : undefined}>
            <button className="segment-time" onClick={() => seek(segment.start)}
              aria-label={`Seek segment ${Number(segment.segment_id) + 1} to ${segment.start.toFixed(2)} seconds`}>
              {segment.start.toFixed(2)}–{segment.end.toFixed(2)}s</button>
            {segment.edited && <span className="edited">Edited</span>}
            <SegmentText segment={segment} seek={seek} />
            {editId === segment.segment_id ? <form onSubmit={event => { event.preventDefault(); void change('save', segment.segment_id); }}>
              <label htmlFor={`edit-${segment.segment_id}`}>Segment text</label>
              <textarea id={`edit-${segment.segment_id}`} value={draft} maxLength={10000} disabled={blocked}
                onChange={event => setDraft(event.target.value)} />
              <button disabled={blocked || invalid} type="submit">Save</button>
              <button type="button" disabled={saving} onClick={() => setEditId(null)}>Cancel</button>
            </form> : <button disabled={blocked || invalid} onClick={() => { setEditId(segment.segment_id); setDraft(segment.text); }}>Edit</button>}
            {segment.edited && <button disabled={blocked || invalid} onClick={() => void change('reset', segment.segment_id)}>Reset Segment</button>}
          </li>)}
        </ol>
      </>}
    </section>
    <CutReview projectId={projectId} revision={revision} busy={busy} seek={seek} onChange={cutsChanged} />
  </div>;
}
