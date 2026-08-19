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
  ChevronRight,
  ChevronDown,
  Save,
  Copy,
  Mail,
  MessageSquare,
  Globe,
  Check,
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
  { label: 'Notifications', icon: Bell, active: true },
  { label: 'Data & Storage', icon: Database, active: false },
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

const notificationTabs = [
  { label: 'Notification Preferences', active: true },
  { label: 'Channels', active: false },
  { label: 'Quiet Hours', active: false },
  { label: 'Digest Settings', active: false },
];

const notificationCategories = [
  {
    name: 'System Alerts',
    color: 'bg-red-500',
    description: 'Critical system issues, downtime, and performance alerts.',
    inApp: true,
    email: true,
    push: true,
    webhook: true,
  },
  {
    name: 'Agent & Task Updates',
    color: 'bg-green-500',
    description: 'Agent status changes, task completions, and failures.',
    inApp: true,
    email: false,
    push: true,
    webhook: false,
  },
  {
    name: 'Pipeline Events',
    color: 'bg-blue-500',
    description: 'Pipeline runs, deployments, and stage updates.',
    inApp: false,
    email: true,
    push: false,
    webhook: true,
  },
  {
    name: 'Security Notifications',
    color: 'bg-purple-500',
    description: 'Login alerts, security issues, and access changes.',
    inApp: true,
    email: true,
    push: true,
    webhook: true,
  },
  {
    name: 'Mentions & Comments',
    color: 'bg-orange-500',
    description: 'You were mentioned or someone commented.',
    inApp: true,
    email: false,
    push: true,
    webhook: false,
  },
  {
    name: 'Reports & Exports',
    color: 'bg-teal-500',
    description: 'Report generation, exports, and downloads.',
    inApp: false,
    email: true,
    push: false,
    webhook: false,
  },
  {
    name: 'Billing & Subscription',
    color: 'bg-pink-500',
    description: 'Invoices, payment confirmations, and subscription updates.',
    inApp: false,
    email: true,
    push: false,
    webhook: false,
  },
];

const channels = [
  {
    icon: Mail,
    label: 'Email',
    detail: 'navi.yanka@nvlabs.dev',
    status: 'Verified',
  },
  {
    icon: Bell,
    label: 'Push Notifications',
    detail: 'iPhone 14 Pro',
    status: 'Connected',
  },
  {
    icon: MessageSquare,
    label: 'Slack',
    detail: '#alerts',
    status: 'Connected',
  },
  {
    icon: Globe,
    label: 'Webhook',
    detail: 'https://hooks.nvlabs.dev/notify',
    status: 'Active',
  },
];

const helpLinks = [
  { title: 'Notification Guide', description: 'Learn how notifications work' },
  { title: 'Troubleshooting', description: 'Fix notification issues' },
  { title: 'Contact Support', description: 'Get help from our team' },
];

// ─── Toggle Switch Component ───────────────────────────────────────────────────

function ToggleSwitch({ enabled }: { enabled: boolean }) {
  return (
    <div
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
        enabled ? 'bg-primary-500' : 'bg-gray-600'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
          enabled ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </div>
  );
}

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
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Notifications</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Configure how and when you want to be notified.
              </p>
            </div>
            <button className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors">
              <Save size={14} />
              Save Changes
            </button>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center gap-1 border-b border-white/[0.08]">
            {notificationTabs.map((tab) => (
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

          {/* Enable Notifications Toggle */}
          <Card padding="lg">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-white">Enable Notifications</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  Turn on or off all notifications for your account.
                </p>
              </div>
              <ToggleSwitch enabled={true} />
            </div>
          </Card>

          {/* Notification Categories */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">Notification Categories</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Choose which notifications you want to receive.
              </p>
            </div>

            {/* Table Header */}
            <div className="grid grid-cols-[1fr_auto] items-center border-b border-white/[0.08] pb-2 mb-2">
              <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Category</span>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Description</span>
              </div>
              <div className="flex items-center gap-6 pl-4">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide w-12 text-center">In-App</span>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide w-12 text-center">Email</span>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide w-12 text-center">Push</span>
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wide w-14 text-center">Webhook</span>
                <span className="w-5" />
              </div>
            </div>

            {/* Table Rows */}
            <div className="divide-y divide-white/[0.08]">
              {notificationCategories.map((category) => (
                <div
                  key={category.name}
                  className="grid grid-cols-[1fr_auto] items-center py-3"
                >
                  <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-4 items-center">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${category.color} flex-shrink-0`} />
                      <span className="text-sm font-medium text-white truncate">{category.name}</span>
                    </div>
                    <span className="text-xs text-gray-400 truncate">{category.description}</span>
                  </div>
                  <div className="flex items-center gap-6 pl-4">
                    <div className="w-12 flex justify-center">
                      <ToggleSwitch enabled={category.inApp} />
                    </div>
                    <div className="w-12 flex justify-center">
                      <ToggleSwitch enabled={category.email} />
                    </div>
                    <div className="w-12 flex justify-center">
                      <ToggleSwitch enabled={category.push} />
                    </div>
                    <div className="w-14 flex justify-center">
                      <ToggleSwitch enabled={category.webhook} />
                    </div>
                    <ChevronDown size={14} className="text-gray-400 w-5" />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Advanced Settings */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-4">Advanced Settings</h3>
            <div className="divide-y divide-white/[0.08]">
              {/* Do not disturb */}
              <div className="flex items-center justify-between py-4 first:pt-0">
                <div className="flex-1 min-w-0 pr-4">
                  <p className="text-sm font-medium text-white">Do not disturb</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Temporarily silence non-critical notifications.
                  </p>
                </div>
                <div className="relative flex items-center">
                  <select
                    className="w-48 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg appearance-none pr-9"
                    defaultValue="Turn off in 1 hour"
                  >
                    <option>Turn off in 1 hour</option>
                  </select>
                  <ChevronDown size={14} className="absolute right-3 text-gray-400 pointer-events-none" />
                </div>
              </div>

              {/* Notification sound */}
              <div className="flex items-center justify-between py-4">
                <div className="flex-1 min-w-0 pr-4">
                  <p className="text-sm font-medium text-white">Notification sound</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Play a sound for in-app notifications.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="relative flex items-center">
                    <select
                      className="w-32 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg appearance-none pr-9"
                      defaultValue="Default"
                    >
                      <option>Default</option>
                    </select>
                    <ChevronDown size={14} className="absolute right-3 text-gray-400 pointer-events-none" />
                  </div>
                  <ToggleSwitch enabled={true} />
                </div>
              </div>

              {/* Browser notifications */}
              <div className="flex items-center justify-between py-4">
                <div className="flex-1 min-w-0 pr-4">
                  <p className="text-sm font-medium text-white">Browser notifications</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Show notifications on your desktop.
                  </p>
                </div>
                <ToggleSwitch enabled={true} />
              </div>

              {/* Webhook URL */}
              <div className="flex items-center justify-between py-4 last:pb-0">
                <div className="flex-1 min-w-0 pr-4">
                  <p className="text-sm font-medium text-white">Webhook URL</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Send notifications to your custom webhook endpoint.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex items-center w-64 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg">
                    <span className="flex-1 truncate">https://hooks.nvlabs.dev/notify</span>
                    <Copy size={14} className="text-gray-400 flex-shrink-0 ml-2" />
                  </div>
                  <ChevronRight size={14} className="text-gray-400" />
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
          {/* Notification Preview */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Notification Preview</h3>
            <p className="text-xs text-gray-400 mb-4">
              This is how your notification will look.
            </p>
            <div className="rounded-lg bg-dark-bg border border-white/[0.08] p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-primary-500" />
                  <span className="text-xs font-medium text-white">NVLABS Mission Control</span>
                </div>
                <span className="text-xs text-gray-500">now</span>
              </div>
              <div className="flex items-start gap-2 mb-2">
                <Check size={14} className="text-green-400 flex-shrink-0 mt-0.5" />
                <p className="text-sm font-medium text-white">Pipeline Deployment Successful</p>
              </div>
              <p className="text-xs text-gray-400 mb-3 ml-5">
                Pipeline &apos;Login Service&apos; has been deployed successfully to production.
              </p>
              <a href="#" className="text-xs text-teal-400 hover:text-teal-300 ml-5 transition-colors">
                View Details &rarr;
              </a>
            </div>
          </Card>

          {/* Your Channels */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Your Channels</h3>
            <p className="text-xs text-gray-400 mb-4">
              Manage your notification channels.
            </p>
            <div className="space-y-3">
              {channels.map((channel) => {
                const Icon = channel.icon;
                return (
                  <div key={channel.label} className="flex items-center gap-3">
                    <div className="p-1.5 rounded-md bg-white/[0.04]">
                      <Icon size={14} className="text-gray-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium text-white">{channel.label}</p>
                      <p className="text-xs text-gray-500 truncate">{channel.detail}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-xs text-green-400">{channel.status}</span>
                      <Check size={10} className="text-green-400" />
                    </div>
                  </div>
                );
              })}
            </div>
            <a href="#" className="inline-block mt-4 text-xs text-primary-400 hover:text-primary-300 transition-colors">
              Manage Channels &rarr;
            </a>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-4">
              Learn more about notifications.
            </p>
            <div className="space-y-3">
              {helpLinks.map((link) => (
                <a
                  key={link.title}
                  href="#"
                  className="flex items-start gap-2 group"
                >
                  <ExternalLink size={12} className="text-gray-400 flex-shrink-0 mt-0.5" />
                  <div>
                    <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                      {link.title}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">{link.description}</p>
                  </div>
                </a>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
