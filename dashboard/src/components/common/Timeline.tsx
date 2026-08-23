import type { ReactNode } from 'react';

export interface TimelineItem {
  id: string;
  title: string;
  timestamp: string;
  description?: string;
  actor?: string;
  icon?: ReactNode;
  status?: 'success' | 'warning' | 'danger' | 'info' | 'neutral';
  link?: string;
  onItemClick?: () => void;
}

export interface TimelineProps {
  items: TimelineItem[];
  className?: string;
}

export function Timeline({ items, className = '' }: TimelineProps) {
  const dotColors = {
    success: 'bg-[#22C55E]',
    warning: 'bg-[#F97316]',
    danger: 'bg-[#EF4444]',
    info: 'bg-[#38BDF8]',
    neutral: 'bg-[#6B6B6E]',
  };

  return (
    <div className={`space-y-4 relative before:absolute before:left-3 before:top-2 before:bottom-2 before:w-px before:bg-white/[0.08] ${className}`}>
      {items.map((item) => (
        <div
          key={item.id}
          onClick={item.onItemClick}
          className={`relative pl-8 flex flex-col group ${item.onItemClick ? 'cursor-pointer' : ''}`}
        >
          {/* Status Dot */}
          <div
            className={`absolute left-[9px] top-1.5 w-2 h-2 rounded-full ring-4 ring-[#141416] shrink-0 ${
              dotColors[item.status || 'neutral']
            }`}
          />

          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
              {item.title}
            </span>
            <span className="font-mono text-[#6B6B6E] text-[11px] shrink-0">
              {new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
            </span>
          </div>

          {item.description && (
            <p className="text-xs text-[#9C9C9F] mt-0.5 leading-relaxed">{item.description}</p>
          )}

          {item.actor && (
            <span className="text-[11px] font-mono text-[#6B6B6E] mt-1">
              by <span className="text-[#A8A8AB]">{item.actor}</span>
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
