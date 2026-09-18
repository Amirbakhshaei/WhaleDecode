import { runDailyRecap } from "./dailyRecap.js";

const DAILY_UTC_HOUR = 14;

export function msUntilNext14Utc(now = new Date()): number {
  const next = new Date(now);
  next.setUTCHours(DAILY_UTC_HOUR, 0, 0, 0);
  if (next <= now) next.setUTCDate(next.getUTCDate() + 1);
  return next.getTime() - now.getTime();
}

export function startRecapCron(log: (m: string) => void = console.log): NodeJS.Timeout {
  let timer: NodeJS.Timeout | null = null;
  const schedule = (): void => {
    const delay = msUntilNext14Utc();
    log(`daily recap scheduled in ${Math.round(delay / 60000)}m (14:00 UTC)`);
    timer = setTimeout(async () => {
      try {
        const recap = await runDailyRecap();
        log(recap ? `daily recap published (${recap.eventCount} events)` : "daily recap: no events");
      } catch (err) {
        log(`daily recap failed: ${err instanceof Error ? err.message : err}`);
      } finally {
        schedule();
      }
    }, delay);
    timer.unref();
  };
  schedule();
  return timer!;
}
