import Link from 'next/link';

export default function NotFound() {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '1rem' }}>
      <h2>404 — Page not found</h2>
      <Link href="/" className="btn btn-solid" style={{ padding: '0.6rem 1.2rem' }}>RETURN TO DASHBOARD</Link>
    </div>
  );
}
