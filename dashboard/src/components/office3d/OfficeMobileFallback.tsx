import type { MockAgent3D } from '@/config/office3dLayout';
import { mockAgents3D, managerAgent } from '@/config/office3dLayout';

interface OfficeMobileFallbackProps {
  selectedAgent: MockAgent3D | null;
  onAgentClick: (agent: MockAgent3D) => void;
  onCloseSidebar: () => void;
  onViewProfile: (agent: MockAgent3D) => void;
}

export function OfficeMobileFallback({
  onAgentClick,
  onViewProfile,
}: OfficeMobileFallbackProps) {
  const allAgents = [...mockAgents3D, managerAgent];

  return (
    <div className="p-4 space-y-3 bg-[#08080A] min-h-screen text-white">
      <h2 className="font-bold text-lg">Office Agents Fleet</h2>
      <div className="space-y-2">
        {allAgents.map((agent) => (
          <div
            key={agent.id}
            onClick={() => onAgentClick(agent)}
            className="p-3 rounded-lg bg-black/60 border border-white/[0.08] flex items-center justify-between"
          >
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-full bg-emerald-600 flex items-center justify-center text-xs font-bold text-white">
                {agent.name.charAt(0)}
              </div>
              <div>
                <div className="font-semibold text-sm">{agent.name}</div>
                <div className="text-xs text-slate-400 font-mono">{agent.role}</div>
              </div>
            </div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onViewProfile(agent);
              }}
              className="px-2.5 py-1 rounded bg-[#FFB020] text-black text-xs font-bold"
            >
              Profile
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

