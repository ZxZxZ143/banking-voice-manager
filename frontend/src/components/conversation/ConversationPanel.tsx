import { useState, type FormEvent } from 'react';
import type { ConversationRuntime, ConversationSnapshot } from '../../runtime/ConversationRuntime';
import { VoiceControls } from '../voice/VoiceControls';

interface Props {
  runtime: ConversationRuntime;
  snapshot: ConversationSnapshot;
}

export function ConversationPanel({ runtime, snapshot }: Props) {
  const [text, setText] = useState('');
  const ready = snapshot.runtimeStatus === 'listening';

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || !text.trim()) return;
    void runtime.sendText(text);
    setText('');
  }

  return (
    <section className="panel" aria-labelledby="conversation-title">
      <h2 id="conversation-title">Диалог с клиентом</h2>
      <div className="controls">
        <button type="button" onClick={() => { void runtime.startConversation(); }}
          disabled={!['idle', 'error'].includes(snapshot.runtimeStatus)
            || snapshot.conversationStatus === 'ended' || snapshot.conversationStatus === 'handoff'}>
          Начать разговор
        </button>
        <button type="button" onClick={() => { void runtime.endConversation(); }}
          disabled={['idle', 'ended'].includes(snapshot.runtimeStatus)}>
          Завершить
        </button>
        <button type="button" onClick={() => { void runtime.resetConversation(); setText(''); }}>
          Сбросить
        </button>
      </div>
      <p role="status">Состояние: {snapshot.runtimeStatus} · диалог: {snapshot.conversationStatus ?? '—'}</p>
      <p className="muted debug-id">session_id: {snapshot.sessionId ?? 'создаётся при старте'}</p>
      {snapshot.sttLatencyMs != null && <p className="muted">STT: {snapshot.sttLatencyMs} ms</p>}
      {snapshot.error && <p className="error" role="alert">{snapshot.error}</p>}
      <div className="history" aria-label="История разговора">
        {snapshot.messages.length === 0 ? <p className="empty-state">История пуста.</p> : (
          snapshot.messages.map((message) => (
            <p key={message.id}><strong>{message.role === 'user' ? 'Клиент' : 'Ассистент'}:</strong> {message.text}</p>
          ))
        )}
      </div>
      <form onSubmit={handleSubmit}>
        <label htmlFor="utterance">Текст клиента (отладочный ввод)</label>
        <textarea id="utterance" rows={3} value={text} onChange={(event) => setText(event.target.value)}
          placeholder="Введите запрос на русском или казахском" maxLength={10_000} disabled={!ready} />
        <button type="submit" disabled={!ready || !text.trim()}>Отправить</button>
      </form>
      <VoiceControls />
    </section>
  );
}
