import { Card } from '@/components/common/Card';
import { Users, ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

export interface OrgNode {
  id: string;
  name: string;
  title: string;
  type: 'ceo' | 'department' | 'team' | 'agent';
  agentCount?: number;
  taskCount?: number;
  children?: OrgNode[];
}

export interface OrgChartProps {
  data: OrgNode[];
  className?: string;
}

function OrgNodeItem({ node, depth = 0 }: { node: OrgNode; depth?: number }) {
  const [expanded, setExpanded] = useState(depth < 2);
  const hasChildren = node.children && node.children.length > 0;

  const typeColors: Record<string, string> = {
    ceo: 'border-l-primary-500 bg-primary-50',
    department: 'border-l-emerald-500 bg-emerald-50',
    team: 'border-l-amber-500 bg-amber-50',
    agent: 'border-l-gray-300 bg-gray-50',
  };

  return (
    <div className={`${depth > 0 ? 'ml-6' : ''}`}>
      <div
        className={`flex items-center gap-3 px-4 py-3 rounded-lg border-l-4 ${typeColors[node.type]} cursor-pointer mb-2`}
        onClick={() => setExpanded(!expanded)}
      >
        {hasChildren ? (
          expanded ? <ChevronDown size={16} className="text-gray-500" /> : <ChevronRight size={16} className="text-gray-500" />
        ) : (
          <div className="w-4" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-gray-900">{node.name}</span>
            <span className="text-xs text-gray-500">{node.title}</span>
          </div>
          {(node.agentCount !== undefined || node.taskCount !== undefined) && (
            <div className="flex items-center gap-3 mt-0.5 text-xs text-gray-500">
              {node.agentCount !== undefined && (
                <span className="flex items-center gap-1">
                  <Users size={12} />
                  {node.agentCount} agents
                </span>
              )}
              {node.taskCount !== undefined && (
                <span>{node.taskCount} active tasks</span>
              )}
            </div>
          )}
        </div>
      </div>
      {expanded && hasChildren && (
        <div>
          {node.children!.map((child) => (
            <OrgNodeItem key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function OrgChart({ data, className = '' }: OrgChartProps) {
  if (data.length === 0) {
    return (
      <Card className={className}>
        <p className="text-sm text-gray-500 text-center py-8">No organization structure defined yet.</p>
      </Card>
    );
  }

  return (
    <div className={className}>
      {data.map((node) => (
        <OrgNodeItem key={node.id} node={node} />
      ))}
    </div>
  );
}
