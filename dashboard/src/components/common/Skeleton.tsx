export interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'rectangular' | 'circular' | 'card' | 'table';
  count?: number;
}

export function Skeleton({
  className = '',
  variant = 'rectangular',
  count = 1,
}: SkeletonProps) {
  const base = 'animate-pulse bg-white/[0.04] border border-white/[0.04]';

  if (variant === 'circular') {
    return <div className={`${base} rounded-full ${className}`} />;
  }

  if (variant === 'card') {
    return (
      <div className="p-6 bg-[#141416] border border-white/[0.08] rounded-[10px] space-y-4">
        <div className="flex justify-between items-center">
          <div className="h-4 w-1/3 bg-white/[0.06] rounded-[4px] animate-pulse" />
          <div className="h-4 w-12 bg-white/[0.04] rounded-[4px] animate-pulse" />
        </div>
        <div className="h-8 w-2/3 bg-white/[0.08] rounded-[4px] animate-pulse" />
        <div className="h-3 w-full bg-white/[0.04] rounded-[4px] animate-pulse" />
      </div>
    );
  }

  if (variant === 'table') {
    return (
      <div className="w-full bg-[#141416] border border-white/[0.08] rounded-[10px] overflow-hidden">
        <div className="h-10 bg-[#101012] border-b border-white/[0.06]" />
        {Array.from({ length: count || 5 }).map((_, i) => (
          <div key={i} className="h-14 border-b border-white/[0.04] px-4 flex items-center gap-4">
            <div className="h-4 w-1/4 bg-white/[0.05] rounded-[4px] animate-pulse" />
            <div className="h-4 w-1/4 bg-white/[0.04] rounded-[4px] animate-pulse" />
            <div className="h-4 w-1/4 bg-white/[0.03] rounded-[4px] animate-pulse" />
            <div className="h-4 w-1/6 bg-white/[0.04] rounded-[4px] animate-pulse ml-auto" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className={`${base} rounded-[4px] ${className || 'h-4 w-full'}`}
        />
      ))}
    </>
  );
}
