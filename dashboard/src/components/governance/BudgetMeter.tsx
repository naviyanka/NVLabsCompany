import { formatCents } from '@/utils/time';

export interface BudgetMeterProps {
  usedCents: number;
  totalCents: number;
  label?: string;
  className?: string;
}

export function BudgetMeter({ usedCents, totalCents, label, className = '' }: BudgetMeterProps) {
  const percent = totalCents > 0 ? Math.min((usedCents / totalCents) * 100, 100) : 0;
  const isWarning = percent >= 75;
  const isDanger = percent >= 90;

  const barColor = isDanger
    ? 'bg-rose-500'
    : isWarning
      ? 'bg-amber-500'
      : 'bg-primary-500';

  return (
    <div className={className}>
      {label && (
        <p className="text-sm font-medium text-gray-700 mb-1">{label}</p>
      )}
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
        <span>{formatCents(usedCents)} used</span>
        <span>{formatCents(totalCents)} total</span>
      </div>
      <div className="w-full h-3 bg-gray-200 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${barColor}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-xs text-gray-500 mt-1 text-right">
        {percent.toFixed(1)}% used | {formatCents(totalCents - usedCents)} remaining
      </p>
    </div>
  );
}
