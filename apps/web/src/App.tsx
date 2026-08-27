import { useEffect, useState } from 'react';

const API = 'http://127.0.0.1:8000';
type Project = { project_id: string; normalization_status: string; reused?: boolean; audio_status?: string };
type Job = { job_id: string; project_id: string; stage: string; status: string; progress: number; error: { message: string } | null; result_project_id: string | null; reused: boolean };
type Metadata = { width: number; height: number; duration_seconds: number; frame_rate: number; rotation_degrees: number };

async function readResponse(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message ?? body.detail?.[0]?.msg ?? 'Import request failed.');
  return body;
}

type Transcript = { language: string; segments: { text: string }[] };

type ApiStatus = 'Checking…' | 'Connected' | 'Disconnected';

export default function App() {
  const [status, setStatus] = useState<ApiStatus>('Checking…');

  const [busy, setBusy] = useState(false);
  const [filename, setFilename] = useState('');
  const [importState, setImportState] = useState('No video imported.');
  const [error, setError] = useState('');
  const [project, setProject] = useState<Project | null>(null);
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [activeId, setActiveId] = useState<string | null>(() => localStorage.getItem('current-project'));
  const [transcript, setTranscript] = useState<Transcript | null>(null);
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    if (!activeId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let loaded = '';
    async function poll() {
      try {
        const body = await readResponse(await fetch(`${API}/projects/${activeId}/jobs/latest`, { signal: controller.signal })) as Job | null;
        if (controller.signal.aborted) return;
        setJob(body);
        if (body) {
          const running = ['pending', 'running'].includes(body.status);
          setBusy(running);
          setImportState(`${body.stage} — ${body.status}${body.reused ? ' — reused verified artifacts' : ''}`);
        }
        // Media readiness is independent of the latest job (which may be a failed transcription).
        const source = await readResponse(await fetch(`${API}/projects/${activeId}`, { signal: controller.signal }));
        const outputId = source.reused_project_id ?? source.project_id;
        const finished = outputId === source.project_id ? source : await readResponse(await fetch(`${API}/projects/${outputId}`, { signal: controller.signal }));
        const revision = `${outputId}:${body?.job_id}:${body?.status}`;
        if (finished.normalization_status === 'completed' && revision !== loaded) {
          const details = await readResponse(await fetch(`${API}/projects/${outputId}/metadata`, { signal: controller.signal })) as Metadata;
          if (!controller.signal.aborted) { setProject(finished); setMetadata(details); }
          const response = await fetch(`${API}/projects/${outputId}/transcript`, { signal: controller.signal });
          const value = response.ok ? await response.json() as Transcript : null;
          if (!controller.signal.aborted) { setTranscript(value); loaded = revision; }
        }
        if (!body) {
          const source = await readResponse(await fetch(`${API}/projects/${activeId}`, { signal: controller.signal }));
          if (!controller.signal.aborted) {
            setImportState(source.normalization_status.replaceAll('_', ' '));
            if (source.error) setError(source.error.message);
          }
        }
      } catch { /* Keep polling through backend restarts. */ }
      if (!controller.signal.aborted) timer = setTimeout(poll, 750);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeId]);

  async function importVideo(file: File) {
    setActiveId(null); setJob(null); setTranscript(null);
    setBusy(true); setFilename(file.name); setError(''); setProject(null); setMetadata(null);
    setImportState('Creating project…');
    try {
      if (!/\.(mp4|mov)$/i.test(file.name)) throw new Error('Select an .mp4 or .mov video.');
      const created = await readResponse(await fetch(`${API}/projects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Media-Import': '1' },
        body: JSON.stringify({ filename: file.name, size_bytes: file.size, last_modified_ms: file.lastModified }),
      })) as Project;
      localStorage.setItem('current-project', created.project_id);
      setJob(null); setActiveId(created.project_id);
      setImportState('Uploading…');
      const started = await readResponse(await fetch(`${API}/projects/${created.project_id}/source?background=true`, {
        method: 'PUT', headers: { 'Content-Type': 'application/octet-stream', 'X-Media-Import': '1' }, body: file,
      })) as Job;
      setJob(started);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Import failed.');
      setImportState('Import failed.');
      setBusy(false);
    }
  }

  async function startTranscription() {
    if (!activeId) return;
    setError(''); setBusy(true);
    try {
      const next = await readResponse(await fetch(`${API}/projects/${activeId}/jobs`, {
        method: 'POST', headers: { 'X-Media-Import': '1', 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage: 'transcribe' }),
      })) as Job;
      setJob(next);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Transcription request failed.');
      setBusy(false);
    }
  }

  async function jobAction(action: 'cancel' | 'retry') {
    if (!job) return;
    try {
      setError('');
      const next = await readResponse(await fetch(`${API}/projects/${job.project_id}/jobs/${job.job_id}/${action}`, {
        method: 'POST', headers: { 'X-Media-Import': '1' },
      })) as Job;
      setJob(next); setBusy(true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Job request failed.'); }
  }

  useEffect(() => {
    let disposed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController;

    async function checkHealth() {
      controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 3000);
      try {
        const response = await fetch('http://127.0.0.1:8000/health', {
          signal: controller.signal,
          cache: 'no-store',
          credentials: 'omit',
        });
        if (!response.ok) throw new Error('Health request failed');
        const body: unknown = await response.json();
        const healthy = typeof body === 'object' && body !== null
          && 'status' in body && body.status === 'ok'
          && 'service' in body && body.service === 'personal-ai-video-editor-api';
        if (!disposed) setStatus(healthy ? 'Connected' : 'Disconnected');
      } catch {
        if (!disposed) setStatus('Disconnected');
      } finally {
        clearTimeout(timeout);
        if (!disposed) retry = setTimeout(checkHealth, 5000);
      }
    }

    void checkHealth();
    return () => {
      disposed = true;
      clearTimeout(retry);
      controller.abort();
    };
  }, []);

  return (
    <main>
      <h1>Personal AI Video Editor</h1>
      <p>Phase 04 — Transcription Engine</p>
      <p role="status">API Status: {status}</p>
      <section aria-label="Video import">
        <label htmlFor="video-input">Import Video</label>
        <input id="video-input" type="file" accept=".mp4,.mov" disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = '';
            if (file) void importVideo(file);
          }} />
        {filename && <p>File: {filename}</p>}
        <p role="status" aria-live="polite">{importState}</p>
        {activeId && <p>Import project: <code>{activeId}</code></p>}
        {job && <>
          <p>Job: <code>{job.job_id}</code> · {job.stage} · {job.status} · {Math.round(job.progress * 100)}%</p>
          <progress max={1} value={job.progress} aria-label="Job progress" />
          {['pending', 'running'].includes(job.status) && <button onClick={() => void jobAction('cancel')}>Cancel</button>}
          {['failed', 'interrupted', 'cancelled'].includes(job.status) && <button onClick={() => void jobAction('retry')}>Retry</button>}
        </>}
        {(error || job?.error?.message) && <p role="alert">{error || job?.error?.message}</p>}
        {project && metadata && <>
          <p>Project: <code>{project.project_id}</code></p>
          <p>Source: {metadata.width} × {metadata.height} · {metadata.duration_seconds.toFixed(2)} seconds
            {' · '}{metadata.frame_rate.toFixed(2)} fps · rotation {metadata.rotation_degrees}°</p>
          {project.audio_status === 'no_audio' && <p>No audio stream: video is ready; audio.wav was not created.</p>}
          {project.audio_status === 'available' && <button disabled={busy} onClick={() => void startTranscription()}>Transcribe</button>}
          {transcript && <section aria-label="Transcript">
            <p>Detected language: {transcript.language}</p>
            <p className="transcript">{transcript.segments.length ? transcript.segments.map(s => s.text).join('') : 'No speech detected.'}</p>
          </section>}
          <video key={project.project_id} controls preload="metadata" src={`${API}/projects/${project.project_id}/proxy`} />
        </>}
      </section>
    </main>
  );
}
