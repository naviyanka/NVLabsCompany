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
  Plus,
  CheckCircle,
  Calendar,
  Archive,
  CircleDot,
  Download,
  MoreVertical,
  ChevronLeft,
  ChevronRight,
  Clock,
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
  { label: 'Backup & Restore', icon: ArchiveRestore, active: true },
  { label: 'Audit Logs', icon: FileText, active: false },
  { label: 'Appearance', icon: Palette, active: false },
  { label: 'Advanced', icon: Wrench, active: false },
];

const footerLinks = [
  { label: 'Documentation' },
  { label: 'Support' },
  { label: 'Privacy Policy' },
  { label: 'Terms of Service' },
];

const backupTabs = [
  { label: 'Backups', active: true },
  { label: 'Restore', active: false },
  { label: 'Schedules', active: false },
  { label: 'Retention Policy', active: false },
  { label: 'Backup Settings', active: false },
];

const backupStats = [
  {
    label: 'Last Backup',
    value: 'May 19, 2024 02:30 PM',
    sub: '2h 15m ago',
    icon: CheckCircle,
    iconColor: 'text-green-400',
    iconBg: 'bg-green-500/10',
  },
  {
    label: 'Total Backups',
    value: '28',
    sub: 'This month',
    icon: Calendar,
    iconColor: 'text-blue-400',
    iconBg: 'bg-blue-500/10',
  },
  {
    label: 'Backup Size',
    value: '168.42 GB',
    sub: 'Compressed',
    icon: Archive,
    iconColor: 'text-blue-400',
    iconBg: 'bg-blue-500/10',
  },
  {
    label: 'Backup Status',
    value: 'Healthy',
    sub: 'All systems protected',
    icon: CircleDot,
    iconColor: 'text-green-400',
    iconBg: 'bg-green-500/10',
  },
];

const recentBackups = [
  {
    name: 'Manual Backup - May 19, 2024',
    description: 'Full backup',
    type: 'Manual',
    typeBadge: 'bg-purple-500/10 text-purple-400',
    size: '168.42 GB',
    status: 'Completed',
    createdAt: 'May 19, 2024 02:30 PM',
  },
  {
    name: 'Scheduled Backup - May 18, 2024',
    description: 'Incremental backup',
    type: 'Scheduled',
    typeBadge: 'bg-blue-500/10 text-blue-400',
    size: '42.18 GB',
    status: 'Completed',
    createdAt: 'May 18, 2024 02:30 PM',
  },
  {
    name: 'Scheduled Backup - May 17, 2024',
    description: 'Incremental backup',
    type: 'Scheduled',
    typeBadge: 'bg-blue-500/10 text-blue-400',
    size: '41.76 GB',
    status: 'Completed',
    createdAt: 'May 17, 2024 02:30 PM',
  },
  {
    name: 'Scheduled Backup - May 16, 2024',
    description: 'Full backup',
    type: 'Scheduled',
    typeBadge: 'bg-blue-500/10 text-blue-400',
    size: '165.09 GB',
    status: 'Completed',
    createdAt: 'May 16, 2024 02:30 PM',
  },
  {
    name: 'Manual Backup - May 15, 2024',
    description: 'Full backup',
    type: 'Manual',
    typeBadge: 'bg-purple-500/10 text-purple-400',
    size: '167.83 GB',
    status: 'Completed',
    createdAt: 'May 15, 2024 01:15 PM',
  },
];

const healthStatus = [
  { label: 'Backup Service', value: 'Healthy' },
  { label: 'Storage Connection', value: 'Healthy' },
  { label: 'Last Backup', value: 'Successful' },
  { label: 'Schedule', value: 'Active' },
  { label: 'Retention Policy', value: 'Compliant' },
];

const retentionPolicies = [
  { label: 'Daily Backups', value: '30 days' },
  { label: 'Weekly Backups', value: '12 weeks' },
  { label: 'Monthly Backups', value: '12 months' },
  { label: 'Yearly Backups', value: '5 years' },
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

            {/* Footer Links */}
            <div className="border-t border-white/[0.08] mt-4 pt-4 space-y-1">
              {footerLinks.map((link) => (
                <a
                  key={link.label}
                  href="#"
                  className="flex items-center gap-2 px-3 py-1.5 text-xs text-gray-400 hover:text-white transition-colors"
                >
                  <ExternalLink size={12} />
                  <span>{link.label}</span>
                </a>
              ))}
            </div>
          </Card>
        </div>

        {/* Center Content */}
        <div className="flex-1 min-w-0 space-y-6">
          {/* Section Header */}
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Backup &amp; Restore</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Protect your data by creating backups and restore when needed.
              </p>
            </div>
            <button className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors">
              <Plus size={16} />
              <span>Create Backup Now</span>
            </button>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center gap-1 border-b border-white/[0.08]">
            {backupTabs.map((tab) => (
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

          {/* Backup Summary Section */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">Backup Summary</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Overview of your backup status and storage.
              </p>
            </div>

            {/* Stat Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {backupStats.map((stat) => {
                const Icon = stat.icon;
                return (
                  <div
                    key={stat.label}
                    className="rounded-lg bg-dark-bg border border-white/[0.08] p-4"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-xs text-gray-400">{stat.label}</p>
                      <div className={`p-1.5 rounded-lg ${stat.iconBg}`}>
                        <Icon size={14} className={stat.iconColor} />
                      </div>
                    </div>
                    <p className="text-sm font-bold text-white">{stat.value}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{stat.sub}</p>
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Recent Backups Section */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">Recent Backups</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                List of the most recent backups.
              </p>
            </div>

            {/* Table Header */}
            <div className="grid grid-cols-[2fr_1fr_0.8fr_0.8fr_1.2fr_0.6fr] gap-4 items-center border-b border-white/[0.08] pb-2 mb-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Backup Name</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Type</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Size</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Status</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Created At</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</span>
            </div>

            {/* Table Rows */}
            <div className="divide-y divide-white/[0.08]">
              {recentBackups.map((backup) => (
                <div
                  key={backup.name}
                  className="grid grid-cols-[2fr_1fr_0.8fr_0.8fr_1.2fr_0.6fr] gap-4 items-center py-3"
                >
                  <div>
                    <span className="text-sm font-medium text-white">{backup.name}</span>
                    <p className="text-xs text-gray-500 mt-0.5">{backup.description}</p>
                  </div>
                  <div>
                    <span className={`inline-flex px-2 py-0.5 text-xs font-medium rounded-full ${backup.typeBadge}`}>
                      {backup.type}
                    </span>
                  </div>
                  <span className="text-sm text-gray-300">{backup.size}</span>
                  <div>
                    <span className="inline-flex items-center gap-1 text-xs font-medium text-green-400">
                      <CheckCircle size={12} />
                      {backup.status}
                    </span>
                  </div>
                  <span className="text-xs text-gray-400">{backup.createdAt}</span>
                  <div className="flex items-center gap-2">
                    <button className="p-1 text-gray-400 hover:text-white transition-colors">
                      <Download size={14} />
                    </button>
                    <button className="p-1 text-gray-400 hover:text-white transition-colors">
                      <MoreVertical size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination Footer */}
            <div className="flex items-center justify-between mt-4 pt-4 border-t border-white/[0.08]">
              <p className="text-xs text-gray-500">Showing 1 to 5 of 28 backups</p>
              <div className="flex items-center gap-1">
                <button className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <ChevronLeft size={14} />
                </button>
                <button className="px-2.5 py-1 rounded text-xs font-medium bg-primary-500/10 text-primary-400">
                  1
                </button>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.04] transition-colors">
                  2
                </button>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.04] transition-colors">
                  3
                </button>
                <span className="px-1 text-xs text-gray-500">...</span>
                <button className="px-2.5 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-white/[0.04] transition-colors">
                  6
                </button>
                <button className="p-1.5 rounded text-gray-400 hover:text-white hover:bg-white/[0.04] transition-colors">
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </Card>

          {/* Backup Schedules Section */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">Backup Schedules</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Manage automated backup schedules for your data.
              </p>
            </div>

            {/* Schedule Item */}
            <div className="rounded-lg border border-white/[0.08] p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <h4 className="text-sm font-medium text-white">Daily Backup (Incremental)</h4>
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/10 text-green-400">
                      <Plus size={10} />
                      Active
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mb-3">Every day at 02:30 PM</p>
                  <p className="text-xs text-gray-400 mb-3">
                    Includes: Agents Data, Pipeline Artifacts, Logs &amp; Events
                  </p>
                  <div className="flex items-center gap-4">
                    <div className="flex items-center gap-1.5">
                      <Clock size={12} className="text-gray-500" />
                      <span className="text-xs text-gray-400">
                        Next Run: <span className="text-white">May 20, 2024 02:30 PM</span>
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Archive size={12} className="text-gray-500" />
                      <span className="text-xs text-gray-400">
                        Retention: <span className="text-white">30 days</span>
                      </span>
                    </div>
                  </div>
                </div>
                <button className="p-1 text-gray-400 hover:text-white transition-colors">
                  <MoreVertical size={16} />
                </button>
              </div>
            </div>

            {/* Add Schedule Button */}
            <div className="flex justify-center mt-4">
              <button className="flex items-center gap-1.5 text-sm text-primary-400 hover:text-primary-300 transition-colors">
                <Plus size={14} />
                <span>Add New Schedule</span>
              </button>
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
          {/* Backup Health */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Backup Health</h3>
            <p className="text-xs text-gray-400 mb-4">
              Overall status of your backup system.
            </p>

            {/* Circular Progress Ring */}
            <div className="flex justify-center mb-4">
              <div className="relative w-32 h-32">
                <svg className="w-full h-full -rotate-90" viewBox="0 0 120 120">
                  <circle
                    cx="60"
                    cy="60"
                    r="52"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="10"
                    className="text-white/[0.08]"
                  />
                  <circle
                    cx="60"
                    cy="60"
                    r="52"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="10"
                    strokeLinecap="round"
                    className="text-green-500"
                    strokeDasharray={`${2 * Math.PI * 52}`}
                    strokeDashoffset={`${2 * Math.PI * 52 * (1 - 1.0)}`}
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-lg font-bold text-white">100%</span>
                </div>
              </div>
            </div>

            {/* Status List */}
            <div className="space-y-3">
              {healthStatus.map((item) => (
                <div key={item.label} className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">{item.label}</span>
                  <span className="text-xs font-medium text-green-400">{item.value}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Storage Usage */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Storage Usage</h3>
            <p className="text-xs text-gray-400 mb-4">
              Backup storage consumption.
            </p>

            {/* Progress Bar */}
            <div className="w-full h-2.5 rounded-full bg-white/[0.08] mb-2">
              <div
                className="h-full rounded-full bg-green-500"
                style={{ width: '67%' }}
              />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">168.42 GB used of 250 GB</span>
              <span className="text-xs font-medium text-white">67%</span>
            </div>
          </Card>

          {/* Retention Summary */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Retention Summary</h3>
            <p className="text-xs text-gray-400 mb-4">
              Your backup retention policy.
            </p>

            <div className="space-y-3 mb-4">
              {retentionPolicies.map((policy) => (
                <div key={policy.label} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                    <span className="text-xs text-gray-300">{policy.label}</span>
                  </div>
                  <span className="text-xs font-medium text-white">{policy.value}</span>
                </div>
              ))}
            </div>

            <button className="w-full px-3 py-2 text-xs font-medium text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-500/10 transition-colors">
              Manage Retention Policy &rarr;
            </button>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-4">
              Learn more about backup &amp; restore.
            </p>
            <div className="space-y-3">
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Backup &amp; Restore Guide
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
