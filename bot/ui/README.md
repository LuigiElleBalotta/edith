# Stile del pannello

Il pannello usa [Tailwind CSS](https://tailwindcss.com). Il file `app/static/panel.css` è **già generato e versionato**: per usare o eseguire il pannello non serve installare niente (niente Node).

Si rigenera solo se cambi le classi in `app/panel.py`. Serve la CLI standalone di Tailwind (un solo eseguibile, senza Node):
scaricala da https://github.com/tailwindlabs/tailwindcss/releases (versione 3.4.x) e, dalla cartella `bot/`:

```
tailwindcss -c ui/tailwind.config.js -i ui/input.css -o app/static/panel.css --minify
```
