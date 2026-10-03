import { useEffect } from 'react';
import { request } from './api';

const ACTIVITY_INTERVAL = 15000;

export function useIdleSession(session, onExpire) {
  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    let expiryTimer,
      activityTimer,
      deadline,
      pending = false,
      dirty = false,
      lastSent = 0,
      lastActivity = 0;
    const live = () => !controller.signal.aborted;
    const arm = (seconds) => {
      clearTimeout(expiryTimer);
      const remaining = Math.max(0, Math.min(seconds, 3600)) * 1000;
      deadline = Date.now() + remaining;
      expiryTimer = setTimeout(check, remaining);
    };
    const check = async () => {
      try {
        // A second tab may have been active. Reading the deadline never renews it.
        const result = await (await request('/session', { signal: controller.signal })).json();
        if (!live()) return;
        if (!result.role) onExpire();
        else arm(result.expires_at - result.server_time);
      } catch (error) {
        if (!live()) return;
        if (error.status === 401 || Date.now() >= deadline) onExpire();
        else arm((deadline - Date.now()) / 1000);
      }
    };
    const flush = async () => {
      activityTimer = undefined;
      if (!live() || pending || !dirty) return;
      dirty = false;
      pending = true;
      lastSent = Date.now();
      try {
        const age_ms = Math.min(60000, Math.max(0, Date.now() - lastActivity));
        await request('/session/activity', { body: { age_ms }, signal: controller.signal });
      } catch (error) {
        if (live() && error.status === 401) onExpire();
      } finally {
        pending = false;
        if (live() && dirty) schedule();
      }
    };
    const schedule = () => {
      if (pending || activityTimer !== undefined) return;
      activityTimer = setTimeout(flush, Math.max(0, lastSent + ACTIVITY_INTERVAL - Date.now()));
    };
    const activity = (event) => {
      if (!event.isTrusted || document.hidden || event.repeat) return;
      lastActivity = Date.now();
      dirty = true;
      schedule();
    };
    const expiry = (event) => arm(event.detail);
    const resume = () => {
      if (!document.hidden) check();
    };
    const events = ['pointerdown', 'keydown', 'input', 'wheel', 'touchmove'];
    for (const event of events) addEventListener(event, activity, { passive: true, capture: true });
    addEventListener('emby-session-expiry', expiry);
    document.addEventListener('visibilitychange', resume);
    arm(session.expires_at - session.server_time);
    return () => {
      controller.abort();
      clearTimeout(expiryTimer);
      clearTimeout(activityTimer);
      for (const event of events) removeEventListener(event, activity, { capture: true });
      removeEventListener('emby-session-expiry', expiry);
      document.removeEventListener('visibilitychange', resume);
    };
  }, [session, onExpire]);
}
