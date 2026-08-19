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
  Eye,
  Copy,
  Plus,
  Search,
  ChevronDown,
  MoreVertical,
  AlertTriangle,
  XCircle,
  CheckCircle2,
  Code2,
  Star,
  BarChart3,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: false },
  { label: 'Security', icon: Shield, active: false },
  { label: 'API Keys', icon: Key, active: true },
  { label: 'Integrations', icon: Puzzle, active: false },
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

const statCards = [
  {
    label: 'Total Keys',
    value: '6',
    subtitle: 'Across all environments',
    icon: Key,
    color: 'primary',
  },
  {
    label: 'Active Keys',
    value: '4',
    subtitle: 'Currently active',
    icon: CheckCircle2,
    color: 'green',
  },
  {
    label: 'Expired Keys',
    value: '1',
    subtitle: 'No longer valid',
    icon: AlertTriangle,
    color: 'warning',
  },
  {
    label: 'Revoked Keys',
    value: '1',
    subtitle: 'Manually revoked',
    icon: XCircle,
    color: 'danger',
  },
];

const apiKeys = [
  {
    name: 'Production Server Key',
    description: 'Used by production services',
    badge: { text: 'Production', color: 'green' },
    key: 'nv_\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    environment: { text: 'Production', color: 'green' },
    status: 'Active',
    lastUsed: 'May 16, 2024, 10:25 AM',
    dimmed: false,
  },
  {
    name: 'Agent Service Key',
    description: 'For AI agent communication',
    badge: { text: 'Backend', color: 'blue' },
    key: 'nv_\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    environment: { text: 'Staging', color: 'orange' },
    status: 'Active',
    lastUsed: 'May 16, 2024, 09:12 AM',
    dimmed: false,
  },
  {
    name: 'Data Ingestion Key',
    description: 'For pipeline data ingestion',
    badge: { text: 'Backend', color: 'blue' },
    key: 'nv_\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    environment: { text: 'Staging', color: 'orange' },
    status: 'Active',
    lastUsed: 'May 15, 2024, 11:47 PM',
    dimmed: false,
  },
  {
    name: 'Dev Environment Key',
    description: 'Development environment access',
    badge: { text: 'Development', color: 'purple' },
    key: 'nv_\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    environment: { text: 'Development', color: 'purple' },
    status: 'Active',
    lastUsed: 'May 15, 2024, 04:32 PM',
    dimmed: false,
  },
  {
    name: 'Old Analytics Key',
    description: 'Deprecated analytics integration',
    badge: { text: 'Analytics', color: 'gray' },
    key: 'nv_\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    environment: { text: 'Production', color: 'green' },
    status: 'Expired',
    lastUsed: 'Apr 20, 2024, 02:15 PM',
    dimmed: true,
  },
  {
    name: 'Revoked Test Key',
    description: 'Compromised key (revoked)',
    badge: { text: 'Test', color: 'gray' },
    key: 'nv_\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022',
    environment: { text: 'Test', color: 'gray' },
    status: 'Revoked',
    lastUsed: 'Mar 12, 2024, 05:40 PM',
    dimmed: true,
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────

function getBadgeClasses(color: string) {
  switch (color) {
    case 'green':
      return 'bg-green-500/20 text-green-400';
    case 'blue':
      return 'bg-blue-500/20 text-blue-400';
    case 'orange':
      return 'bg-orange-500/20 text-orange-400';
    case 'purple':
      return 'bg-purple-500/20 text-purple-400';
    case 'gray':
      return 'bg-gray-500/20 text-gray-400';
    default:
      return 'bg-gray-500/20 text-gray-400';
  }
}

function getStatIconClasses(color: string) {
  switch (color) {
    case 'primary':
      return 'bg-primary-500/10 text-primary-400';
    case 'green':
      return 'bg-green-500/10 text-green-400';
    case 'warning':
      return 'bg-warning-500/10 text-warning-500';
    case 'danger':
      return 'bg-danger-500/10 text-danger-500';
    default:
      return 'bg-primary-500/10 text-primary-400';
  }
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
              <h2 className="text-lg font-semibold text-white">API Keys</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Manage API keys to securely access NVLABS Mission Control APIs.
              </p>
            </div>
            <button className="flex items-center gap-2 px-4 py-2 bg-green-500/20 text-green-400 text-sm font-medium rounded-lg hover:bg-green-500/30 transition-colors">
              <Plus size={16} />
              Generate New Key
            </button>
          </div>

          {/* Stat Cards Row */}
          <div className="grid grid-cols-4 gap-4">
            {statCards.map((stat) => {
              const StatIcon = stat.icon;
              return (
                <Card key={stat.label} padding="md">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-400 font-medium">{stat.label}</span>
                    <div className={`p-1.5 rounded-lg ${getStatIconClasses(stat.color)}`}>
                      <StatIcon size={14} />
                    </div>
                  </div>
                  <p className="text-2xl font-bold text-white">{stat.value}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{stat.subtitle}</p>
                </Card>
              );
            })}
          </div>

          {/* Search/Filter Bar */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search API keys by name or description..."
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg pl-9 pr-3 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-primary-500"
              />
            </div>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              All Status
              <ChevronDown size={14} className="text-gray-400" />
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              All Environments
              <ChevronDown size={14} className="text-gray-400" />
            </button>
          </div>

          {/* API Keys Table */}
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-white/[0.08]">
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">
                      Name &amp; Description
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">
                      Key
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">
                      Environment
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">
                      Status
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">
                      Last Used
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {apiKeys.map((apiKey, idx) => (
                    <tr key={idx} className={apiKey.dimmed ? 'opacity-60' : ''}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className="p-1.5 rounded-lg bg-primary-500/10">
                            <Code2 size={14} className="text-primary-400" />
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium text-white">{apiKey.name}</p>
                              <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${getBadgeClasses(apiKey.badge.color)}`}>
                                {apiKey.badge.text}
                              </span>
                            </div>
                            <p className="text-xs text-gray-400 mt-0.5">{apiKey.description}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <code className="text-xs text-gray-300 font-mono">{apiKey.key}</code>
                          <button className="text-gray-400 hover:text-white transition-colors">
                            <Eye size={14} />
                          </button>
                          <button className="text-gray-400 hover:text-white transition-colors">
                            <Copy size={14} />
                          </button>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${getBadgeClasses(apiKey.environment.color)}`}>
                          {apiKey.environment.text}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`flex items-center gap-1.5 text-xs font-medium ${
                          apiKey.status === 'Active' ? 'text-green-400' : 'text-red-400'
                        }`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${
                            apiKey.status === 'Active' ? 'bg-green-400' : 'bg-red-400'
                          }`} />
                          {apiKey.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-gray-300">{apiKey.lastUsed}</span>
                      </td>
                      <td className="px-4 py-3">
                        <button className="text-gray-400 hover:text-white transition-colors">
                          <MoreVertical size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* API Key Best Practices */}
          <Card padding="lg">
            <div className="flex items-start gap-3">
              <div className="p-2 rounded-lg bg-warning-500/10">
                <Star size={16} className="text-warning-500" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-white mb-2">API Key Best Practices</h3>
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={14} className="text-green-400 flex-shrink-0" />
                    <span className="text-xs text-gray-300">
                      Store API keys securely and never share them publicly.
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={14} className="text-green-400 flex-shrink-0" />
                    <span className="text-xs text-gray-300">
                      Use environment-specific keys with minimal required permissions.
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={14} className="text-green-400 flex-shrink-0" />
                    <span className="text-xs text-gray-300">
                      Rotate keys regularly and revoke unused keys.
                    </span>
                  </div>
                </div>
                <a
                  href="#"
                  className="inline-flex items-center gap-1 mt-3 text-xs text-primary-400 hover:text-primary-300 transition-colors"
                >
                  Learn more in our documentation
                  <ExternalLink size={12} />
                </a>
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
          {/* About API Keys */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">About API Keys</h3>
            <p className="text-xs text-gray-400 mb-4">
              API keys allow external applications and services to authenticate with the NVLABS Mission Control API.
            </p>
            <div className="space-y-3">
              <div className="flex items-start gap-2.5">
                <div className="p-1.5 rounded-lg bg-primary-500/10">
                  <Shield size={14} className="text-primary-400" />
                </div>
                <div>
                  <p className="text-xs font-medium text-white">Secure Access</p>
                  <p className="text-xs text-gray-400 mt-0.5">All keys are encrypted and securely stored.</p>
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <div className="p-1.5 rounded-lg bg-primary-500/10">
                  <SettingsIcon size={14} className="text-primary-400" />
                </div>
                <div>
                  <p className="text-xs font-medium text-white">Fine-grained Control</p>
                  <p className="text-xs text-gray-400 mt-0.5">Manage access with environment-specific keys.</p>
                </div>
              </div>
              <div className="flex items-start gap-2.5">
                <div className="p-1.5 rounded-lg bg-primary-500/10">
                  <BarChart3 size={14} className="text-primary-400" />
                </div>
                <div>
                  <p className="text-xs font-medium text-white">Usage Tracking</p>
                  <p className="text-xs text-gray-400 mt-0.5">Monitor when and how your keys are used.</p>
                </div>
              </div>
            </div>
          </Card>

          {/* Key Permissions */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Key Permissions</h3>
            <p className="text-xs text-gray-400 mb-4">
              All API keys inherit the permissions of the user who created them.
            </p>
            <button className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-white/[0.08] text-sm text-gray-300 rounded-lg hover:bg-white/[0.04] transition-colors">
              Manage Roles &amp; Permissions
              <ExternalLink size={14} />
            </button>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">Need Help?</h3>
            <div className="space-y-2.5">
              <a
                href="#"
                className="flex items-center justify-between text-xs text-gray-300 hover:text-white transition-colors"
              >
                <span>View API Documentation</span>
                <ExternalLink size={12} className="text-gray-400" />
              </a>
              <a
                href="#"
                className="flex items-center justify-between text-xs text-gray-300 hover:text-white transition-colors"
              >
                <span>Postman Collection</span>
                <ExternalLink size={12} className="text-gray-400" />
              </a>
              <a
                href="#"
                className="flex items-center justify-between text-xs text-gray-300 hover:text-white transition-colors"
              >
                <span>Developer Support</span>
                <ExternalLink size={12} className="text-gray-400" />
              </a>
              <a
                href="#"
                className="flex items-center justify-between text-xs text-gray-300 hover:text-white transition-colors"
              >
                <span>API Status</span>
                <span className="text-xs text-green-400">All Systems Operational</span>
              </a>
            </div>
          </Card>

          {/* Rate Limits */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">Rate Limits</h3>
            <div className="space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Standard Requests</span>
                <span className="text-xs font-medium text-white">1,000 / min</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Bulk Requests</span>
                <span className="text-xs font-medium text-white">500 / min</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Webhooks</span>
                <span className="text-xs font-medium text-white">100 / min</span>
              </div>
            </div>
            <a
              href="#"
              className="inline-flex items-center gap-1 mt-3 text-xs text-primary-400 hover:text-primary-300 transition-colors"
            >
              View all rate limits
              <ExternalLink size={12} />
            </a>
          </Card>
        </div>
      </div>
    </div>
  );
}
