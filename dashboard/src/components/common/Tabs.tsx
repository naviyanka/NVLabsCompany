import type { ReactNode } from 'react';

export interface TabItem {
  id: string;
  label: string;
  count?: number;
  icon?: ReactNode;
}

export interface TabsProps {
  tabs: TabItem[];
  activeTab: string;
  onChange: (tabId: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onChange, className = '' }: TabsProps) {
  return (
    <div className={`flex items-center gap-1 border-b border-white/[0.08] overflow-x-auto ${className}`}>
      {tabs.map((tab) => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => onChange(tab.id)}
            className={`px-4 py-2.5 text-xs font-mono whitespace-nowrap transition-colors relative flex items-center gap-2 cursor-pointer ${
              isActive
                ? 'text-[#FFB020] font-medium'
                : 'text-[#9C9C9F] hover:text-[#F2F1EE] hover:bg-white/[0.02]'
            }`}
          >
            {tab.icon && <span className="shrink-0">{tab.icon}</span>}
            <span>{tab.label}</span>
            {tab.count !== undefined && (
              <span
                className={`px-1.5 py-0.2 rounded-[3px] text-[10px] ${
                  isActive ? 'bg-[#FFB020]/20 text-[#FFB020]' : 'bg-white/[0.06] text-[#6B6B6E]'
                }`}
              >
                {tab.count}
              </span>
            )}
            {isActive && (
              <span className="absolute bottom-0 left-0 right-0 h-[2px] bg-[#FFB020]" />
            )}
          </button>
        );
      })}
    </div>
  );
}
