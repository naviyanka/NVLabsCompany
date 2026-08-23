import type { ReactNode, HTMLAttributes } from 'react';

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  header?: ReactNode;
  footer?: ReactNode;
  className?: string;
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

const paddingClasses = {
  none: 'p-0',
  sm: 'p-4',
  md: 'p-6',
  lg: 'p-8',
};

export function Card({
  children,
  header,
  footer,
  className = '',
  padding = 'md',
  ...props
}: CardProps) {
  return (
    <div
      className={`bg-[#141416] border border-white/[0.08] rounded-[10px] transition-colors duration-150 ${className}`}
      {...props}
    >
      {header && (
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between">
          {header}
        </div>
      )}
      <div className={paddingClasses[padding]}>{children}</div>
      {footer && (
        <div className="px-6 py-3.5 border-t border-white/[0.06] bg-white/[0.01]">
          {footer}
        </div>
      )}
    </div>
  );
}
