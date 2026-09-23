export function VoiceControls() {
  return (
    <section className="voice-controls" aria-labelledby="voice-title">
      <h3 id="voice-title">Голосовой ввод и ответ</h3>
      <button type="button" disabled aria-describedby="voice-status">Микрофон</button>
      <p id="voice-status" className="muted">
        Голосовой ввод пока не подключён. Ответы озвучивает браузер.
      </p>
    </section>
  );
}
