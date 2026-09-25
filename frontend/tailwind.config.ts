import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0e14",
          900: "#0f1520",
          800: "#161d2b",
          700: "#212a3d",
          600: "#2e3a52",
          500: "#465370",
          400: "#6b7a99",
          300: "#98a5c0",
          200: "#c4cee0",
          100: "#e4e9f2",
          50: "#f4f6fa",
        },
        accent: {
          600: "#1d4ed8",
          500: "#2563eb",
          400: "#3b82f6",
        },
        fact: "#0f766e",
        calculated: "#7c3aed",
        interpretation: "#b45309",
        danger: "#b91c1c",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "Helvetica", "Arial", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
