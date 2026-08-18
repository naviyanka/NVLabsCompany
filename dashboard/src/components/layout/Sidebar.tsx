import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  ListTodo,
  Network,
  GitPullRequest,
  Shield,
  DollarSign,
  Dna,
  Activity,
  Settings,
} from 'lucide-react';

interface NavItem {
  label: string;
  path: string;
  icon: React.ReactNode;
}

const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: <LayoutDashboard size={20} /> },
  { label: 'Agents', path: '/agents', icon: <Bot size={20} /> },
  { label: 'Tasks', path: '/tasks', icon: <ListTodo size={20} /> },
  { label: 'Organization', path: '/organization', icon: <Network size={20} /> },
  { label: 'Workflows', path: '/workflows', icon: <GitPullRequest size={20} /> },
  { label: 'Approvals', path: '/approvals', icon: <Shield size={20} /> },
  { label: 'Budgets', path: '/budgets', icon: <DollarSign size={20} /> },
  { label: 'Evolution', path: '/evolution', icon: <Dna size={20} /> },
  { label: 'Activity', path: '/activity', icon: <Activity size={20} /> },
  { label: 'Settings', path: '/settings', icon: <Settings size={20} /> },
];

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 bottom-0 w-64 bg-sidebar flex flex-col z-30">
      <div className="flex items-center gap-3 px-5 py-5 border-b border-white/10">
        <div className="h-8 w-8 bg-primary-500 rounded-lg flex items-center justify-center">
          <span className="text-white font-bold text-sm">N</span>
        </div>
        <span className="text-white font-semibold text-lg">NEXUS</span>
      </div>

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
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-3 border-t border-white/10">
        <p className="text-xs text-gray-500">NEXUS Dashboard v1.0</p>
      </div>
    </aside>
  );
}
