import type { MockAgent3D } from '@/config/office3dLayout';
import { mockAgents3D, managerAgent } from '@/config/office3dLayout';

interface AgentsAtGlanceProps {
  onAgentClick: (agent: MockAgent3D) => void;
  selectedAgentId: string | null;
}

export function AgentsAtGlance({ onAgentClick, selectedAgentId }: AgentsAtGlanceProps) {
  const allAgents = [...mockAgents3D, managerAgent];

  return (
    <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 max-w-4xl w-[90%] bg-black/80 backdrop-blur-md border border-white/[0.08] rounded-xl p-2 flex items-center gap-2 overflow-x-auto">
      {allAgents.map((agent) => (
        <button
          key={agent.id}
          onClick={() => onAgentClick(agent)}
          className={`px-3 py-1.5 rounded-lg flex items-center gap-2 shrink-0 border transition-all ${
            selectedAgentId === agent.id
              ? 'bg-[#FFB020]/20 border-[#FFB020] text-white'
              : 'bg-white/[0.03] border-white/[0.06] text-slate-300 hover:bg-white/[0.08]'
          }`}
        >
          <div className="w-5 h-5 rounded-full bg-emerald-600 flex items-center justify-center text-[10px] font-bold text-white">
            {agent.name.charAt(0)}
          </div>
          <div className="text-left text-xs">
            <div className="font-semibold leading-tight">{agent.name}</div>
            <div className="text-[9px] text-slate-400 font-mono">{agent.status}</div>
          </div>
        </button>
      ))}
    </div>
  );
}

