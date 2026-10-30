#!/bin/sh
# Desktop-Starter „Grafana starten“ und „Grafana beenden“ anlegen (Desktop und Anwendungsmenü des angemeldeten Benutzers,
# z. B. in der Remotedesktop-Sitzung mit XFCE oder LXQt). Einmal ausführen: ./desktop-starter.sh
DIR="$(cd "$(dirname "$0")" && pwd)"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
APPS="$HOME/.local/share/applications"
mkdir -p "$DESK" "$APPS"
chmod +x "$DIR/grafana.sh"
make() {   # Dateiname, Name, Kommentar, Befehl, Symbol
  for target in "$DESK/$1" "$APPS/$1"; do
    cat > "$target" <<DESKTOP
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=$4
Icon=$5
Terminal=false
Categories=Utility;
DESKTOP
    chmod +x "$target"
  done
  # XFCE (ab 4.18) und GNOME: Starter auf dem Desktop als vertrauenswürdig markieren
  gio set "$DESK/$1" metadata::trusted true 2>/dev/null || true
  gio set -t string "$DESK/$1" metadata::xfce-exe-checksum "$(sha256sum "$DESK/$1" | cut -d' ' -f1)" 2>/dev/null || true
}
make grafana-starten.desktop "Grafana starten" "Grafana starten und im Browser öffnen" "$DIR/grafana.sh start" web-browser
make grafana-beenden.desktop "Grafana beenden" "Grafana beenden (VictoriaMetrics läuft weiter)" "$DIR/grafana.sh stop" process-stop
echo "Starter angelegt in $DESK und im Anwendungsmenü."
