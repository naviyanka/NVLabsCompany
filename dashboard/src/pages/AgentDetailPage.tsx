import { useParams } from 'react-router-dom';
import { AgentDetail } from '@/components/agents/AgentDetail';
import { useAgent } from '@/hooks/useAgents';

const COMPANY_ID = 'default';

export function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: agent, loading, error } = useAgent(COMPANY_ID, id ?? '');

  return <AgentDetail agent={agent} loading={loading} error={error} />;
}
