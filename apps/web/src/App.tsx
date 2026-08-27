import { useEffect, useState } from 'react';

type ApiStatus = 'Checking…' | 'Connected' | 'Disconnected';

export default function App() {
  const [status, setStatus] = useState<ApiStatus>('Checking…');

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
      <p>Phase 01 — Local App Shell</p>
      <p role="status">API Status: {status}</p>
    </main>
  );
}
