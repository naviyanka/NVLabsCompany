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
  ChevronDown,
  Trash2,
  Archive,
  Download,
  FolderOpen,
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
  { label: 'Data & Storage', icon: Database, active: true },
  { label: 'Backup & Restore', icon: ArchiveRestore, active: false },
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

const storageTabs = [
  { label: 'Storage Overview', active: true },
  { label: 'Data Retention', active: false },
  { label: 'Data Classification', active: false },
  { label: 'Export & Import', active: false },
];

const storageStats = [
  {
    label: 'Total Storage Used',
    value: '1.42 TB',
    sub: 'of 5 TB',
    change: null,
  },
  {
    label: 'Storage Utilization',
    value: '28.4%',
    sub: null,
    change: '+3.2% this month',
  },
  {
    label: 'Objects Stored',
    value: '3.21M',
    sub: null,
    change: '+15% this month',
  },
  {
    label: 'Storage Cost (Est.)',
    value: '$142.48',
    sub: '/ this month',
    change: null,
  },
];

const storageSegments = [
  { label: 'Agents Data', size: '620 GB', percent: 43.7, color: 'bg-purple-500' },
  { label: 'Pipeline Artifacts', size: '420 GB', percent: 29.6, color: 'bg-blue-500' },
  { label: 'Logs & Events', size: '240 GB', percent: 16.9, color: 'bg-teal-500' },
  { label: 'Backups', size: '140 GB', percent: 9.8, color: 'bg-orange-500' },
];

const dataBreakdown = [
  {
    type: 'Agents Data',
    color: 'bg-purple-500',
    description: 'Agent memory, sessions, and knowledge.',
    storage: '620 GB',
    storagePercent: 43.7,
    objects: '1.24M',
    lastUpdated: 'May 19, 2024 02:30 PM',
  },
  {
    type: 'Pipeline Artifacts',
    color: 'bg-blue-500',
    description: 'Build artifacts, test results, and outputs.',
    storage: '420 GB',
    storagePercent: 29.6,
    objects: '843K',
    lastUpdated: 'May 19, 2024 02:25 PM',
  },
  {
    type: 'Logs & Events',
    color: 'bg-teal-500',
    description: 'System logs, audit events, and monitoring.',
    storage: '240 GB',
    storagePercent: 16.9,
    objects: '882K',
    lastUpdated: 'May 19, 2024 02:30 PM',
  },
  {
    type: 'Backups',
    color: 'bg-orange-500',
    description: 'Automated backups and snapshots.',
    storage: '140 GB',
    storagePercent: 9.8,
    objects: '24K',
    lastUpdated: 'May 19, 2024 01:50 PM',
  },
  {
    type: 'Other Data',
    color: 'bg-gray-500',
    description: 'Configs, settings, and miscellaneous.',
    storage: '32 GB',
    storagePercent: 2.3,
    objects: '18K',
    lastUpdated: 'May 19, 2024 01:30 PM',
  },
];

const quickActions = [
  {
    icon: Trash2,
    iconColor: 'text-red-400',
    iconBg: 'bg-red-500/10',
    title: 'Clean Up Storage',
    description: 'Remove old logs, artifacts, and temp files.',
    link: 'Run Cleanup',
  },
  {
    icon: Archive,
    iconColor: 'text-blue-400',
    iconBg: 'bg-blue-500/10',
    title: 'Archive Old Data',
    description: 'Archive data to reduce active storage.',
    link: 'Archive Now',
  },
  {
    icon: Download,
    iconColor: 'text-green-400',
    iconBg: 'bg-green-500/10',
    title: 'Export Data',
    description: 'Export your data in CSV, JSON or Parquet.',
    link: 'Export Now',
  },
  {
    icon: FolderOpen,
    iconColor: 'text-purple-400',
    iconBg: 'bg-purple-500/10',
    title: 'Manage Buckets',
    description: 'View and manage storage buckets.',
    link: 'Manage',
  },
];

const topConsumers = [
  { label: 'Agent Memory', size: '620 GB', percent: 43, color: 'bg-purple-500' },
  { label: 'Pipeline Runs', size: '420 GB', percent: 29.6, color: 'bg-blue-500' },
  { label: 'Logs', size: '240 GB', percent: 16.9, color: 'bg-teal-500' },
  { label: 'Backups', size: '140 GB', percent: 9.8, color: 'bg-orange-500' },
];

const dataProtection = [
  { label: 'Encryption at Rest', value: 'AES-256' },
  { label: 'Encryption in Transit', value: 'TLS 1.3' },
  { label: 'Redundant Storage', value: 'Multi-region' },
  { label: 'Daily Backups', value: 'Enabled' },
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
            <h2 className="text-lg font-semibold text-white">Data &amp; Storage</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              Manage how your data is stored, retained, and protected.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center gap-1 border-b border-white/[0.08]">
            {storageTabs.map((tab) => (
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

          {/* Storage Usage Section */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-sm font-semibold text-white">Storage Usage</h3>
                <p className="text-xs text-gray-400 mt-0.5">
                  Overview of your platform storage across all data types.
                </p>
              </div>
              <div className="relative flex items-center">
                <select className="px-3 py-1.5 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg appearance-none pr-8">
                  <option>All Environments</option>
                </select>
                <ChevronDown size={14} className="absolute right-2.5 text-gray-400 pointer-events-none" />
              </div>
            </div>

            {/* Stat Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              {storageStats.map((stat) => (
                <div
                  key={stat.label}
                  className="rounded-lg bg-dark-bg border border-white/[0.08] p-4"
                >
                  <p className="text-xs text-gray-400 mb-1">{stat.label}</p>
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-xl font-bold text-white">{stat.value}</span>
                    {stat.sub && (
                      <span className="text-xs text-gray-500">{stat.sub}</span>
                    )}
                  </div>
                  {stat.change && (
                    <p className="text-xs text-green-400 mt-1">{stat.change}</p>
                  )}
                </div>
              ))}
            </div>

            {/* Stacked Horizontal Progress Bar */}
            <div className="h-4 w-full rounded-full overflow-hidden flex">
              {storageSegments.map((segment) => (
                <div
                  key={segment.label}
                  className={`${segment.color} h-full`}
                  style={{ width: `${segment.percent}%` }}
                />
              ))}
            </div>

            {/* Legend */}
            <div className="flex items-center gap-6 mt-3">
              {storageSegments.map((segment) => (
                <div key={segment.label} className="flex items-center gap-1.5">
                  <span className={`w-2.5 h-2.5 rounded-full ${segment.color}`} />
                  <span className="text-xs text-gray-400">
                    {segment.label}: {segment.size}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Data Breakdown Section */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">Data Breakdown</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Detailed view of storage usage by data type.
              </p>
            </div>

            {/* Table Header */}
            <div className="grid grid-cols-[2fr_1.2fr_0.8fr_1.2fr_0.6fr] gap-4 items-center border-b border-white/[0.08] pb-2 mb-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Data Type</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Storage Used</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Objects</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Last Updated</span>
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Actions</span>
            </div>

            {/* Table Rows */}
            <div className="divide-y divide-white/[0.08]">
              {dataBreakdown.map((row) => (
                <div
                  key={row.type}
                  className="grid grid-cols-[2fr_1.2fr_0.8fr_1.2fr_0.6fr] gap-4 items-center py-3"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${row.color} flex-shrink-0`} />
                      <span className="text-sm font-medium text-white">{row.type}</span>
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5 ml-4">{row.description}</p>
                  </div>
                  <div>
                    <span className="text-sm text-white">{row.storage}</span>
                    <div className="w-full h-1.5 rounded-full bg-white/[0.08] mt-1">
                      <div
                        className={`h-full rounded-full ${row.color}`}
                        style={{ width: `${row.storagePercent}%` }}
                      />
                    </div>
                  </div>
                  <span className="text-sm text-gray-300">{row.objects}</span>
                  <span className="text-xs text-gray-400">{row.lastUpdated}</span>
                  <a href="#" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                    View
                  </a>
                </div>
              ))}
            </div>

            <p className="text-xs text-gray-500 mt-4">Showing 1 to 5 of 5 items</p>
          </Card>

          {/* Quick Actions */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <Card key={action.title} padding="lg">
                  <div className={`p-2 rounded-lg ${action.iconBg} w-fit mb-3`}>
                    <Icon size={16} className={action.iconColor} />
                  </div>
                  <h4 className="text-sm font-medium text-white mb-1">{action.title}</h4>
                  <p className="text-xs text-gray-400 mb-3">{action.description}</p>
                  <a href="#" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                    {action.link} &rarr;
                  </a>
                </Card>
              );
            })}
          </div>

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
          {/* Storage Quota */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Storage Quota</h3>
            <p className="text-xs text-gray-400 mb-4">
              Configure and manage your storage limits.
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
                    className="text-primary-500"
                    strokeDasharray={`${2 * Math.PI * 52}`}
                    strokeDashoffset={`${2 * Math.PI * 52 * (1 - 0.7)}`}
                  />
                </svg>
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <span className="text-lg font-bold text-white">70%</span>
                </div>
              </div>
            </div>

            <div className="text-center mb-4">
              <p className="text-sm font-medium text-white">5 TB Total Quota</p>
              <p className="text-xs text-gray-400 mt-0.5">3.58 TB Used</p>
            </div>

            <div className="border-t border-white/[0.08] pt-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-gray-400">Alert Threshold</span>
                <span className="text-xs font-medium text-white">85%</span>
              </div>
              <p className="text-xs text-gray-500 mb-3">
                You will be notified when usage exceeds this limit.
              </p>
              <button className="w-full px-3 py-1.5 text-xs font-medium text-gray-300 border border-white/[0.08] rounded-lg hover:bg-white/[0.04] transition-colors">
                Change Threshold
              </button>
            </div>
          </Card>

          {/* Top Consumers */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Top Consumers</h3>
            <p className="text-xs text-gray-400 mb-4">
              Top contributors to storage usage.
            </p>
            <div className="space-y-3">
              {topConsumers.map((consumer) => (
                <div key={consumer.label}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${consumer.color}`} />
                      <span className="text-xs text-gray-300">{consumer.label}</span>
                    </div>
                    <span className="text-xs text-gray-400">{consumer.size}</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full bg-white/[0.08]">
                    <div
                      className={`h-full rounded-full ${consumer.color}`}
                      style={{ width: `${consumer.percent}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Data Protection */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Data Protection</h3>
            <div className="space-y-3">
              {dataProtection.map((item) => (
                <div key={item.label} className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">{item.label}</span>
                  <span className="text-xs font-medium text-white">{item.value}</span>
                </div>
              ))}
            </div>
            <a href="#" className="inline-block mt-4 text-xs text-primary-400 hover:text-primary-300 transition-colors">
              View Backup Settings &rarr;
            </a>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-4">
              Learn more about data &amp; storage.
            </p>
            <div className="space-y-3">
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Data &amp; Storage Guide
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
