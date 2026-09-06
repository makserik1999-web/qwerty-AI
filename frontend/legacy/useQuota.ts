import { useCallback, useEffect, useState } from 'react';

export interface Quota {
  used_hour: number;
  used_day: number;
  limit_hour: number;
  limit_day: number;
  remaining_hour: number;
  remaining_day: number;
}

/**
 * How many videos this account may still ask for.
 *
 * Refreshed after every answer rather than polled: the number only moves when
 * the user generates something, so a timer would spend requests to learn
 * nothing. Fetch failures are swallowed - a missing budget line is a small
 * loss, and the server refuses over-quota requests regardless of what the UI
 * believes.
 */
export const useQuota = (enabled: boolean) => {
  const [quota, setQuota] = useState<Quota | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    try {
      const response = await fetch('/api/quota', { credentials: 'include' });
      if (response.ok) setQuota(await response.json());
    } catch {
      // Keep whatever we last knew.
    }
  }, [enabled]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { quota, refreshQuota: refresh };
};

/**
 * Whether the remaining budget is worth showing.
 *
 * Shown only when it is running out. A counter that is always on screen turns
 * every question into a transaction; one that appears near the end is a
 * warning, which is what it is for.
 */
export const shouldShowQuota = (quota: Quota | null): boolean => {
  if (!quota) return false;
  return quota.remaining_hour <= 5 || quota.remaining_day <= 10;
};
