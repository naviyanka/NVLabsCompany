export interface AppearanceConfig {
  themeMode: 'dark-space' | 'cyberpunk' | 'solarized' | 'midnight';
  accent: string;
  density: 'Compact' | 'Comfortable' | 'Spacious';
  codeFont: string;
  showGlowEffects: boolean;
  reducedAnimations: boolean;
  customCss: string;
}

export const DEFAULT_APPEARANCE: AppearanceConfig = {
  themeMode: 'dark-space',
  accent: 'Cyan',
  density: 'Comfortable',
  codeFont: 'JetBrains Mono',
  showGlowEffects: true,
  reducedAnimations: false,
  customCss: '/* Custom CSS overrides */\n.dashboard-custom-accent {\n  box-shadow: 0 0 15px rgba(6, 182, 212, 0.2);\n}',
};

export const ACCENT_PALETTES: Record<string, { primary500: string; primary400: string; primary600: string; glow: string }> = {
  Cyan: { primary500: '#06b6d4', primary400: '#22d3ee', primary600: '#0891b2', glow: 'rgba(6, 182, 212, 0.3)' },
  Emerald: { primary500: '#10b981', primary400: '#34d399', primary600: '#059669', glow: 'rgba(16, 185, 129, 0.3)' },
  Purple: { primary500: '#8b5cf6', primary400: '#a78bfa', primary600: '#7c3aed', glow: 'rgba(139, 92, 246, 0.3)' },
  Amber: { primary500: '#f59e0b', primary400: '#fbbf24', primary600: '#d97706', glow: 'rgba(245, 158, 11, 0.3)' },
  Rose: { primary500: '#f43f5e', primary400: '#fb7185', primary600: '#e11d48', glow: 'rgba(244, 63, 94, 0.3)' },
};

export const THEME_MODE_COLORS: Record<string, { bgDark: string; cardDark: string; sidebarDark: string; textMain: string }> = {
  'dark-space': { bgDark: '#0f1117', cardDark: '#1e2035', sidebarDark: '#12131f', textMain: '#f8fafc' },
  cyberpunk: { bgDark: '#050508', cardDark: '#0d0d14', sidebarDark: '#08080c', textMain: '#ffffff' },
  solarized: { bgDark: '#0a192f', cardDark: '#112240', sidebarDark: '#071324', textMain: '#e6f1ff' },
  midnight: { bgDark: '#000000', cardDark: '#0a0a0a', sidebarDark: '#050505', textMain: '#fafafa' },
};

export function applyThemeConfig(config: AppearanceConfig) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;

  // 1. Apply Theme Mode Colors
  const modeColors = THEME_MODE_COLORS[config.themeMode] ?? THEME_MODE_COLORS['dark-space'] ?? {
    bgDark: '#0f1117',
    cardDark: '#1e2035',
    sidebarDark: '#12131f',
    textMain: '#f8fafc',
  };
  root.style.setProperty('--bg-dark', modeColors.bgDark);
  root.style.setProperty('--card-dark', modeColors.cardDark);
  root.style.setProperty('--sidebar-dark', modeColors.sidebarDark);
  document.body.style.backgroundColor = modeColors.bgDark;

  // 2. Apply Accent Palette Colors
  const accent = ACCENT_PALETTES[config.accent] ?? ACCENT_PALETTES.Cyan ?? {
    primary500: '#06b6d4',
    primary400: '#22d3ee',
    primary600: '#0891b2',
    glow: 'rgba(6, 182, 212, 0.3)',
  };
  root.style.setProperty('--primary-500', accent.primary500);
  root.style.setProperty('--primary-400', accent.primary400);
  root.style.setProperty('--primary-600', accent.primary600);
  root.style.setProperty('--glow-color', accent.glow);

  // 3. Apply Monospace Font
  root.style.setProperty('--font-code', config.codeFont);

  // 4. Apply Layout Density
  if (config.density === 'Compact') {
    root.style.setProperty('--spacing-density', '0.75');
    root.classList.add('density-compact');
    root.classList.remove('density-spacious');
  } else if (config.density === 'Spacious') {
    root.style.setProperty('--spacing-density', '1.25');
    root.classList.add('density-spacious');
    root.classList.remove('density-compact');
  } else {
    root.style.setProperty('--spacing-density', '1');
    root.classList.remove('density-compact', 'density-spacious');
  }

  // 5. Apply Reduced Motion
  if (config.reducedAnimations) {
    root.classList.add('reduce-motion');
  } else {
    root.classList.remove('reduce-motion');
  }

  // 6. Inject Custom CSS Overrides
  let styleEl = document.getElementById('nvlabs-custom-css');
  if (!styleEl) {
    styleEl = document.createElement('style');
    styleEl.id = 'nvlabs-custom-css';
    document.head.appendChild(styleEl);
  }
  styleEl.textContent = config.customCss || '';
}

export function loadAndApplyTheme(): AppearanceConfig {
  try {
    const saved = localStorage.getItem('nvlabs_appearance_config');
    const config: AppearanceConfig = saved ? JSON.parse(saved) : DEFAULT_APPEARANCE;
    applyThemeConfig(config);
    return config;
  } catch {
    applyThemeConfig(DEFAULT_APPEARANCE);
    return DEFAULT_APPEARANCE;
  }
}
