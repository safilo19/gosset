import { useRef, useState } from 'react';
import { HELP_TEXT, parseCommand } from '../../chatParser';
import { useDataset } from '../../context/DatasetContext';
import { runAnalysis } from '../../runAnalysis';
import { ChatMessage } from './ChatMessage';

const WELCOME = `Hi! Upload a dataset in the Dashboard, then ask me things like:
- "describe the data"
- "correlation between units and revenue"
- "regression on revenue using units"
- "segment by recency, frequency, monetary"
- "forecast revenue for 6 periods"
- "plot units vs revenue"`;

export function ChatPanel() {
  const { dataset } = useDataset();
  const [messages, setMessages] = useState([{ id: 0, role: 'bot', text: WELCOME }]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const nextId = useRef(1);
  const scrollRef = useRef(null);

  function addMessage(msg) {
    const id = nextId.current++;
    setMessages((prev) => [...prev, { id, ...msg }]);
    requestAnimationFrame(() => {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
    });
  }

  async function handleSend(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput('');
    addMessage({ role: 'user', text });

    if (!dataset) {
      addMessage({ role: 'bot', text: 'Please upload a dataset in the Dashboard first, then ask me again.' });
      return;
    }

    const parsed = parseCommand(text, dataset);

    if (parsed.action === 'unknown' || parsed.action === 'error') {
      addMessage({ role: 'bot', text: parsed.message || HELP_TEXT });
      return;
    }

    setBusy(true);
    try {
      const data = await runAnalysis(parsed.action, dataset.dataset_id, parsed.params);
      const narrative = data.conclusion || data.interpretation || data.summary || 'Done — see result below.';
      addMessage({ role: 'bot', text: narrative, data });
    } catch (err) {
      addMessage({ role: 'bot', text: `Error: ${err.message}` });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chat-panel">
      <h2>Chat</h2>
      <div className="chat-history" ref={scrollRef}>
        {messages.map((m) => (
          <ChatMessage key={m.id} role={m.role} text={m.text} data={m.data} />
        ))}
        {busy && <ChatMessage role="bot" text="Working…" />}
      </div>
      <form className="chat-input-row" onSubmit={handleSend}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={dataset ? 'Ask about the data…' : 'Upload a dataset first…'}
        />
        <button type="submit" disabled={busy}>
          Send
        </button>
      </form>
    </div>
  );
}
