/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: '#0D1B1A', soft: '#16302D', line: '#2E4B47' },
        wash: '#F4F7F6',
        rule: { DEFAULT: '#D7E2DF', strong: '#B9C9C5' },
        pass: { DEFAULT: '#0E7C66', soft: '#D6EDE7' },
        cut: { DEFAULT: '#9B2C3F', soft: '#F3DCE0' },
        zone2: { DEFAULT: '#B08308', soft: '#F7EDD2' },
        muted: '#5E7370',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SF Mono', 'Cascadia Mono', 'Menlo', 'Consolas', 'monospace'],
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
