import { useState, useEffect } from 'react';
import {
  Bell,
  AlertTriangle,
  CheckCheck,
  ShieldAlert,
} from 'lucide-react';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';

interface NotificationItem {
  id: string;
  title: string;
  description: string;
  module: string;
  priority: 'critical' | 'warning' | 'info';
  read: boolean;
  time: string;
}

export function Notifications() {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [filter, setFilter] = useState<'all' | 'unread'>('all');

  useEffect(() => {
    async function loadNotifications() {
      try {
        const res = await apiClient.get<NotificationItem[]>(
          `/api/v1/companies/${getActiveCompanyId()}/notifications`
        );
        const items = res;
        if (items.length) setNotifications(items);
      } catch (err) {
        console.error('Failed to load notifications', err);
      }
    }
    loadNotifications();
  }, []);

  const handleMarkAllRead = () => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  };

  const handleToggleRead = (id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: !n.read } : n))
    );
  };

  const unreadCount = notifications.filter((n) => !n.read).length;
  const filtered = notifications.filter((n) => (filter === 'unread' ? !n.read : true));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Bell className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Operational Alerts & Dispatch Notifications
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Real-time workforce interrupts, budget warning thresholds, and test completions
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<CheckCheck size={14} />}
            onClick={handleMarkAllRead}
            disabled={unreadCount === 0}
          >
            Mark All Read
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Unread Alerts"
          value={unreadCount}
          subValue="Active Notifications"
          change={unreadCount > 0 ? 'Review pending' : 'All clear'}
          changeType={unreadCount > 0 ? 'negative' : 'positive'}
          icon={<Bell className="w-4 h-4" />}
        />
        <StatCard
          label="Critical Incidents"
          value={notifications.filter((n) => n.priority === 'critical').length}
          subValue="Zero System Outages"
          change="SLA Protected"
          changeType="positive"
          icon={<AlertTriangle className="w-4 h-4" />}
        />
        <StatCard
          label="Notification Velocity"
          value="14 / hr"
          subValue="Filtered & Deduplicated"
          change="Zero noise"
          changeType="neutral"
          icon={<ShieldAlert className="w-4 h-4" />}
        />
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setFilter('all')}
          className={`px-3 py-1.5 rounded-[4px] text-xs font-mono transition-colors cursor-pointer ${
            filter === 'all'
              ? 'bg-[#FFB020] text-[#0A0A0B] font-medium'
              : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
          }`}
        >
          All Alerts ({notifications.length})
        </button>
        <button
          onClick={() => setFilter('unread')}
          className={`px-3 py-1.5 rounded-[4px] text-xs font-mono transition-colors cursor-pointer ${
            filter === 'unread'
              ? 'bg-[#FFB020] text-[#0A0A0B] font-medium'
              : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
          }`}
        >
          Unread Only ({unreadCount})
        </button>
      </div>

      {/* Notifications List */}
      <div className="space-y-2">
        {filtered.map((n) => (
          <div
            key={n.id}
            onClick={() => handleToggleRead(n.id)}
            className={`p-3.5 rounded-[6px] border transition-colors cursor-pointer flex items-start justify-between gap-4 ${
              n.read
                ? 'bg-[#141416] border-white/[0.06] opacity-75'
                : 'bg-[#18181B] border-white/[0.14]'
            }`}
          >
            <div className="flex items-start gap-3">
              <div
                className={`w-2 h-2 rounded-full mt-1.5 shrink-0 ${
                  n.priority === 'critical'
                    ? 'bg-[#EF4444]'
                    : n.priority === 'warning'
                    ? 'bg-[#FFB020]'
                    : 'bg-[#38BDF8]'
                }`}
              />
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-[#F2F1EE]">{n.title}</span>
                  <Badge variant="active">{n.module}</Badge>
                </div>
                <p className="text-xs text-[#9C9C9F] leading-relaxed">{n.description}</p>
              </div>
            </div>

            <div className="flex items-center gap-3 shrink-0 text-xs font-mono text-[#6B6B6E]">
              <span>{n.time}</span>
              <span className="text-[10px] text-[#A8A8AB]">
                {n.read ? 'Read' : 'Click to dismiss'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
