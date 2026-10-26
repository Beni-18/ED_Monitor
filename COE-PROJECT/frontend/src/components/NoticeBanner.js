import s from './dashboard.module.css';

export default function NoticeBanner({ notice }) {
  if (!notice) return null;
  const isError = notice.type === 'error';
  return (
    <div className={`${s.notice} ${isError ? s.noticeError : s.noticeSuccess}`} role={isError ? 'alert' : 'status'}>
      {isError ? '! ' : '✓ '}{notice.text}
    </div>
  );
}
