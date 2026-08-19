/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        sidebar: '#12131f',
        'dark-bg': '#0f1117',
        'dark-surface': '#1a1b2e',
        'dark-card': '#1e2035',
        'dark-sidebar': '#12131f',
        primary: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
        success: {
          50: '#ecfdf5',
          500: '#10b981',
          600: '#059669',
        },
        warning: {
          50: '#fffbeb',
          500: '#f59e0b',
          600: '#d97706',
        },
        danger: {
          50: '#fff1f2',
          500: '#f43f5e',
          600: '#e11d48',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      animation: {
        'office-pulse': 'office-pulse 2s ease-in-out infinite',
        'office-shake': 'office-shake 0.5s ease-in-out infinite',
        'office-meeting-pulse': 'office-meeting-pulse 3s ease-in-out infinite',
        'office-dash': 'office-dash 1.5s linear infinite',
        'office-ticker': 'office-ticker 30s linear infinite',
      },
      keyframes: {
        'office-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(16, 185, 129, 0.4)' },
          '50%': { boxShadow: '0 0 0 6px rgba(16, 185, 129, 0)' },
        },
        'office-shake': {
          '0%, 100%': { transform: 'translateX(0)' },
          '25%': { transform: 'translateX(-1px)' },
          '75%': { transform: 'translateX(1px)' },
        },
        'office-meeting-pulse': {
          '0%, 100%': { borderColor: 'var(--meeting-border, #fb7185)', opacity: '1' },
          '50%': { borderColor: 'var(--meeting-border, #fb7185)', opacity: '0.7' },
        },
        'office-dash': {
          '0%': { strokeDashoffset: '20' },
          '100%': { strokeDashoffset: '0' },
        },
        'office-ticker': {
          '0%': { transform: 'translateX(0)' },
          '100%': { transform: 'translateX(-50%)' },
        },
      },
    },
  },
  plugins: [],
};
