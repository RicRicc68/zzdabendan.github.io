/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
  theme: {
    container: { center: true, padding: "1rem" },
    extend: {
      fontFamily: {
        sans: ["IBM Plex Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        bg: { DEFAULT: "#0D0E12", panel: "#14151A", terminal: "#050505" },
        border: { DEFAULT: "#1E293B" },
        text: {
          primary: "#E2E8F0",
          secondary: "#94A3B8",
          muted: "#64748B",
        },
        brand: "#3B82F6",
        ok: "#10B981",
        warn: "#F59E0B",
        err: "#EF4444",
        running: "#3B82F6",
        term: { green: "#22C55E", error: "#F87171" },
      },
      borderRadius: { sm: "2px", md: "3px", lg: "4px" },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
