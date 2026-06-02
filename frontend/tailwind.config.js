/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#FFF1F0',
          100: '#FFE4E2',
          200: '#FFCDC9',
          300: '#FFA8A1',
          400: '#FF7068',
          500: '#EF4444',
          600: '#D4000F',
          700: '#B8000D',
          800: '#9A000B',
          900: '#7A0008',
          950: '#450004',
        },
        gold: {
          50: '#FEFCE8',
          100: '#FEF9C3',
          200: '#FEF08A',
          300: '#FDE047',
          400: '#FACC15',
          500: '#D4A017',
          600: '#CA8A04',
          700: '#A16207',
        },
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', '"PingFang SC"', '"Microsoft YaHei"', 'system-ui', 'sans-serif'],
        mono: ['"DIN Alternate"', '"JetBrains Mono"', 'monospace'],
      },
      borderRadius: {
        sm: '2px',
        DEFAULT: '4px',
        md: '4px',
        lg: '4px',
      },
    },
  },
  plugins: [],
};
