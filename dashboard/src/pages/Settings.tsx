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
  Search,
  RotateCcw,
  Pencil,
  CheckCircle,
  Target,
  RefreshCw,
  BookOpen,
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
  { label: 'System Configuration', icon: SettingsIcon, active: true },
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

const tabs = [
  { label: 'General Settings', active: true },
  { label: 'Security & Access', active: false },
  { label: 'Performance', active: false },
  { label: 'Maintenance', active: false },
  { label: 'Integrations', active: false },
  { label: 'Advanced', active: false },
];

const healthItems = [
  { label: 'System Services', status: 'Healthy' },
  { label: 'Security Configuration', status: 'Healthy' },
  { label: 'Database Connections', status: 'Healthy' },
  { label: 'Storage Systems', status: 'Healthy' },
  { label: 'Backup Configuration', status: 'Healthy' },
];

const helpLinks = [
  { title: 'System Configuration Guide', description: 'Learn how to configure the platform.' },
  { title: 'Best Practices', description: 'Follow recommended configuration best practices.' },
  { title: 'Admin Support', description: 'Get help from our support team.' },
  { title: 'Community Forum', description: 'Join discussions with other admins.' },
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

// ─── Config Item Component ─────────────────────────────────────────────────────

function ConfigItem({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-4 border-b border-white/[0.08] last:border-b-0">
      <div className="flex-1 min-w-0 pr-4">
        <p className="text-sm font-medium text-white">{title}</p>
        <p className="text-xs text-gray-400 mt-0.5">{description}</p>
      </div>
      <div className="flex-shrink-0">{children}</div>
    </div>
  );
}

// ─── Input Components ──────────────────────────────────────────────────────────

function TextInput({ value, icon }: { value: string; icon?: React.ReactNode }) {
  return (
    <div className="relative flex items-center">
      <input
        type="text"
        readOnly
        value={value}
        className="w-64 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg pr-9"
      />
      {icon && (
        <span className="absolute right-3 text-gray-400">{icon}</span>
      )}
    </div>
  );
}

function SelectInput({ value }: { value: string }) {
  return (
    <div className="relative flex items-center">
      <select
        className="w-64 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg appearance-none pr-9"
        defaultValue={value}
      >
        <option>{value}</option>
      </select>
      <ChevronDown size={14} className="absolute right-3 text-gray-400 pointer-events-none" />
    </div>
  );
}

function ChevronInput({ value }: { value: string }) {
  return (
    <div className="flex items-center gap-2 w-64 px-3 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg cursor-pointer">
      <span className="flex-1 truncate">{value}</span>
      <ChevronRight size={14} className="text-gray-400 flex-shrink-0" />
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
          <div>
            <h2 className="text-lg font-semibold text-white">System Configuration</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              Configure global system settings and platform behavior.
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

          {/* Search/Actions Bar */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search configuration..."
                className="w-full pl-9 pr-4 py-2 text-sm text-gray-300 bg-white/[0.04] border border-white/[0.08] rounded-lg placeholder-gray-500"
                readOnly
              />
            </div>
            <button className="flex items-center gap-2 px-4 py-2 text-sm text-gray-300 border border-white/[0.12] rounded-lg hover:bg-white/[0.04] transition-colors">
              <RotateCcw size={14} />
              Reset to Defaults
            </button>
            <button className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors">
              Save Changes
            </button>
          </div>

          {/* Section 1: Platform Settings */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Platform Settings</h3>
            <div className="divide-y divide-white/[0.08]">
              <ConfigItem
                title="System Name"
                description="Name of your NVLABS Mission Control instance."
              >
                <TextInput value="NVLABS Mission Control" icon={<Pencil size={14} />} />
              </ConfigItem>
              <ConfigItem
                title="Default Time Zone"
                description="Set the default time zone for the entire platform."
              >
                <SelectInput value="(UTC +05:30) Asia/Kolkata" />
              </ConfigItem>
              <ConfigItem
                title="Date & Time Format"
                description="Choose the default format for date and time."
              >
                <SelectInput value="May 19, 2024 02:45 PM (UTC+05:30)" />
              </ConfigItem>
              <ConfigItem
                title="Language"
                description="Set the default language for the platform."
              >
                <SelectInput value="English (US)" />
              </ConfigItem>
            </div>
          </Card>

          {/* Section 2: Session & Access */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Session &amp; Access</h3>
            <div className="divide-y divide-white/[0.08]">
              <ConfigItem
                title="Session Timeout"
                description="Automatically log out inactive users after."
              >
                <SelectInput value="30 minutes" />
              </ConfigItem>
              <ConfigItem
                title="Require Multi-Factor Authentication (MFA)"
                description="Require MFA for all users to access the platform."
              >
                <ToggleSwitch enabled={true} />
              </ConfigItem>
              <ConfigItem
                title="Allowed IP Ranges"
                description="Restrict access to the platform by IP range."
              >
                <ChevronInput value="192.168.0.0/16, 10.0.0.0/8" />
              </ConfigItem>
            </div>
          </Card>

          {/* Section 3: Data & Operations */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Data &amp; Operations</h3>
            <div className="divide-y divide-white/[0.08]">
              <ConfigItem
                title="Default Data Retention"
                description="Automatically delete data older than the selected period."
              >
                <SelectInput value="90 days" />
              </ConfigItem>
              <ConfigItem
                title="Enable Data Anonymization"
                description="Anonymize sensitive data in logs and analytics."
              >
                <ToggleSwitch enabled={true} />
              </ConfigItem>
              <ConfigItem
                title="Audit Log Retention"
                description="Retain audit logs for the selected period."
              >
                <SelectInput value="1 year" />
              </ConfigItem>
            </div>
          </Card>

          {/* Section 4: System Behavior */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">System Behavior</h3>
            <div className="divide-y divide-white/[0.08]">
              <ConfigItem
                title="Maintenance Mode"
                description="Put the platform in maintenance mode."
              >
                <ToggleSwitch enabled={false} />
              </ConfigItem>
              <ConfigItem
                title="Allow User Self-Registration"
                description="Allow new users to register without admin invite."
              >
                <ToggleSwitch enabled={false} />
              </ConfigItem>
              <ConfigItem
                title="Default Landing Page"
                description="Select the default page after user login."
              >
                <SelectInput value="Dashboard" />
              </ConfigItem>
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
          {/* About System Configuration */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">About System Configuration</h3>
            <p className="text-xs text-gray-400 mb-4">
              Configure global settings that control how NVLABS Mission Control operates. Changes may affect all users and system behavior.
            </p>
            <div className="space-y-4">
              <div className="flex items-start gap-3">
                <div className="p-1.5 rounded-md bg-purple-500/10">
                  <Target size={14} className="text-purple-400" />
                </div>
                <div>
                  <p className="text-xs font-medium text-white">Global Impact</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    These settings apply across the entire platform and all environments.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="p-1.5 rounded-md bg-blue-500/10">
                  <RefreshCw size={14} className="text-blue-400" />
                </div>
                <div>
                  <p className="text-xs font-medium text-white">Change Control</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Some settings may require admin approval and system restart.
                  </p>
                </div>
              </div>
              <div className="flex items-start gap-3">
                <div className="p-1.5 rounded-md bg-green-500/10">
                  <BookOpen size={14} className="text-green-400" />
                </div>
                <div>
                  <p className="text-xs font-medium text-white">Best Practices</p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Review best practices before making critical changes.
                  </p>
                </div>
              </div>
            </div>
          </Card>

          {/* Configuration Health */}
          <Card padding="lg">
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle size={16} className="text-green-400" />
              <h3 className="text-sm font-semibold text-white">All Systems Operational</h3>
            </div>
            <p className="text-xs text-gray-400 mb-4">Last checked: May 19, 2024 02:45 PM</p>
            <div className="space-y-0">
              {healthItems.map((item) => (
                <div
                  key={item.label}
                  className="flex items-center justify-between py-2.5 border-b border-white/[0.08] last:border-b-0"
                >
                  <span className="text-xs text-gray-300">{item.label}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-green-400">{item.status}</span>
                    <ChevronRight size={12} className="text-gray-400" />
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Need Help?</h3>
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
