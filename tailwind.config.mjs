/** @type {import('tailwindcss').Config} */
export default {
  theme: {
    fontSize: {
      xs: ['0.75rem', { lineHeight: '1rem' }],
      sm: ['0.875rem', { lineHeight: '1.375rem' }],
      base: ['1rem', { lineHeight: '1.625rem' }],
      lg: ['1.125rem', { lineHeight: '1.75rem' }],
      xl: ['1.25rem', { lineHeight: '1.875rem' }],
      '2xl': ['1.5rem', { lineHeight: '2rem' }],
      '3xl': ['2rem', { lineHeight: '2.5rem' }],
      '4xl': ['2.75rem', { lineHeight: '3.25rem' }],
    },
    extend: {
      colors: {
        background: '#FFFFFF',
        surface: '#F7F8FA',
        line: '#E2E5EA',
        ink: '#0F1117',
        muted: '#5A6272',
        accent: {
          DEFAULT: '#0057FF',
          dark: '#003FBB',
        },
      },
      fontFamily: {
        display: ['"Fraunces Variable"', 'ui-serif', 'Georgia', 'serif'],
        sans: ['"DM Sans Variable"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'monospace'],
      },
      maxWidth: {
        content: '760px',
      },
    },
  },
};
