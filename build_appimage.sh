#!/usr/bin/env bash
# =====================================================================================================================
#  S7 Datenlogger – AppImage für Linux bauen (x86_64 oder arm64/aarch64)
#
#  Aufruf (im Programmordner):
#      ./build_appimage.sh                 AppImage für die Architektur dieses Rechners bauen
#      ./build_appimage.sh --docker arm64  in einem Docker-Container für arm64 bauen (auf x86_64 per QEMU-Emulation)
#      ./build_appimage.sh --docker amd64  in einem Docker-Container für x86_64 bauen
#
#  Ergebnis: dist/S7Datenlogger-<Version>-x86_64.AppImage bzw. dist/S7Datenlogger-<Version>-aarch64.AppImage
#
#  Ein AppImage ist eine einzelne, ausführbare Datei: herunterladen, ausführbar machen (chmod +x) und starten.
#  Es enthält Logger, Konfigurationsprogramm (Parameter --konfig) und Ereignis-Viewer (--ereignisse).
#
#  PyInstaller kann nicht für eine fremde Architektur übersetzen: ein arm64-AppImage entsteht auf einem arm64-Rechner
#  (z. B. Raspberry Pi 4/5 mit 64-Bit-System, Ubuntu arm64) oder im Docker-Container mit QEMU (--docker arm64,
#  dauert deutlich länger). Für möglichst alte Zielsysteme auf einem älteren System bauen (das AppImage läuft auf
#  Systemen mit gleicher oder neuerer glibc).
#
#  Benötigt: python3 (3.10+) mit venv, gcc/cmake (nur CLX: libplctag), curl/wget, file; für die Qt-Laufzeit die
#  Pakete libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libegl1 libfontconfig1
#  libdbus-1-3 (Debian/Ubuntu-Namen), damit PyInstaller sie mitnimmt.
# =====================================================================================================================
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

APP="S7Datenlogger"
NAME="S7 Datenlogger"
PFX="s7"
PY="${PYTHON:-python3}"

# ------------------------------------------------------------------ Docker-Modus
if [[ "${1:-}" == "--docker" ]]; then
    PLAT="${2:-arm64}"
    case "$PLAT" in arm64|aarch64) PLAT=arm64 ;; amd64|x86_64) PLAT=amd64 ;; *) echo "Unbekannte Plattform: $PLAT"; exit 1 ;; esac
    command -v docker >/dev/null || { echo "[FEHLER] docker fehlt."; exit 1; }
    if [[ "$PLAT" == "arm64" && "$(uname -m)" != "aarch64" ]]; then
        echo "[INFO] QEMU-Emulation für arm64 einrichten (einmalig) ..."
        docker run --privileged --rm tonistiigi/binfmt --install arm64 >/dev/null
    fi
    # Debian 12 (glibc 2.36): läuft auf Debian 12+, Ubuntu 23.04+, Raspberry Pi OS Bookworm und neuer.
    docker run --rm --platform "linux/$PLAT" -v "$PWD":/src -w /src -e HOME=/tmp python:3.12-bookworm bash -c '
        set -e
        apt-get update -qq
        apt-get install -y -qq --no-install-recommends cmake build-essential file wget libgl1 libegl1 \
            libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-xinerama0 \
            libxcb-randr0 libxcb-render-util0 libxcb-image0 libfontconfig1 libdbus-1-3 >/dev/null
        ./build_appimage.sh
        chown -R '"$(id -u):$(id -g)"' dist build'
    exit $?
fi

# ------------------------------------------------------------------ Architektur und Version
case "$(uname -m)" in
    x86_64|amd64)  ARCH=x86_64 ;;
    aarch64|arm64) ARCH=aarch64 ;;
    *) echo "[FEHLER] Architektur $(uname -m) wird nicht unterstützt (x86_64 oder aarch64)."; exit 1 ;;
esac
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "${PFX}_common.py")"
echo "== $NAME $VERSION – AppImage für $ARCH"

B="build/linux-$ARCH"
mkdir -p "$B" dist

# ------------------------------------------------------------------ 1. Python-Umgebung
if [[ ! -x "$B/venv/bin/python" ]]; then
    echo "[1/6] Python-Umgebung anlegen ..."
    "$PY" -m venv "$B/venv"
fi
VPY="$B/venv/bin/python"
"$VPY" -m pip install -q --upgrade pip wheel
if ! "$VPY" -m pip install -q -r requirements.txt; then
    echo "[HINWEIS] Nicht alle Pakete als Wheel verfügbar (z. B. PyQt6 auf älteren arm64-Systemen)."
    echo "          Alternative: System-Pakete verwenden, z. B. sudo apt install python3-pyqt6 python3-pyqt6.qtsvg"
    echo "          und die Umgebung mit  rm -rf $B/venv && PYTHON=/usr/bin/python3 VENV_SYSTEM=1 ./build_appimage.sh  neu anlegen."
    if [[ "${VENV_SYSTEM:-0}" == "1" ]]; then
        rm -rf "$B/venv"; "$PY" -m venv --system-site-packages "$B/venv"
        grep -viE '^(PyQt6|pyqt6)' requirements.txt > "$B/req.txt"
        "$VPY" -m pip install -q -r "$B/req.txt"
    else
        exit 1
    fi
fi
"$VPY" -m pip install -q "pyinstaller>=6.0"

# ------------------------------------------------------------------ 2. Symbol und Zusatzdateien
echo "[2/6] Symbol, Chart.js ..."
if [[ ! -f app.png ]]; then
    QT_QPA_PLATFORM=offscreen "$VPY" make_icon.py || true
fi
if [[ ! -f web_static/chart.umd.js ]]; then
    mkdir -p web_static
    (curl -fsSL -o web_static/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js \
        || wget -q -O web_static/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js) \
        || { rm -f web_static/chart.umd.js; echo "[HINWEIS] Chart.js nicht geladen – der Webserver nutzt dann das CDN."; }
fi
EXTRA=()
[[ -f web_static/chart.umd.js ]] && EXTRA+=(--add-data "$PWD/web_static:web_static")

# ------------------------------------------------------------------ 3. PyInstaller (ein Programm für alles)
echo "[3/6] PyInstaller ..."
"$VPY" -m PyInstaller --noconfirm --clean --windowed --onedir --name "$APP" \
    --distpath "$B/dist" --workpath "$B/work" --specpath "$B" \
    --add-data "$PWD/sprachen:sprachen" \
    --collect-all snap7 --collect-data pyqtgraph --hidden-import PyQt6.QtSvg \
    --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary \
    --collect-all flask --collect-all werkzeug \
    --hidden-import s7_block_dialog --hidden-import s7_branding --hidden-import s7_browser \
    --hidden-import s7_common --hidden-import s7_config --hidden-import s7_db --hidden-import s7_event_viewer \
    --hidden-import s7_events --hidden-import s7_formula --hidden-import s7_formula_dialog \
    --hidden-import s7_gui --hidden-import s7_headless --hidden-import s7_i18n --hidden-import s7_pid \
    --hidden-import s7_pid_dialog --hidden-import s7_recorder --hidden-import s7_splash --hidden-import s7_svg \
    --hidden-import s7_symbols --hidden-import s7_trigger_dialog --hidden-import s7_util \
    --hidden-import s7_web \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    "${PFX}_logger.py"

# ------------------------------------------------------------------ 4. AppDir
echo "[4/6] AppDir zusammenstellen ..."
AD="$B/AppDir"
rm -rf "$AD"
mkdir -p "$AD/usr/lib/$APP" "$AD/usr/share/applications" "$AD/usr/share/icons/hicolor/256x256/apps" "$AD/usr/share/doc/$APP"
cp -a "$B/dist/$APP/." "$AD/usr/lib/$APP/"
cp bedienungsanleitung.rst "$AD/usr/share/doc/$APP/" 2>/dev/null || true
if [[ -f app.png ]]; then
    cp app.png "$AD/$APP.png"
else
    "$VPY" - <<'EOF'
import base64, zlib, struct
# 1x1-Ersatzsymbol, falls make_icon.py nicht lief
def png(w, h, rgb):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
open("app.png", "wb").write(png(64, 64, (27, 42, 65)))
EOF
    cp app.png "$AD/$APP.png"
fi
cp "$AD/$APP.png" "$AD/usr/share/icons/hicolor/256x256/apps/$APP.png"
ln -sf "$APP.png" "$AD/.DirIcon"

cat > "$AD/AppRun" <<EOF
#!/bin/sh
# Startet das Programm aus dem AppImage. Parameter: --konfig (Konfigurationsprogramm), --ereignisse (Ereignis-Viewer),
# --headless (nur Aufzeichnung), --demo, Konfigurationsdatei.
HERE="\$(dirname "\$(readlink -f "\$0")")"
export QT_AUTO_SCREEN_SCALE_FACTOR=1
exec "\$HERE/usr/lib/$APP/$APP" "\$@"
EOF
chmod +x "$AD/AppRun"

cat > "$AD/$APP.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$NAME
Name[en]=$NAME
Comment=SPS-Daten aufzeichnen und anzeigen
Comment[en]=Record and display PLC data
Exec=AppRun %f
Icon=$APP
Categories=Utility;Engineering;
Terminal=false
Actions=Konfiguration;Ereignisse;

[Desktop Action Konfiguration]
Name=Konfiguration
Name[en]=Configuration
Exec=AppRun --konfig

[Desktop Action Ereignisse]
Name=Ereignisprotokoll
Name[en]=Event log
Exec=AppRun --ereignisse
EOF
cp "$AD/$APP.desktop" "$AD/usr/share/applications/"

# ------------------------------------------------------------------ 5. appimagetool
echo "[5/6] appimagetool ..."
TOOL="$B/appimagetool-$ARCH.AppImage"
if [[ ! -x "$TOOL" ]]; then
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    curl -fsSL -o "$TOOL" "$URL" || wget -q -O "$TOOL" "$URL"
    chmod +x "$TOOL"
fi

# ------------------------------------------------------------------ 6. AppImage erzeugen
OUT="dist/$APP-$VERSION-$ARCH.AppImage"
echo "[6/6] $OUT ..."
# --appimage-extract-and-run: funktioniert auch ohne FUSE (z. B. im Docker-Container)
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run --no-appstream "$AD" "$OUT"
chmod +x "$OUT"
echo
echo "[OK] $OUT"
echo "     Start:            ./$(basename "$OUT")"
echo "     Konfiguration:    ./$(basename "$OUT") --konfig"
echo "     Ereignis-Viewer:  ./$(basename "$OUT") --ereignisse"
echo "     Daten liegen in ~/$APP (oder neben dem AppImage, wenn dort eine Datei portable.txt liegt)."
