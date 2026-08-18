import { Card } from '@/components/common/Card';
import { Users, Briefcase } from 'lucide-react';

export interface DepartmentCardProps {
  name: string;
  agentCount: number;
  activeTaskCount: number;
  color?: string;
  onClick?: () => void;
}

export function DepartmentCard({ name, agentCount, activeTaskCount, onClick }: DepartmentCardProps) {
  return (
    <Card onClick={onClick} className="hover:border-primary-200">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">{name}</h3>
      <div className="flex items-center gap-4 text-sm text-gray-500">
        <span className="flex items-center gap-1.5">
          <Users size={14} className="text-primary-500" />
          {agentCount} agents
        </span>
        <span className="flex items-center gap-1.5">
          <Briefcase size={14} className="text-emerald-500" />
          {activeTaskCount} active tasks
        </span>
      </div>
    </Card>
  );
}
