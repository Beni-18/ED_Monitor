'use client';

import { catchError } from 'next/error';
import s from './dashboard.module.css';

/**
 * Component-level error boundary (Next.js `catchError`). Wrapping each dashboard view
 * means a rendering failure in one tab (e.g. a malformed API payload crashing a chart)
 * shows a recoverable message in that tab instead of blanking the whole application.
 * `retry()` re-renders the view inside a transition, preserving state outside the boundary.
 */
function ViewErrorFallback({ name }, { error, retry }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className={s.errorBox} role="alert">
      <h2 className={s.sectionTitle}>THE {name} VIEW FAILED TO RENDER</h2>
      <p className={s.subtle}>{message}</p>
      <button className="btn btn-solid" onClick={() => retry()}>TRY AGAIN</button>
    </div>
  );
}

export default catchError(ViewErrorFallback);
