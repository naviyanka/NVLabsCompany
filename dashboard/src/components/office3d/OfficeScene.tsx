import type { MockAgent3D } from '@/config/office3dLayout';
import { mockAgents3D, managerAgent } from '@/config/office3dLayout';

interface OfficeSceneProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onBackgroundClick: () => void;
  paused?: boolean;
  agents?: MockAgent3D[];
}

export function OfficeScene({
  selectedAgent,
  onAgentClick,
  onBackgroundClick,
  agents,
}: OfficeSceneProps) {
  const allAgents = agents && agents.length > 0 ? agents : [...mockAgents3D, managerAgent];

  return (
    <div
      onClick={onBackgroundClick}
      className="w-full h-full bg-[#08080A] relative flex items-center justify-center p-8 overflow-hidden select-none"
    >
      <div className="max-w-4xl w-full grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4 z-10">
        {allAgents.map((agent) => {
          const isSelected = selectedAgent?.id === agent.id;
          return (
            <div
              key={agent.id}
              onClick={(e) => {
                e.stopPropagation();
                onAgentClick(agent);
              }}
              className={`p-4 rounded-xl border transition-all cursor-pointer ${
                isSelected
                  ? 'bg-[#10B981]/15 border-[#10B981] shadow-lg shadow-emerald-950/40'
                  : 'bg-black/60 border-white/[0.08] hover:border-white/[0.2] hover:bg-white/[0.03]'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <div className="w-6 h-6 rounded-full bg-emerald-600 flex items-center justify-center text-xs font-bold text-white">
                  {agent.name.charAt(0)}
                </div>
                <div>
                  <div className="font-semibold text-xs text-white line-clamp-1">{agent.name}</div>
                  <div className="text-[10px] text-slate-400 font-mono">{agent.role}</div>
                </div>
              </div>
              <div className="text-[10px] text-slate-300 line-clamp-1 italic bg-white/[0.04] p-1.5 rounded">
                {agent.currentTask || 'Idle'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

