import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { ConversationRuntime, ConversationSnapshot } from '../../runtime/ConversationRuntime';
import type { ConversationStatus, RuntimeStatus } from '../../types/agent';
import type { TraceViewModel } from '../trace/traceViewModel';
import { VoiceControls } from '../voice/VoiceControls';
import { createVoiceInputController, type VoiceControlsHandle } from '../voice/voiceRuntimeBridge';
import { SalesLeadPanel } from './SalesLeadPanel';
import type { ScenarioPackId } from '../../types/agent';
import { isSalesPack, scenarioPackNames } from '../../types/agent';

interface Props {
  runtime: ConversationRuntime;
  snapshot: ConversationSnapshot;
  view: TraceViewModel;
}

const runtimeLabels: Record<RuntimeStatus, string> = {
  idle: 'Готов к началу', listening: 'Слушаем', processing: 'Обрабатываем',
  speaking: 'Ассистент говорит', handoff: 'Передаём диалог оператору…', ended: 'Завершён', error: 'Ошибка',
};

const conversationLabels: Record<ConversationStatus, string> = {
  active: 'Активен', awaiting_user: 'Ожидаем ответ клиента',
  awaiting_confirmation: 'Ожидаем подтверждение', handoff: 'Передача оператору', ended: 'Завершён',
};

export function ConversationPanel({ runtime, snapshot, view }: Props) {
  const [text, setText] = useState('');
  const voiceControls = useRef<VoiceControlsHandle | null>(null);
  const ready = snapshot.runtimeStatus === 'listening';
  const locallyStopped = snapshot.runtimeStatus === 'ended'
    && snapshot.conversationStatus !== 'ended' && snapshot.conversationStatus !== 'handoff';

  useEffect(() => {
    runtime.attachVoiceInput(createVoiceInputController(runtime, () => voiceControls.current));
    return () => runtime.attachVoiceInput(null);
  }, [runtime]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || !text.trim()) return;
    void runtime.sendText(text);
    setText('');
  }

  return (
    <section className="panel conversation-panel" aria-labelledby="conversation-title">
      <p className="eyebrow">Демонстрация звонка</p>
      <h2 id="conversation-title">Разговор</h2>
      <label htmlFor="scenario-pack">Бот и кампания звонка</label>
      <select id="scenario-pack" value={snapshot.requestedPack ?? snapshot.activePack}
        disabled={['processing', 'speaking', 'handoff', 'ended'].includes(snapshot.runtimeStatus)}
        onChange={(event) => runtime.selectScenarioPack(event.target.value as ScenarioPackId)}>
        <option value="insurance_manager">Insurance Manager</option>
        {(['product_promoter', 'card_promoter', 'loan_promoter'] as const).map(pack => (
          <option key={pack} value={pack} disabled={isSalesPack(snapshot.activePack)
            && snapshot.sessionId !== null && snapshot.activePack !== pack}>
            {scenarioPackNames[pack]}
          </option>
        ))}
      </select>
      <p className="muted">Оператор задаёт кампанию до звонка. Клиенту предлагается выбранный продукт.</p>
      <p><strong>Активный бот: {scenarioPackNames[snapshot.activePack]}</strong></p>
      {snapshot.requestedPack && <p className="muted">Следующий запрос переключит сценарий на {snapshot.requestedPack}.</p>}
      {snapshot.packNotice && <p role="status">{snapshot.packNotice}</p>}
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
      <label>
        <input type="checkbox" checked={snapshot.voiceInputEnabled}
          onChange={(event) => { void runtime.setVoiceInputEnabled(event.target.checked); }} />
        Голосовой ввод
      </label>
      {!snapshot.voiceInputEnabled && <p className="muted">Только текст: микрофон отключён. Диалог и озвучивание ответов сохраняются.</p>}
      <div className="status-line" role="status" aria-live="polite">
        <span className={`status-dot status-${snapshot.runtimeStatus}`} aria-hidden="true" />
        <strong>{locallyStopped ? 'Остановлен локально'
          : ready && !snapshot.voiceInputEnabled ? 'Ожидаем текст' : runtimeLabels[snapshot.runtimeStatus]}</strong>
        {snapshot.conversationStatus && <span>· {conversationLabels[snapshot.conversationStatus]}</span>}
      </div>
      {snapshot.conversationStatus === 'awaiting_confirmation' && (
        <div className="conversation-notice confirmation-notice">
          <strong>Требуется подтверждение</strong>
          {snapshot.lastResponse?.response_text && <p>{snapshot.lastResponse.response_text}</p>}
        </div>
      )}
      {snapshot.conversationStatus === 'awaiting_user' && (
        <div className="conversation-notice">
          <strong>{view.clarification ? 'Требуется уточнение' : 'Ожидаем ответ клиента'}</strong>
          {(view.clarification ?? snapshot.lastResponse?.response_text) && (
            <p>{view.clarification ?? snapshot.lastResponse?.response_text}</p>
          )}
        </div>
      )}
      {snapshot.conversationStatus === 'handoff' && (
        <div className="conversation-notice handoff-notice"><strong>Передаём диалог оператору…</strong>
          <p>Автоматический разговор завершён. История сохранена на экране.</p>
          {view.handoff?.queue && <p>Очередь: {view.handoff.queue}</p>}
        </div>
      )}
      {snapshot.conversationStatus === 'ended' && (
        <div className="conversation-notice"><strong>Разговор завершён</strong></div>
      )}
      {snapshot.error && <p className="error" role="alert">{snapshot.error}</p>}
      {isSalesPack(snapshot.activePack) && <SalesLeadPanel state={snapshot.latestState} />}
      <div className="history" aria-label="История разговора" aria-live="polite">
        {snapshot.messages.length === 0 ? <p className="empty-state">История пуста.</p> : (
          <ol className="message-list">{snapshot.messages.map((message) => (
            <li key={message.id} className={`message message-${message.role}`}>
              <span className="message-role">{message.role === 'user' ? 'Клиент' : 'Ассистент'}</span>
              <p>{message.text}</p>
            </li>
          ))}</ol>
        )}
      </div>
      <form onSubmit={handleSubmit}>
        <label htmlFor="utterance">Текст клиента (отладочный ввод)</label>
        <textarea id="utterance" rows={3} value={text} onChange={(event) => setText(event.target.value)}
          placeholder="Введите запрос на русском или казахском" maxLength={10_000} disabled={!ready} />
        <button type="submit" disabled={!ready || !text.trim()}>Отправить</button>
      </form>
      <p className="muted debug-id">session_id: {snapshot.sessionId ?? 'создаётся при старте'}</p>
      <VoiceControls ref={voiceControls} sessionId={snapshot.sessionId ?? ''} enabled={ready && snapshot.voiceInputEnabled}
        onTranscript={(transcript) => { void runtime.handleTranscript(transcript); }} />
    </section>
  );
}
