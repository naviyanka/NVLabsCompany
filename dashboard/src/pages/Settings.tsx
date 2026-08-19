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
  ChevronRight,
  MoreVertical,
  UserCheck,
  Filter,
} from 'lucide-react';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const navItems = [
  { label: 'General', icon: Cog, active: false },
  { label: 'Profile', icon: User, active: false },
  { label: 'Security', icon: Shield, active: false },
  { label: 'API Keys', icon: Key, active: false },
  { label: 'Integrations', icon: Puzzle, active: false },
  { label: 'Teams & Users', icon: Users, active: true },
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
  { label: 'Total Users', value: '24', subtitle: 'Across all teams', icon: Users, iconColor: 'text-blue-400', iconBg: 'bg-blue-500/10' },
  { label: 'Active Users', value: '20', subtitle: 'Active in last 30 days', icon: UserCheck, iconColor: 'text-green-400', iconBg: 'bg-green-500/10' },
  { label: 'Administrators', value: '6', subtitle: 'Full access users', icon: Shield, iconColor: 'text-purple-400', iconBg: 'bg-purple-500/10' },
  { label: 'Teams', value: '6', subtitle: 'Across organization', icon: Users, iconColor: 'text-teal-400', iconBg: 'bg-teal-500/10' },
];

const tabs = [
  { label: 'Users', active: true },
  { label: 'Teams', active: false },
];

const usersData = [
  {
    name: 'Navi Yanka',
    initials: 'NY',
    email: 'navi.yanka@nvlabs.dev',
    avatarBg: 'bg-gradient-to-br from-indigo-500 to-purple-500',
    isYou: true,
    team: 'Platform',
    role: 'Administrator',
    roleBg: 'bg-blue-500/20',
    roleColor: 'text-blue-400',
    status: 'Active',
    lastActive: 'Just now',
  },
  {
    name: 'Anaya Sharma',
    initials: 'AS',
    email: 'anaya.sharma@nvlabs.dev',
    avatarBg: 'bg-pink-500/20',
    isYou: false,
    team: 'Security',
    role: 'Manager',
    roleBg: 'bg-purple-500/20',
    roleColor: 'text-purple-400',
    status: 'Active',
    lastActive: '10m ago',
  },
  {
    name: 'Rohit Verma',
    initials: 'RV',
    email: 'rohit.verma@nvlabs.dev',
    avatarBg: 'bg-blue-500/20',
    isYou: false,
    team: 'Engineering',
    role: 'Developer',
    roleBg: 'bg-teal-500/20',
    roleColor: 'text-teal-400',
    status: 'Active',
    lastActive: '1h ago',
  },
  {
    name: 'Priya Singh',
    initials: 'PS',
    email: 'priya.singh@nvlabs.dev',
    avatarBg: 'bg-purple-600/30',
    isYou: false,
    team: 'Operations',
    role: 'Analyst',
    roleBg: 'bg-blue-500/20',
    roleColor: 'text-blue-400',
    status: 'Active',
    lastActive: '2h ago',
  },
  {
    name: 'Arjun Kapoor',
    initials: 'AK',
    email: 'arjun.kapoor@nvlabs.dev',
    avatarBg: 'bg-gray-700',
    isYou: false,
    team: 'Engineering',
    role: 'Developer',
    roleBg: 'bg-teal-500/20',
    roleColor: 'text-teal-400',
    status: 'Active',
    lastActive: '3h ago',
  },
  {
    name: 'Neha Tiwari',
    initials: 'NT',
    email: 'neha.tiwari@nvlabs.dev',
    avatarBg: 'bg-orange-500/20',
    isYou: false,
    team: 'HR',
    role: 'HR Manager',
    roleBg: 'bg-red-500/20',
    roleColor: 'text-red-400',
    status: 'Active',
    lastActive: '1d ago',
  },
  {
    name: 'Dev Mehta',
    initials: 'DM',
    email: 'dev.mehta@nvlabs.dev',
    avatarBg: 'bg-green-500/20',
    isYou: false,
    team: 'Security',
    role: 'Viewer',
    roleBg: 'bg-gray-500/20',
    roleColor: 'text-gray-400',
    status: 'Inactive',
    lastActive: '7d ago',
  },
  {
    name: 'Sahil Khan',
    initials: 'SK',
    email: 'sahil.khan@nvlabs.dev',
    avatarBg: 'bg-teal-500/20',
    isYou: false,
    team: 'Operations',
    role: 'Analyst',
    roleBg: 'bg-blue-500/20',
    roleColor: 'text-blue-400',
    status: 'Active',
    lastActive: '5h ago',
  },
];

const teamManagementActions = [
  { title: 'Create Team', description: 'Create a new team and add members' },
  { title: 'Manage Teams', description: 'View and manage all teams' },
  { title: 'Team Settings', description: 'Configure default team settings' },
];

const userManagementActions = [
  { title: 'Invite User', description: 'Send an invitation to join the platform' },
  { title: 'Bulk Invite', description: 'Invite multiple users at once' },
  { title: 'User Directory', description: 'View all users in the organization' },
];

const activeTeams = [
  { name: 'Platform', users: 6 },
  { name: 'Engineering', users: 7 },
  { name: 'Security', users: 5 },
  { name: 'Operations', users: 4 },
  { name: 'HR', users: 2 },
  { name: 'Support', users: 2 },
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
              <h2 className="text-lg font-semibold text-white">Teams &amp; Users</h2>
              <p className="text-sm text-gray-400 mt-0.5">
                Manage your teams, users, and their access to NVLABS Mission Control.
              </p>
            </div>
            <button className="flex items-center gap-2 px-4 py-2 bg-green-500 text-white text-sm font-medium rounded-lg hover:bg-green-600 transition-colors">
              <Plus size={16} />
              Invite User
            </button>
          </div>

          {/* Search/Filter Bar */}
          <div className="flex items-center gap-3">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Search users by name, email, or role..."
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg pl-9 pr-3 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-primary-500"
              />
            </div>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              All Teams
              <ChevronDown size={14} className="text-gray-400" />
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
              <Filter size={14} className="text-gray-400" />
              Filters
            </button>
          </div>

          {/* Team Overview Stat Cards */}
          <div className="grid grid-cols-4 gap-4">
            {statCards.map((stat) => {
              const Icon = stat.icon;
              return (
                <Card key={stat.label} padding="md">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-xs text-gray-400">{stat.label}</p>
                      <p className="text-2xl font-bold text-white mt-1">{stat.value}</p>
                      <p className="text-xs text-gray-500 mt-1">{stat.subtitle}</p>
                    </div>
                    <div className={`p-2 rounded-lg ${stat.iconBg}`}>
                      <Icon size={16} className={stat.iconColor} />
                    </div>
                  </div>
                </Card>
              );
            })}
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
                  {tab.active && (
                    <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-primary-500 rounded-full" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Users Table */}
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-white/[0.08]">
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">User</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Team</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Role</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Status</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Last Active</th>
                    <th className="text-left text-xs font-medium text-gray-400 uppercase tracking-wider px-4 py-3">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {usersData.map((user) => (
                    <tr key={user.email} className="border-b border-white/[0.06] last:border-b-0 hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-medium text-white ${user.avatarBg}`}>
                            {user.initials}
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-medium text-white">{user.name}</p>
                              {user.isYou && (
                                <span className="px-1.5 py-0.5 text-xs font-medium rounded bg-green-500/20 text-green-400">You</span>
                              )}
                            </div>
                            <p className="text-xs text-gray-400">{user.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-sm text-gray-300">{user.team}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${user.roleBg} ${user.roleColor}`}>
                          {user.role}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="flex items-center gap-1.5 text-sm">
                          <span className={`w-2 h-2 rounded-full ${user.status === 'Active' ? 'bg-green-400' : 'bg-red-400'}`} />
                          <span className={user.status === 'Active' ? 'text-green-400' : 'text-red-400'}>
                            {user.status}
                          </span>
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-sm text-gray-400">{user.lastActive}</span>
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

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-400">Showing 1 to 8 of 24 users</p>
            <div className="flex items-center gap-2">
              <button className="px-3 py-1.5 text-sm text-gray-400 bg-dark-bg border border-white/[0.08] rounded-lg hover:bg-white/[0.04] transition-colors">
                &lt;
              </button>
              <button className="px-3 py-1.5 text-sm text-white bg-primary-500/20 border border-primary-500/30 rounded-lg font-medium">
                1
              </button>
              <button className="px-3 py-1.5 text-sm text-gray-400 bg-dark-bg border border-white/[0.08] rounded-lg hover:bg-white/[0.04] transition-colors">
                2
              </button>
              <button className="px-3 py-1.5 text-sm text-gray-400 bg-dark-bg border border-white/[0.08] rounded-lg hover:bg-white/[0.04] transition-colors">
                3
              </button>
              <button className="px-3 py-1.5 text-sm text-gray-400 bg-dark-bg border border-white/[0.08] rounded-lg hover:bg-white/[0.04] transition-colors">
                &gt;
              </button>
              <button className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-400 bg-dark-bg border border-white/[0.08] rounded-lg hover:bg-white/[0.04] transition-colors ml-2">
                10 / page
                <ChevronDown size={14} />
              </button>
            </div>
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
          {/* Team Management */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">Team Management</h3>
            <div className="space-y-3">
              {teamManagementActions.map((action) => (
                <button
                  key={action.title}
                  className="w-full flex items-center justify-between group"
                >
                  <div className="text-left">
                    <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                      {action.title}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {action.description}
                    </p>
                  </div>
                  <ChevronRight size={14} className="text-gray-400 flex-shrink-0" />
                </button>
              ))}
            </div>
          </Card>

          {/* User Management */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-3">User Management</h3>
            <div className="space-y-3">
              {userManagementActions.map((action) => (
                <button
                  key={action.title}
                  className="w-full flex items-center justify-between group"
                >
                  <div className="text-left">
                    <p className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                      {action.title}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {action.description}
                    </p>
                  </div>
                  <ChevronRight size={14} className="text-gray-400 flex-shrink-0" />
                </button>
              ))}
            </div>
          </Card>

          {/* Active Teams */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">Active Teams</h3>
              <button className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                View All
              </button>
            </div>
            <div className="space-y-3">
              {activeTeams.map((team) => (
                <div key={team.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-green-400" />
                    <span className="text-sm text-gray-300">{team.name}</span>
                  </div>
                  <span className="text-xs text-gray-500">{team.users} users</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
