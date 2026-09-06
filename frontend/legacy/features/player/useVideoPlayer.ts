import { useCallback, useEffect, useRef, useState } from 'react';

export interface VideoPlayerState {
  isPaused: boolean;
  currentTime: number;
  duration: number;
  /** End of the first buffered range, in seconds. Drives the loading bar. */
  buffered: number;
  isLoaded: boolean;
  hasError: boolean;
  /** True between `seeking` and `seeked`, and while a drag is in progress. */
  isSeeking: boolean;
  isWaiting: boolean;
}

/** A duration is only usable once the metadata has actually arrived. */
export function hasUsableDuration(duration: number): boolean {
  return Number.isFinite(duration) && duration > 0;
}

/**
 * Owns everything about the <video> element's playback state.
 *
 * The previous implementation tracked seeking with a React flag that was
 * cleared by `onMouseUp` on the range input. Releasing the button anywhere
 * else - which happens constantly while dragging - left that flag stuck on,
 * and `timeupdate` then stopped writing `currentTime` forever, so the bar
 * froze while the video kept playing. Here the flag is driven by the video's
 * own `seeking`/`seeked` events plus an explicit scrub lock, so nothing can
 * strand it.
 */
export function useVideoPlayer(videoUrl: string | null) {
  const videoRef = useRef<HTMLVideoElement>(null);
  // While the user drags, the bar shows their position rather than the
  // element's - but this never blocks the state machine from recovering.
  const scrubbingRef = useRef(false);

  const [state, setState] = useState<VideoPlayerState>({
    isPaused: true,
    currentTime: 0,
    duration: 0,
    buffered: 0,
    isLoaded: false,
    hasError: false,
    isSeeking: false,
    isWaiting: false,
  });

  const patch = useCallback((next: Partial<VideoPlayerState>) => {
    setState((prev) => ({ ...prev, ...next }));
  }, []);

  // A new video resets everything, including a scrub left in flight.
  useEffect(() => {
    scrubbingRef.current = false;
    setState({
      isPaused: true,
      currentTime: 0,
      duration: 0,
      buffered: 0,
      isLoaded: false,
      hasError: false,
      isSeeking: false,
      isWaiting: false,
    });
  }, [videoUrl]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const readBuffered = () => {
      if (video.buffered.length === 0) return 0;
      // The range covering the playhead is the one worth showing.
      for (let i = 0; i < video.buffered.length; i += 1) {
        if (video.buffered.start(i) <= video.currentTime && video.currentTime <= video.buffered.end(i)) {
          return video.buffered.end(i);
        }
      }
      return video.buffered.end(video.buffered.length - 1);
    };

    const onLoadedMetadata = () => patch({ duration: video.duration, isLoaded: true, hasError: false });
    const onDurationChange = () => patch({ duration: video.duration });
    const onPlay = () => patch({ isPaused: false });
    const onPause = () => patch({ isPaused: true });
    const onError = () => patch({ hasError: true, isLoaded: false });
    const onWaiting = () => patch({ isWaiting: true });
    const onPlaying = () => patch({ isWaiting: false });
    const onProgress = () => patch({ buffered: readBuffered() });
    const onSeeking = () => patch({ isSeeking: true });
    const onSeeked = () =>
      patch({ isSeeking: scrubbingRef.current, currentTime: video.currentTime, isWaiting: false });
    const onTimeUpdate = () => {
      // Only the drag itself suppresses updates; a pending internal seek does
      // not, so the bar keeps tracking even if a `seeked` event is missed.
      if (scrubbingRef.current) return;
      patch({ currentTime: video.currentTime, buffered: readBuffered() });
    };
    const onEnded = () => patch({ isPaused: true });

    video.addEventListener('loadedmetadata', onLoadedMetadata);
    video.addEventListener('durationchange', onDurationChange);
    video.addEventListener('play', onPlay);
    video.addEventListener('pause', onPause);
    video.addEventListener('error', onError);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('playing', onPlaying);
    video.addEventListener('progress', onProgress);
    video.addEventListener('seeking', onSeeking);
    video.addEventListener('seeked', onSeeked);
    video.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('ended', onEnded);

    return () => {
      video.removeEventListener('loadedmetadata', onLoadedMetadata);
      video.removeEventListener('durationchange', onDurationChange);
      video.removeEventListener('play', onPlay);
      video.removeEventListener('pause', onPause);
      video.removeEventListener('error', onError);
      video.removeEventListener('waiting', onWaiting);
      video.removeEventListener('playing', onPlaying);
      video.removeEventListener('progress', onProgress);
      video.removeEventListener('seeking', onSeeking);
      video.removeEventListener('seeked', onSeeked);
      video.removeEventListener('timeupdate', onTimeUpdate);
      video.removeEventListener('ended', onEnded);
    };
    // Registered once per video: nothing here depends on changing state.
  }, [videoUrl, patch]);

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      // A rejected play() (autoplay policy, load error) must not go unhandled.
      void video.play().catch(() => patch({ isPaused: true }));
    } else {
      video.pause();
    }
  }, [patch]);

  const seekTo = useCallback((time: number) => {
    const video = videoRef.current;
    if (!video || !hasUsableDuration(video.duration)) return;
    const clamped = Math.min(Math.max(time, 0), video.duration);
    video.currentTime = clamped;
    patch({ currentTime: clamped });
  }, [patch]);

  const skip = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    seekTo(video.currentTime + seconds);
  }, [seekTo]);

  /** Called by the progress bar while a pointer drag is in progress. */
  const setScrubbing = useCallback((scrubbing: boolean) => {
    scrubbingRef.current = scrubbing;
    patch({ isSeeking: scrubbing });
  }, [patch]);

  return { videoRef, ...state, togglePlay, seekTo, skip, setScrubbing };
}
