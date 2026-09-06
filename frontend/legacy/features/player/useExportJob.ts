import { useCallback, useEffect, useRef, useState } from 'react';

export type ExportType = 'gif' | 'clip' | 'frame' | 'pptx';

export interface ExportJob {
  job_id: string;
  type: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  progress: number;
  error: string;
  output_bytes: number;
  download_url?: string;
}

const POLL_INTERVAL_MS = 1000;
/**
 * Encoding is bounded server-side by EXPORT_JOB_TIMEOUT_SEC; this is the
 * client giving up somewhat later, so a wedged poll cannot spin forever if
 * the server never moves the job out of "running".
 */
const POLL_TIMEOUT_MS = 11 * 60 * 1000;

/**
 * Queue one export and follow it to completion.
 *
 * Polling rather than the chat WebSocket: an export is a request/response the
 * user is watching, not a push, and routing it through the socket would tie
 * the progress bar to a connection that reconnects on its own schedule.
 */
export const useExportJob = () => {
  const [job, setJob] = useState<ExportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const timerRef = useRef<number | null>(null);
  const deadlineRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // A panel closed mid-encode must not leave a timer running against a state
  // setter that no longer has a component behind it.
  useEffect(() => stopPolling, [stopPolling]);

  const poll = useCallback(
    async (jobId: string) => {
      if (Date.now() > deadlineRef.current) {
        setError('The export is taking too long. Try a shorter selection.');
        return;
      }
      try {
        const response = await fetch(`/api/export/${jobId}`, { credentials: 'include' });
        if (!response.ok) {
          setError('Lost track of the export.');
          return;
        }
        const next: ExportJob = await response.json();
        setJob(next);
        if (next.status === 'queued' || next.status === 'running') {
          timerRef.current = window.setTimeout(() => poll(jobId), POLL_INTERVAL_MS);
        } else if (next.status === 'failed') {
          setError(next.error || 'The export failed.');
        }
      } catch {
        setError('Lost track of the export.');
      }
    },
    [],
  );

  const start = useCallback(
    async (type: ExportType, messageId: string, params: Record<string, unknown>) => {
      stopPolling();
      setError(null);
      setJob(null);
      setIsStarting(true);
      try {
        const response = await fetch('/api/export', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ type, message_id: messageId, params }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
          // The server's message is the useful one: it names the actual limit
          // ("Select at most 15 seconds"), which a generic string would lose.
          setError(body.detail || 'Could not start the export.');
          return null;
        }
        deadlineRef.current = Date.now() + POLL_TIMEOUT_MS;
        setJob({
          job_id: body.job_id,
          type,
          status: 'queued',
          progress: 0,
          error: '',
          output_bytes: 0,
        });
        timerRef.current = window.setTimeout(() => poll(body.job_id), POLL_INTERVAL_MS);
        return body.job_id as string;
      } catch {
        setError('Could not reach the server.');
        return null;
      } finally {
        setIsStarting(false);
      }
    },
    [poll, stopPolling],
  );

  const reset = useCallback(() => {
    stopPolling();
    setJob(null);
    setError(null);
  }, [stopPolling]);

  const isBusy = isStarting || job?.status === 'queued' || job?.status === 'running';

  return { job, error, isBusy, start, reset };
};
