import { useCallback, useRef, useState } from 'react';
import { hasUsableDuration } from './useVideoPlayer';

interface ProgressBarProps {
  currentTime: number;
  duration: number;
  buffered: number;
  onSeek: (time: number) => void;
  onScrubbingChange: (scrubbing: boolean) => void;
  disabled?: boolean;
}

const formatTime = (seconds: number): string => {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

/**
 * The scrub bar, built on pointer events rather than <input type="range">.
 *
 * `setPointerCapture` is the point of the exercise: once the drag starts, this
 * element receives every move and the release even when the cursor leaves it.
 * The old range input listened for `mouseup` on itself, so a release anywhere
 * else never arrived and the component stayed stuck in "seeking" forever.
 * `pointercancel` is handled too, for the cases the browser aborts a gesture.
 */
export const ProgressBar: React.FC<ProgressBarProps> = ({
  currentTime,
  duration,
  buffered,
  onSeek,
  onScrubbingChange,
  disabled = false,
}) => {
  const trackRef = useRef<HTMLDivElement>(null);
  const [dragTime, setDragTime] = useState<number | null>(null);
  const seekable = hasUsableDuration(duration) && !disabled;

  // While dragging, the handle follows the pointer rather than the element.
  const shownTime = dragTime ?? currentTime;
  const percent = seekable ? Math.min(100, Math.max(0, (shownTime / duration) * 100)) : 0;
  const bufferedPercent = seekable ? Math.min(100, Math.max(0, (buffered / duration) * 100)) : 0;

  const timeFromEvent = useCallback(
    (clientX: number): number => {
      const track = trackRef.current;
      if (!track || !hasUsableDuration(duration)) return 0;
      const rect = track.getBoundingClientRect();
      if (rect.width === 0) return 0;
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      return ratio * duration;
    },
    [duration],
  );

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!seekable) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    const time = timeFromEvent(e.clientX);
    setDragTime(time);
    onScrubbingChange(true);
    onSeek(time);
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragTime === null || !seekable) return;
    const time = timeFromEvent(e.clientX);
    setDragTime(time);
    onSeek(time);
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (dragTime === null) return;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    onSeek(dragTime);
    setDragTime(null);
    onScrubbingChange(false);
  };

  // Keyboard seeking never went through the old mouse handlers at all, so it
  // could leave the seeking flag inconsistent. Here it is just a seek.
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!seekable) return;
    const step = e.shiftKey ? 10 : 5;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      onSeek(Math.min(duration, currentTime + step));
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      onSeek(Math.max(0, currentTime - step));
    } else if (e.key === 'Home') {
      e.preventDefault();
      onSeek(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      onSeek(duration);
    }
  };

  return (
    // flex-1 so the component fills the controls row: without it this wrapper
    // sizes to its two time labels and the track inside collapses to 0px wide.
    // min-w-0 lets it shrink below the labels' intrinsic width on narrow panes.
    <div className="flex flex-1 min-w-0 items-center gap-3">
      <span className="text-xs text-gray-400 font-mono w-12 text-right tabular-nums">
        {formatTime(shownTime)}
      </span>

      <div
        ref={trackRef}
        role="slider"
        tabIndex={seekable ? 0 : -1}
        aria-label="Video position"
        aria-valuemin={0}
        aria-valuemax={hasUsableDuration(duration) ? Math.floor(duration) : 0}
        aria-valuenow={Math.floor(shownTime)}
        aria-valuetext={`${formatTime(shownTime)} of ${formatTime(duration)}`}
        aria-disabled={!seekable}
        data-testid="seek-bar"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={handleKeyDown}
        className={`group relative flex-1 py-2 outline-none ${
          seekable ? 'cursor-pointer' : 'cursor-default'
        } focus-visible:ring-2 focus-visible:ring-accent-primary/70 rounded`}
      >
        {/* Track */}
        <div className="relative h-1.5 rounded-full bg-dark-600 overflow-hidden">
          {/* Buffered */}
          <div
            className="absolute inset-y-0 left-0 bg-dark-500 transition-[width] duration-300"
            style={{ width: `${bufferedPercent}%` }}
          />
          {/* Played */}
          <div
            className="absolute inset-y-0 left-0 bg-accent-primary"
            style={{ width: `${percent}%` }}
          />
        </div>

        {/* Handle: grows on hover, drag and keyboard focus */}
        <div
          className={`absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full
                      bg-accent-primary shadow transition-transform
                      ${dragTime !== null ? 'scale-125' : 'scale-0 group-hover:scale-100 group-focus-visible:scale-100'}`}
          style={{ left: `${percent}%` }}
        />
      </div>

      <span className="text-xs text-gray-400 font-mono w-12 tabular-nums">
        {formatTime(duration)}
      </span>
    </div>
  );
};
