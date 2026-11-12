// Legge le classi direttamente da app/panel.py. Vedi ui/README.md per rigenerare app/static/panel.css.
// Tema EDITH: blu notte profondo (sfondo e pannelli), arancio ambra (accento, come l'alone caldo e la montatura degli occhiali),
// azzurro ghiaccio (linee del visore). `slate` e `indigo` sono ridefiniti: tutte le classi del pannello prendono i colori nuovi.
module.exports = {
  content: ["./app/panel.py", "./app/panel_ext.py"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        slate: {
          50: "#f1f6fb", 100: "#e3edf7", 200: "#c9dbec", 300: "#a9c2db", 400: "#7f9dbd",
          500: "#6584a6", 600: "#3b5a80", 700: "#1d3a5c", 800: "#0c1a2e", 900: "#050b17", 950: "#02060e",
        },
        indigo: {
          50: "#fff4e5", 100: "#ffe4c2", 200: "#ffcf94", 300: "#ffb865", 400: "#ffa13a",
          500: "#ff8a1f", 600: "#c9540a", 700: "#9e3f05", 800: "#7a3004", 900: "#4d1e02",
        },
      },
    },
  },
  plugins: [],
}
