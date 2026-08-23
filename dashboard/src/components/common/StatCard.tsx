import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';

export interface StatCardProps {
  label: string;
  value: string | number;
  subValue?: string;
  change?: string;
  changeType?: 'positive' | 'negative' | 'neutral';
  to?: string;
  icon?: ReactNode;
  className?: string;
}

export function StatCard({
  label,
  value,
  subValue,
  change,
  changeType = 'neutral',
  to,
  icon,
  className = '',
}: StatCardProps) {
  const navigate = useNavigate();

  const changeColors = {
    positive: 'text-[#22C55E]',
    negative: 'text-[#EF4444]',
    neutral: 'text-[#6B6B6E]',
  };

  const handleClick = () => {
    if (to) {
      navigate(to);
    }
  };

  return (
    <div
      onClick={to ? handleClick : undefined}
      className={`p-5 bg-[#141416] border border-white/[0.08] rounded-[10px] transition-all duration-150 relative group ${
        to ? 'cursor-pointer hover:border-white/[0.18] hover:bg-white/[0.02]' : ''
      } ${className}`}
    >
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-xs font-mono text-[#6B6B6E] tracking-wider uppercase truncate">
          {label}
        </span>
        {icon && (
          <div className="text-[#9C9C9F] group-hover:text-[#F2F1EE] transition-colors shrink-0">
            {icon}
          </div>
        )}
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-2xl font-mono font-medium text-[#F2F1EE] tracking-tight">
          {value}
        </span>
        {subValue && (
          <span className="text-xs font-mono text-[#6B6B6E]">{subValue}</span>
        )}
      </div>

      {change && (
        <div className="mt-2 text-xs font-mono flex items-center gap-1.5">
          <span className={changeColors[changeType]}>{change}</span>
        </div>
      )}
    </div>
  );
}
