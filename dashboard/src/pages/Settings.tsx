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
  Filter,
  Code,
  BarChart3,
  Eye,
  Lock,
  Layers,
  ShieldCheck,
  Check,
  Minus,
  Pencil,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: false },
  { label: 'Security', icon: Shield, active: false },
  { label: 'API Keys', icon: Key, active: false },
  { label: 'Integrations', icon: Puzzle, active: false },
  { label: 'Teams & Users', icon: Users, active: false },
  { label: 'Roles & Permissions', icon: UserCog, active: true },
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

const roleTabs = [
  { label: 'Roles', active: true },
  { label: 'Permissions', active: false },
];

const rolesData = [
  {
    name: 'Administrator',
    icon: Shield,
    iconColor: 'text-blue-400',
    iconBg: 'bg-blue-500/20',
    description: 'Full access to all features, settings, and user management.',
    users: 6,
    status: 'Active' as const,
  },
  {
    name: 'Security Manager',
    icon: Shield,
    iconColor: 'text-purple-400',
    iconBg: 'bg-purple-500/20',
    description: 'Manage security settings, agents, tasks, and reports.',
    users: 4,
    status: 'Active' as const,
  },
  {
    name: 'Developer',
    icon: Code,
    iconColor: 'text-teal-400',
    iconBg: 'bg-teal-500/20',
    description: 'Access to development tools, pipelines, and repositories.',
    users: 7,
    status: 'Active' as const,
  },
  {
    name: 'Analyst',
    icon: BarChart3,
    iconColor: 'text-blue-400',
    iconBg: 'bg-blue-500/20',
    description: 'View and analyze data, reports, and dashboards.',
    users: 5,
    status: 'Active' as const,
  },
  {
    name: 'Operator',
    icon: Cog,
    iconColor: 'text-orange-400',
    iconBg: 'bg-orange-500/20',
    description: 'Run tasks, view dashboards, and manage assigned pipelines.',
    users: 12,
    status: 'Active' as const,
  },
  {
    name: 'Viewer',
    icon: Eye,
    iconColor: 'text-gray-400',
    iconBg: 'bg-gray-500/20',
    description: 'Read-only access to dashboards and reports.',
    users: 8,
    status: 'Inactive' as const,
  },
];

const permissionMatrix = [
  { permission: 'Dashboard: View', values: [true, true, true, true, true, true] },
  { permission: 'Agents: Manage', values: [true, true, false, false, false, false] },
  { permission: 'Tasks: Create / Run', values: [true, true, true, true, false, false] },
  { permission: 'Pipelines: Manage', values: [true, true, true, false, false, false] },
  { permission: 'Users: Manage', values: [true, false, false, false, false, false] },
  { permission: 'Settings: Manage', values: [true, true, false, false, false, false] },
  { permission: 'Reports: Export', values: [true, true, true, true, false, false] },
];

const roleColumns = [
  { name: 'Administrator', color: 'bg-blue-400' },
  { name: 'Security Manager', color: 'bg-purple-400' },
  { name: 'Developer', color: 'bg-teal-400' },
  { name: 'Analyst', color: 'bg-blue-400' },
  { name: 'Operator', color: 'bg-orange-400' },
  { name: 'Viewer', color: 'bg-gray-400' },
];

const sidebarFeatures = [
  {
    icon: Lock,
    title: 'Granular Control',
    description: 'Set fine-grained permissions for each resource and action.',
  },
  {
    icon: Layers,
    title: 'Inherited Permissions',
    description: 'Permissions cascade from role to user to simplify management.',
  },
  {
    icon: ShieldCheck,
    title: 'Secure by Default',
    description: 'New users inherit the safest permissions by default.',
  },
];

const helpLinks = [
  {
    title: 'Roles & Permissions Guide',
    description: 'Learn how to create roles and assign permissions.',
  },
  {
    title: 'Permission Reference',
    description: 'View all available permissions and actions.',
  },
  {
    title: 'Best Practices',
    description: 'Follow security best practices for role management.',
  },
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
              <h2 className="text-lg font-semibold text-white">Roles &amp; Permissions</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Define roles and control access permissions across NVLABS Mission Control.
              </p>
            </div>
            <button className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white text-sm font-medium rounded-lg hover:bg-green-600 transition-colors">
              <Plus size={16} />
              Create Role
            </button>
          </div>

          {/* Tab Navigation */}
          <div className="border-b border-white/[0.08]">
            <div className="flex items-center gap-6">
              {roleTabs.map((tab) => (
                <button
                  key={tab.label}
                  className={`pb-3 text-sm font-medium transition-colors relative ${
                    tab.active
                      ? 'text-primary-400'
                      : 'text-gray-400 hover:text-white'
                  }`}
                >
                  {tab.label}
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
                placeholder="Search roles by name or description..."
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg pl-9 pr-3 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-primary-500"
              />
            </div>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              All Status
              <ChevronDown size={14} className="text-gray-400" />
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              <Filter size={14} className="text-gray-400" />
              Filters
            </button>
          </div>

          {/* Roles Table */}
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-white/[0.08]">
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Role</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Description</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Users</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Status</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rolesData.map((role) => {
                    const RoleIcon = role.icon;
                    return (
                      <tr key={role.name} className="border-b border-white/[0.06] last:border-b-0 hover:bg-white/[0.02] transition-colors">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3">
                            <div className={`w-8 h-8 rounded-full flex items-center justify-center ${role.iconBg}`}>
                              <RoleIcon size={14} className={role.iconColor} />
                            </div>
                            <span className="text-sm font-medium text-white">{role.name}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-400">{role.description}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-300">{role.users}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="flex items-center gap-1.5 text-sm">
                            <span className={`w-2 h-2 rounded-full ${role.status === 'Active' ? 'bg-green-400' : 'bg-gray-400'}`} />
                            <span className={role.status === 'Active' ? 'text-green-400' : 'text-gray-400'}>
                              {role.status}
                            </span>
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <button className="text-gray-400 hover:text-white transition-colors">
                            <MoreVertical size={16} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Showing info */}
          <p className="text-sm text-gray-400">Showing 1 to 6 of 6 roles</p>

          {/* Permission Matrix */}
          <div className="space-y-4">
            <div>
              <h3 className="text-lg font-semibold text-white">Permission Matrix</h3>
              <p className="text-sm text-gray-400 mt-0.5">
                Overview of permissions by role. Click on a permission to view details.
              </p>
            </div>

            <Card padding="none">
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-white/[0.08]">
                      <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Permission</th>
                      {roleColumns.map((col) => (
                        <th key={col.name} className="text-center text-xs font-medium text-gray-400 uppercase tracking-wider px-3 py-3">
                          <div className="flex items-center justify-center gap-1.5">
                            <span className={`w-2 h-2 rounded-full ${col.color}`} />
                            <span>{col.name}</span>
                          </div>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {permissionMatrix.map((row) => (
                      <tr key={row.permission} className="border-b border-white/[0.06] last:border-b-0 hover:bg-white/[0.02] transition-colors">
                        <td className="px-4 py-3">
                          <span className="text-sm text-gray-300">{row.permission}</span>
                        </td>
                        {row.values.map((allowed, idx) => (
                          <td key={idx} className="px-3 py-3 text-center">
                            {allowed ? (
                              <Check size={16} className="text-green-400 inline-block" />
                            ) : (
                              <Minus size={16} className="text-gray-500 inline-block" />
                            )}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            <button className="px-4 py-2 bg-teal-500/20 text-teal-400 text-sm font-medium rounded-lg hover:bg-teal-500/30 transition-colors">
              View All Permissions
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
          {/* About Roles & Permissions */}
          <Card padding="lg">
            <div className="flex items-center gap-2 mb-3">
              <UserCog size={16} className="text-primary-400" />
              <h3 className="text-sm font-semibold text-white">About Roles &amp; Permissions</h3>
            </div>
            <p className="text-xs text-gray-400 mb-4">
              Roles help you group users with similar responsibilities. Permissions define exactly what each role can access or modify.
            </p>
            <div className="space-y-3">
              {sidebarFeatures.map((feature) => {
                const FeatureIcon = feature.icon;
                return (
                  <div key={feature.title} className="flex items-start gap-2.5">
                    <div className="p-1.5 rounded-md bg-white/[0.05] mt-0.5">
                      <FeatureIcon size={12} className="text-gray-400" />
                    </div>
                    <div>
                      <p className="text-xs font-medium text-gray-300">{feature.title}</p>
                      <p className="text-xs text-gray-500 mt-0.5">{feature.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Selected Role Details */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">Selected Role Details</h3>
            </div>
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-white">Administrator</span>
                <span className="px-1.5 py-0.5 text-xs font-medium rounded bg-green-500/20 text-green-400">Active</span>
              </div>
              <p className="text-xs text-gray-400">
                Full access to all features, settings, and user management.
              </p>
              <div className="flex items-center gap-1">
                <span className="text-xs text-gray-400">6 Users assigned</span>
                <div className="flex items-center ml-2">
                  <div className="w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-500 border-2 border-dark-card text-[8px] text-white flex items-center justify-center font-medium">NY</div>
                  <div className="w-6 h-6 rounded-full bg-pink-500/30 border-2 border-dark-card -ml-1.5 text-[8px] text-white flex items-center justify-center font-medium">AS</div>
                  <div className="w-6 h-6 rounded-full bg-blue-500/30 border-2 border-dark-card -ml-1.5 text-[8px] text-white flex items-center justify-center font-medium">RV</div>
                  <div className="w-6 h-6 rounded-full bg-purple-600/30 border-2 border-dark-card -ml-1.5 text-[8px] text-white flex items-center justify-center font-medium">PS</div>
                  <div className="w-6 h-6 rounded-full bg-gray-600 border-2 border-dark-card -ml-1.5 text-[8px] text-white flex items-center justify-center font-medium">+2</div>
                </div>
              </div>
              <div className="border-t border-white/[0.08] pt-3">
                <p className="text-xs font-medium text-gray-300 mb-2">Permissions Summary</p>
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Total Permissions</span>
                    <span className="text-xs text-white font-medium">42</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Allowed</span>
                    <span className="text-xs text-green-400 font-medium">42</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Restricted</span>
                    <span className="text-xs text-red-400 font-medium">0</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Inherited</span>
                    <span className="text-xs text-gray-500 font-medium">&mdash;</span>
                  </div>
                </div>
              </div>
              <button className="w-full flex items-center justify-center gap-2 px-3 py-2 border border-white/[0.12] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
                <Pencil size={14} />
                Edit Role
              </button>
            </div>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">Need Help?</h3>
            <div className="space-y-3">
              {helpLinks.map((link) => (
                <a
                  key={link.title}
                  href="#"
                  className="flex items-start gap-2.5 group"
                >
                  <ExternalLink size={12} className="text-gray-400 mt-0.5 flex-shrink-0" />
                  <div>
                    <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                      {link.title}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {link.description}
                    </p>
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
