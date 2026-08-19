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
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: true },
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
  { label: 'Advanced', icon: Wrench, active: false },
];

const footerLinks = [
  { label: 'Documentation' },
  { label: 'Support' },
  { label: 'Privacy Policy' },
  { label: 'Terms of Service' },
];

// ─── Toggle Component ──────────────────────────────────────────────────────────

function Toggle({ enabled }: { enabled: boolean }) {
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
          {/* Section 1: Platform Information */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-white">Platform Information</h2>
              <button className="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors">
                Save Changes
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Platform Name</label>
                <input
                  type="text"
                  defaultValue="NVLABS Mission Control"
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Tagline</label>
                <input
                  type="text"
                  defaultValue="AI-Powered Security Operations Platform"
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Time Zone</label>
                <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                  <option>(GMT+05:30) Asia/Kolkata</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Date Format</label>
                <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                  <option>May 16, 2024 (MMM DD, YYYY)</option>
                </select>
              </div>
            </div>
          </Card>

          {/* Section 2: Language & Region */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-white">Language &amp; Region</h2>
              <button className="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors">
                Save Changes
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Language</label>
                <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                  <option>English (US)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Number Format</label>
                <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                  <option>1,234.56</option>
                </select>
              </div>
            </div>
          </Card>

          {/* Section 3: Default Preferences */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-white">Default Preferences</h2>
              <button className="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors">
                Save Changes
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div>
                  <p className="text-sm font-medium text-white">Auto refresh dashboard</p>
                  <p className="text-xs text-gray-400 mt-0.5">Automatically refresh dashboard data</p>
                </div>
                <Toggle enabled={true} />
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div>
                  <p className="text-sm font-medium text-white">Shortcut tips</p>
                  <p className="text-xs text-gray-400 mt-0.5">Show tips and onboarding hints</p>
                </div>
                <Toggle enabled={true} />
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div>
                  <p className="text-sm font-medium text-white">Compact mode</p>
                  <p className="text-xs text-gray-400 mt-0.5">Reduce spacing and use compact layout</p>
                </div>
                <Toggle enabled={false} />
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div>
                  <p className="text-sm font-medium text-white">Confirm before delete</p>
                  <p className="text-xs text-gray-400 mt-0.5">Ask for confirmation before deleting items</p>
                </div>
                <Toggle enabled={true} />
              </div>
            </div>
          </Card>

          {/* Section 4: Session Settings */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-semibold text-white">Session Settings</h2>
              <button className="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors">
                Save Changes
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Session Timeout</label>
                <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                  <option>30 minutes</option>
                </select>
                <p className="text-xs text-gray-400 mt-1.5">Automatically sign out after period of inactivity</p>
              </div>
              <div className="flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div>
                  <p className="text-sm font-medium text-white">Concurrent Sessions</p>
                  <p className="text-xs text-gray-400 mt-0.5">Allow multiple active sessions</p>
                </div>
                <Toggle enabled={true} />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Max Session Duration</label>
                <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                  <option>8 hours</option>
                </select>
                <p className="text-xs text-gray-400 mt-1.5">Maximum allowed session duration</p>
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
          {/* Account Overview */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-4">Account Overview</h3>
            <div className="flex flex-col items-center text-center">
              <div className="w-16 h-16 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white text-xl font-bold mb-3">
                NY
              </div>
              <p className="text-sm font-medium text-white">Navi Yanka</p>
              <p className="text-xs text-gray-400 mt-0.5">navi.yanka@nvlabs.dev</p>
              <button className="mt-4 w-full px-4 py-2 border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white hover:border-white/20 transition-colors">
                Edit Profile
              </button>
            </div>
          </Card>

          {/* Subscription Plan */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-4">Subscription Plan</h3>
            <div className="space-y-3">
              <span className="inline-block px-2.5 py-1 text-xs font-medium rounded-full bg-primary-500/20 text-primary-400">
                Enterprise
              </span>
              <p className="text-xs text-gray-400">
                Advanced security operations for enterprise teams.
              </p>
              <div className="space-y-2 pt-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">Status</span>
                  <span className="text-xs font-medium text-green-400">Active</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">Renewal Date</span>
                  <span className="text-xs text-white">June 16, 2024</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">Seats Used</span>
                  <span className="text-xs text-white">12 / 25</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">Storage Used</span>
                  <span className="text-xs text-white">256 GB / 1 TB</span>
                </div>
              </div>
              <button className="mt-2 w-full flex items-center justify-center gap-1.5 px-4 py-2 border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white hover:border-white/20 transition-colors">
                Manage Subscription
                <ExternalLink size={12} />
              </button>
            </div>
          </Card>

          {/* System Information */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-4">System Information</h3>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Version</span>
                <span className="text-xs text-white font-mono">v2.1.0</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Environment</span>
                <span className="text-xs text-white">Production</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Uptime</span>
                <span className="text-xs text-white">15d 6h 24m</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Last Updated</span>
                <span className="text-xs text-white">May 16, 2024 10:25 AM</span>
              </div>
            </div>
            <button className="mt-4 w-full flex items-center justify-center gap-1.5 px-4 py-2 border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white hover:border-white/20 transition-colors">
              View System Health
              <ExternalLink size={12} />
            </button>
          </Card>

          {/* Danger Zone */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-red-400 mb-2">Danger Zone</h3>
            <p className="text-xs text-gray-400 mb-4">
              These actions are destructive and cannot be undone.
            </p>
            <div className="space-y-2">
              <button className="w-full flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08] hover:border-white/20 transition-colors group">
                <div className="text-left">
                  <p className="text-sm font-medium text-white">Clear Cache</p>
                  <p className="text-xs text-gray-400 mt-0.5">Clear application cache and temporary data</p>
                </div>
                <ChevronRight size={16} className="text-gray-400 group-hover:text-white" />
              </button>
              <button className="w-full flex items-center justify-between p-3 rounded-lg bg-dark-bg border border-white/[0.08] hover:border-red-500/30 transition-colors group">
                <div className="text-left">
                  <p className="text-sm font-medium text-red-400">Delete Account</p>
                  <p className="text-xs text-gray-400 mt-0.5">Permanently delete your account and all data</p>
                </div>
                <ChevronRight size={16} className="text-gray-400 group-hover:text-red-400" />
              </button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
