import typography from '@tailwindcss/typography';

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{astro,html,js,jsx,ts,tsx,md,mdx}'],
  theme: {
    extend: {
      colors: {
        // Meta Blue 系統（#1877F2 を 500 に置く Salesforce / Meta Business Suite 寄り）
        brand: {
          50: '#e7f3ff',
          100: '#d0e8ff',
          200: '#a8d2ff',
          300: '#6bb6ff',
          400: '#2e94ff',
          500: '#1877f2',
          600: '#166fe5',
          700: '#1463cc',
          800: '#1158b5',
          900: '#0e498f',
        },
      },
      fontFamily: {
        sans: [
          '"Noto Sans JP"',
          'Hiragino Sans',
          '"Yu Gothic"',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
      },
      maxWidth: {
        reading: '65ch',
      },
    },
  },
  plugins: [typography],
};
