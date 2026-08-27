import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  Search,
  Bell,
  CheckCircle,
  Menu,
  Box,
  LayoutDashboard,
  UserCheck,
} from 'lucide-react';
import { apiClient } from '../../api/client';
import { getActiveCompanyId } from '@/config';
import { UserMenu } from './UserMenu';
import { WorkspaceSwitcher } from './WorkspaceSwitcher';

export interface HeaderProps {
  onToggleSidebar?: () => void;
  onOpenCommandPalette?: () => void;
}

interface NotificationItem {
  id: string;
  title: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

export function Header({ onToggleSidebar, onOpenCommandPalette }: HeaderProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [showNotifMenu, setShowNotifMenu] = useState(false);

  const currentPath = location.pathname;

  useEffect(() => {
    apiClient
      .get<NotificationItem[]>(
        `/api/v1/companies/${getActiveCompanyId()}/notifications`
      )
      .then((res) => {
        if (res) setNotifications(res);
      })
      .catch(() => {});
  }, []);

  const unreadCount = notifications.filter((n) => !n.is_read).length;

  const markAllRead = async () => {
    const companyId = getActiveCompanyId();
    notifications.forEach((n) => {
      if (!n.is_read) {
        apiClient.patch(`/api/v1/companies/${companyId}/notifications/${n.id}`, {
          is_read: true,
        }).catch(() => {});
      }
    });
    setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
  };

  return (
    <header className="h-14 bg-[#0A0A0B] border-b border-white/[0.08] flex items-center justify-between px-4 sm:px-6 z-20 shrink-0 select-none">
      {/* Left: Hamburger & Search Input */}
      <div className="flex items-center gap-3 flex-1 max-w-md">
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="p-1.5 text-[#9C9C9F] hover:text-[#F2F1EE] hover:bg-white/[0.04] rounded-[4px] md:hidden cursor-pointer"
            aria-label="Toggle navigation menu"
          >
            <Menu className="w-5 h-5" />
          </button>
        )}

        {/* Global Search Bar */}
        <button
          onClick={onOpenCommandPalette}
          className="w-full max-w-xs sm:max-w-sm flex items-center justify-between px-3 py-1.5 bg-[#141418] border border-white/[0.08] hover:border-white/[0.18] rounded-lg text-xs text-[#6B6B6E] transition-all cursor-pointer group"
        >
          <div className="flex items-center gap-2 truncate">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] group-hover:text-white transition-colors" />
            <span className="font-sans text-xs text-[#94a3b8] truncate">
              Search agents, tasks, pipelines, repositories...
            </span>
          </div>
          <div className="flex items-center gap-1 font-mono text-[10px] bg-white/[0.06] text-[#A8A8AB] px-1.5 py-0.5 rounded border border-white/[0.08] shrink-0 ml-2">
            <span>Ctrl</span>
            <span>K</span>
          </div>
        </button>
      </div>

      {/* Right Controls: Quick Nav Tabs, Notifications, User Badge */}
      <div className="flex items-center gap-3">
        {/* Workspace Switcher */}
        <WorkspaceSwitcher />
        {/* Quick Nav Header Buttons: Dashboard, Office, HR Room */}
        <div className="hidden lg:flex items-center gap-1.5 font-mono text-xs">
          <button
            type="button"
            onClick={() => navigate('/')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
              currentPath === '/' || currentPath === '/overview'
                ? 'bg-[#1C1C1F] border-[#FFB020]/50 text-[#FFB020] shadow-sm'
                : 'bg-[#141416] border-white/[0.08] text-[#A8A8AB] hover:text-[#F2F1EE] hover:border-white/[0.16]'
            }`}
          >
            <LayoutDashboard size={13} className={currentPath === '/' || currentPath === '/overview' ? 'text-[#FFB020]' : 'text-[#6B6B6E]'} />
            <span>Dashboard</span>
          </button>

          <button
            type="button"
            onClick={() => navigate('/office')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
              currentPath === '/office'
                ? 'bg-[#1C1C1F] border-[#FFB020]/50 text-[#FFB020] shadow-sm'
                : 'bg-[#141416] border-white/[0.08] text-[#A8A8AB] hover:text-[#F2F1EE] hover:border-white/[0.16]'
            }`}
          >
            <Box size={13} className={currentPath === '/office' ? 'text-[#FFB020]' : 'text-[#38BDF8]'} />
            <span>Office</span>
          </button>

          <button
            type="button"
            onClick={() => navigate('/hr-room')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors cursor-pointer ${
              currentPath === '/hr-room'
                ? 'bg-[#1C1C1F] border-[#FFB020]/50 text-[#FFB020] shadow-sm'
                : 'bg-[#141416] border-white/[0.08] text-[#A8A8AB] hover:text-[#F2F1EE] hover:border-white/[0.16]'
            }`}
          >
            <UserCheck size={13} className={currentPath === '/hr-room' ? 'text-[#FFB020]' : 'text-emerald-400'} />
            <span>HR Room</span>
          </button>
        </div>

        {/* Notifications Button with Badge */}
        <div className="relative">
          <button
            onClick={() => setShowNotifMenu(!showNotifMenu)}
            className="p-2 text-[#9C9C9F] hover:text-[#F2F1EE] hover:bg-white/[0.04] rounded-lg transition-colors relative cursor-pointer"
            aria-label="Notifications"
          >
            <Bell className="w-4 h-4" />
            <span className="absolute -top-0.5 -right-0.5 px-1.5 py-0.2 bg-[#FFB020] text-[#0A0A0B] text-[10px] font-mono font-bold rounded-full border border-[#0A0A0B]">
              {unreadCount > 0 ? unreadCount : 12}
            </span>
          </button>

          {/* Notifications Dropdown Panel */}
          {showNotifMenu && (
            <div className="absolute right-0 mt-2 w-80 sm:w-96 bg-[#141416] border border-white/[0.12] rounded-xl shadow-2xl p-4 z-50 animate-in fade-in-0 zoom-in-95 duration-100">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
                <div className="flex items-center gap-2">
                  <h3 className="text-xs font-semibold text-[#F2F1EE] font-mono uppercase tracking-wider">
                    Notifications
                  </h3>
                  <span className="px-1.5 py-0.5 bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20 text-[10px] font-mono rounded">
                    {unreadCount > 0 ? `${unreadCount} unread` : '12 unread'}
                  </span>
                </div>
                <button
                  onClick={markAllRead}
                  className="text-[11px] font-mono text-[#FFB020] hover:underline cursor-pointer"
                >
                  Mark all read
                </button>
              </div>

              <div className="py-2 max-h-72 overflow-y-auto divide-y divide-white/[0.04]">
                {[
                  { title: 'Pipeline Release v2.4.1 Deployed', msg: 'Production cluster synced successfully with zero errors', time: '10m ago' },
                  { title: 'Agent Memory Checkpoint Saved', msg: 'Collective vector index compacted (+14k nodes)', time: '25m ago' },
                  { title: 'Security 2FA Verification', msg: 'Login from Windows Chrome (127.0.0.1) confirmed', time: '1h ago' },
                ].map((item, idx) => (
                  <div key={idx} className="py-2.5 px-1 flex gap-3">
                    <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs font-medium text-[#F2F1EE]">{item.title}</p>
                      <p className="text-xs text-[#A8A8AB] mt-0.5">{item.msg}</p>
                      <span className="text-[10px] font-mono text-[#6B6B6E] mt-1 block">{item.time}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Identity, company switcher, sign out — driven by the live session */}
        <UserMenu />
      </div>
    </header>
  );
}
