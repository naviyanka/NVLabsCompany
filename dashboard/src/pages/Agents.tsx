import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgentList } from '@/components/agents/AgentList';
import { AgentChatDrawer } from '@/components/agents/AgentChatDrawer';
import { Button } from '@/components/common/Button';
import { useApi } from '@/hooks/useApi';
import { listAgents, deleteAgent } from '@/api/agents';
import type { Agent } from '@/types/agent';
import { UserPlus, Users } from 'lucide-react';
import { HireAgentModal } from '@/components/agents/HireAgentModal';

export function Agents() {
  const [showHireModal, setShowHireModal] = useState(false);
  const [chatAgent, setChatAgent] = useState<Agent | null>(null);
  const navigate = useNavigate();

  const { data: agents, loading, error, refetch } = useApi<Agent[]>(
    () => listAgents(),
    []
  );

  const displayAgents = agents || [];

  const handleAgentClick = (agent: Agent) => {
    navigate(`/agents/${agent.id}`);
  };

  const handleAgentChat = (agent: Agent) => {
    setChatAgent(agent);
  };

  const handleAgentFire = async (agent: Agent) => {
    try {
      await deleteAgent(agent.id);
      refetch();
    } catch (err) {
      console.error('Failed to fire agent', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Workforce Agents Directory
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Active autonomous models, capabilities, and telemetry scores
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<UserPlus size={15} />}
          onClick={() => setShowHireModal(true)}
        >
          Hire Agent
        </Button>
      </div>

      <AgentList
        agents={displayAgents}
        loading={loading}
        error={error ? error.message : null}
        onAgentClick={handleAgentClick}
        onAgentChat={handleAgentChat}
        onAgentFire={handleAgentFire}
        onHireAgent={() => setShowHireModal(true)}
      />

      {/* Enhanced Hire Agent Modal */}
      <HireAgentModal
        isOpen={showHireModal}
        onClose={() => setShowHireModal(false)}
        onSuccess={() => {
          setShowHireModal(false);
          refetch();
        }}
      />

      {/* Agent Chat Drawer */}
      <AgentChatDrawer
        agent={chatAgent}
        isOpen={!!chatAgent}
        onClose={() => setChatAgent(null)}
      />
    </div>
  );
}
