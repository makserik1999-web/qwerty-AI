import { useCallback, useEffect, useRef, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { PendingScreenshot } from '../../types';
import { AnnotationCanvas, AnnotationCanvasHandle, DrawingTool } from './AnnotationCanvas';
import { DeckButton } from './DeckButton';
import { ExportPanel } from './ExportPanel';
import { ProgressBar } from './ProgressBar';
import { hasUsableDuration, useVideoPlayer } from './useVideoPlayer';
import {
  CameraIcon,
  DownloadIcon,
  EraserIcon,
  NoVideoIcon,
  PauseIcon,
  PenIcon,
  PlayIcon,
  RedoIcon,
  ScissorsIcon,
  SkipBackIcon,
  SkipForwardIcon,
  TrashIcon,
  UndoIcon,
  WarningIcon,
} from './icons';

interface VideoPlayerProps {
  videoUrl: string | null;
  /**
   * The assistant message this video belongs to. Exports are addressed by
   * message rather than by file so the server can check the chat is yours -
   * a filename would be a bare capability anyone could guess.
   */
  messageId?: string | null;
  onScreenshotCapture: (screenshot: PendingScreenshot) => void;
}

const PEN_COLORS = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7', '#ffffff'];

export const VideoPlayer: React.FC<VideoPlayerProps> = ({
  videoUrl,
  messageId = null,
  onScreenshotCapture,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasHandle = useRef<AnnotationCanvasHandle>(null);

  const {
    videoRef,
    isPaused,
    currentTime,
    duration,
    buffered,
    isLoaded,
    hasError,
    isWaiting,
    togglePlay,
    seekTo,
    skip,
    setScrubbing,
  } = useVideoPlayer(videoUrl);

  // Draw mode is OFF by default and is toggled explicitly. Pausing the video
  // is not a request to draw - conflating the two is what made the brush
  // "turn itself on" and swallow clicks meant to resume playback.
  const [drawMode, setDrawMode] = useState(false);
  const [tool, setTool] = useState<DrawingTool>('pen');
  const [brushSize, setBrushSize] = useState(4);
  const [color, setColor] = useState(PEN_COLORS[0]);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [historyVersion, setHistoryVersion] = useState(0);
  const [exportOpen, setExportOpen] = useState(false);
  const [videoSize, setVideoSize] = useState({ width: 0, height: 0 });

  const onHistoryChange = useCallback(() => setHistoryVersion((v) => v + 1), []);

  useEffect(() => {
    setDrawMode(false);
    setHistoryVersion(0);
    setExportOpen(false);
  }, [videoUrl]);

  // Match the canvas to the letterboxed video box, not to the container.
  const updateCanvasSize = useCallback(() => {
    const video = videoRef.current;
    const container = containerRef.current;
    if (!video || !container || !video.videoWidth || !video.videoHeight) return;

    const rect = container.getBoundingClientRect();
    const videoAspect = video.videoWidth / video.videoHeight;
    const containerAspect = rect.width / rect.height;

    const width = videoAspect > containerAspect ? rect.width : rect.height * videoAspect;
    const height = videoAspect > containerAspect ? rect.width / videoAspect : rect.height;
    setCanvasSize({ width, height });
    setVideoSize({ width: video.videoWidth, height: video.videoHeight });
  }, [videoRef]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver(updateCanvasSize);
    observer.observe(container);
    return () => observer.disconnect();
  }, [updateCanvasSize]);

  useEffect(() => {
    if (isLoaded) updateCanvasSize();
  }, [isLoaded, updateCanvasSize]);

  const toggleDrawMode = useCallback(() => {
    setDrawMode((wasOn) => {
      // Turning drawing ON pauses the video, because annotating a moving
      // picture is meaningless. The reverse does NOT hold: pausing leaves
      // draw mode alone.
      if (!wasOn && videoRef.current && !videoRef.current.paused) {
        videoRef.current.pause();
      }
      return !wasOn;
    });
  }, [videoRef]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const active = document.activeElement;
      const isTyping =
        active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        active?.getAttribute('contenteditable') === 'true';
      if (isTyping || !videoUrl) return;

      const meta = e.ctrlKey || e.metaKey;
      if (meta && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        e.preventDefault();
        canvasHandle.current?.undo();
      } else if (meta && (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey))) {
        e.preventDefault();
        canvasHandle.current?.redo();
      } else if (meta) {
        return;
      } else if (e.key === ' ') {
        // The seek bar handles its own arrows when focused; space is global.
        e.preventDefault();
        togglePlay();
      } else if (e.key === 'ArrowRight' && active?.getAttribute('data-testid') !== 'seek-bar') {
        e.preventDefault();
        skip(5);
      } else if (e.key === 'ArrowLeft' && active?.getAttribute('data-testid') !== 'seek-bar') {
        e.preventDefault();
        skip(-5);
      } else if (e.key.toLowerCase() === 'd') {
        toggleDrawMode();
      } else if (e.key.toLowerCase() === 'e' && drawMode) {
        setTool('eraser');
      } else if (e.key.toLowerCase() === 'p' && drawMode) {
        setTool('pen');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [videoUrl, drawMode, togglePlay, skip, toggleDrawMode]);

  const captureScreenshot = () => {
    const video = videoRef.current;
    const drawCanvas = canvasHandle.current?.getCanvas();
    if (!video || !video.videoWidth) return;

    const merged = document.createElement('canvas');
    merged.width = video.videoWidth;
    merged.height = video.videoHeight;
    const ctx = merged.getContext('2d');
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, merged.width, merged.height);
    if (drawCanvas && drawCanvas.width > 0) {
      // The overlay is sized in CSS pixels; stretch it over the video frame.
      ctx.drawImage(drawCanvas, 0, 0, merged.width, merged.height);
    }

    onScreenshotCapture({ id: uuidv4(), dataUrl: merged.toDataURL('image/png') });
    canvasHandle.current?.clear();
  };

  const canUndo = canvasHandle.current?.canUndo() ?? false;
  const canRedo = canvasHandle.current?.canRedo() ?? false;
  // historyVersion is what re-renders this component when the canvas history
  // moves; referencing it keeps the dependency honest for linters and readers.
  void historyVersion;

  const controlsEnabled = isLoaded && !hasError;
  const drawControlsEnabled = controlsEnabled && drawMode;

  const buttonClass = (enabled: boolean, activeState = false) =>
    `p-2.5 rounded-xl transition-all duration-200 ${
      !enabled
        ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
        : activeState
        ? 'bg-accent-primary text-white'
        : 'bg-dark-600 hover:bg-dark-500 text-white'
    }`;

  return (
    <div className="flex flex-col h-full bg-dark-900">
      <div
        ref={containerRef}
        className="flex-1 relative flex items-center justify-center overflow-hidden bg-black"
      >
        {!videoUrl ? (
          <div className="flex flex-col items-center justify-center text-gray-500">
            <NoVideoIcon className="w-20 h-20 mb-4 opacity-30" />
            <p className="text-lg font-medium">No video yet</p>
            <p className="text-sm mt-1">Ask a question to generate a video</p>
          </div>
        ) : hasError ? (
          <div className="flex flex-col items-center justify-center text-red-400">
            <WarningIcon className="w-16 h-16 mb-4" />
            <p className="text-lg font-medium">Failed to load video</p>
            <p className="text-sm mt-1 text-gray-500">Please try again later</p>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              src={videoUrl}
              data-testid="video-element"
              className="max-w-full max-h-full object-contain"
              onClick={togglePlay}
              onLoadedMetadata={updateCanvasSize}
              playsInline
              preload="metadata"
            />

            <AnnotationCanvas
              ref={canvasHandle}
              width={canvasSize.width}
              height={canvasSize.height}
              active={drawMode}
              tool={tool}
              brushSize={brushSize}
              color={color}
              onHistoryChange={onHistoryChange}
            />

            {isPaused && isLoaded && !drawMode && (
              <button
                onClick={togglePlay}
                aria-label="Play"
                className="absolute inset-0 flex items-center justify-center bg-black/20"
              >
                <span className="bg-black/50 rounded-full p-4 backdrop-blur-sm">
                  <PlayIcon className="w-12 h-12 text-white/80" />
                </span>
              </button>
            )}

            {isWaiting && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="h-10 w-10 rounded-full border-2 border-white/30 border-t-white animate-spin" />
              </div>
            )}

            {drawMode && (
              <>
                <div className="pointer-events-none absolute inset-0 ring-2 ring-inset ring-accent-primary/70" />
                <div className="absolute top-4 left-4 flex flex-col gap-2 pointer-events-none">
                  <div className="bg-accent-primary/90 text-white text-xs font-medium px-3 py-1.5 rounded-full backdrop-blur-sm">
                    Draw mode on - press D to exit
                  </div>
                  <div className="bg-dark-800/90 text-gray-300 text-xs px-3 py-1.5 rounded-full backdrop-blur-sm">
                    {tool === 'pen' ? 'Pen (P)' : 'Eraser (E)'} - Ctrl+Z undo
                  </div>
                </div>
              </>
            )}
          </>
        )}
      </div>

      {videoUrl && !hasError && exportOpen && (
        <ExportPanel
          messageId={messageId}
          duration={duration}
          currentTime={currentTime}
          videoWidth={videoSize.width}
          videoHeight={videoSize.height}
          onClose={() => setExportOpen(false)}
          onPreviewSeek={seekTo}
        />
      )}

      {videoUrl && !hasError && (
        <div className="px-4 py-2 bg-dark-850 border-t border-dark-700">
          <div className="flex items-center gap-3">
            <button
              onClick={() => skip(-5)}
              disabled={!controlsEnabled}
              className="p-1.5 text-gray-400 hover:text-white disabled:text-gray-700 transition-colors"
              title="Back 5s"
              aria-label="Back 5 seconds"
            >
              <SkipBackIcon />
            </button>

            <ProgressBar
              currentTime={currentTime}
              duration={duration}
              buffered={buffered}
              onSeek={seekTo}
              onScrubbingChange={setScrubbing}
              disabled={!controlsEnabled}
            />

            <button
              onClick={() => skip(5)}
              disabled={!controlsEnabled}
              className="p-1.5 text-gray-400 hover:text-white disabled:text-gray-700 transition-colors"
              title="Forward 5s"
              aria-label="Forward 5 seconds"
            >
              <SkipForwardIcon />
            </button>
          </div>
        </div>
      )}

      <div className="p-4 bg-dark-800 border-t border-dark-600">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={togglePlay}
              disabled={!controlsEnabled}
              className={`p-3 rounded-xl transition-all duration-200 ${
                controlsEnabled
                  ? 'bg-dark-600 hover:bg-dark-500 text-white'
                  : 'bg-dark-700 text-gray-600 cursor-not-allowed'
              }`}
              title={isPaused ? 'Play (Space)' : 'Pause (Space)'}
              aria-label={isPaused ? 'Play' : 'Pause'}
            >
              {isPaused ? <PlayIcon /> : <PauseIcon />}
            </button>

            <button
              onClick={toggleDrawMode}
              disabled={!controlsEnabled}
              data-testid="draw-mode-toggle"
              aria-pressed={drawMode}
              className={`px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                          flex items-center gap-2 ${
                            !controlsEnabled
                              ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
                              : drawMode
                              ? 'bg-accent-primary text-white'
                              : 'bg-dark-600 hover:bg-dark-500 text-white'
                          }`}
              title="Toggle draw mode (D)"
            >
              <PenIcon />
              {drawMode ? 'Drawing' : 'Draw'}
            </button>

            <div className="h-6 w-px bg-dark-500 mx-1" />

            <button
              onClick={() => setTool('pen')}
              disabled={!drawControlsEnabled}
              className={buttonClass(drawControlsEnabled, tool === 'pen')}
              title="Pen (P)"
              aria-label="Pen"
            >
              <PenIcon />
            </button>

            <button
              onClick={() => setTool('eraser')}
              disabled={!drawControlsEnabled}
              className={buttonClass(drawControlsEnabled, tool === 'eraser')}
              title="Eraser (E)"
              aria-label="Eraser"
            >
              <EraserIcon />
            </button>

            <div className="flex items-center gap-1">
              {PEN_COLORS.map((swatch) => (
                <button
                  key={swatch}
                  onClick={() => {
                    setColor(swatch);
                    setTool('pen');
                  }}
                  disabled={!drawControlsEnabled}
                  aria-label={`Pen colour ${swatch}`}
                  className={`h-5 w-5 rounded-full border-2 transition-transform disabled:opacity-30 ${
                    color === swatch ? 'border-white scale-110' : 'border-transparent'
                  }`}
                  style={{ backgroundColor: swatch }}
                />
              ))}
            </div>

            <div className="flex items-center gap-1 ml-1">
              <span className="text-xs text-gray-500">Size:</span>
              <input
                type="range"
                min={2}
                max={12}
                value={brushSize}
                onChange={(e) => setBrushSize(parseInt(e.target.value, 10))}
                disabled={!drawControlsEnabled}
                aria-label="Brush size"
                className="w-16 h-1 bg-dark-600 rounded-full appearance-none cursor-pointer
                           [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3
                           [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-white
                           [&::-webkit-slider-thumb]:rounded-full"
              />
            </div>

            <button
              onClick={() => canvasHandle.current?.undo()}
              disabled={!drawControlsEnabled || !canUndo}
              className={buttonClass(drawControlsEnabled && canUndo)}
              title="Undo (Ctrl+Z)"
              aria-label="Undo"
            >
              <UndoIcon />
            </button>

            <button
              onClick={() => canvasHandle.current?.redo()}
              disabled={!drawControlsEnabled || !canRedo}
              className={buttonClass(drawControlsEnabled && canRedo)}
              title="Redo (Ctrl+Y)"
              aria-label="Redo"
            >
              <RedoIcon />
            </button>

            <button
              onClick={() => canvasHandle.current?.clear()}
              disabled={!drawControlsEnabled}
              className={`px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200
                          flex items-center gap-1.5 ${
                            drawControlsEnabled
                              ? 'bg-dark-600 hover:bg-dark-500 text-white'
                              : 'bg-dark-700 text-gray-600 cursor-not-allowed'
                          }`}
              title="Clear drawings"
            >
              <TrashIcon />
              Clear
            </button>
          </div>

          <div className="flex items-center gap-2">
            <a
              href={videoUrl ? `${videoUrl}?download=1` : undefined}
              download
              data-testid="download-video"
              aria-disabled={!controlsEnabled}
              className={`px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                          flex items-center gap-2 ${
                            controlsEnabled
                              ? 'bg-dark-600 hover:bg-dark-500 text-white'
                              : 'bg-dark-700 text-gray-600 pointer-events-none'
                          }`}
              title="Download the whole video"
            >
              <DownloadIcon />
              Download
            </a>

            <button
              onClick={() => setExportOpen((open) => !open)}
              disabled={!controlsEnabled}
              data-testid="export-toggle"
              aria-pressed={exportOpen}
              className={`px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                          flex items-center gap-2 ${
                            !controlsEnabled
                              ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
                              : exportOpen
                              ? 'bg-accent-primary text-white'
                              : 'bg-dark-600 hover:bg-dark-500 text-white'
                          }`}
              title="Cut a GIF or an mp4 out of the video"
            >
              <ScissorsIcon />
              Cut
            </button>

            <DeckButton messageId={messageId} disabled={!controlsEnabled} />

            <button
              onClick={captureScreenshot}
              disabled={!controlsEnabled}
              data-testid="add-screenshot"
              className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                          flex items-center gap-2 ${
                            controlsEnabled
                              ? 'bg-accent-primary hover:bg-accent-secondary text-white shadow-lg shadow-accent-primary/20'
                              : 'bg-dark-700 text-gray-600 cursor-not-allowed'
                          }`}
            >
              <CameraIcon />
              Add Screenshot
            </button>
          </div>
        </div>

        {videoUrl && isLoaded && (
          <div className="mt-3 text-xs text-gray-500 text-center">
            {drawMode ? (
              <span>Draw on the video to highlight areas, then attach it to your question</span>
            ) : (
              <span>
                Space play/pause - arrows seek 5s - D to draw
                {!hasUsableDuration(duration) && ' - loading video info...'}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
