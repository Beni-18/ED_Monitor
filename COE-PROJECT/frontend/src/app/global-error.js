'use client';

/**
 * Last-resort boundary for errors in the root layout itself. It replaces the layout
 * while active, so it must render its own <html>/<body> and cannot rely on global CSS.
 */
export default function GlobalError({ retry }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, minHeight: '100vh', background: '#000', color: '#fff', fontFamily: 'monospace', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem' }}>
        <h2>ED MONITOR — CRITICAL UI ERROR</h2>
        <p style={{ color: '#888' }}>The application failed to load. Please try again.</p>
        <button onClick={() => retry()} style={{ padding: '0.6rem 1.2rem', fontWeight: 'bold', cursor: 'pointer' }}>
          TRY AGAIN
        </button>
      </body>
    </html>
  );
}
