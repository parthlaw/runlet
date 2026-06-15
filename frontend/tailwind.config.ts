/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Surface layers — background → elevated
        surface: {
          DEFAULT:  "#13131b",
          low:      "#1b1b23",
          mid:      "#1f1f27",
          high:     "#292932",
          highest:  "#34343d",
          bright:   "#393841",
        },
        // Borders
        outline: {
          DEFAULT:  "#908fa0",
          strong:   "#464554",
        },
        // Text
        content: {
          DEFAULT:  "#e4e1ed",
          dim:      "#c7c4d7",
          muted:    "#908fa0",
          ghost:    "#464554",
        },
        // Primary indigo
        primary: {
          DEFAULT:  "#6366f1",
          soft:     "#c0c1ff",
        },
        // Status
        status: {
          success:  "#10b981",
          failed:   "#ef4444",
          running:  "#f59e0b",
          skipped:  "#4b5563",
          pending:  "#1f2937",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
