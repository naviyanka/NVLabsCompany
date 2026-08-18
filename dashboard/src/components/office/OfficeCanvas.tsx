import { useRef, useCallback, useState } from 'react';
import { CANVAS_WIDTH, CANVAS_HEIGHT, GRID_SIZE } from '@/config/officeLayout';

interface OfficeCanvasProps {
  zoom: number;
  panX: number;
  panY: number;
  onPanChange: (x: number, y: number) => void;
  onZoomChange: (zoom: number) => void;
  nightMode: boolean;
  children: React.ReactNode;
}

export function OfficeCanvas({
  zoom,
  panX,
  panY,
  onPanChange,
  onZoomChange,
  nightMode,
  children,
}: OfficeCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{ x: number; y: number; panX: number; panY: number }>({
    x: 0,
    y: 0,
    panX: 0,
    panY: 0,
  });

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return; // Only left click
      setIsDragging(true);
      dragStartRef.current = { x: e.clientX, y: e.clientY, panX, panY };
    },
    [panX, panY]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging) return;
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      onPanChange(dragStartRef.current.panX + dx, dragStartRef.current.panY + dy);
    },
    [isDragging, onPanChange]
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.1 : 0.1;
      const newZoom = Math.max(0.3, Math.min(2.5, zoom + delta));
      onZoomChange(newZoom);
    },
    [zoom, onZoomChange]
  );

  // Generate grid pattern
  const gridLines: React.ReactNode[] = [];
  for (let x = 0; x <= CANVAS_WIDTH; x += GRID_SIZE) {
    gridLines.push(
      <line
        key={`v-${x}`}
        x1={x}
        y1={0}
        x2={x}
        y2={CANVAS_HEIGHT}
        stroke={nightMode ? '#334155' : '#e5e7eb'}
        strokeWidth="0.5"
      />
    );
  }
  for (let y = 0; y <= CANVAS_HEIGHT; y += GRID_SIZE) {
    gridLines.push(
      <line
        key={`h-${y}`}
        x1={0}
        y1={y}
        x2={CANVAS_WIDTH}
        y2={y}
        stroke={nightMode ? '#334155' : '#e5e7eb'}
        strokeWidth="0.5"
      />
    );
  }

  return (
    <div
      ref={containerRef}
      className={`w-full h-full overflow-hidden relative select-none ${nightMode ? 'bg-slate-900' : 'bg-gray-50'} ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onWheel={handleWheel}
    >
      <div
        className="origin-top-left transition-transform duration-75 ease-out"
        style={{
          transform: `translate3d(${panX}px, ${panY}px, 0) scale(${zoom})`,
          width: `${CANVAS_WIDTH}px`,
          height: `${CANVAS_HEIGHT}px`,
        }}
      >
        {/* Grid background */}
        <svg
          className="absolute inset-0 pointer-events-none"
          width={CANVAS_WIDTH}
          height={CANVAS_HEIGHT}
        >
          {gridLines}
        </svg>

        {/* Floor plan content */}
        <div className="absolute inset-0">
          {children}
        </div>
      </div>
    </div>
  );
}
