import {
  Activity,
  BookOpen,
  Box,
  Boxes,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  Database,
  DollarSign,
  GitBranch,
  GitPullRequest,
  LayoutDashboard,
  Network,
  Settings,
  Share2,
  Shield,
  Sparkles,
  Target,
  TrendingUp,
  UserCheck,
  Users,
  Video,
  Wrench,
  Zap
} from 'lucide-react';
import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

import type { LucideIcon } from 'lucide-react';

export interface SidebarProps {
  isMobileOpen?: boolean;
  onCloseMobile?: () => void;
}

interface NavItem {
  name: string;
  to: string;
  icon: LucideIcon;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    label: 'OPERATIONS',
    items: [
      { name: 'Ops Floor', to: '/', icon: LayoutDashboard },
      { name: 'The Plaza Feed', to: '/plaza', icon: Sparkles },
      { name: '3D Virtual Office', to: '/office', icon: Box },
      { name: 'Workforce Agents', to: '/agents', icon: Users },
      { name: 'Task Operations', to: '/tasks', icon: CheckSquare },
      { name: 'Pipelines', to: '/pipelines', icon: GitPullRequest },
      { name: 'Workflows', to: '/workflows', icon: Zap },
      { name: 'Node Library', to: '/nodes', icon: Boxes },
    ],
  },
  {
    label: 'ORGANIZATION',
    items: [
      { name: 'Strategic Goals', to: '/goals', icon: Target },
      { name: 'Standups & Syncs', to: '/meetings', icon: Video },
      { name: 'Org Hierarchy', to: '/organization', icon: Network },
      { name: 'Skills Matrix', to: '/skills', icon: Shield },
      { name: 'Tools Access', to: '/tools', icon: Wrench },
      { name: 'HR & Review', to: '/hr-room', icon: UserCheck },
    ],
  },
  {
    label: 'GOVERNANCE & DATA',
    items: [
      { name: 'Budgets & Limits', to: '/budgets', icon: DollarSign },
      { name: 'Evolution & Evals', to: '/evolution', icon: TrendingUp },
      { name: 'Memory Graph', to: '/memory-graph', icon: Share2 },
      { name: 'Collective Memory', to: '/memory', icon: Database },
      { name: 'Knowledge Plaza', to: '/knowledge', icon: BookOpen },
      { name: 'Source Repos', to: '/git-repos', icon: GitBranch },
      { name: 'Telemetry Audit', to: '/activity', icon: Activity },
      { name: 'Settings & Control', to: '/settings', icon: Settings },
    ],
  },
];

export function Sidebar({ isMobileOpen = false, onCloseMobile }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('nexus_sidebar_collapsed') === 'true';
    } catch {
      return false;
    }
  });

  const location = useLocation();

  useEffect(() => {
    try {
      localStorage.setItem('nexus_sidebar_collapsed', String(collapsed));
    } catch {
      // ignore
    }
  }, [collapsed]);

  const toggleCollapsed = () => setCollapsed(!collapsed);

  return (
    <>
      {/* Mobile Backdrop */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 bg-[#0A0A0B]/80 z-40 md:hidden"
          onClick={onCloseMobile}
          aria-hidden="true"
        />
      )}

      {/* Sidebar Container */}
      <aside
        className={`fixed md:static inset-y-0 left-0 z-40 bg-[#0E0E10] border-r border-white/[0.08] flex flex-col transition-all duration-200 select-none ${collapsed ? 'w-16' : 'w-60'
          } ${isMobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
          }`}
      >
        {/* Brand Header */}
        <div className="h-14 flex items-center justify-between px-4 border-b border-white/[0.08] shrink-0 bg-[#0A0A0B]">
          <div className="flex items-center gap-2.5 overflow-hidden">
            {/* Minimalist Nexus Monogram */}
            <div className="w-7 h-7 rounded-[4px] bg-[#FFB020] flex items-center justify-center text-[#0A0A0B] font-bold font-display text-sm shrink-0">
              N
            </div>
            {!collapsed && (
              <div className="flex flex-col">
                <span className="font-display font-bold text-sm tracking-wide text-[#F2F1EE]">
                  NEXUS
                </span>
                <span className="font-mono text-[9px] text-[#6B6B6E] tracking-wider uppercase">
                  MISSION CONTROL
                </span>
              </div>
            )}
          </div>

          <button
            onClick={toggleCollapsed}
            className="hidden md:flex p-1 text-[#6B6B6E] hover:text-[#F2F1EE] hover:bg-white/[0.04] rounded-[4px] transition-colors cursor-pointer"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>

        {/* Navigation Menu Links */}
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-5">
          {navGroups.map((group) => (
            <div key={group.label} className="space-y-1">
              {!collapsed && (
                <div className="px-3 text-[10px] font-mono font-medium text-[#6B6B6E] uppercase tracking-wider mb-1.5">
                  {group.label}
                </div>
              )}
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive =
                  item.to === '/'
                    ? location.pathname === '/' || location.pathname === '/overview'
                    : location.pathname.startsWith(item.to);

                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    onClick={onCloseMobile}
                    className={`sidebar-link flex items-center gap-3 px-3 py-2 text-xs transition-colors rounded-[4px] relative ${isActive ? 'active' : ''
                      } ${collapsed ? 'justify-center px-0' : ''}`}
                    title={collapsed ? item.name : undefined}
                  >
                    <Icon className={`w-4 h-4 shrink-0 ${isActive ? 'text-[#FFB020]' : 'text-[#6B6B6E]'}`} />
                    {!collapsed && (
                      <span className="truncate font-sans">{item.name}</span>
                    )}
                  </NavLink>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Bottom Operational Status Card */}
        <div className="p-3 border-t border-white/[0.08] bg-[#0A0A0B] shrink-0">
          {!collapsed ? (
            <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded-[6px] space-y-2">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-[#6B6B6E]">OPERATIONAL STATE</span>
                <span className="flex items-center gap-1 text-[#22C55E]">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E] animate-pulse" />
                  NOMINAL
                </span>
              </div>
              <div className="flex items-center justify-between text-[10px] font-mono text-[#A8A8AB]">
                <span>Spend MTD</span>
                <span className="text-[#F2F1EE] font-medium">$4,235 / $10k (42%)</span>
              </div>
              <div className="w-full bg-white/[0.06] h-1 rounded-full overflow-hidden">
                <div className="bg-[#FFB020] h-full" style={{ width: '42%' }} />
              </div>
            </div>
          ) : (
            <div className="flex justify-center" title="Nominal State · $4.2k Spend">
              <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
