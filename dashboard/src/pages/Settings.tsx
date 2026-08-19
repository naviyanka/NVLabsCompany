import { useState } from 'react';
import { Card } from '@/components/common/Card';
import {
  Settings as SettingsIcon,
  User,
  Shield,
  ShieldCheck,
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
  EyeOff,
  Smartphone,
  Laptop,
  Monitor,
  CheckCircle2,
  ChevronRight,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: false },
  { label: 'Security', icon: Shield, active: true },
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

const activeSessions = [
  {
    device: 'Windows \u2022 Chrome',
    label: 'This device',
    icon: Monitor,
    location: 'Kolkata, India',
    ip: '117.230.45.12',
    lastActive: 'Just now',
    status: 'Active',
    current: true,
  },
  {
    device: 'Android \u2022 Chrome',
    label: 'OnePlus 11',
    icon: Smartphone,
    location: 'Delhi, India',
    ip: '103.2.145.67',
    lastActive: 'May 16, 2024, 10:12 AM',
    status: 'Active',
    current: false,
  },
  {
    device: 'macOS \u2022 Safari',
    label: 'MacBook Pro',
    icon: Laptop,
    location: 'Bangalore, India',
    ip: '2405:201:2500:1234::1',
    lastActive: 'May 15, 2024, 07:45 PM',
    status: 'Active',
    current: false,
  },
];

const securityChecklist = [
  'Password is strong',
  'Two-factor authentication is enabled',
  'Recovery email is verified',
  'No suspicious activity detected',
];

const recentSecurityActivity = [
  {
    color: 'bg-green-400',
    title: 'Successful login',
    subtitle: 'Windows \u2022 Kolkata, India',
    time: 'Just now',
  },
  {
    color: 'bg-orange-400',
    title: 'Password changed',
    subtitle: 'Kolkata, India',
    time: 'May 12, 10:30 AM',
  },
  {
    color: 'bg-blue-400',
    title: '2FA enabled',
    subtitle: 'Kolkata, India',
    time: 'May 10, 09:15 PM',
  },
  {
    color: 'bg-purple-400',
    title: 'Recovery email updated',
    subtitle: 'Kolkata, India',
    time: 'May 05, 04:22 PM',
  },
  {
    color: 'bg-orange-400',
    title: 'New device login',
    subtitle: 'Android \u2022 Delhi, India',
    time: 'May 02, 11:08 AM',
  },
];

// ─── Main Component ────────────────────────────────────────────────────────────

export function Settings() {
  const [showCurrentPassword, setShowCurrentPassword] = useState(false);
  const [showNewPassword, setShowNewPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

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
          {/* Section 1: Password */}
          <Card padding="lg">
            <div className="mb-5">
              <h2 className="text-lg font-semibold text-white">Password</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Ensure your password is strong and unique.
              </p>
            </div>

            <div className="space-y-4">
              {/* Current Password */}
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <label className="block text-sm text-gray-400 mb-1.5">Current Password</label>
                  <div className="relative">
                    <input
                      type={showCurrentPassword ? 'text' : 'password'}
                      defaultValue="securepassword123"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowCurrentPassword(!showCurrentPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
                    >
                      {showCurrentPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                <div className="pt-6">
                  <span className="text-xs text-gray-400 whitespace-nowrap">Last changed: May 12, 2024</span>
                </div>
              </div>

              {/* New Password */}
              <div className="flex items-center gap-4">
                <div className="flex-1">
                  <label className="block text-sm text-gray-400 mb-1.5">New Password</label>
                  <div className="relative">
                    <input
                      type={showNewPassword ? 'text' : 'password'}
                      defaultValue="newstrongpassword"
                      className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 pr-10"
                    />
                    <button
                      type="button"
                      onClick={() => setShowNewPassword(!showNewPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
                    >
                      {showNewPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
                <div className="pt-6 flex items-center gap-2">
                  <div className="flex gap-1">
                    <div className="w-6 h-1.5 rounded-full bg-green-400" />
                    <div className="w-6 h-1.5 rounded-full bg-green-400" />
                    <div className="w-6 h-1.5 rounded-full bg-green-400" />
                    <div className="w-6 h-1.5 rounded-full bg-green-400" />
                  </div>
                  <span className="text-xs text-green-400 font-medium">Strong</span>
                </div>
              </div>

              {/* Confirm New Password */}
              <div>
                <label className="block text-sm text-gray-400 mb-1.5">Confirm New Password</label>
                <div className="relative">
                  <input
                    type={showConfirmPassword ? 'text' : 'password'}
                    defaultValue="newstrongpassword"
                    className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
                  >
                    {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-6">
              <button className="px-4 py-2 bg-teal-500/20 text-teal-400 text-sm font-medium rounded-lg hover:bg-teal-500/30 transition-colors">
                Update Password
              </button>
            </div>
          </Card>

          {/* Section 2: Two-Factor Authentication */}
          <Card padding="lg">
            <div className="mb-5">
              <h2 className="text-lg font-semibold text-white">Two-Factor Authentication (2FA)</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Add an extra layer of security to your account.
              </p>
            </div>

            {/* Status Row */}
            <div className="flex items-center gap-3 mb-6 p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
              <span className="text-sm text-gray-400">Status</span>
              <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/20 text-green-400">
                Enabled
              </span>
              <span className="text-sm text-gray-400 flex-1">
                Your account is protected with two-factor authentication.
              </span>
              <button className="px-3 py-1.5 border border-white/[0.08] text-sm text-gray-300 rounded-lg hover:bg-white/[0.04] transition-colors">
                Manage 2FA
              </button>
            </div>

            {/* Methods */}
            <div className="space-y-3">
              <div className="flex items-center gap-3 p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div className="p-2 rounded-lg bg-primary-500/10">
                  <ShieldCheck size={16} className="text-primary-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white">Authenticator App</p>
                  <p className="text-xs text-gray-400 mt-0.5">Using Google Authenticator</p>
                </div>
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/20 text-green-400">
                  Primary
                </span>
                <button className="px-3 py-1.5 border border-white/[0.08] text-sm text-gray-300 rounded-lg hover:bg-white/[0.04] transition-colors">
                  Change Method
                </button>
              </div>

              <div className="flex items-center gap-3 p-3 rounded-lg bg-dark-bg border border-white/[0.08]">
                <div className="p-2 rounded-lg bg-primary-500/10">
                  <Key size={16} className="text-primary-400" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white">Backup Codes</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Use these codes to access your account if you lose your device.
                  </p>
                </div>
                <button className="px-3 py-1.5 border border-white/[0.08] text-sm text-gray-300 rounded-lg hover:bg-white/[0.04] transition-colors">
                  View Backup Codes
                </button>
              </div>
            </div>
          </Card>

          {/* Section 3: Active Sessions */}
          <Card padding="lg">
            <div className="mb-5">
              <h2 className="text-lg font-semibold text-white">Active Sessions</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Manage your active sessions across devices.
              </p>
            </div>

            {/* Sessions Table */}
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-white/[0.08]">
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider pb-3">
                      Device
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider pb-3">
                      Location / IP
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider pb-3">
                      Last Active
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider pb-3">
                      Status
                    </th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider pb-3">
                      Action
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {activeSessions.map((session, idx) => {
                    const DeviceIcon = session.icon;
                    return (
                      <tr key={idx}>
                        <td className="py-3">
                          <div className="flex items-center gap-2">
                            <DeviceIcon size={14} className="text-gray-400" />
                            <div>
                              <p className="text-sm text-white">{session.device}</p>
                              <p className="text-xs text-gray-400">{session.label}</p>
                            </div>
                          </div>
                        </td>
                        <td className="py-3">
                          <p className="text-sm text-white">{session.location}</p>
                          <p className="text-xs text-gray-400">{session.ip}</p>
                        </td>
                        <td className="py-3">
                          <span className="text-sm text-gray-300">{session.lastActive}</span>
                        </td>
                        <td className="py-3">
                          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/20 text-green-400">
                            {session.status}
                          </span>
                        </td>
                        <td className="py-3">
                          {session.current ? (
                            <span className="text-sm text-gray-500">&mdash;</span>
                          ) : (
                            <button className="px-3 py-1 text-xs font-medium text-red-400 bg-red-500/10 rounded-lg hover:bg-red-500/20 transition-colors">
                              Revoke
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="mt-4">
              <a
                href="#"
                className="text-sm text-teal-400 hover:text-teal-300 transition-colors"
              >
                View All Sessions
              </a>
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
          {/* Security Overview */}
          <Card padding="lg">
            <div className="flex flex-col items-center text-center mb-4">
              <div className="p-3 rounded-full bg-green-500/10 mb-3">
                <ShieldCheck size={32} className="text-green-400" />
              </div>
              <p className="text-sm font-semibold text-green-400">Your account is secure</p>
              <p className="text-xs text-gray-400 mt-1">Last security check: Just now</p>
            </div>
            <div className="space-y-2.5">
              {securityChecklist.map((item) => (
                <div key={item} className="flex items-center gap-2">
                  <CheckCircle2 size={14} className="text-green-400 flex-shrink-0" />
                  <span className="text-xs text-gray-300">{item}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Account Recovery */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Account Recovery</h3>
            <p className="text-xs text-gray-400 mb-4">
              Manage your recovery email and phone number.
            </p>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-400">Recovery Email</p>
                  <p className="text-xs text-white mt-0.5">navi.yanka@nvlabs.dev</p>
                </div>
                <span className="flex items-center gap-1 text-xs text-green-400 font-medium">
                  Verified <CheckCircle2 size={12} />
                </span>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs text-gray-400">Recovery Phone</p>
                  <p className="text-xs text-white mt-0.5">+91 98765 43210</p>
                </div>
                <span className="flex items-center gap-1 text-xs text-green-400 font-medium">
                  Verified <CheckCircle2 size={12} />
                </span>
              </div>
            </div>
            <a
              href="#"
              className="mt-4 inline-flex items-center gap-1 text-xs text-teal-400 hover:text-teal-300 transition-colors"
            >
              Manage Recovery Options
              <ChevronRight size={12} />
            </a>
          </Card>

          {/* Recent Security Activity */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white">Recent Security Activity</h3>
              <a
                href="#"
                className="text-xs text-primary-400 hover:text-primary-300 transition-colors"
              >
                View All
              </a>
            </div>
            <div className="space-y-3">
              {recentSecurityActivity.map((activity, idx) => (
                <a
                  key={idx}
                  href="#"
                  className="flex items-center gap-3 group"
                >
                  <div className={`w-2 h-2 rounded-full ${activity.color} flex-shrink-0`} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-white">{activity.title}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{activity.subtitle}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{activity.time}</p>
                  </div>
                  <ChevronRight
                    size={14}
                    className="text-gray-500 group-hover:text-gray-300 transition-colors flex-shrink-0"
                  />
                </a>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
