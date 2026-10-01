/** Add channel IDs here; channel identity never controls Agent business decisions. */
export type Channel = 'web' | 'phone' | 'mobile';

export interface ChannelContext {
  readonly channel: Channel;
  readonly metadata?: Record<string, unknown>;
}
