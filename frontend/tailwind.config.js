/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ops: {
          bg: "#0b0d10",
          panel: "#111418",
          panel2: "#161a20",
          line: "#232a33",
          dim: "#7d8794",
          text: "#e6eaf0",
          red: "#ff4d4f",
          amber: "#f5a524",
          green: "#22c55e",
          cyan: "#22d3ee",
          violet: "#a78bfa",
          sky: "#38bdf8",
        },
      },
      fontFamily: {
        mono: ["'JetBrains Mono'", "ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
      },
      keyframes: {
        pulseRing: { "0%": { boxShadow: "0 0 0 0 rgba(255,77,79,.6)" }, "100%": { boxShadow: "0 0 0 10px rgba(255,77,79,0)" } },
        slideIn: { "0%": { transform: "translateY(-8px)", opacity: 0 }, "100%": { transform: "translateY(0)", opacity: 1 } },
        scan: { "0%": { backgroundPosition: "0 0" }, "100%": { backgroundPosition: "0 40px" } },
      },
      animation: { pulseRing: "pulseRing 1.4s infinite", slideIn: "slideIn .25s ease-out", scan: "scan 2s linear infinite" },
    },
  },
  plugins: [],
};
