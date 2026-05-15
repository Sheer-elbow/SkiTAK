/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // SkiTAK brand — dark outdoor palette
        surface: {
          DEFAULT: '#0f1117',
          raised: '#1a1d27',
          border: '#2a2d3a',
        },
        accent: {
          DEFAULT: '#3b82f6',   // blue — primary actions
          green: '#22c55e',     // online / tracking
          amber: '#f59e0b',     // warning / low battery
          red: '#ef4444',       // emergency / offline
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
