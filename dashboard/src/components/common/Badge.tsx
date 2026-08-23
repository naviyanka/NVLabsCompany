import type { ReactNode } from 'react';

export type BadgeVariant =
  | 'active'
  | 'working'
  | 'idle'
  | 'paused'
  | 'completed'
  | 'in_progress'
  | 'pending'
  | 'failed'
  | 'error'
  | 'warning'
  | 'success'
  | 'info'
  | 'neutral'
  | 'amber'
  | 'primary'
  | 'danger'
  | 'default';

export interface BadgeProps {
  children: ReactNode;
  variant?: BadgeVariant;
  dot?: boolean;
  size?: 'sm' | 'md' | 'lg' | string;
  className?: string;
}

const statusConfig: Record<BadgeVariant, { dotColor: string; textColor: string; bgColor: string }> = {
  active: { dotColor: 'bg-[#22C55E]', textColor: 'text-[#22C55E]', bgColor: 'bg-[#22C55E]/10' },
  working: { dotColor: 'bg-[#22C55E]', textColor: 'text-[#22C55E]', bgColor: 'bg-[#22C55E]/10' },
  success: { dotColor: 'bg-[#22C55E]', textColor: 'text-[#22C55E]', bgColor: 'bg-[#22C55E]/10' },
  completed: { dotColor: 'bg-[#22C55E]', textColor: 'text-[#22C55E]', bgColor: 'bg-[#22C55E]/10' },
  
  in_progress: { dotColor: 'bg-[#38BDF8]', textColor: 'text-[#38BDF8]', bgColor: 'bg-[#38BDF8]/10' },
  info: { dotColor: 'bg-[#38BDF8]', textColor: 'text-[#38BDF8]', bgColor: 'bg-[#38BDF8]/10' },
  primary: { dotColor: 'bg-[#FFB020]', textColor: 'text-[#FFB020]', bgColor: 'bg-[#FFB020]/10' },
  
  warning: { dotColor: 'bg-[#F97316]', textColor: 'text-[#F97316]', bgColor: 'bg-[#F97316]/10' },
  amber: { dotColor: 'bg-[#FFB020]', textColor: 'text-[#FFB020]', bgColor: 'bg-[#FFB020]/10' },
  
  failed: { dotColor: 'bg-[#EF4444]', textColor: 'text-[#EF4444]', bgColor: 'bg-[#EF4444]/10' },
  error: { dotColor: 'bg-[#EF4444]', textColor: 'text-[#EF4444]', bgColor: 'bg-[#EF4444]/10' },
  danger: { dotColor: 'bg-[#EF4444]', textColor: 'text-[#EF4444]', bgColor: 'bg-[#EF4444]/10' },
  
  idle: { dotColor: 'bg-[#6B6B6E]', textColor: 'text-[#9C9C9F]', bgColor: 'bg-white/[0.04]' },
  paused: { dotColor: 'bg-[#6B6B6E]', textColor: 'text-[#9C9C9F]', bgColor: 'bg-white/[0.04]' },
  pending: { dotColor: 'bg-[#6B6B6E]', textColor: 'text-[#9C9C9F]', bgColor: 'bg-white/[0.04]' },
  neutral: { dotColor: 'bg-[#6B6B6E]', textColor: 'text-[#9C9C9F]', bgColor: 'bg-white/[0.04]' },
  default: { dotColor: 'bg-[#6B6B6E]', textColor: 'text-[#9C9C9F]', bgColor: 'bg-white/[0.04]' },
};

export function Badge({
  children,
  variant = 'neutral',
  dot = true,
  className = '',
}: BadgeProps) {
  const config = statusConfig[variant] || statusConfig.neutral;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-[11px] font-mono whitespace-nowrap rounded-[4px] border border-white/[0.06] ${config.bgColor} ${config.textColor} ${className}`}
    >
      {dot && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${config.dotColor}`} />}
      <span className="leading-none">{children}</span>
    </span>
  );
}
