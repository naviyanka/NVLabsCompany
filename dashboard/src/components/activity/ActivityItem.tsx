import { Bot, CheckCircle, AlertTriangle, Info, Zap } from 'lucide-react';
import { formatRelativeTime } from '@/utils/time';

export interface ActivityEntry {
  id: string;
  type: 'agent_action' | 'task_completed' | 'task_failed' | 'approval_request' | 'system' | 'evolution';
  message: string;
  timestamp: string;
  agentName?: string;
}

export interface ActivityItemProps {
  entry: ActivityEntry;
}

function getIcon(type: ActivityEntry['type']) {
  switch (type) {
    case 'agent_action': return <Bot size={14} className="text-primary-500" />;
    case 'task_completed': return <CheckCircle size={14} className="text-emerald-500" />;
    case 'task_failed': return <AlertTriangle size={14} className="text-rose-500" />;
    case 'approval_request': return <Zap size={14} className="text-amber-500" />;
    case 'evolution': return <Zap size={14} className="text-primary-500" />;
    case 'system': return <Info size={14} className="text-gray-400" />;
    default: return <Info size={14} className="text-gray-400" />;
  }
}

export function ActivityItem({ entry }: ActivityItemProps) {
  return (
    <div className="flex items-start gap-3 py-2.5 px-3 rounded-lg hover:bg-gray-50">
      <div className="mt-0.5 flex-shrink-0">
        {getIcon(entry.type)}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-700">{entry.message}</p>
        <div className="flex items-center gap-2 mt-0.5">
          {entry.agentName && (
            <span className="text-xs text-primary-600 font-medium">{entry.agentName}</span>
          )}
          <span className="text-xs text-gray-400">{formatRelativeTime(entry.timestamp)}</span>
        </div>
      </div>
    </div>
  );
}
