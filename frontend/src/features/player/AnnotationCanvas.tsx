import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';

export type DrawingTool = 'pen' | 'eraser';

export interface AnnotationCanvasHandle {
  /** The drawing layer, for compositing into a screenshot. */
  getCanvas: () => HTMLCanvasElement | null;
  clear: () => void;
  undo: () => void;
  redo: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
}

interface AnnotationCanvasProps {
  width: number;
  height: number;
  /** Pointer events reach the canvas ONLY when this is true. */
  active: boolean;
  tool: DrawingTool;
  brushSize: number;
  color: string;
  onHistoryChange: () => void;
}

const MAX_HISTORY = 15;

/**
 * The drawing overlay.
 *
 * The important bit is `active`. Previously the canvas took pointer events
 * whenever the video was merely PAUSED, which meant a click intended to resume
 * playback drew a red line instead - and the <video>'s own click handler was
 * unreachable underneath it. Pausing is not a request to draw, so the overlay
 * now stays transparent to the pointer until draw mode is explicitly on.
 */
export const AnnotationCanvas = forwardRef<AnnotationCanvasHandle, AnnotationCanvasProps>(
  ({ width, height, active, tool, brushSize, color, onHistoryChange }, ref) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const isDrawingRef = useRef(false);
    const historyRef = useRef<ImageData[]>([]);
    const historyIndexRef = useRef(-1);
    const [, forceRender] = useState(0);

    const notify = useCallback(() => {
      forceRender((n) => n + 1);
      onHistoryChange();
    }, [onHistoryChange]);

    const context = () => canvasRef.current?.getContext('2d') ?? null;

    // Resizing the element clears its bitmap, so the drawing is re-applied
    // from the last history entry, scaled to the new size.
    useEffect(() => {
      const canvas = canvasRef.current;
      const ctx = context();
      if (!canvas || !ctx || width === 0 || height === 0) return;

      const dpr = window.devicePixelRatio || 1;
      const snapshot = historyRef.current[historyIndexRef.current] ?? null;

      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      if (snapshot) {
        // putImageData ignores the transform, so go through a scratch canvas.
        const scratch = document.createElement('canvas');
        scratch.width = snapshot.width;
        scratch.height = snapshot.height;
        scratch.getContext('2d')?.putImageData(snapshot, 0, 0);
        ctx.drawImage(scratch, 0, 0, width, height);
      }
    }, [width, height]);

    const pushHistory = useCallback(() => {
      const canvas = canvasRef.current;
      const ctx = context();
      if (!canvas || !ctx || canvas.width === 0) return;

      const snapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
      historyRef.current = historyRef.current.slice(0, historyIndexRef.current + 1);
      historyRef.current.push(snapshot);
      if (historyRef.current.length > MAX_HISTORY) historyRef.current.shift();
      historyIndexRef.current = historyRef.current.length - 1;
      notify();
    }, [notify]);

    const restore = useCallback((index: number) => {
      const canvas = canvasRef.current;
      const ctx = context();
      if (!canvas || !ctx) return;
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const snapshot = historyRef.current[index];
      if (snapshot) ctx.putImageData(snapshot, 0, 0);
      ctx.restore();
    }, []);

    useImperativeHandle(ref, () => ({
      getCanvas: () => canvasRef.current,
      clear: () => {
        const canvas = canvasRef.current;
        const ctx = context();
        if (!canvas || !ctx) return;
        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.restore();
        pushHistory();
      },
      undo: () => {
        if (historyIndexRef.current <= 0) {
          // Step 0 is the first stroke; undoing it means an empty canvas.
          const canvas = canvasRef.current;
          const ctx = context();
          if (canvas && ctx && historyIndexRef.current === 0) {
            ctx.save();
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.restore();
            historyIndexRef.current = -1;
            notify();
          }
          return;
        }
        historyIndexRef.current -= 1;
        restore(historyIndexRef.current);
        notify();
      },
      redo: () => {
        if (historyIndexRef.current >= historyRef.current.length - 1) return;
        historyIndexRef.current += 1;
        restore(historyIndexRef.current);
        notify();
      },
      canUndo: () => historyIndexRef.current >= 0,
      canRedo: () => historyIndexRef.current < historyRef.current.length - 1,
    }));

    const pointFrom = (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const startStroke = (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!active) return;
      const ctx = context();
      const point = pointFrom(e);
      if (!ctx || !point) return;

      e.currentTarget.setPointerCapture(e.pointerId);
      isDrawingRef.current = true;

      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      if (tool === 'eraser') {
        ctx.globalCompositeOperation = 'destination-out';
        ctx.lineWidth = brushSize * 3;
      } else {
        ctx.globalCompositeOperation = 'source-over';
        ctx.strokeStyle = color;
        ctx.lineWidth = brushSize;
      }
    };

    const extendStroke = (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!isDrawingRef.current || !active) return;
      const ctx = context();
      const point = pointFrom(e);
      if (!ctx || !point) return;
      ctx.lineTo(point.x, point.y);
      ctx.stroke();
    };

    const endStroke = (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!isDrawingRef.current) return;
      isDrawingRef.current = false;
      if (e.currentTarget.hasPointerCapture(e.pointerId)) {
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
      const ctx = context();
      if (ctx) ctx.globalCompositeOperation = 'source-over';
      pushHistory();
    };

    return (
      <canvas
        ref={canvasRef}
        data-testid="annotation-canvas"
        data-active={active}
        className="absolute"
        style={{
          left: '50%',
          top: '50%',
          transform: 'translate(-50%, -50%)',
          width,
          height,
          // The whole point of D2: no interception unless draw mode is on.
          pointerEvents: active ? 'auto' : 'none',
          cursor: tool === 'eraser' ? 'cell' : 'crosshair',
          touchAction: 'none',
        }}
        onPointerDown={startStroke}
        onPointerMove={extendStroke}
        onPointerUp={endStroke}
        onPointerCancel={endStroke}
      />
    );
  },
);

AnnotationCanvas.displayName = 'AnnotationCanvas';
