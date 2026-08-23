import type { ButtonHTMLAttributes, ReactNode } from 'react';

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'danger-solid';
export type ButtonSize = 'sm' | 'md' | 'lg' | 'xs';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  children: ReactNode;
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: ReactNode;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-[#FFB020] text-[#0A0A0B] font-medium hover:bg-[#FFC04D] active:bg-[#E59E1C] shadow-sm',
  secondary: 'bg-transparent border border-white/[0.12] text-[#F2F1EE] hover:bg-white/[0.04] hover:border-white/[0.2]',
  danger: 'bg-transparent border border-[#EF4444]/40 text-[#EF4444] hover:bg-[#EF4444]/10 hover:border-[#EF4444]/60',
  'danger-solid': 'bg-[#EF4444] text-white hover:bg-[#DC2626]',
  ghost: 'bg-transparent text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.04]',
};

const sizeClasses: Record<ButtonSize, string> = {
  xs: 'px-2.5 py-1 text-xs',
  sm: 'px-3 py-1.5 text-xs font-medium',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-2.5 text-base',
};

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  loading = false,
  icon,
  disabled,
  className = '',
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-[6px] transition-all duration-150 select-none focus:outline-none focus-visible:ring-1 focus-visible:ring-[#FFB020]/60 focus-visible:ring-offset-1 focus-visible:ring-offset-[#0A0A0B] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      ) : icon ? (
        <span className="shrink-0">{icon}</span>
      ) : null}
      <span>{children}</span>
    </button>
  );
}
