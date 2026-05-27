/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        "surface-page":  "var(--surface-page)",
        "surface-1":     "var(--surface-1)",
        "surface-2":     "var(--surface-2)",
        "surface-input": "var(--surface-input)",
        "text-hi":       "var(--text-hi)",
        "text-md":       "var(--text-md)",
        "text-lo":       "var(--text-lo)",
        "accent-sky":    "var(--bg-sky)",
        "accent-emerald":"var(--bg-emerald)",
        "accent-rose":   "var(--bg-rose)",
        "accent-amber":  "var(--bg-amber)",
        "text-sky-token":     "var(--text-sky)",
        "text-emerald-token": "var(--text-emerald)",
        "text-rose-token":    "var(--text-rose)",
        "text-amber-token":   "var(--text-amber)",
      },
      borderColor: {
        "subtle":        "var(--border-subtle)",
        "default-theme": "var(--border-default)",
      },
      boxShadow: {
        "card": "var(--shadow-card)",
      },
      backgroundImage: {
        "gradient-card":       "var(--gradient-card)",
        "gradient-panel":      "var(--gradient-panel)",
        "gradient-panel-deep": "var(--gradient-panel-deep)",
        "gradient-panel-mid":  "var(--gradient-panel-mid)",
        "gradient-shell":   "var(--gradient-shell)",
        "gradient-header":  "var(--gradient-header)",
        "gradient-sidebar": "var(--gradient-sidebar)",
        "gradient-hero":    "var(--gradient-hero)",
      },
    },
  },
  plugins: [],
};
