/** Content-free, monotonic, bounded diagnostics. No session IDs, text or audio. */
export type VoiceTimingName =
  | "tts.request"
  | "tts.first_audio"
  | "tts.end"
  | "input.prewarm"
  | "input.ready"
  | "input.active"
  | "speech.start"
  | "endpoint"
  | "realtime.final"
  | "bounded.final"
  | "candidate.ready"
  | "readback.first_audio"
  | "agent.first_audio"
  | "input.echo_rejected"
  | "input.preroll";
const samples: { event: VoiceTimingName; at: number; durationMs?: number }[] =
  [];
export function voiceTiming(event: VoiceTimingName, durationMs?: number) {
  const sample = {
    event,
    at: performance.now(),
    ...(durationMs !== undefined &&
    Number.isFinite(durationMs) &&
    durationMs >= 0
      ? { durationMs }
      : {}),
  };
  samples.push(sample);
  if (samples.length > 128) samples.shift();
  if (typeof window !== "undefined")
    window.dispatchEvent(new CustomEvent("voice-timing", { detail: sample }));
}
export function voiceTimings() {
  return samples.map((sample) => ({ ...sample }));
}
