import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        genie: {
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          800: '#166534',
          900: '#14532d',
        },
      },
      animation: {
        'genie-glow': 'genie-glow 2s ease-in-out infinite',
        'genie-float': 'genie-float 3s ease-in-out infinite',
        'sparkle-1': 'sparkle 1.5s ease-in-out infinite',
        'sparkle-2': 'sparkle 1.8s ease-in-out infinite 0.3s',
        'sparkle-3': 'sparkle 2s ease-in-out infinite 0.6s',
        'sparkle-4': 'sparkle 1.6s ease-in-out infinite 0.9s',
        'fade-in': 'fadeIn 0.3s ease-out',
      },
      keyframes: {
        'genie-glow': {
          '0%, 100%': { boxShadow: '0 0 8px 2px rgba(34, 197, 94, 0.3)', borderRadius: '9999px' },
          '50%': { boxShadow: '0 0 20px 6px rgba(34, 197, 94, 0.5)', borderRadius: '9999px' },
        },
        'genie-float': {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-3px)' },
        },
        'sparkle': {
          '0%': { opacity: '0', transform: 'scale(0) translateY(0)' },
          '50%': { opacity: '1', transform: 'scale(1) translateY(-6px)' },
          '100%': { opacity: '0', transform: 'scale(0) translateY(-12px)' },
        },
        'fadeIn': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
} satisfies Config
