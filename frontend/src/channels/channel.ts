/** The two supported user channels; identity never controls Agent business decisions. */
export type Channel = 'web' | 'phone';

export interface ChannelContext {
  readonly channel: Channel;
  readonly metadata?: Record<string, unknown>;
}
