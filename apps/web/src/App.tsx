import { useEffect, useState } from 'react';

const API = 'http://127.0.0.1:8000';
type Project = { project_id: string; normalization_status: string; reused?: boolean; audio_status?: string };
type Metadata = { width: number; height: number; duration_seconds: number; frame_rate: number; rotation_degrees: number };

async function readResponse(response: Response) {
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message ?? body.detail?.[0]?.msg ?? 'Import request failed.');
  return body;
}

type ApiStatus = 'Checking…' | 'Connected' | 'Disconnected';

export default function App() {
  const [status, setStatus] = useState<ApiStatus>('Checking…');

  const [busy, setBusy] = useState(false);
  const [filename, setFilename] = useState('');
  const [importState, setImportState] = useState('No video imported.');
  const [error, setError] = useState('');
  const [project, setProject] = useState<Project | null>(null);
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  useEffect(() => {
    if (!activeId) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(`${API}/projects/${activeId}`, { signal: controller.signal });
        const body = await readResponse(response) as Project;
        if (!controller.signal.aborted) setImportState(body.normalization_status.replaceAll('_', ' '));
      } catch { /* The upload request reports errors; temporary polling errors can recover. */ }
      if (!controller.signal.aborted) timer = setTimeout(poll, 750);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [activeId]);

  async function importVideo(file: File) {
    setBusy(true); setFilename(file.name); setError(''); setProject(null); setMetadata(null);
    setImportState('Creating project…');
    try {
      if (!/\.(mp4|mov)$/i.test(file.name)) throw new Error('Select an .mp4 or .mov video.');
      const created = await readResponse(await fetch(`${API}/projects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Media-Import': '1' },
        body: JSON.stringify({ filename: file.name, size_bytes: file.size, last_modified_ms: file.lastModified }),
      })) as Project;
      setActiveId(created.project_id);
      setImportState('Uploading…');
      const finished = await readResponse(await fetch(`${API}/projects/${created.project_id}/source`, {
        method: 'PUT', headers: { 'Content-Type': 'application/octet-stream', 'X-Media-Import': '1' }, body: file,
      })) as Project;
      setActiveId(null);
      const details = await readResponse(await fetch(`${API}/projects/${finished.project_id}/metadata`)) as Metadata;
      setProject(finished); setMetadata(details);
      setImportState(finished.reused ? 'Success — reused verified normalized assets.' : 'Success — normalization completed.');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Import failed.');
      setImportState('Import failed.');
    } finally {
      setActiveId(null); setBusy(false);
    }
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
      <p>Phase 02 — Media Import and Normalization</p>
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
        {error && <p role="alert">{error}</p>}
        {project && metadata && <>
          <p>Project: <code>{project.project_id}</code></p>
          <p>Source: {metadata.width} × {metadata.height} · {metadata.duration_seconds.toFixed(2)} seconds
            {' · '}{metadata.frame_rate.toFixed(2)} fps · rotation {metadata.rotation_degrees}°</p>
          {project.audio_status === 'no_audio' && <p>No audio stream: video is ready; audio.wav was not created.</p>}
          <video key={project.project_id} controls preload="metadata" src={`${API}/projects/${project.project_id}/proxy`} />
        </>}
      </section>
    </main>
  );
}
