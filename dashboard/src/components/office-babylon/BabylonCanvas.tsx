import { useEffect, useRef, useCallback, useState } from 'react';
import { Engine, Scene } from '@babylonjs/core';
import { initOfficeScene } from './OfficeScene';
import type { AgentData } from './agents/AgentModel';
import type { RoomDefinition } from './layout/roomDefinitions';

export interface SelectionState {
  type: 'agent' | 'room' | null;
  agent?: AgentData;
  room?: RoomDefinition;
  agentCount?: number;
}

interface BabylonCanvasProps {
  onSelectionChange?: (selection: SelectionState) => void;
}

/**
 * React wrapper for Babylon.js canvas.
 */
export function BabylonCanvas({ onSelectionChange }: BabylonCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<Engine | null>(null);
  const callbackRef = useRef(onSelectionChange);
  callbackRef.current = onSelectionChange;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const engine = new Engine(canvas, true, { preserveDrawingBuffer: true, stencil: true });
    engineRef.current = engine;

    const scene = initOfficeScene(engine, canvas, (selection) => {
      callbackRef.current?.(selection);
    });

    engine.runRenderLoop(() => {
      scene.render();
    });

    const handleResize = () => engine.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      engine.stopRenderLoop();
      scene.dispose();
      engine.dispose();
      engineRef.current = null;
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full block outline-none"
      style={{ touchAction: 'none' }}
    />
  );
}
