import { useState } from 'react';
import { Settings as SettingsIcon, CheckCircle2, ExternalLink } from 'lucide-react';
import { SettingsNav } from '@/components/settings/SettingsNav';
import { OtherSettingsTabs } from '@/components/settings/OtherSettingsTabs';
import type { SettingsTabId } from '@/components/settings/types';

export function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTabId>('profile');
  const [showToast, setShowToast] = useState(false);
  const [toastMessage, setToastMessage] = useState('Settings updated successfully');

  const triggerToast = (msg = 'Settings updated successfully') => {
    setToastMessage(msg);
    setShowToast(true);
    setTimeout(() => {
      setShowToast(false);
    }, 3500);
  };

  return (
    <div className="w-full max-w-7xl mx-auto space-y-6 pb-12 font-sans">
      {/* Settings Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2">
        <div className="flex items-center gap-3.5">
          <div className="w-10 h-10 rounded-xl bg-[#141416] border border-[#FFB020]/20 flex items-center justify-center text-[#FFB020] shadow-sm">
            <SettingsIcon size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-[#F2F1EE] tracking-tight">System Settings & Governance</h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono uppercase bg-[#FFB020]/10 text-[#FFB020] border border-[#FFB020]/20">
                v2.4 Control
              </span>
            </div>
            <p className="text-xs text-[#A8A8AB] mt-0.5">
              Manage operator profile, system hyperparameters, autonomous permissions, and platform security.
            </p>
          </div>
        </div>

        {showToast && (
          <div className="flex items-center gap-2 px-3.5 py-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-xs font-mono font-medium text-emerald-400 animate-in fade-in slide-in-from-top-2 duration-200">
            <CheckCircle2 size={15} />
            <span>{toastMessage}</span>
          </div>
        )}
      </div>

      {/* Main Settings Body: Left Grouped Navigation + Right Modular View */}
      <div className="flex flex-col md:flex-row gap-6 items-start">
        {/* Left Grouped Category Menu */}
        <SettingsNav activeTab={activeTab} onSelectTab={setActiveTab} />

        {/* Right Active Modular Tab View */}
        <div className="flex-1 w-full min-w-0 bg-[#141416] border border-white/[0.08] rounded-xl p-5 sm:p-6 shadow-sm">
          <OtherSettingsTabs
            activeTab={activeTab}
            onSaveToast={triggerToast}
          />
        </div>
      </div>

      {/* Footer */}
      <footer className="pt-8 border-t border-white/[0.06] flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-[#6B6B6E]">
        <div>© 2024 NEXUS Mission Control. All rights reserved.</div>
        <div className="flex items-center gap-6 font-mono text-[11px]">
          <a
            href="#docs"
            onClick={(e) => e.preventDefault()}
            className="hover:text-[#F2F1EE] flex items-center gap-1 transition-colors"
          >
            <span>Documentation</span>
            <ExternalLink size={11} />
          </a>
          <a
            href="#support"
            onClick={(e) => e.preventDefault()}
            className="hover:text-[#F2F1EE] flex items-center gap-1 transition-colors"
          >
            <span>Support</span>
            <ExternalLink size={11} />
          </a>
          <a
            href="#privacy"
            onClick={(e) => e.preventDefault()}
            className="hover:text-[#F2F1EE] flex items-center gap-1 transition-colors"
          >
            <span>Privacy Policy</span>
            <ExternalLink size={11} />
          </a>
          <a
            href="#terms"
            onClick={(e) => e.preventDefault()}
            className="hover:text-[#F2F1EE] flex items-center gap-1 transition-colors"
          >
            <span>Terms of Service</span>
            <ExternalLink size={11} />
          </a>
        </div>
      </footer>
    </div>
  );
}
