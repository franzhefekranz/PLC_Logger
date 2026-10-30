#!/usr/bin/env bash
# =====================================================================================================================
#  PLC Datenlogger – macOS-App bauen (Apple Silicon arm64 oder Intel x86_64, je nach Rechner)
#
#  Aufruf (im Projektordner, auf einem Mac):
#      ./build_macos.sh
#      ./build_macos.sh doc      nur die Anleitung: doc/*.html und PDF deutsch/englisch (build/doc, dist)
#
#  Ergebnis: dist/PLC Datenlogger.app und dist/PLCDatenlogger-<Version>-macos-<arm64|x86_64>.dmg
#
#  Die App enthält Logger, Konfigurationsprogramm (Parameter --konfig), IO-Check (--iocheck) und Ereignis-Viewer
#  (--ereignisse); die Daten liegen in ~/PLCDatenlogger. Sie ist nur „ad hoc“ signiert (ohne Apple-Entwicklerkonto):
#  macOS fragt beim ersten Start nach (Rechtsklick › Öffnen) oder die Sperre wird entfernt mit
#      xattr -dr com.apple.quarantine "/Applications/PLC Datenlogger.app"
#  Mit Entwicklerkonto: MACOS_SIGN_ID="Developer ID Application: …" setzen, dann wird damit signiert (Notarisierung
#  danach mit xcrun notarytool).
#
#  PyInstaller kann nicht für eine fremde Architektur übersetzen: arm64 auf einem Apple-Silicon-Mac bauen, x86_64 auf
#  einem Intel-Mac (oder per GitHub Actions, Workflow „macOS“, beides).
#
#  Benötigt: python3 (3.10+), Xcode Command Line Tools (clang, hdiutil, iconutil, sips), cmake (nur CLX: libplctag,
#  z. B. brew install cmake).
# =====================================================================================================================
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

APP="PLCDatenlogger"
NAME="PLC Datenlogger"
PFX="plc"
PY="${PYTHON:-python3}"
ARCH="$(uname -m)"                                   # arm64 oder x86_64
VERSION="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "src/${PFX}_common.py")"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
echo "== $NAME $VERSION – macOS-App für $ARCH"

B="build/macos-$ARCH"
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

# ------------------------------------------------------------------ 1. Python-Umgebung
if [[ ! -x "$B/venv/bin/python" ]]; then
    echo "[1/6] Python-Umgebung anlegen ..."
    "$PY" -m venv "$B/venv"
fi
VPY="$B/venv/bin/python"
"$VPY" -m pip install -q --upgrade pip wheel
"$VPY" -m pip install -q -r requirements.txt
"$VPY" -m pip install -q "pyinstaller>=6.0" docutils

# ------------------------------------------------------------------ 2. Symbol, Chart.js, Anleitung
echo "[2/6] Symbol, Chart.js, Anleitung ..."
if [[ ! -f app.png ]]; then
    QT_QPA_PLATFORM=offscreen "$VPY" tools/make_icon.py || true
fi
ICNS="$B/app.icns"
SRC=app.png
[[ -f icons/logger_1024.png ]] && SRC=icons/logger_1024.png     # Programm-Icon in voller Größe (für Retina)
if [[ -f "$SRC" && ! -f "$ICNS" ]]; then
    SET="$B/app.iconset"
    rm -rf "$SET"; mkdir -p "$SET"
    for s in 16 32 128 256 512; do
        sips -z $s $s "$SRC" --out "$SET/icon_${s}x${s}.png" >/dev/null
        sips -z $((s * 2)) $((s * 2)) "$SRC" --out "$SET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns "$SET" -o "$ICNS"
fi
if [[ ! -f web_static/chart.umd.js ]]; then
    mkdir -p web_static
    curl -fsSL -o web_static/chart.umd.js https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js \
        || { rm -f web_static/chart.umd.js; echo "[HINWEIS] Chart.js nicht geladen – der Webserver nutzt dann das CDN."; }
fi
# Anleitung als HTML (Hilfe › Bedienungsanleitung, F1) samt Bildern und ggf. PDF in die App (Ordner Doku)
DOC="$B/Doku"
rm -rf "$DOC"; mkdir -p "$DOC"
for DOCN in bedienungsanleitung user_manual; do
    "$VPY" -c "import docutils.core as d; d.publish_file(source_path='doc/$DOCN.rst', destination_path='$DOC/$DOCN.html', writer_name='html5', settings_overrides={'input_encoding':'utf-8','output_encoding':'utf-8','syntax_highlight':'none'})" >/dev/null 2>&1 \
        || cp "doc/$DOCN.rst" "$DOC/"
done
[[ -d doc/images ]] && cp -R doc/images "$DOC/images"
cp build/doc/Bedienungsanleitung.pdf build/doc/User_Manual.pdf "$DOC/" 2>/dev/null || true
for f in LICENSE COPYING THIRD_PARTY_LICENSES.md; do [[ -f "$f" ]] && cp "$f" "$DOC/"; done

EXTRA=(--add-data "$ROOT/$DOC:Doku")
[[ -f web_static/chart.umd.js ]] && EXTRA+=(--add-data "$ROOT/web_static:web_static")
[[ -f "$ICNS" ]] && EXTRA+=(--icon "$ROOT/$ICNS")

# ------------------------------------------------------------------ 3. libplctag (Treiber clx)
PLCTAG_VER="2.7.2"
LIB="$B/libplctag.dylib"
if [[ ! -f "$LIB" && "${SKIP_PLCTAG:-0}" != "1" ]]; then
    if command -v cmake >/dev/null; then
        echo "[3/6] libplctag $PLCTAG_VER aus dem Quelltext bauen ..."
        rm -rf "$B/libplctag-src"
        git clone -q --depth 1 --branch "v$PLCTAG_VER" https://github.com/libplctag/libplctag.git "$B/libplctag-src"
        cmake -S "$B/libplctag-src" -B "$B/libplctag-src/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
        cmake --build "$B/libplctag-src/build" --target plctag_dyn -j"$(sysctl -n hw.ncpu)" >/dev/null
        cp "$(find "$B/libplctag-src/build" -name 'libplctag*.dylib' -type f | head -1)" "$LIB"
    else
        echo "[HINWEIS] cmake fehlt (brew install cmake) – libplctag wird nicht gebaut, der Treiber clx funktioniert nicht."
    fi
fi
[[ -f "$LIB" ]] && EXTRA+=(--add-binary "$ROOT/$LIB:.")

# ------------------------------------------------------------------ 4. PyInstaller: App-Bündel
echo "[4/6] PyInstaller ..."
"$VPY" -m PyInstaller --noconfirm --clean --windowed --onedir --name "$NAME" \
    --osx-bundle-identifier de.taxis-instruments.plcdatenlogger \
    --distpath "$B/dist" --workpath "$B/work" --specpath "$B" --paths "$ROOT/src" \
    --add-data "$ROOT/sprachen:sprachen" \
    --add-data "$ROOT/vorlagen:vorlagen" \
    --add-data "$ROOT/logo.png:." --add-data "$ROOT/app.ico:." --add-data "$ROOT/icons:icons" \
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
    --hidden-import plc_csvjoin --hidden-import plc_analysis --hidden-import plc_analysis_dialog --hidden-import plc_iocheck --hidden-import plc_iocheck_dialog --hidden-import plc_iocheck_web --hidden-import plc_qr --hidden-import plc_notify --hidden-import plc_notify_dialog --hidden-import plc_opcua_server --hidden-import plc_opcua_dialog --hidden-import plc_web_prozess --hidden-import plc_netscan --hidden-import plc_netscan_dialog --hidden-import plc_headless --hidden-import plc_headless_dialog --hidden-import plc_grafana \
    --hidden-import cryptography.x509 --hidden-import cryptography.hazmat.primitives.asymmetric.rsa \
    --collect-submodules plc_treiber --add-data "$ROOT/src/plc_treiber/_vorlage.py:plc_treiber" \
    ${EXTRA[@]+"${EXTRA[@]}"} \
    "$ROOT/src/${PFX}_logger.py"

APPDIR="$B/dist/$NAME.app"
[[ -d "$APPDIR" ]] || { echo "[FEHLER] $APPDIR fehlt"; exit 1; }

# ------------------------------------------------------------------ 5. Info.plist, Signatur
echo "[5/6] Info.plist und Signatur ..."
PLIST="$APPDIR/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace CFBundleDisplayName -string "$NAME" "$PLIST"
plutil -replace NSHumanReadableCopyright -string "© Michael Taxis, LGPL-3.0-or-later" "$PLIST"
plutil -replace LSMinimumSystemVersion -string "12.0" "$PLIST"
# Die geänderte Info.plist macht die Signatur von PyInstaller ungültig: neu signieren (ad hoc oder Developer ID).
# Ad hoc ("-") ohne Hardened Runtime: sonst lehnt macOS die ebenfalls ad hoc signierten Bibliotheken ab.
if [[ -n "${MACOS_SIGN_ID:-}" ]]; then
    codesign --force --deep --options runtime --timestamp --sign "$MACOS_SIGN_ID" "$APPDIR"
else
    codesign --force --deep --sign - "$APPDIR"
fi
codesign --verify --deep "$APPDIR"

# ------------------------------------------------------------------ 6. DMG
OUT="dist/$APP-$VERSION-macos-$ARCH.dmg"
echo "[6/6] $OUT ..."
STAGE="$B/dmg"
rm -rf "$STAGE" "dist/$NAME.app"; mkdir -p "$STAGE"
cp -R "$APPDIR" "$STAGE/"
cp -R "$APPDIR" "dist/"
ln -s /Applications "$STAGE/Programme"
[[ -f vorlagen/LIESMICH.txt ]] && cp -R vorlagen "$STAGE/SPS-Vorlagen"
rm -f "$OUT"
hdiutil create -volname "$NAME $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null
echo
echo "[OK] $OUT"
echo "     Installieren: DMG öffnen, „${NAME}“ auf „Programme“ ziehen."
echo "     Erster Start: Rechtsklick › Öffnen (nicht signiert) oder"
echo "                   xattr -dr com.apple.quarantine \"/Applications/$NAME.app\""
echo "     Konfiguration: \"/Applications/$NAME.app/Contents/MacOS/$NAME\" --konfig"
