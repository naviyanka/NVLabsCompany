import { Card } from '@/components/common/Card';
import { Users } from 'lucide-react';

export interface TeamCardProps {
  name: string;
  memberCount: number;
  description?: string;
  onClick?: () => void;
}

export function TeamCard({ name, memberCount, description, onClick }: TeamCardProps) {
  return (
    <Card onClick={onClick} className="hover:border-primary-200">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 bg-amber-100 text-amber-600 rounded-lg flex items-center justify-center">
          <Users size={16} />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-900">{name}</h3>
          {description && (
            <p className="text-xs text-gray-500 truncate">{description}</p>
          )}
        </div>
        <span className="text-xs text-gray-500">{memberCount} members</span>
      </div>
    </Card>
  );
}
