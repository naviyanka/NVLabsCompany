export type IndicatorStatus = 'online' | 'offline' | 'busy' | 'idle' | 'error';

export interface StatusIndicatorProps {
  status: IndicatorStatus;
  label?: string;
  size?: 'sm' | 'md';
  className?: string;
}

const statusColors: Record<IndicatorStatus, string> = {
  online: 'bg-emerald-500',
  offline: 'bg-gray-400',
  busy: 'bg-amber-500',
  idle: 'bg-sky-400',
  error: 'bg-rose-500',
};

const statusLabels: Record<IndicatorStatus, string> = {
  online: 'Online',
  offline: 'Offline',
  busy: 'Busy',
  idle: 'Idle',
  error: 'Error',
};

const sizeClasses = {
  sm: 'h-2 w-2',
  md: 'h-3 w-3',
};

export function StatusIndicator({ status, label, size = 'sm', className = '' }: StatusIndicatorProps) {
  const displayLabel = label || statusLabels[status];

  return (
    <span className={`inline-flex items-center gap-1.5 ${className}`}>
      <span className={`inline-block rounded-full ${statusColors[status]} ${sizeClasses[size]}`} />
      <span className="text-sm text-gray-600">{displayLabel}</span>
    </span>
  );
}
