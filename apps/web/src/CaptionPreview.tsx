import { useEffect, useState } from 'react';
import { activeCaption } from './captions.js';
import type { CaptionPlan, EmphasisPlan } from './captions.js';

export function useCaptionPlan(projectId: string, revision: string) {
  const [reload, setReload] = useState(0);
  const key = JSON.stringify([projectId, revision, reload]);
  const [result, setResult] = useState<{ key: string; plan: CaptionPlan | null; error: string } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    const timeout = setTimeout(() => controller.abort(), 15000);
    void (async () => {
      try {
        const response = await fetch(`http://127.0.0.1:8000/projects/${projectId}/captions`,
          { signal: controller.signal, cache: 'no-store' });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error?.message ?? 'Caption plan could not be loaded.');
        if (!disposed) setResult({ key, plan: body as CaptionPlan, error: '' });
      } catch (failure) {
        if (!disposed) setResult({ key, plan: null, error: controller.signal.aborted
          ? 'Caption request timed out. Reload captions to retry.'
          : failure instanceof Error ? failure.message : 'Caption plan could not be loaded.' });
      } finally { clearTimeout(timeout); }
    })();
    return () => { disposed = true; clearTimeout(timeout); controller.abort(); };
  }, [key, projectId]);
  // A revision change hides the prior snapshot during the very first render,
  // before effects run. A slow response cannot restore captions from old inputs.
  const current = result?.key === key ? result : null;
  return { plan: current?.plan ?? null, error: current?.error ?? '',
    loading: !current, reload: () => setReload(n => n + 1) };
}

export function useEmphasisPlan(projectId: string, revision: string) {
  const [result, setResult] = useState<{ key: string; plan: EmphasisPlan | null } | null>(null);
  const key = JSON.stringify([projectId, revision]);
  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    void fetch(`http://127.0.0.1:8000/projects/${projectId}/emphasis`,
      { signal: controller.signal, cache: 'no-store' }).then(async response => {
        if (!response.ok) return null;
        return await response.json() as EmphasisPlan;
      }).then(plan => { if (!disposed) setResult({ key, plan }); }).catch(() => {
        if (!disposed) setResult({ key, plan: null });
      });
    return () => { disposed = true; controller.abort(); };
  }, [key, projectId]);
  return result?.key === key ? result.plan : null;
}

export function CaptionOverlay({ plan, emphasis = null, time }: {
  plan: CaptionPlan | null; emphasis?: EmphasisPlan | null; time: number;
}) {
  const active = activeCaption(plan, time);
  const aggregate = active && emphasis?.caption_aggregates?.find(item => item.caption_id === active.caption_id);
  const decision = aggregate && emphasis?.decisions?.find(item => item.decision_id === aggregate.selected_decision_id);
  return active ? <div className="caption-overlay" data-caption-id={active.caption_id}>
    <span>{active.text}</span>
    {decision && <small className="emphasis-diagnostic">
      {decision.text} · {decision.behavior.toUpperCase()} · {decision.score.toFixed(2)} · E {decision.signals.energy.toFixed(2)} · P {decision.signals.pause.toFixed(2)} · D {decision.signals.duration.toFixed(2)}
    </small>}
  </div> : null;
}

export function CaptionStatus({ plan, error, loading, reload }: {
  plan: CaptionPlan | null; error: string; loading: boolean; reload: () => void;
}) {
  return <section className="caption-status" aria-label="Caption preview">
    <h2>Caption preview</h2>
    <p>HTML preview only · original proxy time · no video export.</p>
    <button disabled={loading} onClick={reload}>Reload captions</button>
    {loading && <p role="status">Loading captions…</p>}
    {error && <p role="alert">{error}</p>}
    {plan && <p>{plan.items.length} caption groups. Timing is approximate.</p>}
    {plan?.warnings.map((warning, i) => <p role="alert" key={i}>
      Segment {Number(warning.segment_id) + 1}: {warning.message}
    </p>)}
  </section>;
}
