#!/bin/sh
# Grafana bei Bedarf starten bzw. beenden (z. B. Raspberry Pi; VictoriaMetrics läuft dauerhaft weiter).
#   ./grafana.sh start    Grafana starten, warten bis bereit, im Desktop den Browser öffnen
#   ./grafana.sh stop     Grafana beenden
#   ./grafana.sh status   läuft Grafana?
# Damit Grafana nach einem Neustart nicht von selbst startet: grafana-bei-bedarf.yml nach docker-compose.override.yml
# kopieren (siehe Bedienungsanleitung, Raspberry Pi).
cd "$(dirname "$0")" || exit 1
URL="http://127.0.0.1:3000/"
case "${1:-start}" in
  start)
    docker compose up -d --no-deps grafana || exit 1
    i=0
    until curl -sf "${URL}api/health" >/dev/null 2>&1; do
      i=$((i + 1))
      if [ "$i" -gt 90 ]; then echo "Grafana antwortet nicht (docker compose logs grafana)"; exit 1; fi
      sleep 1
    done
    echo "Grafana läuft: $URL"
    if [ -n "$DISPLAY" ] && command -v xdg-open >/dev/null 2>&1; then
      xdg-open "$URL" >/dev/null 2>&1 &
    fi
    ;;
  stop)
    docker compose stop grafana
    ;;
  status)
    docker compose ps grafana
    ;;
  *)
    echo "Aufruf: $0 start|stop|status"
    exit 2
    ;;
esac
