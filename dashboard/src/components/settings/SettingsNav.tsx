import {
  Sliders,
  User,
  Shield,
  Key,
  Boxes,
  Users,
  ShieldCheck,
  CreditCard,
  Settings2,
  Bell,
  Database,
  RotateCcw,
  FileText,
  Palette,
  Terminal,
} from 'lucide-react';
import type { SettingsTabId } from './types';

interface SettingsNavProps {
  activeTab: SettingsTabId;
  onSelectTab: (tab: SettingsTabId) => void;
}

interface NavCategory {
  id: SettingsTabId;
  label: string;
  icon: typeof User;
  badge?: string;
}

const navCategories: NavCategory[] = [
  { id: 'general', label: 'General', icon: Sliders },
  { id: 'profile', label: 'Profile', icon: User },
  { id: 'security', label: 'Security', icon: Shield },
  { id: 'api_keys', label: 'API Keys', icon: Key },
  { id: 'integrations', label: 'Integrations', icon: Boxes },
  { id: 'teams', label: 'Teams & Users', icon: Users },
  { id: 'roles', label: 'Roles & Permissions', icon: ShieldCheck },
  { id: 'billing', label: 'Billing & Subscription', icon: CreditCard },
  { id: 'system_config', label: 'System Configuration', icon: Settings2 },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'data_storage', label: 'Data & Storage', icon: Database },
  { id: 'backup', label: 'Backup & Restore', icon: RotateCcw },
  { id: 'audit_logs', label: 'Audit Logs', icon: FileText },
  { id: 'appearance', label: 'Appearance', icon: Palette },
  { id: 'advanced', label: 'Advanced', icon: Terminal },
];

export function SettingsNav({ activeTab, onSelectTab }: SettingsNavProps) {
  return (
    <nav className="w-full md:w-60 lg:w-64 shrink-0 flex flex-row md:flex-col gap-1 overflow-x-auto md:overflow-y-auto pb-2 md:pb-0 scrollbar-thin">
      {navCategories.map((cat) => {
        const Icon = cat.icon;
        const isActive = activeTab === cat.id;

        return (
          <button
            key={cat.id}
            id={`settings-tab-${cat.id}`}
            type="button"
            onClick={() => onSelectTab(cat.id)}
            className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-xs font-medium transition-all duration-150 whitespace-nowrap text-left cursor-pointer group relative ${
              isActive
                ? 'bg-[#1C1C1F] text-[#FFB020] shadow-sm border border-[#FFB020]/30 font-semibold'
                : 'text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.03] border border-transparent'
            }`}
          >
            {isActive && (
              <span className="hidden md:block absolute left-0 top-2 bottom-2 w-0.5 bg-[#FFB020] rounded-r" />
            )}
            <Icon
              size={16}
              className={`shrink-0 transition-colors ${
                isActive ? 'text-[#FFB020]' : 'text-[#6B6B6E] group-hover:text-[#A8A8AB]'
              }`}
            />
            <span className="flex-1 truncate">{cat.label}</span>
            {cat.badge && (
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20">
                {cat.badge}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
