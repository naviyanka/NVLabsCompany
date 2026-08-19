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
  Pencil,
  Camera,
  Monitor,
  Sun,
  Moon,
  Plus,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: true },
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

const sessionActivity = [
  {
    date: 'Current Session',
    device: 'Windows \u2022 Chrome \u2022 127.0.0.1',
    active: true,
  },
  {
    date: 'May 16, 2024, 09:12 AM',
    device: 'Windows \u2022 Chrome \u2022 127.0.0.1',
    active: false,
  },
  {
    date: 'May 15, 2024, 07:45 PM',
    device: 'Android \u2022 Chrome \u2022 223.18.45.67',
    active: false,
  },
  {
    date: 'May 15, 2024, 03:22 PM',
    device: 'Windows \u2022 Edge \u2022 127.0.0.1',
    active: false,
  },
  {
    date: 'May 14, 2024, 11:08 AM',
    device: 'iOS \u2022 Safari \u2022 106.51.12.34',
    active: false,
  },
];

const linkedAccounts = [
  { name: 'Google', detail: 'navi.yanka@gmail.com', connected: true },
  { name: 'GitHub', detail: 'navi-yanka', connected: true },
  { name: 'Slack', detail: 'navi_yanka', connected: true },
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
          <Card padding="lg">
            <div className="flex items-center justify-between mb-5">
              <div>
                <h2 className="text-lg font-semibold text-white">Profile</h2>
                <p className="text-sm text-gray-400 mt-0.5">
                  View and update your personal information and preferences.
                </p>
              </div>
              <button className="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors">
                Save Changes
              </button>
            </div>

            {/* Profile Information */}
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-white mb-4">Profile Information</h3>
              <div className="flex items-start gap-6 mb-6">
                <div className="flex flex-col items-center gap-2">
                  <div className="relative">
                    <div className="w-20 h-20 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center text-white text-2xl font-bold">
                      NY
                    </div>
                    <div className="absolute bottom-0 right-0 w-7 h-7 rounded-full bg-dark-surface border-2 border-dark-card flex items-center justify-center">
                      <Pencil size={12} className="text-gray-400" />
                    </div>
                  </div>
                  <button className="px-3 py-1.5 bg-teal-500/20 text-teal-400 text-xs font-medium rounded-lg hover:bg-teal-500/30 transition-colors flex items-center gap-1.5">
                    <Camera size={12} />
                    Change Photo
                  </button>
                  <p className="text-xs text-gray-500">JPG, PNG or WebP. Max 2MB.</p>
                </div>
                <div className="flex-1 grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-400 mb-1.5">Full Name</label>
                    <input
                      type="text"
                      defaultValue="Navi Yanka"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1.5">Username</label>
                    <input
                      type="text"
                      defaultValue="navi_yanka"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1.5">Email Address</label>
                    <input
                      type="email"
                      defaultValue="navi.yanka@nvlabs.dev"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1.5">Job Title</label>
                    <input
                      type="text"
                      defaultValue="Operator"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1.5">Phone Number</label>
                    <div className="flex items-center gap-2">
                      <div className="flex items-center gap-1.5 px-2 py-2 bg-dark-bg border border-white/[0.08] rounded-lg">
                        <span className="text-sm">🇮🇳</span>
                      </div>
                      <input
                        type="text"
                        defaultValue="+91 98765 43210"
                        className="flex-1 bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm text-gray-400 mb-1.5">Department</label>
                    <input
                      type="text"
                      defaultValue="Operations"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                    />
                  </div>
                </div>
              </div>
            </div>

            {/* About You */}
            <div className="mb-6">
              <h3 className="text-sm font-semibold text-white mb-4">About You</h3>
              <div className="relative">
                <label className="block text-sm text-gray-400 mb-1.5">Bio</label>
                <textarea
                  defaultValue="Passionate about cybersecurity, automation, and building intelligent systems."
                  maxLength={200}
                  rows={3}
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 resize-none"
                />
                <p className="text-xs text-gray-500 text-right mt-1">67/200</p>
              </div>
            </div>

            {/* Preferences */}
            <div>
              <h3 className="text-sm font-semibold text-white mb-1">Preferences</h3>
              <p className="text-xs text-gray-400 mb-4">
                Customize your experience and how you interact with the platform.
              </p>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm text-gray-400 mb-1.5">Language</label>
                  <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                    <option>English (US)</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">Select your preferred language</p>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1.5">Time Zone</label>
                  <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                    <option>(GMT+05:30) Asia/Kolkata</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">Select your local time zone</p>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1.5">Date Format</label>
                  <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                    <option>May 16, 2024 (MMM DD, YYYY)</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">Choose your preferred date format</p>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-4">Theme</label>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="p-3 rounded-lg bg-dark-bg border-2 border-primary-500 cursor-pointer">
                      <div className="flex items-center gap-2 mb-1.5">
                        <Monitor size={16} className="text-primary-400" />
                        <span className="text-sm font-medium text-white">System</span>
                      </div>
                      <p className="text-xs text-gray-400">Use system setting</p>
                    </div>
                    <div className="p-3 rounded-lg bg-dark-bg border border-white/[0.08] cursor-pointer hover:border-white/20 transition-colors">
                      <div className="flex items-center gap-2 mb-1.5">
                        <Sun size={16} className="text-gray-400" />
                        <span className="text-sm font-medium text-white">Light</span>
                      </div>
                      <p className="text-xs text-gray-400">Light theme</p>
                    </div>
                    <div className="p-3 rounded-lg bg-dark-bg border border-white/[0.08] cursor-pointer hover:border-white/20 transition-colors">
                      <div className="flex items-center gap-2 mb-1.5">
                        <Moon size={16} className="text-gray-400" />
                        <span className="text-sm font-medium text-white">Dark</span>
                      </div>
                      <p className="text-xs text-gray-400">Dark theme</p>
                    </div>
                  </div>
                </div>
                <div>
                  <label className="block text-sm text-gray-400 mb-1.5">Week Starts On</label>
                  <select className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 appearance-none">
                    <option>Monday</option>
                  </select>
                  <p className="text-xs text-gray-500 mt-1">Select the first day of the week</p>
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
          {/* Account Status */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white">Account Status</h3>
              <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/20 text-green-400">
                Active
              </span>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Member since</span>
                <span className="text-xs text-white">March 12, 2024</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Last login</span>
                <span className="text-xs text-white">May 16, 2024, 10:25 AM</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">Account type</span>
                <span className="text-xs text-white">Operator</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">2FA Status</span>
                <span className="text-xs font-medium text-green-400">Enabled</span>
              </div>
            </div>
          </Card>

          {/* Session Activity */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white">Session Activity</h3>
              <a href="#" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                View All
              </a>
            </div>
            <div className="space-y-3">
              {sessionActivity.map((session, idx) => (
                <div key={idx} className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="text-xs text-gray-400 truncate">{session.date}</p>
                    <p className="text-xs text-white truncate mt-0.5">{session.device}</p>
                  </div>
                  {session.active && (
                    <span className="flex items-center gap-1 text-xs text-green-400 whitespace-nowrap">
                      <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                      Active
                    </span>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* Linked Accounts */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white">Linked Accounts</h3>
              <a href="#" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                Manage
              </a>
            </div>
            <div className="space-y-3">
              {linkedAccounts.map((account) => (
                <div key={account.name} className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-medium text-white">{account.name}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{account.detail}</p>
                  </div>
                  <span className="text-xs font-medium text-green-400">Connected</span>
                </div>
              ))}
            </div>
            <button className="mt-4 w-full flex items-center justify-center gap-1.5 px-4 py-2 bg-teal-500/20 text-teal-400 text-sm font-medium rounded-lg hover:bg-teal-500/30 transition-colors">
              <Plus size={14} />
              Connect Account
            </button>
          </Card>
        </div>
      </div>
    </div>
  );
}
