'use client';

import { useEffect } from 'react';

/**
 * Route-segment error boundary: catches errors thrown while rendering the page or any
 * nested component that isn't already inside a ViewBoundary. (This Next.js version
 * passes `retry`, which re-fetches and re-renders the segment; `reset` only clears state.)
 */
export default function RouteError({ error, retry }) {
  useEffect(() => {
    console.error('[ED Monitor] Unhandled UI error:', error);
  }, [error]);

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem', padding: '1rem', textAlign: 'center' }}>
      <h2>Something went wrong</h2>
      <p style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono), monospace', maxWidth: 480 }}>
        The dashboard hit an unexpected error. Your session is unaffected.
        {error?.digest ? ` (ref: ${error.digest})` : ''}
      </p>
      <button className="btn btn-solid" onClick={() => retry()}>TRY AGAIN</button>
    </div>
  );
}
