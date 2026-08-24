/**
 * Theme System — CSS variable-based theming for the NEXUS dashboard.
 *
 * Each theme defines a set of CSS custom properties. The active theme
 * is applied by setting these variables on document.documentElement.
 *
 * Usage:
 *   import { themes, applyTheme } from '@/styles/themes';
 *   applyTheme('midnight');
 */

export interface Theme {
  id: string;
  name: string;
  description: string;
  colors: {
    '--bg-primary': string;
    '--bg-secondary': string;
    '--bg-tertiary': string;
    '--text-primary': string;
    '--text-secondary': string;
    '--text-muted': string;
    '--accent': string;
    '--accent-hover': string;
    '--border': string;
    '--success': string;
    '--warning': string;
    '--error': string;
  };
}

export const themes: Theme[] = [
  {
    id: 'midnight',
    name: 'Midnight',
    description: 'Default dark theme with amber accents',
    colors: {
      '--bg-primary': '#0A0A0B',
      '--bg-secondary': '#101012',
      '--bg-tertiary': '#141416',
      '--text-primary': '#F2F1EE',
      '--text-secondary': '#A8A8AB',
      '--text-muted': '#6B6B6E',
      '--accent': '#FFB020',
      '--accent-hover': '#FFC040',
      '--border': 'rgba(255,255,255,0.08)',
      '--success': '#22C55E',
      '--warning': '#F59E0B',
      '--error': '#EF4444',
    },
  },
  {
    id: 'obsidian',
    name: 'Obsidian',
    description: 'Deep blue-black with cyan accents',
    colors: {
      '--bg-primary': '#0B0E14',
      '--bg-secondary': '#0F131A',
      '--bg-tertiary': '#141820',
      '--text-primary': '#E6E8EB',
      '--text-secondary': '#8B9BB4',
      '--text-muted': '#565E70',
      '--accent': '#00BCD4',
      '--accent-hover': '#26C6DA',
      '--border': 'rgba(100,150,200,0.1)',
      '--success': '#4CAF50',
      '--warning': '#FF9800',
      '--error': '#F44336',
    },
  },
  {
    id: 'daylight',
    name: 'Daylight',
    description: 'Light theme for bright environments',
    colors: {
      '--bg-primary': '#FFFFFF',
      '--bg-secondary': '#F8F9FA',
      '--bg-tertiary': '#F1F3F5',
      '--text-primary': '#1A1A2E',
      '--text-secondary': '#4A4A5A',
      '--text-muted': '#8A8A9A',
      '--accent': '#2563EB',
      '--accent-hover': '#3B82F6',
      '--border': 'rgba(0,0,0,0.08)',
      '--success': '#16A34A',
      '--warning': '#CA8A04',
      '--error': '#DC2626',
    },
  },
  {
    id: 'emerald',
    name: 'Emerald Matrix',
    description: 'Green-on-black terminal aesthetic',
    colors: {
      '--bg-primary': '#0A0F0A',
      '--bg-secondary': '#0F150F',
      '--bg-tertiary': '#141A14',
      '--text-primary': '#00FF88',
      '--text-secondary': '#00CC66',
      '--text-muted': '#006633',
      '--accent': '#00FF88',
      '--accent-hover': '#33FFAA',
      '--border': 'rgba(0,255,136,0.1)',
      '--success': '#00FF88',
      '--warning': '#FFCC00',
      '--error': '#FF3333',
    },
  },
  {
    id: 'nord',
    name: 'Nord',
    description: 'Arctic-inspired cool palette',
    colors: {
      '--bg-primary': '#2E3440',
      '--bg-secondary': '#3B4252',
      '--bg-tertiary': '#434C5E',
      '--text-primary': '#ECEFF4',
      '--text-secondary': '#D8DEE9',
      '--text-muted': '#7B88A1',
      '--accent': '#88C0D0',
      '--accent-hover': '#8FBCBB',
      '--border': 'rgba(216,222,233,0.1)',
      '--success': '#A3BE8C',
      '--warning': '#EBCB8B',
      '--error': '#BF616A',
    },
  },
];

export function applyTheme(themeId: string): void {
  const theme = themes.find((t) => t.id === themeId);
  if (!theme) return;

  const root = document.documentElement;
  for (const [key, value] of Object.entries(theme.colors)) {
    root.style.setProperty(key, value);
  }
  localStorage.setItem('nexus_theme', themeId);
}

export function getActiveTheme(): string {
  return localStorage.getItem('nexus_theme') || 'midnight';
}
