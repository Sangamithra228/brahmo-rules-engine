/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: '#1A2321', soft: '#2A3634' },
        wash: '#F4F7F6',
        rule: { DEFAULT: '#D7E2DF', strong: '#B9C9C5' },
        pass: { DEFAULT: '#0E7C66', soft: '#E2F0EC' },
        cut: { DEFAULT: '#9B2C3F', soft: '#F3E3E6' },
        zone2: { DEFAULT: '#8A6608', soft: '#F5EEDC' },
        muted: '#67736F',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SF Mono', 'Cascadia Mono', 'Menlo', 'Consolas', 'monospace'],
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
