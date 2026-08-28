import { useEffect, useRef, useState } from 'react';
import { decisionLabel } from './cuts.js';
import type { Candidate, CutReviewData } from './cuts.js';
const API = 'http://127.0.0.1:8000';

export function CandidateRow({ candidate, blocked, change, seek }: {
  candidate: Candidate; blocked: boolean;
  change: (action: 'accept' | 'reject' | 'reset', id: string) => void; seek: (time: number) => void;
}) {
  return <li className="cut-candidate">
    <p>{candidate.start.toFixed(3)}–{candidate.end.toFixed(3)}s · {(candidate.end - candidate.start).toFixed(3)}s
      {' · '}{candidate.reason} · <strong>{decisionLabel(candidate.decision)}</strong></p>
    <button onClick={() => seek(candidate.start)}>Seek start</button>
    <button onClick={() => seek(candidate.end)}>Seek end</button>
    <button disabled={blocked} onClick={() => change('accept', candidate.cut_id)}>Accept</button>
    <button disabled={blocked} onClick={() => change('reject', candidate.cut_id)}>Reject</button>
    <button disabled={blocked || candidate.decision === 'pending'} onClick={() => change('reset', candidate.cut_id)}>Reset decision</button>
  </li>;
}

export default function CutReview({ projectId, revision, busy, seek, onChange }: {
  projectId: string; revision: string; busy: boolean; seek: (time: number) => void; onChange?: () => void;
}) {
  const [review, setReview] = useState<CutReviewData | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [reload, setReload] = useState(0);
  const generation = useRef(0);
  const savingRef = useRef(false);
  const base = `${API}/projects/${projectId}/cuts`;
  useEffect(() => {
    const controller = new AbortController();
    const current = ++generation.current;
    const timeout = setTimeout(() => controller.abort(), 15000);
    setLoading(true); setReview(null); setError('');
    void (async () => {
      try {
        const response = await fetch(base + '/review', { signal: controller.signal, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error?.message ?? 'Smart Cuts could not be loaded.');
        if (generation.current === current) setReview(body);
      } catch (failure) {
        if (generation.current === current) setError(controller.signal.aborted ? 'Smart Cuts request timed out. Reload to retry.'
          : failure instanceof Error ? failure.message : 'Smart Cuts could not be loaded.');
      } finally {
        clearTimeout(timeout);
        if (generation.current === current) { setLoading(false); onChange?.(); }
      }
    })();
    return () => { clearTimeout(timeout); controller.abort(); generation.current++; };
  }, [base, revision, reload, onChange]);

  async function change(action: 'accept' | 'reject' | 'reset' | 'reset-all', id?: string) {
    if (!review || busy || loading || savingRef.current) return;
    savingRef.current = true; setSaving(true); setError('');
    const current = ++generation.current;
    const endpoint = action === 'reset-all' ? '/overrides/reset'
      : `/overrides/${id}${action === 'reset' ? '/reset' : ''}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(base + endpoint, {
        method: action === 'accept' || action === 'reject' ? 'PUT' : 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-Media-Import': '1' },
        body: JSON.stringify({ source_cuts_checksum: review.source_cuts_checksum,
          ...((action === 'accept' || action === 'reject') ? { action } : {}) }),
      });
      const body = await response.json();
      if (!response.ok) {
        if (response.status === 409 && body.error?.code !== 'job_busy') setReload(n => n + 1);
        throw new Error(body.error?.message ?? 'Decision could not be saved.');
      }
      if (generation.current === current) setReview(body);
    } catch (failure) {
      if (generation.current === current) setError(controller.signal.aborted
        ? 'Save timed out. Reload Smart Cuts to verify whether it was saved.'
        : failure instanceof Error ? failure.message : 'Save failed. Reload to verify.');
    } finally { clearTimeout(timeout); savingRef.current = false; setSaving(false); onChange?.(); }
  }
  const invalid = review?.override_state === 'stale' || review?.override_state === 'invalid';
  return <section className="cuts-panel" aria-label="Smart Cuts review">
    <h2>Smart Cuts</h2>
    <p>Proposals only. Pending and rejected intervals stay in the effective plan. Only accepted proposals shorten it.
      Video playback remains original and unchanged.</p>
    <button disabled={loading || saving} onClick={() => setReload(n => n + 1)}>Reload Smart Cuts</button>
    {loading && <p role="status">Loading Smart Cuts…</p>}
    {error && <p role="alert">{error}</p>}
    {review && <>
      <p className="cut-durations">Estimated original: {review.effective.source_duration.toFixed(3)}s · effective: {review.effective.effective_duration.toFixed(3)}s
        {' · '}removed: {review.effective.time_removed.toFixed(3)}s</p>
      {review.warnings.map(w => <p role="alert" key={w}>{w}</p>)}
      {review.override_message && <p role="alert">{review.override_message}</p>}
      <button disabled={busy || loading || saving || (!invalid && review.candidates.every(c => c.decision === 'pending'))}
        onClick={() => void change('reset-all')}>Reset All Decisions</button>
      {!review.candidates.length && <p>No conservative silence candidates found.</p>}
      <ol>{review.candidates.map(candidate => <CandidateRow key={candidate.cut_id} candidate={candidate}
        blocked={busy || loading || saving || invalid} seek={seek} change={(a, id) => void change(a, id)} />)}</ol>
    </>}
  </section>;
}
