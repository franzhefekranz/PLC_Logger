#!/usr/bin/env bash
# =====================================================================================================================
#  PLC Datenlogger – AppImage für Linux bauen (x86_64 oder arm64/aarch64)
#
#  Aufruf (im Projektordner; Programmdateien in src/, Anleitung in doc/):
#      ./build_appimage.sh                 AppImage für die Architektur dieses Rechners bauen
#      ./build_appimage.sh --docker arm64  in einem Docker-Container für arm64 bauen (auf x86_64 per QEMU-Emulation)
#      ./build_appimage.sh --docker amd64  in einem Docker-Container für x86_64 bauen
#      ./build_appimage.sh doc             nur die Anleitung: doc/*.html und PDF deutsch/englisch (build/doc, dist)
#
#  Ergebnis: dist/PLCDatenlogger-<Version>-x86_64.AppImage bzw. dist/PLCDatenlogger-<Version>-aarch64.AppImage
#            und das Debian-Paket dist/plc-datenlogger_<Version>_amd64.deb bzw. _arm64.deb (nur mit dpkg-deb;
#            abschalten mit SKIP_DEB=1)
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

APP="PLCDatenlogger"
NAME="PLC Datenlogger"
PFX="plc"
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
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "src/${PFX}_common.py")"
# Programmmodule (plc_*, Paket plc_treiber) liegen in src: für PyInstaller und --collect-submodules auffindbar machen
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
echo "== $NAME $VERSION – AppImage für $ARCH"

B="build/linux-$ARCH"
mkdir -p "$B" dist

# ------------------------------------------------------------------ nur die Anleitung (Parameter doc)
# HTML (doc/*.html, für F1) und PDF deutsch/englisch (build/doc/Bedienungsanleitung.pdf, User_Manual.pdf und Kopien mit
# Versionsnummer in dist/) – in einer eigenen, kleinen Python-Umgebung build/doc-venv (Sphinx, rinohtype, docutils).
if [[ "${1:-}" == "doc" ]]; then
    echo "== $NAME $VERSION – nur die Anleitung"
    DV="build/doc-venv"
    [[ -x "$DV/bin/python" ]] || "$PY" -m venv "$DV"
    "$DV/bin/python" -m pip install -q --upgrade pip
    "$DV/bin/python" -m pip install -q -r doc/requirements.txt docutils
    mkdir -p build/doc dist
    for DOCN in bedienungsanleitung user_manual; do
        "$DV/bin/python" -c "import docutils.core as d; d.publish_file(source_path='doc/$DOCN.rst', destination_path='doc/$DOCN.html', writer_name='html5', settings_overrides={'input_encoding':'utf-8','output_encoding':'utf-8','syntax_highlight':'none'})" >/dev/null 2>&1 \
            && echo "[OK] doc/$DOCN.html" || echo "[HINWEIS] doc/$DOCN.html konnte nicht erzeugt werden."
    done
    FAILED=0
    for L in de en; do
        PDF="build/doc/Bedienungsanleitung.pdf"; COPY="dist/PLC_Datenlogger_Bedienungsanleitung_$VERSION.pdf"
        [[ "$L" == en ]] && PDF="build/doc/User_Manual.pdf" && COPY="dist/PLC_Datenlogger_User_Manual_$VERSION.pdf"
        rm -f "$PDF"
        echo "PDF ($L) …"
        if "$DV/bin/python" tools/build_doc.py --lang "$L" --copy-to "$PDF" > "build/doc/pdf_$L.log" 2>&1 && [[ -f "$PDF" ]]; then
            cp "$PDF" "$COPY"
            echo "[OK] $PDF und $COPY"
        else
            FAILED=1
            echo "[FEHLER] PDF ($L) nicht erzeugt. Letzte Meldungen (vollständig: build/doc/pdf_$L.log):"
            tr '\r' '\n' < "build/doc/pdf_$L.log" | grep -v 'ETA' | tail -n 12
        fi
    done
    exit $FAILED
fi

# ------------------------------------------------------------------ 0. Werkzeuge prüfen (vor dem langen Build)
PLCTAG_VER="2.7.2"
LIB="$B/libplctag.so"
MISSING=()
"$PY" -c 'import venv, ensurepip' 2>/dev/null || MISSING+=(python3-venv)
command -v file >/dev/null || MISSING+=(file)
command -v curl >/dev/null || command -v wget >/dev/null || MISSING+=(curl)
if [[ ! -f "$LIB" && "${SKIP_PLCTAG:-0}" != "1" ]]; then
    command -v cmake >/dev/null || MISSING+=(cmake)
    { command -v cc >/dev/null && command -v make >/dev/null; } || MISSING+=(build-essential)
    command -v git >/dev/null || command -v curl >/dev/null || MISSING+=(git)
fi
if (( ${#MISSING[@]} )); then
    echo "[FEHLER] Es fehlen Werkzeuge für den Build: ${MISSING[*]}"
    echo "         Debian/Ubuntu/Mint:  sudo apt install ${MISSING[*]} libxkbcommon-x11-0 libxcb-cursor0 \\"
    echo "                              libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libegl1 libfontconfig1 libdbus-1-3"
    echo "         Fedora:              sudo dnf install cmake gcc gcc-c++ make file python3"
    echo "         Ohne libplctag (Treiber clx dann ohne Funktion):  SKIP_PLCTAG=1 ./build_appimage.sh"
    exit 1
fi

# ------------------------------------------------------------------ 1. Python-Umgebung
if [[ ! -x "$B/venv/bin/python" ]]; then
    echo "[1/7] Python-Umgebung anlegen ..."
    "$PY" -m venv "$B/venv"
fi
VPY="$B/venv/bin/python"
"$VPY" -m pip install -q --upgrade pip wheel
if ! "$VPY" -m pip install -q -r requirements.txt; then
    echo "[HINWEIS] Nicht alle Pakete als Wheel verfügbar (z. B. PySide6 auf älteren arm64-Systemen)."
    echo "          Alternative: System-Pakete verwenden, z. B. sudo apt install python3-pyside6.qtwidgets python3-pyside6.qtsvg"
    echo "          und die Umgebung mit  rm -rf $B/venv && PYTHON=/usr/bin/python3 VENV_SYSTEM=1 ./build_appimage.sh  neu anlegen."
    if [[ "${VENV_SYSTEM:-0}" == "1" ]]; then
        rm -rf "$B/venv"; "$PY" -m venv --system-site-packages "$B/venv"
        grep -viE '^(PySide6|pyside6)' requirements.txt > "$B/req.txt"
        "$VPY" -m pip install -q -r "$B/req.txt"
    else
        exit 1
    fi
fi
"$VPY" -m pip install -q "pyinstaller>=6.0"

# ------------------------------------------------------------------ 2. Symbol und Zusatzdateien
echo "[2/7] Symbol, Chart.js ..."
if [[ ! -f app.png ]]; then
    QT_QPA_PLATFORM=offscreen "$VPY" tools/make_icon.py || true
fi
if [[ ! -f web_static/chart.umd.js ]]; then
    mkdir -p web_static
    (curl -fsSL -o web_static/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js \
        || wget -q -O web_static/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js) \
        || { rm -f web_static/chart.umd.js; echo "[HINWEIS] Chart.js nicht geladen – der Webserver nutzt dann das CDN."; }
fi
EXTRA=()
[[ -f web_static/chart.umd.js ]] && EXTRA+=(--add-data "$PWD/web_static:web_static")

# ------------------------------------------------------------------ 2b. libplctag (natives Linux-Gegenstück zu plctag.dll)
if [[ ! -f "$LIB" && "${SKIP_PLCTAG:-0}" == "1" ]]; then
    echo "[HINWEIS] SKIP_PLCTAG=1: libplctag wird nicht gebaut – der Treiber clx funktioniert im AppImage nicht."
elif [[ ! -f "$LIB" ]]; then
    echo "[2/7] libplctag $PLCTAG_VER aus dem Quelltext bauen (cmake, gcc) ..."
    rm -rf "$B/libplctag-src"
    if ! git clone -q --depth 1 --branch "v$PLCTAG_VER" https://github.com/libplctag/libplctag.git "$B/libplctag-src"; then
        mkdir -p "$B/libplctag-src"
        curl -fsSL "https://github.com/libplctag/libplctag/archive/refs/tags/v$PLCTAG_VER.tar.gz" \
            | tar -xz -C "$B/libplctag-src" --strip-components=1
    fi
    cmake -S "$B/libplctag-src" -B "$B/libplctag-src/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
    cmake --build "$B/libplctag-src/build" --target plctag_dyn -j"$(nproc)" >/dev/null
    cp "$(find "$B/libplctag-src/build" -name 'libplctag.so*' -type f | head -1)" "$LIB"
fi
[[ -f "$LIB" ]] && EXTRA+=(--add-binary "$PWD/$LIB:.")

# ------------------------------------------------------------------ 3. PyInstaller (ein Programm für alles)
echo "[3/7] PyInstaller ..."
"$VPY" -m PyInstaller --noconfirm --clean --windowed --onedir --name "$APP" \
    --distpath "$B/dist" --workpath "$B/work" --specpath "$B" --paths "$PWD/src" \
    --add-data "$PWD/sprachen:sprachen" \
    --add-data "$PWD/vorlagen:vorlagen" \
    --add-data "$PWD/logo.png:." --add-data "$PWD/app.ico:." \
    --collect-all snap7 --collect-all pycomm3 --collect-all s7commplus --collect-all asyncua --collect-all pymodbus --collect-all serial --collect-data pyqtgraph --hidden-import PySide6.QtSvg --exclude-module PyQt6 --exclude-module PyQt5 \
    --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary \
    --collect-all flask --collect-all werkzeug \
    --hidden-import plc_about --hidden-import plc_export --collect-all openpyxl --hidden-import plc_block_dialog --hidden-import plc_branding --hidden-import plc_common \
    --hidden-import plc_config --hidden-import plc_db --hidden-import plc_db_dialog --hidden-import plc_event_viewer \
    --hidden-import plc_events --hidden-import plc_formula --hidden-import plc_formula_dialog \
    --hidden-import plc_gui --hidden-import plc_headless --hidden-import plc_i18n --hidden-import plc_pid \
    --hidden-import plc_pid_dialog --hidden-import plc_recorder --hidden-import plc_splash \
    --hidden-import plc_svg --hidden-import plc_trigger_dialog --hidden-import plc_util \
    --hidden-import plc_web --hidden-import plc_webauth --hidden-import plc_web_dialog --hidden-import plc_report \
    --hidden-import plc_csvjoin --hidden-import plc_analysis --hidden-import plc_analysis_dialog --hidden-import plc_iocheck --hidden-import plc_iocheck_dialog --hidden-import plc_iocheck_web --hidden-import plc_qr --hidden-import plc_notify --hidden-import plc_notify_dialog --hidden-import plc_opcua_server --hidden-import plc_opcua_dialog --hidden-import plc_web_prozess --hidden-import plc_netscan --hidden-import plc_netscan_dialog --hidden-import plc_headless --hidden-import plc_headless_dialog \
    --hidden-import cryptography.x509 --hidden-import cryptography.hazmat.primitives.asymmetric.rsa \
    --collect-submodules plc_treiber --add-data "$PWD/src/plc_treiber/_vorlage.py:plc_treiber" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    "$PWD/src/${PFX}_logger.py"

# ------------------------------------------------------------------ 4. AppDir
echo "[4/7] AppDir zusammenstellen ..."
AD="$B/AppDir"
rm -rf "$AD"
mkdir -p "$AD/usr/lib/$APP" "$AD/usr/share/applications" "$AD/usr/share/icons/hicolor/256x256/apps" "$AD/usr/share/doc/$APP"
cp -a "$B/dist/$APP/." "$AD/usr/lib/$APP/"
cp doc/bedienungsanleitung.rst doc/user_manual.rst "$AD/usr/share/doc/$APP/" 2>/dev/null || true
# HTML-Fassung der Anleitung erzeugen (docutils; für die Kontexthilfe F1 nötig) und mit der PDF-Fassung
# (falls mit tools/build_doc.py erzeugt) beilegen; Menü Hilfe › Bedienungsanleitung bzw. F1 öffnen sie
# (deutsch: bedienungsanleitung, englisch: user_manual)
for DOCN in bedienungsanleitung user_manual; do
  "$VPY" -c "import docutils.core as d; d.publish_file(source_path='doc/$DOCN.rst', destination_path='doc/$DOCN.html', writer_name='html5', settings_overrides={'input_encoding':'utf-8','output_encoding':'utf-8','syntax_highlight':'none'})" >/dev/null 2>&1 \
      || echo "[HINWEIS] doc/$DOCN.html konnte nicht erzeugt werden (F1 öffnet dann die Anleitung am Anfang)."
  cp "doc/$DOCN.html" "$AD/usr/share/doc/$APP/" 2>/dev/null || true
done
[[ -d doc/images ]] && cp -r doc/images "$AD/usr/share/doc/$APP/" || true
cp build/doc/Bedienungsanleitung.pdf build/doc/User_Manual.pdf "$AD/usr/share/doc/$APP/" 2>/dev/null || true
# Lizenz (LGPL-3.0-or-later) und Lizenztexte: neben das Programm und nach usr/share/doc
for f in LICENSE COPYING THIRD_PARTY_LICENSES.md; do
    if [[ -f "$f" ]]; then
        cp "$f" "$AD/usr/lib/$APP/"
        cp "$f" "$AD/usr/share/doc/$APP/"
    fi
done
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
echo "[5/7] appimagetool ..."
TOOL="$B/appimagetool-$ARCH.AppImage"
if [[ ! -x "$TOOL" ]]; then
    URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    curl -fsSL -o "$TOOL" "$URL" || wget -q -O "$TOOL" "$URL"
    chmod +x "$TOOL"
fi

# ------------------------------------------------------------------ 6. AppImage erzeugen
OUT="dist/$APP-$VERSION-$ARCH.AppImage"
echo "[6/7] $OUT ..."
# --appimage-extract-and-run: funktioniert auch ohne FUSE (z. B. im Docker-Container)
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run --no-appstream "$AD" "$OUT"
chmod +x "$OUT"

# ------------------------------------------------------------------ 7. Debian-Paket (.deb) aus demselben AppDir
# Für Debian, Ubuntu, Mint und Raspberry Pi OS: installiert das Programm nach /usr/lib/PLCDatenlogger (gleicher Aufbau
# wie im AppImage, die Anleitung liegt damit unter /usr/share/doc/PLCDatenlogger), Startbefehle in /usr/bin und
# Einträge im Startmenü. Ohne dpkg-deb (z. B. Fedora) wird das Paket übersprungen.
DEB=""
if command -v dpkg-deb >/dev/null && [[ "${SKIP_DEB:-0}" != "1" ]]; then
    PKG="plc-datenlogger"
    case "$ARCH" in x86_64) DARCH=amd64 ;; aarch64) DARCH=arm64 ;; esac
    # Mindest-glibc = glibc des Build-Systems (PyInstaller-Programme laufen nur mit gleicher oder neuerer glibc)
    GLIBC="$(ldd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+$' || true)"
    DEB="dist/${PKG}_${VERSION}_${DARCH}.deb"
    echo "[7/7] $DEB ..."
    DR="$B/deb"
    rm -rf "$DR"
    mkdir -p "$DR/DEBIAN" "$DR/usr/bin" "$DR/usr/share/doc/$PKG"
    cp -a "$AD/usr/." "$DR/usr/"
    # Startbefehle: Logger, Konfigurationsprogramm, IO-Check, Ereignis-Viewer
    mkcmd() {
        printf '#!/bin/sh\n# %s (Paket %s)\nexec /usr/lib/%s/%s %s"$@"\n' "$2" "$PKG" "$APP" "$APP" "$3" > "$DR/usr/bin/$1"
        chmod 755 "$DR/usr/bin/$1"
    }
    mkcmd plc-datenlogger    "$NAME"                 ""
    mkcmd plc-konfiguration  "Konfigurationsprogramm" "--konfig "
    mkcmd plc-iocheck        "IO-Check"               "--iocheck "
    mkcmd plc-ereignisse     "Ereignis-Viewer"        "--ereignisse "
    # Startmenü: Logger (mit Aktionen wie im AppImage), dazu Konfiguration und IO-Check als eigene Einträge
    sed -e 's#^Exec=AppRun --konfig#Exec=plc-konfiguration#' -e 's#^Exec=AppRun --ereignisse#Exec=plc-ereignisse#' \
        -e 's#^Exec=AppRun#Exec=plc-datenlogger#' "$AD/$APP.desktop" > "$DR/usr/share/applications/$PKG.desktop"
    rm -f "$DR/usr/share/applications/$APP.desktop"
    desk() {
        cat > "$DR/usr/share/applications/$1.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=$2
Name[en]=$3
Exec=$1 %f
Icon=$APP
Categories=Utility;Engineering;
Terminal=false
DESK
    }
    desk plc-konfiguration "PLC Konfiguration" "PLC Configuration"
    desk plc-iocheck       "PLC IO-Check"      "PLC IO check"
    cp "$DR/usr/share/doc/$APP/LICENSE" "$DR/usr/share/doc/$PKG/copyright" 2>/dev/null || true
    SIZE="$(du -sk "$DR/usr" | cut -f1)"
    cat > "$DR/DEBIAN/control" <<CTRL
Package: $PKG
Version: $VERSION
Architecture: $DARCH
Maintainer: Michael Taxis <mxtaxis@gmail.com>
Installed-Size: $SIZE
Depends: libc6 (>= ${GLIBC:-2.31}), libgl1, libegl1, libfontconfig1, libxkbcommon-x11-0, libxcb-cursor0, libdbus-1-3
Section: misc
Priority: optional
Homepage: https://github.com/franzhefekranz/PLC_Logger
Description: PLC Datenlogger - SPS-Daten aufzeichnen und anzeigen
 Zeichnet Werte von Steuerungen (Siemens S7, Allen-Bradley, Modbus, OPC UA u. a.)
 auf, zeigt sie als Diagramme, schreibt CSV-Dateien und Datenbanken und bietet
 Webserver, Ereignisse, Berichte und IO-Check.
 .
 Records PLC values, shows them as charts, writes CSV files and databases.
CTRL
    # Startmenü und Symbole nach Installation/Entfernen auffrischen (falls die Werkzeuge vorhanden sind)
    for S in postinst postrm; do
        printf '#!/bin/sh\nset -e\ncommand -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true\ncommand -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true\nexit 0\n' > "$DR/DEBIAN/$S"
        chmod 755 "$DR/DEBIAN/$S"
    done
    find "$DR" -type d -exec chmod 755 {} +
    dpkg-deb --root-owner-group -Zxz --build "$DR" "$DEB" >/dev/null
fi

echo
echo "[OK] $OUT"
echo "     Start:            ./$(basename "$OUT")"
echo "     Konfiguration:    ./$(basename "$OUT") --konfig"
echo "     Ereignis-Viewer:  ./$(basename "$OUT") --ereignisse"
echo "     Daten liegen in ~/$APP (oder neben dem AppImage, wenn dort eine Datei portable.txt liegt)."
if [[ -n "$DEB" ]]; then
    echo "[OK] $DEB"
    echo "     Installieren:     sudo apt install ./$(basename "$DEB")"
    echo "     Start:            plc-datenlogger, plc-konfiguration, plc-iocheck, plc-ereignisse (oder Startmenü)"
fi
