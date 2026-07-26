import { ResultRenderer } from '../ResultRenderer';

export function ChatMessage({ role, text, data }) {
  return (
    <div className={`chat-message chat-message-${role}`}>
      <div className="chat-bubble">
        {text && <p className="chat-text">{text}</p>}
        {data && <ResultRenderer data={data} hideNarrative />}
      </div>
    </div>
  );
}
