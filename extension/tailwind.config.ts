import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./*.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(214 22% 86%)",
        background: "hsl(210 20% 98%)",
        foreground: "hsl(217 30% 12%)",
        muted: "hsl(215 18% 91%)",
        "muted-foreground": "hsl(217 12% 42%)",
        primary: "hsl(168 74% 28%)",
        "primary-foreground": "hsl(0 0% 100%)",
        danger: "hsl(0 74% 46%)"
      },
      borderRadius: {
        md: "8px"
      }
    }
  },
  plugins: []
};

export default config;

