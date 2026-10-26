'use client';

import { useEffect, useRef, useState } from 'react';
import s from './dashboard.module.css';

const INTRO = 'Hello! I am your ED Clinical Copilot. I can assist you with patient vitals, ward deterioration trends, NEWS2 scores, and clinical care guidelines. How can I help?';
const PROMPTS = [
  ['Ward Patients Status', 'Summarize all assessed patients and their risk levels.'],
  ['High Risk Summary', 'List all High Risk patients in the ward.'],
  ['Sepsis Guidelines', 'What are the warning signs of sepsis in ED patients?'],
];

const stripBold = (t) => t.trim().replace(/\*\*/g, '');

function Table({ rows }) {
  const clean = rows.filter((r) => !r.every((cell) => /^[:\s-]+$/.test(cell.trim())));
  if (!clean.length) return null;
  const [head, ...body] = clean;
  return (
    <div className="table-scroll" style={{ margin: '0.6rem 0' }}>
      <table className="data-table">
        <thead><tr>{head.map((c, i) => <th key={i}>{stripBold(c)}</th>)}</tr></thead>
        <tbody>{body.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{stripBold(c)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** Minimal renderer for the assistant's output: **bold** and pipe tables. */
function MessageBody({ text }) {
  const out = [];
  let table = [];
  const flush = (key) => {
    if (table.length) out.push(<Table key={key} rows={table} />);
    table = [];
  };
  text.split('\n').forEach((line, i) => {
    const t = line.trim();
    if (t.startsWith('|') && t.endsWith('|')) {
      table.push(t.split('|').slice(1, -1));
      return;
    }
    flush(`t${i}`);
    if (!t) { out.push(<div key={i} style={{ height: '0.35rem' }} />); return; }
    out.push(
      <div key={i} className={s.msgLine}>
        {line.split(/(\*\*.*?\*\*)/g).map((part, j) => (
          part.startsWith('**') && part.endsWith('**') ? <strong key={j}>{part.slice(2, -2)}</strong> : part
        ))}
      </div>,
    );
  });
  flush('end');
  return out;
}

export default function ChatWidget({ authFetch, selectedPatient }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([{ sender: 'assistant', text: INTRO, ood: false }]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }); }, [messages, sending, open]);

  const send = async (override) => {
    const text = (override ?? input).trim();
    if (!text || sending) return;
    setMessages((m) => [...m, { sender: 'user', text }]);
    if (override == null) setInput('');
    setSending(true);
    let reply = { text: 'Network error connecting to chat service.', ood: false };
    try {
      const res = await authFetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, patient_id: selectedPatient?.patient_id || null }),
      });
      if (res.ok) {
        const data = await res.json();
        reply = { text: data.reply, ood: data.out_of_domain };
      } else {
        reply = { text: 'Error communicating with Clinical Chat Assistant.', ood: false };
      }
    } catch (err) {
      console.error('Chat error:', err);
    }
    setMessages((m) => [...m, { sender: 'assistant', ...reply }]);
    setSending(false);
  };

  if (!open) {
    return <button className={s.chatLauncher} onClick={() => setOpen(true)}>💬 CLINICAL COPILOT</button>;
  }

  return (
    <div className={s.chatPanel} role="dialog" aria-label="ED Clinical Copilot">
      <div className={s.chatHead}>
        <div>
          <div className={s.chatTitle}>ED CLINICAL COPILOT</div>
          <div className={s.subtle}>AI Clinical Decision Support & Ward Assistant</div>
        </div>
        <button className={s.chatClose} onClick={() => setOpen(false)} aria-label="Close chat">✕</button>
      </div>
      <div className={s.chatContext}>
        CONTEXT: <span style={{ color: selectedPatient ? 'var(--text-primary)' : undefined }}>
          {selectedPatient ? `${selectedPatient.name} (BED ${selectedPatient.bed_number})` : 'FULL WARD DATABASE'}
        </span>
      </div>
      <div className={s.chatMessages}>
        {messages.map((m, i) => (
          <div key={i} className={`${s.msg} ${m.sender === 'user' ? s.msgUser : m.ood ? s.msgOod : s.msgBot}`}>
            <MessageBody text={m.text} />
          </div>
        ))}
        {sending && <div className={s.subtle}>Analyzing ward data & guidelines...</div>}
        <div ref={endRef} />
      </div>
      <div className={s.chatPills}>
        {PROMPTS.map(([label, prompt]) => (
          <button key={label} className={s.pill} onClick={() => send(prompt)} disabled={sending}>{label}</button>
        ))}
      </div>
      <form className={s.chatForm} onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input className="input" placeholder="Ask about patient status, vitals, NEWS2..." value={input}
          onChange={(e) => setInput(e.target.value)} aria-label="Chat message" />
        <button type="submit" className="btn btn-solid" disabled={sending}>SEND</button>
      </form>
    </div>
  );
}
