import { NavLink } from 'react-router-dom';
import {
  Rocket,
  LayoutDashboard,
  Building2,
  Users,
  Bot,
  ListTodo,
  GitBranch,
  Brain,
  GitFork,
  BookOpen,
  Activity,
  Bell,
  Settings,
  ChevronRight,
} from 'lucide-react';

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
  badge?: string;
  badgeColor?: string;
  hasChevron?: boolean;
}

const navItems: NavItem[] = [
  { label: 'Overview', path: '/', icon: <LayoutDashboard size={18} /> },
  { label: 'Office', path: '/office', icon: <Building2 size={18} /> },
  { label: 'HR Room', path: '/hr-room', icon: <Users size={18} />, badge: 'New', badgeColor: 'bg-green-500' },
  { label: 'Agents', path: '/agents', icon: <Bot size={18} />, hasChevron: true },
  { label: 'Tasks', path: '/tasks', icon: <ListTodo size={18} />, hasChevron: true },
  { label: 'Pipelines', path: '/pipelines', icon: <GitBranch size={18} />, hasChevron: true },
  { label: 'Memory', path: '/memory', icon: <Brain size={18} /> },
  { label: 'Git Repos', path: '/git-repos', icon: <GitFork size={18} /> },
  { label: 'Knowledge Base', path: '/knowledge-base', icon: <BookOpen size={18} /> },
  { label: 'Activity', path: '/activity', icon: <Activity size={18} /> },
  { label: 'Notifications', path: '/notifications', icon: <Bell size={18} />, badge: '12', badgeColor: 'bg-red-500' },
  { label: 'Settings', path: '/settings', icon: <Settings size={18} /> },
];

interface SystemStatusItem {
  label: string;
  status: string;
}

const systemStatus: SystemStatusItem[] = [
  { label: 'Gateway', status: 'Online' },
  { label: 'WebSocket', status: 'Connected' },
  { label: 'Database', status: 'Healthy' },
  { label: 'Memory Store', status: 'Healthy' },
  { label: 'Vector DB', status: 'Healthy' },
];

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 bottom-0 w-64 bg-[#12131f] flex flex-col z-30">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-white/[0.08]">
        <div className="h-9 w-9 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center">
          <Rocket size={18} className="text-white" />
        </div>
        <div>
          <span className="text-white font-bold text-lg tracking-wide">NVLABS</span>
          <p className="text-xs text-gray-500">Mission Control</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `sidebar-link ${isActive ? 'sidebar-link-active' : 'sidebar-link-inactive'}`
            }
          >
            {item.icon}
            <span className="flex-1">{item.label}</span>
            {item.badge && (
              <span className={`${item.badgeColor} text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full`}>
                {item.badge}
              </span>
            )}
            {item.hasChevron && <ChevronRight size={14} className="text-gray-500" />}
          </NavLink>
        ))}
      </nav>

      {/* System Status */}
      <div className="px-4 py-3 border-t border-white/[0.08]">
        <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-2">System Status</p>
        <div className="space-y-1.5">
          {systemStatus.map((item) => (
            <div key={item.label} className="flex items-center justify-between">
              <span className="text-xs text-gray-400">{item.label}</span>
              <div className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                <span className="text-[10px] text-green-400">{item.status}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* User Profile */}
      <div className="px-4 py-3 border-t border-white/[0.08] flex items-center gap-3">
        <div className="h-8 w-8 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-full flex items-center justify-center">
          <span className="text-white text-xs font-bold">NY</span>
        </div>
        <div>
          <p className="text-sm text-white font-medium">Navi Yanka</p>
          <p className="text-[10px] text-gray-500">Administrator</p>
        </div>
      </div>
    </aside>
  );
}
