/**
 * ThemeTab — Theme selector for Settings page.
 */

import { applyTheme, getActiveTheme, themes } from '@/styles/themes';
import { Check } from 'lucide-react';
import { useState } from 'react';

interface ThemeTabProps {
  onSaveToast: (msg: string) => void;
}

export function ThemeTab({ onSaveToast }: ThemeTabProps) {
  const [activeTheme, setActiveTheme] = useState(getActiveTheme());

  const handleSelect = (themeId: string) => {
    applyTheme(themeId);
    setActiveTheme(themeId);
    onSaveToast(`Theme changed to "${themes.find((t) => t.id === themeId)?.name}"`);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-medium text-[#F2F1EE] mb-1">Appearance</h3>
        <p className="text-xs text-[#6B6B6E] font-mono">Choose a theme for the dashboard. Changes apply immediately.</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {themes.map((theme) => (
          <button
            key={theme.id}
            onClick={() => handleSelect(theme.id)}
            className={`p-4 rounded-[8px] border text-left transition-all cursor-pointer ${activeTheme === theme.id
                ? 'border-[#FFB020] bg-[#FFB020]/5'
                : 'border-white/[0.08] bg-[#141416] hover:border-white/[0.15]'
              }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-[#F2F1EE]">{theme.name}</span>
              {activeTheme === theme.id && <Check size={14} className="text-[#FFB020]" />}
            </div>
            <p className="text-[10px] text-[#6B6B6E] font-mono mb-3">{theme.description}</p>
            {/* Color swatches */}
            <div className="flex gap-1">
              <div className="w-5 h-5 rounded-[3px] border border-white/[0.1]" style={{ backgroundColor: theme.colors['--bg-primary'] }} />
              <div className="w-5 h-5 rounded-[3px] border border-white/[0.1]" style={{ backgroundColor: theme.colors['--bg-secondary'] }} />
              <div className="w-5 h-5 rounded-[3px] border border-white/[0.1]" style={{ backgroundColor: theme.colors['--accent'] }} />
              <div className="w-5 h-5 rounded-[3px] border border-white/[0.1]" style={{ backgroundColor: theme.colors['--text-primary'] }} />
              <div className="w-5 h-5 rounded-[3px] border border-white/[0.1]" style={{ backgroundColor: theme.colors['--success'] }} />
              <div className="w-5 h-5 rounded-[3px] border border-white/[0.1]" style={{ backgroundColor: theme.colors['--error'] }} />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
