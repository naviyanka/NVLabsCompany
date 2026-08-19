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
  Monitor,
  Sun,
  Moon,
  PanelLeft,
  PanelLeftClose,
  Square,
  Check,
  Lightbulb,
  Sparkles,
  Eye,
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
  { label: 'Appearance', icon: Palette, active: true },
  { label: 'Advanced', icon: Wrench, active: false },
];

const footerLinks = [
  { label: 'Documentation' },
  { label: 'Support' },
  { label: 'Privacy Policy' },
  { label: 'Terms of Service' },
];

const tabs = [
  { label: 'Theme', active: true },
  { label: 'Layout', active: false },
  { label: 'Colors', active: false },
  { label: 'Typography', active: false },
  { label: 'Icons', active: false },
  { label: 'Custom CSS', active: false },
];

const themeOptions = [
  { label: 'System', description: 'Use system preference', icon: Monitor, selected: false },
  { label: 'Light', description: 'Clean and bright', icon: Sun, selected: false },
  { label: 'Dark', description: 'Easy on the eyes', icon: Moon, selected: true },
];

const accentColors = [
  { color: 'bg-red-500', selected: true },
  { color: 'bg-blue-600', selected: false },
  { color: 'bg-blue-400', selected: false },
  { color: 'bg-cyan-500', selected: false },
  { color: 'bg-teal-500', selected: false },
  { color: 'bg-green-600', selected: false },
  { color: 'bg-green-400', selected: false },
  { color: 'bg-emerald-500', selected: false },
  { color: 'bg-lime-500', selected: false },
  { color: 'bg-yellow-500', selected: false },
  { color: 'bg-orange-500', selected: false },
  { color: 'bg-orange-700', selected: false },
  { color: 'bg-pink-500', selected: false },
];

const sidebarStyles = [
  { label: 'Full', description: 'Full width sidebar', selected: true },
  { label: 'Compact', description: 'Narrower sidebar', selected: false },
  { label: 'Icon Only', description: 'Minimal icons only', selected: false },
];

const darkModeToggles = [
  { label: 'Sidebar', description: 'Use a slightly darker tone for the sidebar.', enabled: true },
  { label: 'Card Style', description: 'Use elevated cards with soft borders.', enabled: true },
  { label: 'Reduce Contrast', description: 'Reduces contrast for a softer look.', enabled: false },
];

const backgroundStyles = [
  { label: 'Solid', selected: true },
  { label: 'Subtle Grid', selected: false },
  { label: 'Minimal Dots', selected: false },
  { label: 'Topography', selected: false },
  { label: 'Gradient', selected: false },
];

const otherPreferences = [
  { label: 'Animations', description: 'Enable smooth UI transitions.', enabled: true },
  { label: 'Blur Effects', description: 'Enable blur for overlays and modals.', enabled: true },
  { label: 'Show Splash Screen', description: 'Show splash screen on app launch.', enabled: true },
  { label: 'Compact Mode', description: 'Reduce spacing for a denser UI.', enabled: false },
];

const themeTips = [
  {
    icon: Lightbulb,
    iconBg: 'bg-purple-500/10',
    iconColor: 'text-purple-400',
    title: 'Consistent Experience',
    description: 'Choose a theme that reduces eye strain and improves productivity.',
  },
  {
    icon: Sparkles,
    iconBg: 'bg-blue-500/10',
    iconColor: 'text-blue-400',
    title: 'Brand Alignment',
    description: "Use accent colors that match your organization's brand identity.",
  },
  {
    icon: Eye,
    iconBg: 'bg-green-500/10',
    iconColor: 'text-green-400',
    title: 'Accessibility',
    description: 'Ensure sufficient contrast for better readability and accessibility.',
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
            <h2 className="text-lg font-semibold text-white">Appearance</h2>
            <p className="text-sm text-gray-400 mt-0.5">
              Customize the look and feel of NVLABS Mission Control.
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

          {/* Section 1: Theme Mode */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">1. Theme Mode</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Choose your preferred theme for the application.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-4">
              {themeOptions.map((option) => {
                const Icon = option.icon;
                return (
                  <div
                    key={option.label}
                    className={`relative rounded-lg border p-4 cursor-pointer transition-colors ${
                      option.selected
                        ? 'border-primary-500 bg-primary-500/5'
                        : 'border-white/[0.08] bg-dark-bg hover:border-white/[0.16]'
                    }`}
                  >
                    <div className="flex flex-col items-center text-center gap-3">
                      <div className={`p-3 rounded-lg ${option.selected ? 'bg-primary-500/10' : 'bg-white/[0.04]'}`}>
                        <Icon size={24} className={option.selected ? 'text-primary-400' : 'text-gray-400'} />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-white">{option.label}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{option.description}</p>
                      </div>
                    </div>
                    {/* Radio indicator */}
                    <div className="absolute top-3 right-3">
                      <div
                        className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${
                          option.selected
                            ? 'border-primary-500 bg-primary-500'
                            : 'border-gray-500'
                        }`}
                      >
                        {option.selected && (
                          <div className="w-1.5 h-1.5 rounded-full bg-white" />
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>

          {/* Section 2: Accent Color */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">2. Accent Color</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Choose the primary accent color used across the platform.
              </p>
            </div>

            <div className="flex items-center gap-3 flex-wrap">
              {accentColors.map((item, idx) => (
                <button
                  key={idx}
                  className={`relative w-8 h-8 rounded-full ${item.color} transition-transform hover:scale-110 ${
                    item.selected ? 'ring-2 ring-white ring-offset-2 ring-offset-dark-surface' : ''
                  }`}
                >
                  {item.selected && (
                    <Check size={14} className="absolute inset-0 m-auto text-white" />
                  )}
                </button>
              ))}
            </div>
          </Card>

          {/* Section 3: Sidebar Style */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">3. Sidebar Style</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Choose how the sidebar should behave.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-4">
              {sidebarStyles.map((style, idx) => (
                <div
                  key={style.label}
                  className={`relative rounded-lg border p-4 cursor-pointer transition-colors ${
                    style.selected
                      ? 'border-primary-500 bg-primary-500/5'
                      : 'border-white/[0.08] bg-dark-bg hover:border-white/[0.16]'
                  }`}
                >
                  <div className="flex flex-col items-center text-center gap-3">
                    <div className={`p-3 rounded-lg ${style.selected ? 'bg-primary-500/10' : 'bg-white/[0.04]'}`}>
                      {idx === 0 && <PanelLeft size={24} className={style.selected ? 'text-primary-400' : 'text-gray-400'} />}
                      {idx === 1 && <PanelLeftClose size={24} className={style.selected ? 'text-primary-400' : 'text-gray-400'} />}
                      {idx === 2 && <Square size={24} className={style.selected ? 'text-primary-400' : 'text-gray-400'} />}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-white">{style.label}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{style.description}</p>
                    </div>
                  </div>
                  {/* Toggle indicator */}
                  <div className="absolute top-3 right-3">
                    <div
                      className={`w-9 h-5 rounded-full transition-colors ${
                        style.selected ? 'bg-primary-500' : 'bg-gray-600'
                      }`}
                    >
                      <div
                        className={`w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-transform mt-[3px] ${
                          style.selected ? 'translate-x-[18px]' : 'translate-x-[3px]'
                        }`}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Section 4: Dark Mode Settings */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">4. Dark Mode Settings</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Fine tune your dark mode experience.
              </p>
            </div>

            <div className="grid grid-cols-2 gap-6">
              {/* Left column: Toggles */}
              <div className="space-y-4">
                {darkModeToggles.map((toggle) => (
                  <div key={toggle.label} className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-white">{toggle.label}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{toggle.description}</p>
                    </div>
                    <div
                      className={`w-9 h-5 rounded-full flex-shrink-0 transition-colors ${
                        toggle.enabled ? 'bg-primary-500' : 'bg-gray-600'
                      }`}
                    >
                      <div
                        className={`w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-transform mt-[3px] ${
                          toggle.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'
                        }`}
                      />
                    </div>
                  </div>
                ))}
              </div>

              {/* Right column: Background Style */}
              <div>
                <p className="text-sm font-medium text-white mb-1">Background Style</p>
                <p className="text-xs text-gray-400 mb-3">Choose the background pattern.</p>
                <div className="space-y-2">
                  {backgroundStyles.map((bg) => (
                    <div
                      key={bg.label}
                      className={`flex items-center justify-between px-3 py-2 rounded-lg border cursor-pointer transition-colors ${
                        bg.selected
                          ? 'border-primary-500 bg-primary-500/5'
                          : 'border-white/[0.08] hover:border-white/[0.16]'
                      }`}
                    >
                      <span className={`text-xs font-medium ${bg.selected ? 'text-primary-400' : 'text-gray-300'}`}>
                        {bg.label}
                      </span>
                      {bg.selected && <Check size={14} className="text-primary-400" />}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </Card>

          {/* Section 5: Other Preferences */}
          <Card padding="lg">
            <div className="mb-4">
              <h3 className="text-sm font-semibold text-white">5. Other Preferences</h3>
              <p className="text-xs text-gray-400 mt-0.5">
                Additional UI preferences and settings.
              </p>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {otherPreferences.map((pref) => (
                <div
                  key={pref.label}
                  className="rounded-lg border border-white/[0.08] bg-dark-bg p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-sm font-medium text-white">{pref.label}</p>
                    <div
                      className={`w-9 h-5 rounded-full flex-shrink-0 transition-colors ${
                        pref.enabled ? 'bg-primary-500' : 'bg-gray-600'
                      }`}
                    >
                      <div
                        className={`w-3.5 h-3.5 rounded-full bg-white shadow-sm transition-transform mt-[3px] ${
                          pref.enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'
                        }`}
                      />
                    </div>
                  </div>
                  <p className="text-xs text-gray-400">{pref.description}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Right Sidebar */}
        <div className="w-[25%] flex-shrink-0 space-y-6">
          {/* Live Preview */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Live Preview</h3>
            <p className="text-xs text-gray-400 mb-4">
              See how your changes look in real-time.
            </p>

            {/* Mini Preview Mockup */}
            <div className="rounded-lg border border-white/[0.08] bg-dark-bg p-3 overflow-hidden">
              {/* Mock header */}
              <div className="flex items-center gap-2 mb-3">
                <div className="w-3 h-3 rounded-sm bg-primary-500/60" />
                <div className="h-2 w-24 rounded bg-white/20" />
              </div>
              <p className="text-[9px] text-gray-500 mb-2">NVLABS Mission Control</p>
              {/* Mock content blocks */}
              <div className="flex gap-1.5 mb-2">
                <div className="flex-1 h-6 rounded bg-purple-500/30" />
                <div className="flex-1 h-6 rounded bg-blue-500/30" />
              </div>
              <div className="flex gap-1.5 mb-2">
                <div className="flex-1 h-6 rounded bg-teal-500/30" />
                <div className="flex-1 h-6 rounded bg-green-500/30" />
              </div>
              <div className="flex gap-1.5">
                <div className="flex-1 h-4 rounded bg-orange-500/30" />
                <div className="flex-1 h-4 rounded bg-pink-500/30" />
              </div>
            </div>
          </Card>

          {/* Theme Tips */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Theme Tips</h3>
            <p className="text-xs text-gray-400 mb-4">
              Best practices for customization.
            </p>

            <div className="space-y-4">
              {themeTips.map((tip) => {
                const Icon = tip.icon;
                return (
                  <div key={tip.title} className="flex items-start gap-3">
                    <div className={`p-1.5 rounded-lg ${tip.iconBg} flex-shrink-0`}>
                      <Icon size={14} className={tip.iconColor} />
                    </div>
                    <div>
                      <p className="text-xs font-medium text-white">{tip.title}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{tip.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <a
              href="#"
              className="inline-flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300 mt-4 transition-colors"
            >
              Learn more about appearance settings &rarr;
            </a>
          </Card>

          {/* Need Help? */}
          <Card padding="lg">
            <h3 className="text-sm font-semibold text-white mb-1">Need Help?</h3>
            <p className="text-xs text-gray-400 mb-4">
              Learn more about customizing the appearance.
            </p>
            <div className="space-y-3">
              <a href="#" className="flex items-center gap-2 group">
                <ExternalLink size={12} className="text-gray-400 flex-shrink-0" />
                <span className="text-xs font-medium text-gray-300 group-hover:text-white transition-colors">
                  Appearance Guide
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
