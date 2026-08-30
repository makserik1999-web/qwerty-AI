import { useRef, useState, useEffect, useCallback } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { PendingScreenshot } from '../types';

interface VideoPanelProps {
  videoUrl: string | null;
  onScreenshotCapture: (screenshot: PendingScreenshot) => void;
}

type DrawingTool = 'pen' | 'eraser';

interface DrawingHistoryEntry {
  imageData: ImageData;
}

export const VideoPanel: React.FC<VideoPanelProps> = ({
  videoUrl,
  onScreenshotCapture,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  
  const [isPaused, setIsPaused] = useState(true);
  const [isDrawing, setIsDrawing] = useState(false);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [videoLoaded, setVideoLoaded] = useState(false);
  const [videoError, setVideoError] = useState(false);
  
  // Video progress states
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isSeeking, setIsSeeking] = useState(false);
  
  // Drawing tool states
  const [currentTool, setCurrentTool] = useState<DrawingTool>('pen');
  const [brushSize, setBrushSize] = useState(4);
  
  // Undo/Redo history
  const [history, setHistory] = useState<DrawingHistoryEntry[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const isUndoRedoAction = useRef(false);
  
  // Track previous video URL to detect changes
  const prevVideoUrlRef = useRef<string | null>(null);

  // Reset all state when video URL changes
  useEffect(() => {
    if (prevVideoUrlRef.current !== videoUrl) {
      setCurrentTime(0);
      setDuration(0);
      setVideoLoaded(false);
      setVideoError(false);
      setIsPaused(true);
      setHistory([]);
      setHistoryIndex(-1);
      
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext('2d');
      if (ctx && canvas) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      
      if (videoRef.current) {
        videoRef.current.currentTime = 0;
      }
      
      prevVideoUrlRef.current = videoUrl;
    }
  }, [videoUrl]);

  const formatTime = (seconds: number): string => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const saveToHistory = useCallback(() => {
    if (isUndoRedoAction.current) {
      isUndoRedoAction.current = false;
      return;
    }
    
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx || !canvas) return;
    
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push({ imageData });
    
    if (newHistory.length > 15) {
      newHistory.shift();
    }
    
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
  }, [history, historyIndex]);

  const undo = useCallback(() => {
    if (historyIndex <= 0) return;
    
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx || !canvas) return;
    
    isUndoRedoAction.current = true;
    const newIndex = historyIndex - 1;
    
    if (newIndex >= 0) {
      ctx.putImageData(history[newIndex].imageData, 0, 0);
    } else {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    
    setHistoryIndex(newIndex);
  }, [history, historyIndex]);

  const redo = useCallback(() => {
    if (historyIndex >= history.length - 1) return;
    
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx || !canvas) return;
    
    isUndoRedoAction.current = true;
    const newIndex = historyIndex + 1;
    ctx.putImageData(history[newIndex].imageData, 0, 0);
    setHistoryIndex(newIndex);
  }, [history, historyIndex]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in input fields
      const activeElement = document.activeElement;
      const isTyping = activeElement instanceof HTMLInputElement || 
                       activeElement instanceof HTMLTextAreaElement ||
                       activeElement?.getAttribute('contenteditable') === 'true';
      
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        if (!isTyping) {
          e.preventDefault();
          undo();
        }
      } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) {
        if (!isTyping) {
          e.preventDefault();
          redo();
        }
      } else if (e.key === 'e' && isPaused && !isTyping) {
        setCurrentTool(currentTool === 'eraser' ? 'pen' : 'eraser');
      } else if (e.key === 'p' && isPaused && !isTyping) {
        setCurrentTool('pen');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [undo, redo, isPaused, currentTool]);

  const updateCanvasSize = useCallback(() => {
    if (videoRef.current && containerRef.current) {
      const video = videoRef.current;
      const container = containerRef.current;
      
      const containerRect = container.getBoundingClientRect();
      const videoAspect = video.videoWidth / video.videoHeight;
      const containerAspect = containerRect.width / containerRect.height;
      
      let displayWidth, displayHeight;
      
      if (videoAspect > containerAspect) {
        displayWidth = containerRect.width;
        displayHeight = containerRect.width / videoAspect;
      } else {
        displayHeight = containerRect.height;
        displayWidth = containerRect.height * videoAspect;
      }
      
      setCanvasSize({
        width: displayWidth,
        height: displayHeight,
      });
    }
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleLoadedData = () => {
      setVideoLoaded(true);
      setVideoError(false);
      setDuration(video.duration);
      updateCanvasSize();
      video.pause();
      setIsPaused(true);
      setHistory([]);
      setHistoryIndex(-1);
    };

    const handleError = () => {
      setVideoError(true);
      setVideoLoaded(false);
    };

    const handlePlay = () => setIsPaused(false);
    const handlePause = () => setIsPaused(true);
    
    const handleTimeUpdate = () => {
      if (!isSeeking) {
        setCurrentTime(video.currentTime);
      }
    };
    
    const handleDurationChange = () => {
      setDuration(video.duration);
    };

    video.addEventListener('loadeddata', handleLoadedData);
    video.addEventListener('error', handleError);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('durationchange', handleDurationChange);

    return () => {
      video.removeEventListener('loadeddata', handleLoadedData);
      video.removeEventListener('error', handleError);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('durationchange', handleDurationChange);
    };
  }, [videoUrl, updateCanvasSize, isSeeking]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const resizeObserver = new ResizeObserver(() => {
      updateCanvasSize();
    });

    resizeObserver.observe(container);
    return () => resizeObserver.disconnect();
  }, [updateCanvasSize]);

  useEffect(() => {
    if (!isPaused && canvasRef.current) {
      const ctx = canvasRef.current.getContext('2d');
      if (ctx) {
        ctx.clearRect(0, 0, canvasRef.current.width, canvasRef.current.height);
        setHistory([]);
        setHistoryIndex(-1);
      }
    }
  }, [isPaused]);

  const getCanvasCoordinates = (e: React.MouseEvent | React.TouchEvent): { x: number; y: number } | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;

    const rect = canvas.getBoundingClientRect();
    let clientX, clientY;

    if ('touches' in e) {
      clientX = e.touches[0].clientX;
      clientY = e.touches[0].clientY;
    } else {
      clientX = e.clientX;
      clientY = e.clientY;
    }

    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
    };
  };

  const startDrawing = (e: React.MouseEvent | React.TouchEvent) => {
    if (!isPaused) return;
    
    const coords = getCanvasCoordinates(e);
    if (!coords) return;

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;

    setIsDrawing(true);
    ctx.beginPath();
    ctx.moveTo(coords.x, coords.y);
    
    if (currentTool === 'eraser') {
      ctx.globalCompositeOperation = 'destination-out';
      ctx.lineWidth = brushSize * 3;
    } else {
      ctx.globalCompositeOperation = 'source-over';
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = brushSize;
    }
    
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
  };

  const draw = (e: React.MouseEvent | React.TouchEvent) => {
    if (!isDrawing || !isPaused) return;

    const coords = getCanvasCoordinates(e);
    if (!coords) return;

    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!ctx) return;

    ctx.lineTo(coords.x, coords.y);
    ctx.stroke();
  };

  const stopDrawing = () => {
    if (isDrawing) {
      saveToHistory();
    }
    setIsDrawing(false);
    
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (ctx) {
      ctx.globalCompositeOperation = 'source-over';
    }
  };

  const togglePlayPause = () => {
    const video = videoRef.current;
    if (!video) return;

    if (video.paused) {
      video.play();
    } else {
      video.pause();
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const video = videoRef.current;
    if (!video) return;
    
    const time = parseFloat(e.target.value);
    setCurrentTime(time);
    video.currentTime = time;
  };

  const handleSeekStart = () => {
    setIsSeeking(true);
    // Pause video while seeking for smoother experience
    if (videoRef.current && !videoRef.current.paused) {
      videoRef.current.pause();
    }
  };

  const handleSeekEnd = (e: React.MouseEvent<HTMLInputElement> | React.TouchEvent<HTMLInputElement>) => {
    const video = videoRef.current;
    if (!video) return;
    
    // Apply the final seek position
    const input = e.target as HTMLInputElement;
    const time = parseFloat(input.value);
    video.currentTime = time;
    setCurrentTime(time);
    setIsSeeking(false);
  };

  const skip = (seconds: number) => {
    const video = videoRef.current;
    if (!video || !duration) return;
    
    const newTime = Math.max(0, Math.min(duration, video.currentTime + seconds));
    video.currentTime = newTime;
    setCurrentTime(newTime);
  };

  const captureScreenshot = () => {
    const video = videoRef.current;
    const drawCanvas = canvasRef.current;
    if (!video || !drawCanvas) return;

    const mergeCanvas = document.createElement('canvas');
    mergeCanvas.width = video.videoWidth;
    mergeCanvas.height = video.videoHeight;
    const ctx = mergeCanvas.getContext('2d');
    if (!ctx) return;

    ctx.drawImage(video, 0, 0, mergeCanvas.width, mergeCanvas.height);

    const scaleX = mergeCanvas.width / drawCanvas.width;
    const scaleY = mergeCanvas.height / drawCanvas.height;
    
    ctx.save();
    ctx.scale(scaleX, scaleY);
    ctx.drawImage(drawCanvas, 0, 0);
    ctx.restore();

    const dataUrl = mergeCanvas.toDataURL('image/png');

    const screenshot: PendingScreenshot = {
      id: uuidv4(),
      dataUrl,
    };

    onScreenshotCapture(screenshot);

    const drawCtx = drawCanvas.getContext('2d');
    if (drawCtx) {
      drawCtx.clearRect(0, 0, drawCanvas.width, drawCanvas.height);
      setHistory([]);
      setHistoryIndex(-1);
    }
  };

  const clearDrawings = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (ctx && canvas) {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      saveToHistory();
    }
  };

  const canUndo = historyIndex > 0;
  const canRedo = historyIndex < history.length - 1;

  return (
    <div className="flex flex-col h-full bg-dark-900">
      {/* Video Container */}
      <div 
        ref={containerRef}
        className="flex-1 relative flex items-center justify-center overflow-hidden bg-black"
      >
        {!videoUrl ? (
          <div className="flex flex-col items-center justify-center text-gray-500">
            <svg className="w-20 h-20 mb-4 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} 
                    d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            <p className="text-lg font-medium">No video yet</p>
            <p className="text-sm mt-1">Ask a question to generate a video</p>
          </div>
        ) : videoError ? (
          <div className="flex flex-col items-center justify-center text-red-400">
            <svg className="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <p className="text-lg font-medium">Failed to load video</p>
            <p className="text-sm mt-1 text-gray-500">Please try again later</p>
          </div>
        ) : (
          <>
            <video
              ref={videoRef}
              src={videoUrl}
              className="max-w-full max-h-full object-contain"
              onClick={togglePlayPause}
              playsInline
            />
            
            <canvas
              ref={canvasRef}
              width={canvasSize.width}
              height={canvasSize.height}
              className={`absolute pointer-events-none ${isPaused ? 'pointer-events-auto' : ''}`}
              style={{
                left: '50%',
                top: '50%',
                transform: 'translate(-50%, -50%)',
                width: canvasSize.width,
                height: canvasSize.height,
                cursor: isPaused ? (currentTool === 'eraser' ? 'cell' : 'crosshair') : 'pointer',
              }}
              onMouseDown={startDrawing}
              onMouseMove={draw}
              onMouseUp={stopDrawing}
              onMouseLeave={stopDrawing}
              onTouchStart={startDrawing}
              onTouchMove={draw}
              onTouchEnd={stopDrawing}
            />

            {isPaused && videoLoaded && (
              <div 
                className="absolute inset-0 flex items-center justify-center pointer-events-none"
                style={{ background: 'rgba(0,0,0,0.2)' }}
              >
                <div className="bg-black/50 rounded-full p-4 backdrop-blur-sm">
                  <svg className="w-12 h-12 text-white/80" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </div>
              </div>
            )}

            {isPaused && videoLoaded && (
              <div className="absolute top-4 left-4 flex flex-col gap-2">
                <div className="bg-accent-primary/90 text-white text-xs font-medium 
                              px-3 py-1.5 rounded-full backdrop-blur-sm flex items-center gap-2">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                  </svg>
                  Draw mode active
                </div>
                <div className="bg-dark-800/90 text-gray-300 text-xs px-3 py-1.5 rounded-full backdrop-blur-sm">
                  Tool: {currentTool === 'pen' ? '🖊️ Pen' : '🧽 Eraser'} | Press E to toggle
                </div>
              </div>
            )}

            {isPaused && videoLoaded && (
              <div className="absolute top-4 right-4 bg-dark-800/90 text-gray-400 text-xs 
                            px-3 py-2 rounded-lg backdrop-blur-sm">
                <div className="space-y-1">
                  <div><kbd className="bg-dark-600 px-1.5 py-0.5 rounded">Ctrl+Z</kbd> Undo</div>
                  <div><kbd className="bg-dark-600 px-1.5 py-0.5 rounded">Ctrl+Y</kbd> Redo</div>
                  <div><kbd className="bg-dark-600 px-1.5 py-0.5 rounded">E</kbd> Eraser</div>
                  <div><kbd className="bg-dark-600 px-1.5 py-0.5 rounded">P</kbd> Pen</div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Video Progress Bar */}
      {videoLoaded && videoUrl && (
        <div className="px-4 py-2 bg-dark-850 border-t border-dark-700">
          <div className="flex items-center gap-3">
            <button
              onClick={() => skip(-3)}
              className="p-1.5 text-gray-400 hover:text-white transition-colors"
              title="Skip back 3s"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0019 16V8a1 1 0 00-1.6-.8l-5.334 4zM4.066 11.2a1 1 0 000 1.6l5.334 4A1 1 0 0011 16V8a1 1 0 00-1.6-.8l-5.334 4z" />
              </svg>
            </button>

            <span className="text-xs text-gray-400 font-mono w-12 text-right">
              {formatTime(currentTime)}
            </span>

            <input
              type="range"
              min={0}
              max={duration || 0}
              step={0.1}
              value={currentTime}
              onChange={handleSeek}
              onMouseDown={handleSeekStart}
              onMouseUp={handleSeekEnd}
              onTouchStart={handleSeekStart}
              onTouchEnd={handleSeekEnd}
              className="flex-1 h-1.5 bg-dark-600 rounded-full appearance-none cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 
                         [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-accent-primary 
                         [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer
                         [&::-webkit-slider-thumb]:hover:scale-125 [&::-webkit-slider-thumb]:transition-transform"
              style={{
                background: `linear-gradient(to right, #6366f1 0%, #6366f1 ${(currentTime / duration) * 100}%, #2a2a3a ${(currentTime / duration) * 100}%, #2a2a3a 100%)`
              }}
            />

            <span className="text-xs text-gray-400 font-mono w-12">
              {formatTime(duration)}
            </span>

            <button
              onClick={() => skip(3)}
              className="p-1.5 text-gray-400 hover:text-white transition-colors"
              title="Skip forward 3s"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.933 12.8a1 1 0 000-1.6L6.6 7.2A1 1 0 005 8v8a1 1 0 001.6.8l5.333-4zM19.933 12.8a1 1 0 000-1.6l-5.333-4A1 1 0 0013 8v8a1 1 0 001.6.8l5.333-4z" />
              </svg>
            </button>
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="p-4 bg-dark-800 border-t border-dark-600">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlayPause}
              disabled={!videoLoaded}
              className={`p-3 rounded-xl transition-all duration-200 ${
                videoLoaded
                  ? 'bg-dark-600 hover:bg-dark-500 text-white'
                  : 'bg-dark-700 text-gray-600 cursor-not-allowed'
              }`}
              title={isPaused ? 'Play' : 'Pause'}
            >
              {isPaused ? (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
              ) : (
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                </svg>
              )}
            </button>

            <button
              onClick={() => setCurrentTool('pen')}
              disabled={!isPaused || !videoLoaded}
              className={`p-2.5 rounded-xl transition-all duration-200 ${
                !isPaused || !videoLoaded
                  ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
                  : currentTool === 'pen'
                  ? 'bg-accent-primary text-white'
                  : 'bg-dark-600 hover:bg-dark-500 text-white'
              }`}
              title="Pen tool (P)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                      d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
              </svg>
            </button>

            <button
              onClick={() => setCurrentTool('eraser')}
              disabled={!isPaused || !videoLoaded}
              className={`p-2.5 rounded-xl transition-all duration-200 ${
                !isPaused || !videoLoaded
                  ? 'bg-dark-700 text-gray-600 cursor-not-allowed'
                  : currentTool === 'eraser'
                  ? 'bg-orange-500 text-white'
                  : 'bg-dark-600 hover:bg-dark-500 text-white'
              }`}
              title="Eraser tool (E)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                      d="M4 4l16 16m0-16L4 20" />
              </svg>
            </button>

            <div className="flex items-center gap-1 ml-2">
              <span className="text-xs text-gray-500">Size:</span>
              <input
                type="range"
                min={2}
                max={12}
                value={brushSize}
                onChange={(e) => setBrushSize(parseInt(e.target.value))}
                disabled={!isPaused || !videoLoaded}
                className="w-16 h-1 bg-dark-600 rounded-full appearance-none cursor-pointer
                           [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 
                           [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-white 
                           [&::-webkit-slider-thumb]:rounded-full"
              />
            </div>

            <div className="h-6 w-px bg-dark-500 mx-2" />

            <button
              onClick={undo}
              disabled={!canUndo || !isPaused || !videoLoaded}
              className={`p-2.5 rounded-xl transition-all duration-200 ${
                canUndo && isPaused && videoLoaded
                  ? 'bg-dark-600 hover:bg-dark-500 text-white'
                  : 'bg-dark-700 text-gray-600 cursor-not-allowed'
              }`}
              title="Undo (Ctrl+Z)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                      d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
              </svg>
            </button>

            <button
              onClick={redo}
              disabled={!canRedo || !isPaused || !videoLoaded}
              className={`p-2.5 rounded-xl transition-all duration-200 ${
                canRedo && isPaused && videoLoaded
                  ? 'bg-dark-600 hover:bg-dark-500 text-white'
                  : 'bg-dark-700 text-gray-600 cursor-not-allowed'
              }`}
              title="Redo (Ctrl+Y)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                      d="M21 10h-10a8 8 0 00-8 8v2M21 10l-6 6m6-6l-6-6" />
              </svg>
            </button>

            <button
              onClick={clearDrawings}
              disabled={!isPaused || !videoLoaded}
              className={`px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200
                         flex items-center gap-1.5 ${
                isPaused && videoLoaded
                  ? 'bg-dark-600 hover:bg-dark-500 text-white'
                  : 'bg-dark-700 text-gray-600 cursor-not-allowed'
              }`}
              title="Clear all drawings"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Clear
            </button>
          </div>

          <button
            onClick={captureScreenshot}
            disabled={!isPaused || !videoLoaded}
            className={`px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200
                       flex items-center gap-2 ${
              isPaused && videoLoaded
                ? 'bg-accent-primary hover:bg-accent-secondary text-white shadow-lg shadow-accent-primary/20'
                : 'bg-dark-700 text-gray-600 cursor-not-allowed'
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                    d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} 
                    d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            Add Screenshot
          </button>
        </div>

        {videoLoaded && videoUrl && (
          <div className="mt-3 text-xs text-gray-500 text-center">
            {isPaused ? (
              <span className="animate-fade-in">
                Draw on the video to highlight areas • Use eraser to correct • Click "Add Screenshot" to attach
              </span>
            ) : (
              <span>Pause the video to start drawing</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

