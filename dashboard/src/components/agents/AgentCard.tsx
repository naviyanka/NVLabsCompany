import type { Agent } from '@/types/agent';
import { Card } from '@/components/common/Card';
import { StatusIndicator } from '@/components/common/StatusIndicator';
import { Badge } from '@/components/common/Badge';
import { Bot } from 'lucide-react';

export interface AgentCardProps {
  agent: Agent;
  onClick?: (agent: Agent) => void;
}

function agentStatusToIndicator(status: Agent['status']): 'online' | 'offline' | 'busy' | 'idle' | 'error' {
  switch (status) {
    case 'active':
      return 'online';
    case 'idle':
      return 'idle';
    case 'busy':
      return 'busy';
    case 'offline':
      return 'offline';
    case 'error':
      return 'error';
    default:
      return 'offline';
  }
}

export function AgentCard({ agent, onClick }: AgentCardProps) {
  return (
    <Card
      className="hover:border-primary-200"
      onClick={onClick ? () => onClick(agent) : undefined}
    >
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 w-10 h-10 bg-primary-100 text-primary-600 rounded-lg flex items-center justify-center">
          <Bot size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{agent.name}</h3>
            <StatusIndicator status={agentStatusToIndicator(agent.status)} size="sm" />
          </div>
          <p className="text-xs text-gray-500 mt-0.5">{agent.title}</p>
          <div className="flex items-center gap-2 mt-2">
            <Badge variant="primary" size="sm">{agent.role}</Badge>
            <Badge variant="default" size="sm">{agent.model}</Badge>
          </div>
          {agent.objectives && (
            <p className="text-xs text-gray-500 mt-2 truncate">
              {agent.objectives}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
