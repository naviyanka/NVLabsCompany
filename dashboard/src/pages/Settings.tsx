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
  Diamond,
  Download,
  Trash2,
  ChevronRight,
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
  { label: 'Billing & Subscription', icon: CreditCard, active: true },
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

const planFeatures = [
  'Unlimited agents & tasks',
  'Advanced AI models',
  'Private pipelines',
  'SLA & priority support',
  'Advanced security & SSO',
  'Custom integrations',
];

const usageLimits = [
  { label: 'Agents', used: '124', total: 'Unlimited', percentage: 100 },
  { label: 'Tasks', used: '12,548', total: 'Unlimited', percentage: 100 },
  { label: 'Pipelines', used: '85', total: 'Unlimited', percentage: 100 },
  { label: 'Storage', used: '1.2 TB', total: '5 TB', percentage: 24 },
  { label: 'API Calls', used: '2.4M', total: '10M', percentage: 24 },
];

const invoices = [
  { id: 'INV-2024-0489', date: 'May 1, 2024', amount: '$499.00', status: 'Paid' },
  { id: 'INV-2024-0410', date: 'Apr 1, 2024', amount: '$499.00', status: 'Paid' },
  { id: 'INV-2024-0331', date: 'Mar 1, 2024', amount: '$499.00', status: 'Paid' },
  { id: 'INV-2024-0229', date: 'Feb 1, 2024', amount: '$499.00', status: 'Paid' },
  { id: 'INV-2024-0129', date: 'Jan 1, 2024', amount: '$499.00', status: 'Paid' },
];

const helpLinks = [
  { title: 'Billing & Subscription FAQ' },
  { title: 'Contact Support' },
  { title: 'Request a Call' },
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
          <div>
            <h2 className="text-lg font-semibold text-white">Billing &amp; Subscription</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              Manage your subscription, payment methods, and billing history.
            </p>
          </div>

          {/* Current Plan Card */}
          <Card padding="lg">
            <div className="grid grid-cols-3 gap-6">
              {/* Left: Plan Info */}
              <div className="space-y-3">
                <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">Current Plan</p>
                <div className="flex items-center gap-2">
                  <Diamond size={18} className="text-red-400" />
                  <span className="text-lg font-bold text-white">Enterprise</span>
                </div>
                <div>
                  <span className="text-2xl font-bold text-white">$499</span>
                  <span className="text-sm text-gray-400"> / month</span>
                </div>
                <p className="text-xs text-gray-400">Billed monthly</p>
                <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/20 text-green-400">
                  Active
                </span>
              </div>

              {/* Center: Plan Features */}
              <div className="space-y-3">
                <p className="text-xs font-medium text-gray-400">Everything in Professional, plus:</p>
                <div className="space-y-2">
                  {planFeatures.map((feature) => (
                    <div key={feature} className="flex items-center gap-2">
                      <Check size={14} className="text-green-400 flex-shrink-0" />
                      <span className="text-sm text-gray-300">{feature}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Right: Billing Details */}
              <div className="space-y-3">
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Next billing date:</span>
                    <span className="text-xs text-gray-300">June 1, 2024</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Billing cycle:</span>
                    <span className="text-xs text-gray-300">Monthly</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-gray-400">Seats:</span>
                    <span className="text-xs text-gray-300">24 / 50</span>
                  </div>
                </div>
                <button className="w-full mt-3 px-4 py-2 border border-white/[0.12] rounded-lg text-sm text-gray-300 hover:bg-white/[0.04] transition-colors">
                  Manage Plan
                </button>
              </div>
            </div>
          </Card>

          {/* Usage & Plan Limits */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">Usage &amp; Plan Limits</h3>
              <a href="#" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                View all limits
              </a>
            </div>
            <div className="grid grid-cols-5 gap-3">
              {usageLimits.map((item) => (
                <Card key={item.label} padding="sm">
                  <div className="space-y-2">
                    <p className="text-xs text-gray-400">{item.label}</p>
                    <p className="text-sm font-semibold text-white">
                      {item.used} / {item.total}
                    </p>
                    <div className="w-full h-1.5 bg-dark-bg rounded-full overflow-hidden">
                      <div
                        className="h-full bg-primary-500 rounded-full"
                        style={{ width: `${item.percentage}%` }}
                      />
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          </div>

          {/* Payment Method */}
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-white">Payment Method</h3>
              <p className="text-xs text-gray-400 mt-0.5">Manage your saved payment methods.</p>
            </div>
            <Card padding="md">
              <div className="flex items-center gap-4">
                {/* VISA text logo */}
                <div className="w-12 h-8 bg-white rounded flex items-center justify-center">
                  <span className="text-[10px] font-bold text-blue-900 italic tracking-tight">VISA</span>
                </div>
                <div className="flex-1">
                  <p className="text-sm text-white font-medium">
                    Visa &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; 4242
                  </p>
                </div>
                <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-500/20 text-green-400">
                  Default
                </span>
                <span className="text-xs text-gray-400">Expires 08/27</span>
                <button className="px-3 py-1.5 text-xs text-gray-300 border border-white/[0.12] rounded-lg hover:bg-white/[0.04] transition-colors">
                  Edit
                </button>
                <button className="text-gray-400 hover:text-red-400 transition-colors">
                  <Trash2 size={16} />
                </button>
              </div>
            </Card>
            <button className="w-full px-4 py-2 border border-white/[0.12] border-dashed rounded-lg text-sm text-gray-400 hover:text-white hover:border-white/[0.2] transition-colors">
              + Add Payment Method
            </button>
          </div>

          {/* Billing Information */}
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold text-white">Billing Information</h3>
              <p className="text-xs text-gray-400 mt-0.5">Update your billing details and download invoices.</p>
            </div>
            <Card padding="md">
              <div className="grid grid-cols-3 gap-6">
                <div className="space-y-2">
                  <p className="text-xs text-gray-400">Billing Email</p>
                  <p className="text-sm text-white">billing@nvlabs.dev</p>
                  <a href="#" className="text-xs text-teal-400 hover:text-teal-300 transition-colors">Edit</a>
                </div>
                <div className="space-y-2">
                  <p className="text-xs text-gray-400">Billing Address</p>
                  <p className="text-sm text-white leading-relaxed">
                    NVLABS Technologies Pvt. Ltd.<br />
                    Gurgaon, Haryana 122001<br />
                    India
                  </p>
                  <a href="#" className="text-xs text-teal-400 hover:text-teal-300 transition-colors">Edit</a>
                </div>
                <div className="space-y-2">
                  <p className="text-xs text-gray-400">Tax ID / GSTIN</p>
                  <p className="text-sm text-white">06AAGCN1234H1Z5</p>
                  <a href="#" className="text-xs text-teal-400 hover:text-teal-300 transition-colors">Edit</a>
                </div>
              </div>
            </Card>
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
          {/* Invoices */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-white">Invoices</h3>
              <a href="#" className="text-xs text-primary-400 hover:text-primary-300 transition-colors">
                View all invoices
              </a>
            </div>
            <div className="space-y-3">
              {invoices.map((invoice) => (
                <div key={invoice.id} className="flex items-center gap-2 text-xs">
                  <div className="flex-1 min-w-0">
                    <p className="text-gray-300 font-medium truncate">{invoice.id}</p>
                    <p className="text-gray-500">{invoice.date}</p>
                  </div>
                  <span className="text-gray-300">{invoice.amount}</span>
                  <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-green-500/20 text-green-400">
                    {invoice.status}
                  </span>
                  <button className="text-gray-400 hover:text-white transition-colors">
                    <Download size={12} />
                  </button>
                </div>
              ))}
            </div>
          </Card>

          {/* Payment Method (Sidebar) */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Payment Method</h3>
            <p className="text-xs text-gray-400 mb-3">Default payment method for recurring billing.</p>
            <div className="flex items-center gap-3 mb-2">
              <div className="w-10 h-6 bg-white rounded flex items-center justify-center">
                <span className="text-[8px] font-bold text-blue-900 italic tracking-tight">VISA</span>
              </div>
              <div className="flex-1">
                <p className="text-xs text-white font-medium">
                  Visa &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; &bull;&bull;&bull;&bull; 4242
                </p>
              </div>
              <span className="px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-green-500/20 text-green-400">
                Default
              </span>
            </div>
            <p className="text-xs text-gray-400 mb-3">Expires 08/27</p>
            <a href="#" className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 transition-colors">
              Update Payment Method
              <ChevronRight size={12} />
            </a>
          </Card>

          {/* Usage This Month */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Usage This Month</h3>
            <p className="text-xs text-gray-400 mb-4">Your usage will reset on June 1, 2024.</p>
            <div className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">Compute Minutes</span>
                  <span className="text-xs text-gray-300">1,245 / 5,000 min</span>
                </div>
                <div className="w-full h-1.5 bg-dark-bg rounded-full overflow-hidden">
                  <div className="h-full bg-primary-500 rounded-full" style={{ width: '25%' }} />
                </div>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-400">AI Tokens</span>
                  <span className="text-xs text-gray-300">24.6M / 100M tokens</span>
                </div>
                <div className="w-full h-1.5 bg-dark-bg rounded-full overflow-hidden">
                  <div className="h-full bg-primary-500 rounded-full" style={{ width: '24.6%' }} />
                </div>
              </div>
            </div>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-2">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-3">Our support team is here to help you.</p>
            <div className="space-y-3">
              {helpLinks.map((link) => (
                <a
                  key={link.title}
                  href="#"
                  className="flex items-center gap-2 group"
                >
                  <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                  <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                    {link.title}
                  </span>
                </a>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
