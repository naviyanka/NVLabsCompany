/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'bg-base': '#0A0A0B',
        'bg-surface': '#141416',
        'bg-surface-raised': '#1C1C1F',
        'border-default': 'rgba(255,255,255,0.08)',
        'border-strong': 'rgba(255,255,255,0.14)',
        'text-primary': '#F2F1EE',
        'text-secondary': '#A8A8AB',
        'text-muted': '#6B6B6E',
        'accent-primary': '#FFB020',
        'accent-hover': '#FFC04D',
        'status-success': '#22C55E',
        'status-warning': '#F97316',
        'status-danger': '#EF4444',
        'status-info': '#38BDF8',
        'status-idle': '#6B6B6E',
      },
      fontFamily: {
        display: ['Space Grotesk', 'sans-serif'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['IBM Plex Mono', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '6px',
        card: '10px',
      },
      animation: {
        'pulse-line': 'pulse-scroll 35s linear infinite',
        'pulse-fast': 'pulse 1.5s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        'pulse-scroll': {
          '0%': { transform: 'translateX(0%)' },
          '100%': { transform: 'translateX(-50%)' },
        },
      },
    },
  },
  plugins: [],
};

