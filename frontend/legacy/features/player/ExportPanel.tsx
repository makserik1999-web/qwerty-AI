import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DownloadIcon } from './icons';
import { ExportType, useExportJob } from './useExportJob';

interface ExportPanelProps {
  messageId: string | null;
  duration: number;
  currentTime: number;
  videoWidth: number;
  videoHeight: number;
  onClose: () => void;
  onPreviewSeek: (time: number) => void;
}

const MAX_CLIP_SEC = 15;
const FPS_CHOICES = [10, 15, 20];
const WIDTH_CHOICES = [320, 480, 640, 800];

/**
 * Rough size before encoding, so the choice between formats is informed.
 *
 * Bits per pixel, measured on this product's own output rather than taken
 * from a general rule of thumb: a 5s/480px/15fps fragment comes out at 136KB
 * as a GIF and 21KB as an mp4, because Manim animation is mostly flat colour
 * and compresses several times better than camera footage would.
 *
 * Content still varies - a busy scene encodes larger - so these stay
 * estimates, shown with a "~" and replaced by the real number the moment the
 * encode finishes.
 */
const BITS_PER_PIXEL = { clip: 0.018, gif: 0.11 } as const;

const estimateBytes = (
  format: 'gif' | 'clip',
  seconds: number,
  width: number,
  aspect: number,
  fps: number,
): number => {
  const height = Math.round(width / (aspect || 16 / 9));
  const frames = Math.max(seconds, 0) * fps;
  return (width * height * frames * BITS_PER_PIXEL[format]) / 8;
};

export const formatBytes = (bytes: number): string => {
  if (bytes <= 0) return '0 KB';
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const formatTime = (seconds: number): string => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

/**
 * Cutting a fragment out of the video as an animated GIF or an mp4 clip.
 *
 * Both formats are equally visible buttons, on purpose. mp4 is preselected
 * because it is roughly ten times smaller at better quality, but GIF is what
 * people actually ask for - it pastes into a chat and plays by itself - so it
 * is a peer here rather than an option hidden behind "advanced".
 */
export const ExportPanel: React.FC<ExportPanelProps> = ({
  messageId,
  duration,
  currentTime,
  videoWidth,
  videoHeight,
  onClose,
  onPreviewSeek,
}) => {
  const usable = Number.isFinite(duration) && duration > 0;
  const [range, setRange] = useState(() => {
    const start = Math.max(0, Math.min(currentTime, Math.max(0, duration - 1)));
    return { start, end: Math.min(duration, start + 5) };
  });
  const [format, setFormat] = useState<'clip' | 'gif'>('clip');
  const [fps, setFps] = useState(15);
  const [width, setWidth] = useState(640);
  const [loop, setLoop] = useState(true);
  const [caption, setCaption] = useState('');

  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef<'start' | 'end' | null>(null);
  const { job, error, isBusy, start, reset } = useExportJob();

  const aspect = videoWidth && videoHeight ? videoWidth / videoHeight : 16 / 9;
  const selected = Math.max(0, range.end - range.start);
  const tooLong = selected > MAX_CLIP_SEC;

  const estimates = useMemo(
    () => ({
      clip: estimateBytes('clip', selected, width, aspect, fps),
      gif: estimateBytes('gif', selected, width, aspect, fps),
    }),
    [selected, width, aspect, fps],
  );

  const timeFromEvent = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track || !usable) return 0;
      const rect = track.getBoundingClientRect();
      if (rect.width === 0) return 0;
      return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)) * duration;
    },
    [duration, usable],
  );

  const handlePointerDown = (handle: 'start' | 'end') => (e: React.PointerEvent) => {
    if (!usable) return;
    e.preventDefault();
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    draggingRef.current = handle;
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    const handle = draggingRef.current;
    if (!handle) return;
    const time = timeFromEvent(e.clientX);
    setRange((current) => {
      // The handles must not cross: a start after the end is an empty
      // selection the server would refuse, and it looks broken on the way.
      if (handle === 'start') {
        return { start: Math.min(time, current.end - 0.2), end: current.end };
      }
      return { start: current.start, end: Math.max(time, current.start + 0.2) };
    });
  };

  const endDrag = (e: React.PointerEvent) => {
    if (!draggingRef.current) return;
    const handle = draggingRef.current;
    draggingRef.current = null;
    if ((e.target as HTMLElement).hasPointerCapture?.(e.pointerId)) {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    }
    // Show the frame at whichever end was just moved, so the choice is visible.
    onPreviewSeek(handle === 'start' ? range.start : range.end);
  };

  // A new selection invalidates whatever was produced from the old one.
  useEffect(() => {
    reset();
  }, [range.start, range.end, format, fps, width, reset]);

  const startExport = () => {
    if (!messageId || tooLong || selected <= 0) return;
    start(format as ExportType, messageId, {
      start: Number(range.start.toFixed(3)),
      end: Number(range.end.toFixed(3)),
      fps,
      width,
      loop,
      caption,
    });
  };

  const startPercent = usable ? (range.start / duration) * 100 : 0;
  const endPercent = usable ? (range.end / duration) * 100 : 0;

  const chipClass = (active: boolean) =>
    `flex-1 px-4 py-3 rounded-xl border text-left transition-all ${
      active
        ? 'border-accent-primary bg-accent-primary/15 text-white'
        : 'border-dark-600 bg-dark-700 text-gray-300 hover:border-dark-500'
    }`;

  return (
    <div
      className="border-t border-dark-600 bg-dark-850 px-4 py-3"
      data-testid="export-panel"
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-white">Cut a fragment</h3>
        <button
          onClick={onClose}
          className="text-xs text-gray-400 hover:text-white"
          data-testid="export-close"
        >
          Close
        </button>
      </div>

      {/* Range on the timeline */}
      <div
        ref={trackRef}
        className="relative h-8 mb-2 select-none"
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div className="absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-dark-600" />
        <div
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-accent-primary/70"
          style={{ left: `${startPercent}%`, width: `${Math.max(0, endPercent - startPercent)}%` }}
          data-testid="export-selection"
        />
        {(['start', 'end'] as const).map((handle) => (
          <div
            key={handle}
            role="slider"
            tabIndex={0}
            aria-label={`Fragment ${handle}`}
            aria-valuemin={0}
            aria-valuemax={usable ? Math.floor(duration) : 0}
            aria-valuenow={Math.floor(handle === 'start' ? range.start : range.end)}
            data-testid={`export-handle-${handle}`}
            onPointerDown={handlePointerDown(handle)}
            className="absolute top-1/2 h-5 w-5 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize
                       rounded-full border-2 border-white bg-accent-primary shadow-lg
                       focus-visible:ring-2 focus-visible:ring-white"
            style={{ left: `${handle === 'start' ? startPercent : endPercent}%` }}
          />
        ))}
      </div>

      <div className="flex items-center justify-between text-xs mb-3">
        <span className="font-mono text-gray-400 tabular-nums">
          {formatTime(range.start)} - {formatTime(range.end)}
        </span>
        <span
          className={tooLong ? 'text-red-400 font-medium' : 'text-gray-400'}
          data-testid="export-length"
        >
          {selected.toFixed(1)}s{tooLong && ` - at most ${MAX_CLIP_SEC}s`}
        </span>
      </div>

      {/* Format: two peers, not a default and an alternative */}
      <div className="flex gap-2 mb-3">
        <button
          onClick={() => setFormat('clip')}
          className={chipClass(format === 'clip')}
          data-testid="export-format-clip"
          aria-pressed={format === 'clip'}
        >
          <div className="text-sm font-medium">MP4</div>
          <div className="text-xs opacity-70">~{formatBytes(estimates.clip)}</div>
        </button>
        <button
          onClick={() => setFormat('gif')}
          className={chipClass(format === 'gif')}
          data-testid="export-format-gif"
          aria-pressed={format === 'gif'}
        >
          <div className="text-sm font-medium">GIF</div>
          <div className="text-xs opacity-70">~{formatBytes(estimates.gif)}</div>
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-3 text-xs text-gray-400">
        <label className="flex items-center gap-1.5">
          fps
          <select
            value={fps}
            onChange={(e) => setFps(Number(e.target.value))}
            data-testid="export-fps"
            className="bg-dark-700 border border-dark-600 rounded-lg px-2 py-1 text-white"
          >
            {FPS_CHOICES.map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1.5">
          width
          <select
            value={width}
            onChange={(e) => setWidth(Number(e.target.value))}
            data-testid="export-width"
            className="bg-dark-700 border border-dark-600 rounded-lg px-2 py-1 text-white"
          >
            {WIDTH_CHOICES.map((v) => (
              <option key={v} value={v}>{v}px</option>
            ))}
          </select>
        </label>

        {format === 'gif' && (
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={loop}
              onChange={(e) => setLoop(e.target.checked)}
              className="accent-accent-primary"
            />
            loop
          </label>
        )}

        <input
          type="text"
          value={caption}
          onChange={(e) => setCaption(e.target.value.slice(0, 120))}
          placeholder="Caption (optional)"
          data-testid="export-caption"
          className="flex-1 min-w-[140px] bg-dark-700 border border-dark-600 rounded-lg px-2 py-1
                     text-white placeholder-gray-600"
        />
      </div>

      {error && (
        <p className="text-xs text-red-400 mb-2" data-testid="export-error">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={startExport}
          disabled={!messageId || tooLong || selected <= 0 || isBusy}
          data-testid="export-submit"
          className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${
            !messageId || tooLong || selected <= 0 || isBusy
              ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
              : 'bg-accent-primary hover:bg-accent-secondary text-white'
          }`}
        >
          {isBusy ? 'Encoding...' : `Make ${format === 'gif' ? 'GIF' : 'MP4'}`}
        </button>

        {isBusy && job && (
          <div className="flex-1 h-1.5 rounded-full bg-dark-600 overflow-hidden">
            <div
              className="h-full bg-accent-primary transition-[width] duration-500"
              style={{ width: `${Math.max(5, job.progress)}%` }}
              data-testid="export-progress"
            />
          </div>
        )}

        {job?.status === 'done' && job.download_url && (
          <a
            href={job.download_url}
            download
            data-testid="export-download"
            className="px-4 py-2 rounded-xl text-sm font-medium bg-green-600 hover:bg-green-500
                       text-white flex items-center gap-2"
          >
            <DownloadIcon />
            Save {formatBytes(job.output_bytes)}
          </a>
        )}
      </div>

      {!messageId && (
        <p className="text-xs text-gray-500 mt-2">
          Ask a question first - a fragment is cut from a video in this chat.
        </p>
      )}
    </div>
  );
};
