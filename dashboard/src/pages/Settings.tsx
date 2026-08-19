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
  Search,
  ChevronDown,
  MoreVertical,
  GitBranch,
  MessageSquare,
  Cloud,
  Container,
  Activity,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: false },
  { label: 'Security', icon: Shield, active: false },
  { label: 'API Keys', icon: Key, active: false },
  { label: 'Integrations', icon: Puzzle, active: true },
  { label: 'Teams & Users', icon: Users, active: false },
  { label: 'Roles & Permissions', icon: UserCog, active: false },
  { label: 'Billing & Subscription', icon: CreditCard, active: false },
  { label: 'System Configuration', icon: SettingsIcon, active: false },
  { label: 'Notifications', icon: Bell, active: false },
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

const connectedIntegrations = [
  {
    name: 'GitHub',
    description: 'Connect repositories, issues, and pull requests.',
    category: 'Code Repository',
    icon: GitBranch,
    iconBg: 'bg-gray-700',
    iconColor: 'text-white',
    connectedDate: 'Connected on May 10, 2024',
  },
  {
    name: 'Slack',
    description: 'Get notifications and updates in your Slack channels.',
    category: 'Communication',
    icon: MessageSquare,
    iconBg: 'bg-purple-500/20',
    iconColor: 'text-purple-400',
    connectedDate: 'Connected on May 08, 2024',
  },
  {
    name: 'Google Drive',
    description: 'Store and access files from your Google Drive.',
    category: 'Cloud Storage',
    icon: Cloud,
    iconBg: 'bg-blue-500/20',
    iconColor: 'text-blue-400',
    connectedDate: 'Connected on Apr 28, 2024',
  },
  {
    name: 'Notion',
    description: 'Sync knowledge base and documentation.',
    category: 'Knowledge Management',
    icon: FileText,
    iconBg: 'bg-gray-700',
    iconColor: 'text-white',
    connectedDate: 'Connected on Apr 21, 2024',
  },
];

const availableIntegrations = [
  {
    name: 'Jira Software',
    description: 'Track issues, bugs, and project progress.',
    category: 'Project Management',
    icon: FileText,
    iconBg: 'bg-blue-500/20',
    iconColor: 'text-blue-400',
  },
  {
    name: 'AWS S3',
    description: 'Store and manage large amounts of data.',
    category: 'Cloud Storage',
    icon: Cloud,
    iconBg: 'bg-orange-500/20',
    iconColor: 'text-orange-400',
  },
  {
    name: 'Docker Hub',
    description: 'Pull and manage Docker images.',
    category: 'DevOps',
    icon: Container,
    iconBg: 'bg-blue-500/20',
    iconColor: 'text-blue-400',
  },
  {
    name: 'Datadog',
    description: 'Monitor infrastructure and application performance.',
    category: 'Monitoring',
    icon: Activity,
    iconBg: 'bg-purple-500/20',
    iconColor: 'text-purple-400',
  },
];

const recentActivity = [
  {
    text: 'GitHub connection refreshed',
    timestamp: 'May 16, 2024, 10:25 AM',
    dotColor: 'bg-green-400',
  },
  {
    text: 'Slack reconnected',
    timestamp: 'May 16, 2024, 09:12 AM',
    dotColor: 'bg-purple-400',
  },
  {
    text: 'Google Drive file sync completed',
    timestamp: 'May 15, 2024, 11:47 PM',
    dotColor: 'bg-blue-400',
  },
  {
    text: 'Notion sync failed',
    timestamp: 'May 15, 2024, 08:30 PM',
    dotColor: 'bg-red-400',
  },
];

const tabs = [
  { label: 'All Integrations', active: true, count: null },
  { label: 'Connected', active: false, count: 8 },
  { label: 'Available', active: false, count: 18 },
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
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">Integrations</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Connect NVLABS Mission Control with your favorite tools and services.
              </p>
            </div>
            <button className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white text-sm font-medium rounded-lg hover:bg-primary-600 transition-colors">
              <Plus size={16} />
              Add Integration
            </button>
          </div>

          {/* Tab Navigation */}
          <div className="border-b border-white/[0.08]">
            <div className="flex items-center gap-6">
              {tabs.map((tab) => (
                <button
                  key={tab.label}
                  className={`pb-3 text-sm font-medium transition-colors relative ${
                    tab.active
                      ? 'text-primary-400'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  {tab.label}
                  {tab.count !== null && (
                    <span className="ml-1.5 text-xs text-gray-500">({tab.count})</span>
                  )}
                  {tab.active && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary-500 rounded-full" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Search/Filter Bar */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search integrations..."
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg pl-9 pr-3 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-primary-500"
              />
            </div>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              All Categories
              <ChevronDown size={14} className="text-gray-400" />
            </button>
          </div>

          {/* Connected Integrations */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-white">Connected Integrations</h3>
            {connectedIntegrations.map((integration) => {
              const Icon = integration.icon;
              return (
                <Card key={integration.name} padding="md">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-lg ${integration.iconBg}`}>
                        <Icon size={18} className={integration.iconColor} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-white">{integration.name}</p>
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-white/[0.06] text-gray-300">
                            {integration.category}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">{integration.description}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <span className="flex items-center gap-1.5 text-xs font-medium text-green-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                          Connected
                        </span>
                        <p className="text-xs text-gray-400 mt-0.5">{integration.connectedDate}</p>
                      </div>
                      <button className="text-gray-400 hover:text-white transition-colors">
                        <MoreVertical size={16} />
                      </button>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>

          {/* Available Integrations */}
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-white">Available Integrations</h3>
            {availableIntegrations.map((integration) => {
              const Icon = integration.icon;
              return (
                <Card key={integration.name} padding="md">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`p-2 rounded-lg ${integration.iconBg}`}>
                        <Icon size={18} className={integration.iconColor} />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-white">{integration.name}</p>
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-white/[0.06] text-gray-300">
                            {integration.category}
                          </span>
                        </div>
                        <p className="text-xs text-gray-400 mt-0.5">{integration.description}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button className="flex items-center gap-1.5 px-3 py-1.5 bg-teal-500/20 text-teal-400 text-xs font-medium rounded-lg hover:bg-teal-500/30 transition-colors">
                        Connect
                        <ChevronDown size={12} />
                      </button>
                    </div>
                  </div>
                </Card>
              );
            })}
          </div>

          {/* View More Link */}
          <div className="text-center">
            <button className="text-sm text-primary-400 hover:text-primary-300 transition-colors inline-flex items-center gap-1">
              View 14 more integrations
              <ChevronDown size={14} />
            </button>
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
          {/* Integration Overview */}
          <Card padding="lg">
            <div className="flex items-center gap-2 mb-3">
              <div className="p-1.5 rounded-lg bg-purple-500/10">
                <Puzzle size={16} className="text-purple-400" />
              </div>
              <h3 className="text-sm font-semibold text-white">Integration Overview</h3>
            </div>
            <p className="text-xs text-gray-400 mb-4">
              Extend the power of NVLABS Mission Control by connecting with the tools you already use.
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <p className="text-lg font-bold text-white">26</p>
                <p className="text-xs text-gray-400">Total Integrations</p>
              </div>
              <div className="p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <p className="text-lg font-bold text-green-400">8</p>
                <p className="text-xs text-gray-400">Connected</p>
              </div>
              <div className="p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <p className="text-lg font-bold text-blue-400">18</p>
                <p className="text-xs text-gray-400">Available</p>
              </div>
              <div className="p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <p className="text-lg font-bold text-purple-400">7</p>
                <p className="text-xs text-gray-400">Categories</p>
              </div>
            </div>
          </Card>

          {/* Recent Integration Activity */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">Recent Integration Activity</h3>
            <div className="space-y-3">
              {recentActivity.map((item, idx) => (
                <div key={idx} className="flex items-start gap-2.5">
                  <span className={`w-2 h-2 rounded-full mt-1.5 flex-shrink-0 ${item.dotColor}`} />
                  <div>
                    <p className="text-xs text-gray-300">{item.text}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{item.timestamp}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">Need Help?</h3>
            <div className="space-y-3">
              <a
                href="#"
                className="flex items-start justify-between group"
              >
                <div>
                  <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                    Integration Documentation
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Learn how to connect and configure integrations.
                  </p>
                </div>
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0 mt-0.5" />
              </a>
              <a
                href="#"
                className="flex items-start justify-between group"
              >
                <div>
                  <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                    View Webhooks
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Manage incoming and outgoing webhooks.
                  </p>
                </div>
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0 mt-0.5" />
              </a>
              <a
                href="#"
                className="flex items-start justify-between group"
              >
                <div>
                  <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                    Developer Support
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Get help from our developer community.
                  </p>
                </div>
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0 mt-0.5" />
              </a>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
