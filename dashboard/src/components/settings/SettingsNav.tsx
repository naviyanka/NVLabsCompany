import { useState } from 'react';
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
  Search,
} from 'lucide-react';
import type { SettingsTabId } from './types';

interface SettingsNavProps {
  activeTab: SettingsTabId;
  onSelectTab: (tab: SettingsTabId) => void;
}

interface NavItem {
  id: SettingsTabId;
  label: string;
  icon: typeof User;
  badge?: string;
}

interface NavCategoryGroup {
  groupName: string;
  items: NavItem[];
}

const categoryGroups: NavCategoryGroup[] = [
  {
    groupName: 'Account & Identity',
    items: [
      { id: 'profile', label: 'Profile Settings', icon: User },
      { id: 'security', label: 'Security & Auth', icon: Shield },
      { id: 'api_keys', label: 'API Access Keys', icon: Key, badge: 'Live' },
    ],
  },
  {
    groupName: 'Workspace & Governance',
    items: [
      { id: 'general', label: 'General & Workspace', icon: Sliders },
      { id: 'teams', label: 'Teams & Users', icon: Users },
      { id: 'roles', label: 'Roles & RBAC', icon: ShieldCheck },
      { id: 'billing', label: 'Billing & Subscriptions', icon: CreditCard },
    ],
  },
  {
    groupName: 'Autonomous AI System',
    items: [
      { id: 'system_config', label: 'System Hyperparameters', icon: Settings2, badge: 'v2.4' },
      { id: 'integrations', label: 'Integrations', icon: Boxes },
      { id: 'notifications', label: 'Notification Rules', icon: Bell },
    ],
  },
  {
    groupName: 'Security & Operations',
    items: [
      { id: 'data_storage', label: 'Data & Storage', icon: Database },
      { id: 'backup', label: 'Backup & Restore', icon: RotateCcw },
      { id: 'audit_logs', label: 'Audit Logs', icon: FileText },
      { id: 'appearance', label: 'Theme & Appearance', icon: Palette },
      { id: 'advanced', label: 'Advanced CLI & Tools', icon: Terminal },
    ],
  },
];

export function SettingsNav({ activeTab, onSelectTab }: SettingsNavProps) {
  const [search, setSearch] = useState('');

  const filteredGroups = categoryGroups
    .map((grp) => ({
      ...grp,
      items: grp.items.filter((item) =>
        item.label.toLowerCase().includes(search.toLowerCase())
      ),
    }))
    .filter((grp) => grp.items.length > 0);

  return (
    <nav className="w-full md:w-64 lg:w-72 shrink-0 space-y-4">
      {/* Quick Search */}
      <div className="relative">
        <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter setting categories..."
          className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-lg text-xs text-white placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
        />
      </div>

      <div className="flex flex-col gap-4 overflow-y-auto max-h-[calc(100vh-14rem)] pr-1 scrollbar-thin">
        {filteredGroups.map((group, gIdx) => (
          <div key={gIdx} className="space-y-1">
            <h3 className="px-3 text-[10px] font-mono font-bold uppercase tracking-wider text-[#6B6B6E]">
              {group.groupName}
            </h3>

            <div className="space-y-0.5">
              {group.items.map((cat) => {
                const Icon = cat.icon;
                const isActive = activeTab === cat.id;

                return (
                  <button
                    key={cat.id}
                    id={`settings-tab-${cat.id}`}
                    type="button"
                    onClick={() => onSelectTab(cat.id)}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150 text-left cursor-pointer group relative ${
                      isActive
                        ? 'bg-[#1C1C1F] text-[#FFB020] shadow-sm border border-[#FFB020]/30 font-semibold'
                        : 'text-[#A8A8AB] hover:text-[#F2F1EE] hover:bg-white/[0.03] border border-transparent'
                    }`}
                  >
                    {isActive && (
                      <span className="absolute left-0 top-1.5 bottom-1.5 w-0.5 bg-[#FFB020] rounded-r" />
                    )}
                    <Icon
                      size={15}
                      className={`shrink-0 transition-colors ${
                        isActive ? 'text-[#FFB020]' : 'text-[#6B6B6E] group-hover:text-[#A8A8AB]'
                      }`}
                    />
                    <span className="flex-1 truncate">{cat.label}</span>
                    {cat.badge && (
                      <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20">
                        {cat.badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </nav>
  );
}
