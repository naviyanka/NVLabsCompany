import type { Agent2D } from './types';

interface AgentsBottomBarProps {
  agents: Agent2D[];
  selectedAgentId: string | null;
  onSelectAgent: (agent: Agent2D) => void;
}

export function AgentsBottomBar({
  agents,
  selectedAgentId,
  onSelectAgent,
}: AgentsBottomBarProps) {
  return (
    <footer className="h-16 px-4 bg-[#0A0A0B]/90 backdrop-blur border-t border-white/[0.08] flex items-center gap-3 overflow-x-auto shrink-0 z-20 select-none scrollbar-thin scrollbar-thumb-white/10">
      <span className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider shrink-0 hidden sm:block">
        ACTIVE WORKFORCE ({agents.length}):
      </span>

      <div className="flex items-center gap-2">
        {agents.map((agent) => {
          const isSelected = agent.id === selectedAgentId;
          return (
            <button
              key={agent.id}
              onClick={() => onSelectAgent(agent)}
              className={`flex items-center gap-2.5 px-3 py-1.5 rounded-lg border text-left transition-all shrink-0 ${
                isSelected
                  ? 'bg-[#FFB020]/15 border-[#FFB020] shadow-md shadow-[#FFB020]/10'
                  : 'bg-white/[0.03] border-white/[0.06] hover:border-white/[0.15] hover:bg-white/[0.06]'
              }`}
            >
              {/* Mini Pixel Avatar */}
              <div
                className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold font-mono shrink-0 shadow-inner"
                style={{
                  backgroundColor: agent.sprite.outfitColor || '#2563EB',
                  color: '#FFFFFF',
                }}
              >
                {agent.name.charAt(0)}
              </div>

              <div>
                <div className="flex items-center gap-1.5">
                  <span
                    className={`text-xs font-bold font-mono ${
                      isSelected ? 'text-[#FFB020]' : 'text-white'
                    }`}
                  >
                    {agent.name}
                  </span>
                  <div
                    className={`w-1.5 h-1.5 rounded-full ${
                      agent.status === 'working'
                        ? 'bg-[#10B981]'
                        : agent.status === 'review'
                        ? 'bg-[#A855F7]'
                        : agent.status === 'idle'
                        ? 'bg-[#F59E0B]'
                        : 'bg-[#6B6B6E]'
                    }`}
                  />
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[10px] text-[#6B6B6E] font-mono truncate max-w-[90px]">
                    {agent.state2D.replace(/_/g, ' ')}
                  </span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </footer>
  );
}
