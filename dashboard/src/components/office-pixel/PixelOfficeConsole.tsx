import { useEffect, useRef, useState, useMemo } from 'react';
import { OfficeState } from './engine/officeState';
import PixelOfficeScene from './scene/PixelOfficeScene';
import { createDefaultEditorState } from './editor/editorState';
import type { EditorState } from './editor/editorState';
import { mockAgents3D, managerAgent } from '@/config/office3dLayout';
import type { MockAgent3D } from '@/config/office3dLayout';
import { Layers, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

interface PixelOfficeConsoleProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onBackgroundClick?: () => void;
}

const OFFICE_THEMES = [
  { id: 'realistic', name: 'High-Res Studio', path: '/offices/realistic-office.png' },
  { id: 'cyberpunk', name: 'Cyberpunk HQ', path: '/offices/cyberpunk.jpeg' },
  { id: 'cozy', name: 'Modern Cozy', path: '/offices/modern-cozy.jpeg' },
  { id: 'sifi', name: 'Sci-Fi Lab', path: '/offices/sifi.jpeg' },
  { id: 'darkLegend', name: 'Dark Legend', path: '/offices/darkLegend.jpeg' },
];

/**
 * PixelOfficeConsole — HTML5 2D Tilemap Pixel Canvas Engine from OpenOffice.
 * Complete 2D floor design, pixel tile rendering, A* pathfinding, seat assignments,
 * walking animations, and dynamic agent motion.
 */
export function PixelOfficeConsole({ selectedAgent, onAgentClick, onBackgroundClick }: PixelOfficeConsoleProps) {
  const officeStateRef = useRef<OfficeState | null>(null);
  const editorRef = useRef<EditorState>(createDefaultEditorState());
  const zoomRef = useRef<number>(4);
  const panRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const [activeTheme, setActiveTheme] = useState(OFFICE_THEMES[0]);

  const allAgents = useMemo(() => [managerAgent, ...mockAgents3D], []);

  // Sync agents into OfficeState when scene is ready
  const handleAssetsLoaded = () => {
    const office = officeStateRef.current;
    if (!office) return;

    allAgents.forEach((agent, i) => {
      office.setAgentState(agent.id, {
        name: agent.name,
        role: agent.role,
        status: agent.status,
        palette: i % 7,
      });
      office.updateCharacterStatus(agent.id, agent.status);
    });
  };

  // Update background image when active theme changes
  useEffect(() => {
    const office = officeStateRef.current;
    if (!office || !activeTheme.path) return;

    const img = new Image();
    img.src = activeTheme.path;
    img.onload = () => {
      office.setBackgroundImage(img);
    };
  }, [activeTheme]);

  return (
    <div
      onClick={onBackgroundClick}
      className="w-full h-full relative overflow-hidden bg-[#0a0d18] flex items-center justify-center select-none"
    >
      {/* Top Floating Control UI */}
      <div className="absolute top-16 left-6 z-20 flex items-center gap-2 pointer-events-auto">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900/90 border border-white/10 text-xs font-semibold text-white shadow-xl backdrop-blur-md">
          <Layers size={14} className="text-primary-400" />
          <span>OpenOffice 2D Pixel Engine</span>
        </div>
      </div>

      {/* Top Right Zoom Controls */}
      <div className="absolute top-16 right-6 z-20 flex items-center gap-1.5 bg-slate-900/90 border border-white/10 rounded-xl p-1 shadow-xl backdrop-blur-md text-xs pointer-events-auto">
        <button
          onClick={(e) => {
            e.stopPropagation();
            zoomRef.current = Math.min(zoomRef.current + 1, 8);
          }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
          title="Zoom In"
        >
          <ZoomIn size={14} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            zoomRef.current = Math.max(zoomRef.current - 1, 2);
          }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
          title="Zoom Out"
        >
          <ZoomOut size={14} />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            zoomRef.current = 4;
            panRef.current = { x: 0, y: 0 };
          }}
          className="p-1.5 rounded-lg text-gray-300 hover:text-white hover:bg-white/10 transition-colors"
          title="Reset View"
        >
          <Maximize2 size={14} />
        </button>
      </div>

      {/* HTML5 2D Canvas Scene */}
      <div className="w-full h-full">
        <PixelOfficeScene
          editMode={false}
          editorRef={editorRef}
          officeStateRef={officeStateRef}
          zoomRef={zoomRef}
          panRef={panRef}
          onAssetsLoaded={handleAssetsLoaded}
          onAdapterReady={() => {}}
          onAgentClick={(numericOrStringId) => {
            const found = allAgents.find(
              (a) => a.id === String(numericOrStringId) || a.name.toLowerCase() === String(numericOrStringId).toLowerCase()
            );
            if (found) {
              onAgentClick(found);
            }
          }}
        />
      </div>
    </div>
  );
}
