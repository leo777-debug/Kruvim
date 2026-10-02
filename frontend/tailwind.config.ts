import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', "Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        bg: v("bg"),
        side: v("side"),
        panel: v("panel"),
        raised: v("raised"),
        line: v("line"),
        "line-strong": v("line-strong"),
        fg: v("fg"),
        muted: v("muted"),
        faint: v("faint"),
        brand: { DEFAULT: v("brand"), fg: v("brand-fg"), soft: v("brand-soft") },
        pos: v("pos"),
        neg: v("neg"),
        warn: v("warn"),
        info: v("info"),
      },
      borderRadius: { lg: "8px", md: "6px", sm: "4px" },
      fontSize: { "2xs": ["11.5px", "15px"] },
      boxShadow: {
        panel: "0 1px 2px rgb(16 24 40 / 0.04)",
        pop: "0 10px 30px -8px rgb(16 24 40 / 0.22), 0 0 0 1px rgb(var(--line) / 1)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        pulse2: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        shimmer: { from: { backgroundPosition: "-200% 0" }, to: { backgroundPosition: "200% 0" } },
      },
      animation: {
        "fade-in": "fade-in .15s ease-out",
        pulse2: "pulse2 1.4s ease-in-out infinite",
        shimmer: "shimmer 2s linear infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
