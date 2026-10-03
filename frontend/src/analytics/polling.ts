/** One request at a time; schedule after settlement, abort on refresh/disposal. */
export function startPolling<T>(
  load: (signal: AbortSignal) => Promise<T>,
  events: {
    loading(): void;
    data(value: T): void;
    error(message: string): void;
  },
  intervalMs = 0,
  visible = () =>
    typeof document === "undefined" || document.visibilityState !== "hidden",
) {
  let stopped = false;
  let generation = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  function schedule() {
    if (!stopped && intervalMs > 0)
      timer = setTimeout(() => {
        if (visible()) void run();
        else schedule();
      }, intervalMs);
  }
  async function run() {
    if (stopped) return;
    clearTimeout(timer);
    controller?.abort();
    const current = ++generation;
    controller = new AbortController();
    events.loading();
    try {
      const value = await load(controller.signal);
      if (!stopped && current === generation) events.data(value);
    } catch (error) {
      if (!stopped && current === generation && !controller.signal.aborted)
        events.error(
          error instanceof Error ? error.message : "Analytics request failed.",
        );
    } finally {
      if (current === generation) schedule();
    }
  }
  void run();
  return {
    refresh: () => {
      void run();
    },
    stop: () => {
      stopped = true;
      generation++;
      clearTimeout(timer);
      controller?.abort();
    },
  };
}
