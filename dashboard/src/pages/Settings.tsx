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
  AlertTriangle,
  Cloud,
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
  { label: 'Audit Logs', icon: FileText, active: false },
  { label: 'Appearance', icon: Palette, active: false },
  { label: 'Advanced', icon: Wrench, active: true },
];

const footerLinks = [
  { label: 'Documentation' },
  { label: 'Support' },
  { label: 'Privacy Policy' },
  { label: 'Terms of Service' },
];

const advancedTabs = [
  { label: 'System', active: true },
  { label: 'Developer', active: false },
  { label: 'Performance', active: false },
  { label: 'Experimental Features', active: false },
  { label: 'Maintenance', active: false },
  { label: 'Diagnostics', active: false },
];

const advancedOptionsCards = [
  {
    title: 'Database Optimization',
    description: 'Enable advanced query cache and index recommendations.',
    icon: Database,
    hasToggle: true,
    toggleOn: true,
  },
  {
    title: 'Background Jobs',
    description: 'Configure concurrency and retry policies.',
    icon: Cog,
    hasToggle: false,
    toggleOn: false,
  },
  {
    title: 'Cache Management',
    description: 'Manage cache providers and expiration policies.',
    icon: Cloud,
    hasToggle: false,
    toggleOn: false,
  },
  {
    title: 'Security Headers',
    description: 'Configure HTTP security headers and policies.',
    icon: Shield,
    hasToggle: false,
    toggleOn: false,
  },
];

const systemHealthItems = [
  { label: 'Configuration', status: 'Healthy', healthy: true },
  { label: 'Cache', status: 'Healthy', healthy: true },
  { label: 'Background Jobs', status: 'Healthy', healthy: true },
  { label: 'Message Queue', status: 'Healthy', healthy: true },
  { label: 'External Services', status: 'Degraded', healthy: false },
  { label: 'File Storage', status: 'Healthy', healthy: true },
];

const developerTools = [
  { title: 'API Explorer', description: 'Test and explore API endpoints.' },
  { title: 'Database Viewer', description: 'View and query database (read-only).' },
  { title: 'Log Viewer', description: 'Search and analyze system logs.' },
  { title: 'Queue Inspector', description: 'Inspect job queues and workers.' },
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
          <div>
            <h2 className="text-lg font-semibold text-white">Advanced</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              Configure advanced settings and developer options for your platform.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex items-center gap-1 border-b border-white/[0.08]">
            {advancedTabs.map((tab) => (
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

          {/* Settings List Card */}
          <Card padding="lg">
            <div className="divide-y divide-white/[0.08]">
              {/* Environment Mode */}
              <div className="flex items-start justify-between py-4 first:pt-0">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Environment Mode</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Control the runtime environment for the platform.
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    Changes require restart to take effect.
                  </p>
                </div>
                <div className="flex-shrink-0 ml-4">
                  <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-white/[0.08] bg-dark-bg text-sm text-white">
                    <span>Production</span>
                    <ChevronDown size={14} className="text-gray-400" />
                  </div>
                </div>
              </div>

              {/* Debug Mode */}
              <div className="flex items-start justify-between py-4">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Debug Mode</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Enable verbose logging and detailed error reporting.
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Disabled in production</p>
                </div>
                <div className="flex-shrink-0 ml-4">
                  <div className="w-9 h-5 rounded-full bg-white/[0.08] relative cursor-pointer">
                    <div className="absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-gray-400 transition-transform" />
                  </div>
                </div>
              </div>

              {/* Feature Flags */}
              <div className="flex items-start justify-between py-4">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Feature Flags</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Manage feature flags and rollouts for your organization.
                  </p>
                </div>
                <div className="flex-shrink-0 ml-4">
                  <button className="text-sm font-medium text-primary-400 hover:text-primary-300 transition-colors">
                    Manage Feature Flags &rarr;
                  </button>
                </div>
              </div>

              {/* Request Timeout */}
              <div className="flex items-start justify-between py-4">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Request Timeout</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Set the default timeout for API and internal requests.
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Range: 5 - 300 seconds</p>
                </div>
                <div className="flex-shrink-0 ml-4 flex items-center gap-2">
                  <input
                    type="text"
                    defaultValue="30"
                    className="w-16 px-2.5 py-1.5 text-sm text-white bg-dark-bg border border-white/[0.08] rounded-lg text-center"
                    readOnly
                  />
                  <span className="text-xs text-gray-400">seconds</span>
                </div>
              </div>

              {/* Session Timeout */}
              <div className="flex items-start justify-between py-4">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Session Timeout</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Set the inactive session timeout for users.
                  </p>
                  <p className="text-xs text-gray-500 mt-1">Range: 15 - 1440 minutes</p>
                </div>
                <div className="flex-shrink-0 ml-4 flex items-center gap-2">
                  <input
                    type="text"
                    defaultValue="60"
                    className="w-16 px-2.5 py-1.5 text-sm text-white bg-dark-bg border border-white/[0.08] rounded-lg text-center"
                    readOnly
                  />
                  <span className="text-xs text-gray-400">minutes</span>
                </div>
              </div>

              {/* Rate Limiting */}
              <div className="flex items-start justify-between py-4">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Rate Limiting</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Configure global rate limiting for API requests.
                  </p>
                </div>
                <div className="flex-shrink-0 ml-4 flex items-center gap-3">
                  <div className="w-9 h-5 rounded-full bg-primary-500 relative cursor-pointer">
                    <div className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-white transition-transform" />
                  </div>
                  <button className="text-sm font-medium text-primary-400 hover:text-primary-300 transition-colors">
                    Configure Limits &rarr;
                  </button>
                </div>
              </div>

              {/* IP Allowlist */}
              <div className="flex items-start justify-between py-4">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">IP Allowlist</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Allow requests only from trusted IP addresses and ranges.
                  </p>
                </div>
                <div className="flex-shrink-0 ml-4 flex items-center gap-3">
                  <span className="text-sm text-white font-medium">12</span>
                  <span className="text-xs text-gray-400">IPs configured</span>
                  <button className="text-sm font-medium text-primary-400 hover:text-primary-300 transition-colors">
                    Manage IPs &rarr;
                  </button>
                </div>
              </div>

              {/* Webhooks Security */}
              <div className="flex items-start justify-between py-4 last:pb-0">
                <div className="flex-1">
                  <h4 className="text-sm font-medium text-white">Webhooks Security</h4>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Enforce webhook signing and verify signatures.
                  </p>
                </div>
                <div className="flex-shrink-0 ml-4 flex items-center gap-3">
                  <div className="w-9 h-5 rounded-full bg-primary-500 relative cursor-pointer">
                    <div className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-white transition-transform" />
                  </div>
                  <button className="text-sm font-medium text-primary-400 hover:text-primary-300 transition-colors">
                    Configure Webhooks &rarr;
                  </button>
                </div>
              </div>
            </div>
          </Card>

          {/* Advanced Options Section */}
          <div>
            <h3 className="text-sm font-semibold text-white mb-4">Advanced Options</h3>
            <div className="grid grid-cols-4 gap-4">
              {advancedOptionsCards.map((card) => {
                const Icon = card.icon;
                return (
                  <Card key={card.title} padding="md">
                    <div className="flex flex-col h-full">
                      <div className="p-2 rounded-lg bg-primary-500/10 w-fit mb-3">
                        <Icon size={18} className="text-primary-400" />
                      </div>
                      <h4 className="text-sm font-medium text-white mb-1">{card.title}</h4>
                      <p className="text-xs text-gray-400 mb-4 flex-1">{card.description}</p>
                      {card.hasToggle && (
                        <div className="mb-3">
                          <div className="w-9 h-5 rounded-full bg-primary-500 relative cursor-pointer">
                            <div className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full bg-white transition-transform" />
                          </div>
                        </div>
                      )}
                      <button className="w-full px-3 py-2 text-xs font-medium text-primary-400 border border-primary-500/30 rounded-lg hover:bg-primary-500/10 transition-colors">
                        Configure
                      </button>
                    </div>
                  </Card>
                );
              })}
            </div>
          </div>

          {/* Danger Zone Section */}
          <Card padding="lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-red-500/10">
                  <AlertTriangle size={18} className="text-red-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-red-400">Danger Zone</h3>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Irreversible and potentially dangerous actions.
                  </p>
                </div>
              </div>
              <button className="px-4 py-2 text-sm font-medium text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/10 transition-colors">
                Open Danger Zone
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
          {/* System Health */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">System Health</h3>
            <p className="text-xs text-gray-400 mb-4">
              Real-time status of advanced systems.
            </p>

            <div className="space-y-3 mb-4">
              {systemHealthItems.map((item) => (
                <div key={item.label} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className={`w-2 h-2 rounded-full ${
                        item.healthy ? 'bg-green-400' : 'bg-red-400'
                      }`}
                    />
                    <span className="text-xs text-gray-300">{item.label}</span>
                  </div>
                  <span
                    className={`text-xs font-medium ${
                      item.healthy ? 'text-green-400' : 'text-red-400'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
              ))}
            </div>

            <button className="text-xs font-medium text-primary-400 hover:text-primary-300 transition-colors">
              View System Health &rarr;
            </button>
          </Card>

          {/* Developer Tools */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Developer Tools</h3>
            <p className="text-xs text-gray-400 mb-4">
              Useful tools for developers and admins.
            </p>

            <div className="space-y-3 mb-4">
              {developerTools.map((tool) => (
                <div key={tool.title}>
                  <h4 className="text-xs font-medium text-white">{tool.title}</h4>
                  <p className="text-xs text-gray-400 mt-0.5">{tool.description}</p>
                </div>
              ))}
            </div>

            <button className="text-xs font-medium text-primary-400 hover:text-primary-300 transition-colors">
              View All Tools &rarr;
            </button>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-4">
              Learn more about advanced settings.
            </p>
            <div className="space-y-3">
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Advanced Settings Guide
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
