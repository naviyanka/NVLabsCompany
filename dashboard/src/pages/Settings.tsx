import { Card } from '@/components/common/Card';
import {
  Settings as SettingsIcon,
  User,
  Shield,
  Key,
  Puzzle,
  Users,
  UserCog,
  CreditCard,
  Cog,
  Bell,
  Database,
  ArchiveRestore,
  FileText,
  Palette,
  Wrench,
  ExternalLink,
  Search,
  Filter,
  Calendar,
  Download,
  ArrowUpDown,
  Info,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  FileBarChart,
  ShieldCheck,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: false },
  { label: 'Security', icon: Shield, active: false },
  { label: 'API Keys', icon: Key, active: false },
  { label: 'Integrations', icon: Puzzle, active: false },
  { label: 'Teams & Users', icon: Users, active: false },
  { label: 'Roles & Permissions', icon: UserCog, active: false },
  { label: 'Billing & Subscription', icon: CreditCard, active: false },
  { label: 'System Configuration', icon: SettingsIcon, active: false },
  { label: 'Notifications', icon: Bell, active: false },
  { label: 'Data & Storage', icon: Database, active: false },
  { label: 'Backup & Restore', icon: ArchiveRestore, active: false },
  { label: 'Audit Logs', icon: FileText, active: true },
  { label: 'Appearance', icon: Palette, active: false },
  { label: 'Advanced', icon: Wrench, active: false },
];

const footerLinks = [
  { label: 'Documentation' },
  { label: 'Support' },
  { label: 'Privacy Policy' },
  { label: 'Terms of Service' },
];

const tabs = [
  { label: 'All Logs', active: true },
  { label: 'Admin Actions', active: false },
  { label: 'User Activity', active: false },
  { label: 'Security Events', active: false },
  { label: 'System Events', active: false },
  { label: 'Data Changes', active: false },
];

interface LogEntry {
  time: string;
  timeAgo: string;
  userName: string;
  userEmail: string;
  avatarColor: string;
  initial: string;
  action: string;
  actionCategory: string;
  actionBadgeColor: string;
  resource: string;
  ipAddress: string;
  location: string;
}

const logEntries: LogEntry[] = [
  {
    time: 'May 19, 2024 02:30 PM',
    timeAgo: '2 minutes ago',
    userName: 'Navi Yanka',
    userEmail: 'navi.yanka@nvlabs.dev',
    avatarColor: 'bg-purple-500',
    initial: 'N',
    action: 'User Login',
    actionCategory: 'Auth',
    actionBadgeColor: 'bg-teal-500/10 text-teal-400',
    resource: 'Auth Service',
    ipAddress: '203.0.113.24',
    location: 'India, Gurgaon',
  },
  {
    time: 'May 19, 2024 02:25 PM',
    timeAgo: '7 minutes ago',
    userName: 'Aman Verma',
    userEmail: 'aman.verma@nvlabs.dev',
    avatarColor: 'bg-blue-500',
    initial: 'A',
    action: 'Pipeline Triggered',
    actionCategory: 'Pipeline',
    actionBadgeColor: 'bg-purple-500/10 text-purple-400',
    resource: 'Pipeline / Login Service',
    ipAddress: '203.0.113.24',
    location: 'India, Gurgaon',
  },
  {
    time: 'May 19, 2024 02:20 PM',
    timeAgo: '12 minutes ago',
    userName: 'Sneha Iyer',
    userEmail: 'sneha.iyer@nvlabs.dev',
    avatarColor: 'bg-orange-500',
    initial: 'S',
    action: 'Role Updated',
    actionCategory: 'Admin',
    actionBadgeColor: 'bg-orange-500/10 text-orange-400',
    resource: 'Role / Developer',
    ipAddress: '198.51.100.11',
    location: 'India, Bangalore',
  },
  {
    time: 'May 19, 2024 02:15 PM',
    timeAgo: '17 minutes ago',
    userName: 'System',
    userEmail: 'system@nvlabs.dev',
    avatarColor: 'bg-green-500',
    initial: 'S',
    action: 'Backup Created',
    actionCategory: 'System',
    actionBadgeColor: 'bg-green-500/10 text-green-400',
    resource: 'Backup / Manual Backup',
    ipAddress: '10.0.0.5',
    location: '-',
  },
  {
    time: 'May 19, 2024 02:10 PM',
    timeAgo: '22 minutes ago',
    userName: 'Aman Verma',
    userEmail: 'aman.verma@nvlabs.dev',
    avatarColor: 'bg-blue-500',
    initial: 'A',
    action: 'Data Exported',
    actionCategory: 'Data',
    actionBadgeColor: 'bg-blue-500/10 text-blue-400',
    resource: 'Export / Agents Data',
    ipAddress: '203.0.113.24',
    location: 'India, Gurgaon',
  },
  {
    time: 'May 19, 2024 02:05 PM',
    timeAgo: '27 minutes ago',
    userName: 'Navi Yanka',
    userEmail: 'navi.yanka@nvlabs.dev',
    avatarColor: 'bg-purple-500',
    initial: 'N',
    action: 'API Key Created',
    actionCategory: 'API',
    actionBadgeColor: 'bg-gray-500/10 text-gray-400',
    resource: 'API Key / OpenAI Key',
    ipAddress: '203.0.113.24',
    location: 'India, Gurgaon',
  },
  {
    time: 'May 19, 2024 01:55 PM',
    timeAgo: '37 minutes ago',
    userName: 'Sneha Iyer',
    userEmail: 'sneha.iyer@nvlabs.dev',
    avatarColor: 'bg-orange-500',
    initial: 'S',
    action: 'Permission Changed',
    actionCategory: 'Secr',
    actionBadgeColor: 'bg-red-500/10 text-red-400',
    resource: 'Permission / Agents: Read',
    ipAddress: '198.51.100.11',
    location: 'India, Bangalore',
  },
  {
    time: 'May 19, 2024 01:45 PM',
    timeAgo: '47 minutes ago',
    userName: 'Rohan Mehta',
    userEmail: 'rohan.mehta@nvlabs.dev',
    avatarColor: 'bg-cyan-500',
    initial: 'R',
    action: 'Agent Created',
    actionCategory: 'Agents',
    actionBadgeColor: 'bg-blue-500/10 text-blue-400',
    resource: 'Agent / Recon Agent',
    ipAddress: '203.0.113.14',
    location: 'India, Mumbai',
  },
  {
    time: 'May 19, 2024 01:30 PM',
    timeAgo: '1 hour ago',
    userName: 'System',
    userEmail: 'system@nvlabs.dev',
    avatarColor: 'bg-green-500',
    initial: 'S',
    action: 'System Update',
    actionCategory: 'System',
    actionBadgeColor: 'bg-green-500/10 text-green-400',
    resource: 'System / v2.4.1',
    ipAddress: '10.0.0.5',
    location: '-',
  },
  {
    time: 'May 19, 2024 01:15 PM',
    timeAgo: '1 hour ago',
    userName: 'Navi Yanka',
    userEmail: 'navi.yanka@nvlabs.dev',
    avatarColor: 'bg-purple-500',
    initial: 'N',
    action: 'Settings Updated',
    actionCategory: 'Settings',
    actionBadgeColor: 'bg-teal-500/10 text-teal-400',
    resource: 'Settings / Notification',
    ipAddress: '203.0.113.24',
    location: 'India, Gurgaon',
  },
];

const topActions = [
  { label: 'User Login', count: 342, percent: 27.4, color: 'border-teal-400', barColor: 'bg-teal-400' },
  { label: 'Pipeline Triggered', count: 258, percent: 20.5, color: 'border-purple-400', barColor: 'bg-purple-400' },
  { label: 'Data Exported', count: 187, percent: 15.0, color: 'border-blue-400', barColor: 'bg-blue-400' },
  { label: 'Role Updated', count: 142, percent: 11.4, color: 'border-orange-400', barColor: 'bg-orange-400' },
  { label: 'Settings Updated', count: 98, percent: 7.8, color: 'border-green-400', barColor: 'bg-green-400' },
];

// ─── Main Component ────────────────────────────────────────────────────────────

export function Settings() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-primary-500/10">
          <SettingsIcon size={20} className="text-primary-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            Manage your preferences, system configuration, and platform settings
          </p>
        </div>
      </div>

      {/* Main Layout: Left Nav + Center Content + Right Sidebar */}
      <div className="flex gap-6">
        {/* Left Settings Navigation */}
        <div className="w-[20%] flex-shrink-0">
          <Card padding="sm">
            <nav className="space-y-0.5">
              {navItems.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.label}
                    className={`w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors ${
                      item.active
                        ? 'bg-primary-500/10 text-primary-400 font-medium'
                        : 'text-gray-400 hover:text-white hover:bg-white/[0.04]'
                    }`}
                  >
                    <Icon size={16} />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </nav>
          </Card>
        </div>

        {/* Center Content */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Section Header */}
          <div>
            <h2 className="text-lg font-semibold text-white">Audit Logs</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              View and search all system activity and changes across your organization.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center gap-1 border-b border-white/[0.08]">
            {tabs.map((tab) => (
              <button
                key={tab.label}
                className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 ${
                  tab.active
                    ? 'border-primary-500 text-primary-400'
                    : 'border-transparent text-gray-400 hover:text-white'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Search and Filter Bar */}
          <div className="flex items-center gap-3">
            <div className="flex-1 relative">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search logs by user, action, resource, IP..."
                className="w-full pl-9 pr-16 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg placeholder-gray-500 focus:outline-none focus:border-primary-500/50"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-gray-500 bg-white/[0.06] px-1.5 py-0.5 rounded border border-white/[0.08]">
                Ctrl F
              </span>
            </div>
            <button className="flex items-center gap-2 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg hover:bg-white/[0.06] transition-colors">
              <Filter size={14} />
              <span>Filters</span>
              <ChevronDown size={14} />
            </button>
            <button className="flex items-center gap-2 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg hover:bg-white/[0.06] transition-colors">
              <Calendar size={14} />
              <span>May 12, 2024 - May 19, 2024</span>
            </button>
            <button className="flex items-center gap-2 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg hover:bg-white/[0.06] transition-colors">
              <Download size={14} />
              <span>Export</span>
              <ChevronDown size={14} />
            </button>
          </div>

          {/* Log Table */}
          <Card padding="none">
            {/* Table Header */}
            <div className="grid grid-cols-[1.4fr_1.6fr_1.4fr_1.2fr_1.2fr_0.3fr] gap-4 items-center px-4 py-3 border-b border-white/[0.08]">
              <div className="flex items-center gap-1">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Time</span>
                <ArrowUpDown size={12} className="text-gray-500" />
              </div>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">User</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Action</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Resource</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">IP Address</span>
              <span />
            </div>

            {/* Table Rows */}
            <div className="divide-y divide-white/[0.08]">
              {logEntries.map((entry, index) => (
                <div
                  key={index}
                  className="grid grid-cols-[1.4fr_1.6fr_1.4fr_1.2fr_1.2fr_0.3fr] gap-4 items-center px-4 py-3 hover:bg-white/[0.02] transition-colors"
                >
                  {/* Time */}
                  <div>
                    <p className="text-sm text-white">{entry.time}</p>
                    <p className="text-xs text-gray-500">{entry.timeAgo}</p>
                  </div>

                  {/* User */}
                  <div className="flex items-center gap-2.5">
                    <div className={`w-7 h-7 rounded-full ${entry.avatarColor} flex items-center justify-center flex-shrink-0`}>
                      <span className="text-xs font-bold text-white">{entry.initial}</span>
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm text-white truncate">{entry.userName}</p>
                      <p className="text-xs text-gray-500 truncate">{entry.userEmail}</p>
                    </div>
                  </div>

                  {/* Action */}
                  <div>
                    <span className="text-sm text-white">{entry.action}</span>
                    <span className={`ml-2 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${entry.actionBadgeColor}`}>
                      {entry.actionCategory}
                    </span>
                  </div>

                  {/* Resource */}
                  <span className="text-sm text-gray-300">{entry.resource}</span>

                  {/* IP Address */}
                  <div>
                    <p className="text-sm text-gray-300">{entry.ipAddress}</p>
                    <p className="text-xs text-gray-500">{entry.location}</p>
                  </div>

                  {/* Detail Button */}
                  <div className="flex justify-end">
                    <button className="p-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">
                      <Info size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination Footer */}
            <div className="flex items-center justify-between px-4 py-3 border-t border-white/[0.08]">
              <p className="text-xs text-gray-400">Showing 1 to 10 of 1,248 logs</p>
              <div className="flex items-center gap-1">
                <button className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">
                  <ChevronLeft size={14} />
                </button>
                <button className="px-2.5 py-1 rounded text-xs font-medium bg-primary-500/10 text-primary-400">1</button>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">2</button>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">3</button>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">4</button>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">5</button>
                <span className="px-1 text-xs text-gray-500">...</span>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">125</button>
                <button className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-white/[0.06] transition-colors">
                  <ChevronRight size={14} />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">Rows per page</span>
                <div className="relative">
                  <select className="px-2 py-1 text-xs text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded appearance-none pr-6">
                    <option>10</option>
                  </select>
                  <ChevronDown size={12} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                </div>
              </div>
            </div>
          </Card>

          {/* Footer */}
          <div className="border-t border-white/[0.08] pt-6 pb-4">
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
              <p className="text-sm text-gray-400">
                &copy; 2024 NVLABS Mission Control. All rights reserved.
              </p>
              <div className="flex items-center gap-4">
                {footerLinks.map((link) => (
                  <a
                    key={link.label}
                    href="#"
                    className="flex items-center gap-1 text-sm text-gray-400 hover:text-white transition-colors"
                  >
                    {link.label}
                    <ExternalLink size={12} />
                  </a>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Right Sidebar */}
        <div className="w-[25%] flex-shrink-0 space-y-6">
          {/* Log Summary */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Log Summary</h3>
            <p className="text-xs text-gray-400 mb-4">
              Overview of audit logs for the selected period.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-dark-bg border border-white/[0.08] p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <FileBarChart size={14} className="text-blue-400" />
                </div>
                <p className="text-lg font-bold text-white">1,248</p>
                <p className="text-xs text-gray-400">Total Logs</p>
              </div>
              <div className="rounded-lg bg-dark-bg border border-white/[0.08] p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <Users size={14} className="text-green-400" />
                </div>
                <p className="text-lg font-bold text-white">156</p>
                <p className="text-xs text-gray-400">Unique Users</p>
              </div>
              <div className="rounded-lg bg-dark-bg border border-white/[0.08] p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <ShieldCheck size={14} className="text-purple-400" />
                </div>
                <p className="text-lg font-bold text-white">78</p>
                <p className="text-xs text-gray-400">Security Events</p>
              </div>
              <div className="rounded-lg bg-dark-bg border border-white/[0.08] p-3">
                <div className="flex items-center gap-2 mb-1.5">
                  <Database size={14} className="text-orange-400" />
                </div>
                <p className="text-lg font-bold text-white">312</p>
                <p className="text-xs text-gray-400">Data Changes</p>
              </div>
            </div>
          </Card>

          {/* Top Actions */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Top Actions</h3>
            <p className="text-xs text-gray-400 mb-4">
              Most performed actions in this period.
            </p>
            <div className="space-y-3">
              {topActions.map((action) => (
                <div key={action.label} className={`border-l-2 ${action.color} pl-3`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-gray-300">{action.label}</span>
                    <span className="text-xs text-gray-400">
                      {action.count} ({action.percent}%)
                    </span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-white/[0.08]">
                    <div
                      className={`h-full rounded-full ${action.barColor}`}
                      style={{ width: `${action.percent}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
            <button className="mt-4 w-full px-3 py-1.5 text-xs font-medium text-primary-400 border border-primary-500/30 rounded-lg hover:bg-primary-500/10 transition-colors">
              View All Actions &rarr;
            </button>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-4">
              Learn more about audit logs.
            </p>
            <div className="space-y-3">
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Audit Logs Guide
                </span>
              </a>
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Best Practices
                </span>
              </a>
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Contact Support
                </span>
              </a>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
