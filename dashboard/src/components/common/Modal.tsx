import { useEffect, type ReactNode } from 'react';
import { X } from 'lucide-react';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
}

const sizeClasses = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-3xl',
};

export function Modal({ isOpen, onClose, title, children, size = 'md' }: ModalProps) {
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
    }
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div
        className="fixed inset-0 bg-[#0A0A0B]/80 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={`relative bg-[#1C1C1F] border border-white/[0.14] rounded-[10px] w-full ${sizeClasses[size]} max-h-[90vh] flex flex-col overflow-hidden shadow-2xl z-10`}
      >
        {title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-white/[0.08] shrink-0 bg-[#17171A]">
            <h2 className="text-base font-display font-medium text-[#F2F1EE] tracking-tight">{title}</h2>
            <button
              onClick={onClose}
              className="p-1 text-[#9C9C9F] hover:text-[#F2F1EE] hover:bg-white/[0.06] rounded-[4px] transition-colors"
              aria-label="Close modal"
            >
              <X size={18} />
            </button>
          </div>
        )}
        <div className="p-6 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
