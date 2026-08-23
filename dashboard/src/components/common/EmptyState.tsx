import type { ReactNode } from 'react';
import { Button } from './Button';

export interface EmptyStateProps {
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  icon?: ReactNode;
  className?: string;
}

export function EmptyState({
  title,
  description,
  actionLabel,
  onAction,
  icon,
  className = '',
}: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center p-12 text-center bg-[#141416] border border-white/[0.08] rounded-[10px] ${className}`}
    >
      {icon && (
        <div className="w-10 h-10 rounded-[6px] bg-white/[0.03] border border-white/[0.06] flex items-center justify-center text-[#6B6B6E] mb-3 shrink-0">
          {icon}
        </div>
      )}
      <h3 className="text-sm font-display font-medium text-[#F2F1EE]">{title}</h3>
      <p className="text-xs text-[#9C9C9F] max-w-sm mt-1 mb-4 leading-relaxed">{description}</p>
      {actionLabel && onAction && (
        <Button variant="primary" size="sm" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  );
}
