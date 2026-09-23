import { useState, type FormEvent } from 'react';
import { submitTextTurn } from '../../api/client';
import { VoiceControls } from '../voice/VoiceControls';

export function ConversationPanel({ sessionId }: { sessionId: string }) {
  const [text, setText] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim() || pending) return;
    setPending(true);
    setError(null);
    try {
      await submitTextTurn({ session_id: sessionId, text: text.trim() });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось отправить запрос.');
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="conversation-title">
      <h2 id="conversation-title">Диалог с клиентом</h2>
      <div className="empty-state">
        История пуста. Маршрутизация и ответы агента ещё не реализованы.
      </div>
      <form onSubmit={handleSubmit}>
        <label htmlFor="utterance">Текст клиента</label>
        <textarea
          id="utterance"
          rows={4}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Введите запрос на русском или казахском"
          aria-describedby="text-status"
          required
          maxLength={10_000}
          disabled={pending}
        />
        <p id="text-status" className="muted">
          Сейчас API возвращает 501 not_implemented. Текстовое поле проверяет соединение с ним.
        </p>
        <button type="submit" disabled={pending || !text.trim()}>
          {pending ? 'Отправка…' : 'Отправить текст'}
        </button>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      <VoiceControls sessionId={sessionId} onTranscript={setText} />
    </section>
  );
}
