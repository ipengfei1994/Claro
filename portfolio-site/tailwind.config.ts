import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1320px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: "hsl(var(--card))",
        surface: "hsl(var(--surface))",
        muted: "hsl(var(--muted))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        accent: "hsl(var(--accent))",
        success: "hsl(var(--success))",
        warning: "hsl(var(--warning))",
        danger: "hsl(var(--danger))",
        night: "hsl(var(--night))",
        "night-soft": "hsl(var(--night-soft))",
        "night-line": "hsl(var(--night-line))",
        "night-muted": "hsl(var(--night-muted))",
        "night-foreground": "hsl(var(--night-foreground))",
      },
      fontFamily: {
        sans: ["Inter", "PingFang SC", "Microsoft YaHei", "Segoe UI", "sans-serif"],
        display: ["Georgia", "Songti SC", "STSong", "SimSun", "serif"],
        mono: ["Cascadia Code", "SFMono-Regular", "Consolas", "monospace"],
      },
      maxWidth: { shell: "1240px", reading: "720px" },
      borderRadius: { sm: "2px", DEFAULT: "3px", lg: "4px" },
      boxShadow: { frame: "0 18px 50px -36px hsl(var(--foreground) / 0.45)" },
      keyframes: {
        "soft-enter": {
          from: { opacity: 0, transform: "translateY(8px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
      },
      animation: { "soft-enter": "soft-enter 420ms ease-out both" },
    },
  },
  plugins: [],
};

export default config;
