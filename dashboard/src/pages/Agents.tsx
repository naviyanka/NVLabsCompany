import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AgentList } from '@/components/agents/AgentList';
import { AgentCreate } from '@/components/agents/AgentCreate';
import { Button } from '@/components/common/Button';
import { Modal } from '@/components/common/Modal';
import { useApi } from '@/hooks/useApi';
import { agentsApi } from '@/api/agents';
import type { Agent, AgentCreateRequest } from '@/types/agent';
import type { PaginatedResponse } from '@/types/common';
import { UserPlus } from 'lucide-react';

const COMPANY_ID = 'default';

export function Agents() {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  const { data, loading, error, refetch } = useApi<PaginatedResponse<Agent>>(
    () => agentsApi.list(COMPANY_ID),
    [COMPANY_ID]
  );

  const agents = data?.items ?? [];

  const handleAgentClick = (agent: Agent) => {
    navigate(`/agents/${agent.id}`);
  };

  const handleCreateAgent = async (formData: AgentCreateRequest) => {
    setCreating(true);
    try {
      await agentsApi.create(COMPANY_ID, formData);
      setShowCreateModal(false);
      refetch();
    } catch {
      // Error handled via toast in future
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Agents</h1>
          <p className="text-sm text-gray-500 mt-1">Manage your AI workforce</p>
        </div>
        <Button icon={<UserPlus size={16} />} onClick={() => setShowCreateModal(true)}>
          Hire Agent
        </Button>
      </div>

      <AgentList
        agents={agents}
        loading={loading}
        error={error}
        onAgentClick={handleAgentClick}
      />

      <Modal isOpen={showCreateModal} onClose={() => setShowCreateModal(false)} title="Hire New Agent" size="lg">
        <AgentCreate
          onSubmit={handleCreateAgent}
          onCancel={() => setShowCreateModal(false)}
          loading={creating}
        />
      </Modal>
    </div>
  );
}
