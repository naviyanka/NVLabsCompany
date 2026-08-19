import type { ReactNode } from 'react';

export interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
  onClick?: () => void;
}

const paddingClasses = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
};

export function Card({ children, className = '', padding = 'md', onClick }: CardProps) {
  const baseClasses = 'bg-[#1a1b2e] rounded-xl border border-white/[0.08]';
  const interactiveClasses = onClick ? 'cursor-pointer hover:bg-[#1e2035] transition-colors' : '';
  const padClass = paddingClasses[padding];

  return (
    <div
      className={`${baseClasses} ${interactiveClasses} ${padClass} ${className}`}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter') onClick(); } : undefined}
    >
      {children}
    </div>
  );
}
