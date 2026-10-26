@echo off
rem ====================================================================================
rem  PLC Datenlogger - Build-Skript
rem
rem  Erzeugt mit PyInstaller die drei Programme (PLCLogger.exe, PLCKonfiguration.exe, PLCIOCheck.exe)
rem  in EINEM gemeinsamen Ordner und baut daraus mit Inno Setup die Setup-Datei.
rem  PLCLogger.exe laeuft mit Oberflaeche oder (Option "Headless" bzw. Parameter --headless) ohne.
rem  Fuer den Webserver wird Chart.js einmalig nach web_static\chart.umd.js geladen und mit eingepackt.
rem  Die Bedienungsanleitung (deutsch und englisch) kommt als HTML und PDF (doc\requirements.txt, tools\build_doc.py) in Installer und ZIP.
rem
rem  Aufruf:   build.bat              alles: Umgebung, .exe-Dateien, Installer
rem            build.bat exe          nur die .exe-Dateien (dist\PLCDatenlogger)
rem            build.bat portable     .exe-Dateien und portables ZIP (ohne Installer):
rem                                   dist\PLCDatenlogger_portable_<Version>.zip - entpacken, .exe starten
rem            build.bat installer    nur den Installer (setzt vorhandenes dist\ voraus)
rem
rem  Ein Programm fuer alle Steuerungen: die Treiber (Paket plc_treiber: S7/snap7, TIA/s7commplus, Logix/libplctag,
rem  Modbus TCP) werden komplett eingepackt. libplctag gibt es nicht als pip-Paket: plctag.dll (64 Bit) wird einmalig
rem  aus dem offiziellen GitHub-Release geladen (oder liegt bereits neben diesem Skript) und eingepackt.
rem  Voraussetzungen: Python 3.9+ (py-Launcher oder python im PATH), Internetzugang fuer
rem  pip (beim ersten Lauf), Inno Setup 7 oder 6 (https://jrsoftware.org/isinfo.php) fuer den Installer.
rem  Die Versionsnummer kommt aus APP_VERSION in src\plc_common.py (neue Version: python tools\bump_version.py).
rem  Ordner: Programmdateien in src\, Anleitung und Bilder in doc\, Icon/Logo/plctag.dll/sprachen im Projektordner.
rem ====================================================================================
setlocal EnableExtensions
cd /d "%~dp0"
rem  Programmmodule (plc_*, Paket plc_treiber) liegen in src: fuer PyInstaller und --collect-submodules auffindbar machen
set "PYTHONPATH=%~dp0src"

rem  Versionsnummer aus src\plc_common.py (Zeile  APP_VERSION = "x.y.z"; einzige Stelle, an der sie steht)
set "VERSION="
for /f "tokens=3" %%V in ('findstr /b /c:"APP_VERSION = " "src\plc_common.py"') do set "VERSION=%%~V"
if not defined VERSION (
    echo [FEHLER] APP_VERSION in src\plc_common.py nicht gefunden.
    goto :fail
)
rem  Version der libplctag-Bibliothek (GitHub-Release), aus der plctag.dll geladen wird.
set "PLCTAG_VER=2.7.2"
set "STEP=%~1"
if "%STEP%"=="" set "STEP=all"

echo ================================================================
echo  PLC Datenlogger - Build (%STEP%), Version %VERSION%
echo ================================================================

if /I "%STEP%"=="installer" goto :installer
if /I "%STEP%"=="all" goto :exe
if /I "%STEP%"=="exe" goto :exe
if /I "%STEP%"=="portable" goto :exe
echo [FEHLER] Unbekannter Parameter "%STEP%". Erlaubt: all, exe, portable, installer
goto :fail

rem ------------------------------------------------------------------ 1. Python-Umgebung
:exe
set "PY="
rem  BUILD_PYTHON: Python fest vorgeben (z. B. im GitHub-Workflow), sonst py-Launcher bzw. python aus dem PATH
if defined BUILD_PYTHON set "PY=%BUILD_PYTHON%"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo [FEHLER] Python wurde nicht gefunden. Bitte Python 3.9 oder neuer installieren.
    goto :fail
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Erzeuge virtuelle Umgebung .venv ...
    %PY% -m venv .venv || goto :fail
) else (
    echo [1/6] Virtuelle Umgebung .venv vorhanden.
)
set "VPY=.venv\Scripts\python.exe"

echo [2/6] Installiere Abhaengigkeiten aus requirements.txt ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt || goto :fail

rem ------------------------------------------------------------------ 2. Icon
if not exist "app.ico" (
    echo [3/6] Erzeuge Programm-Icon app.ico ...
    "%VPY%" tools\make_icon.py || goto :fail
) else (
    echo [3/6] Vorhandene app.ico wird verwendet.
)

rem ------------------------------------------------------------------ 2b. Chart.js fuer den Webserver
rem  Der Webserver liefert Chart.js lokal aus (funktioniert dann auch ohne Internet auf dem Tablet).
if not exist "web_static\chart.umd.js" (
    echo [3/6] Lade Chart.js nach web_static ...
    if not exist "web_static" mkdir "web_static"
    powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri 'https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.js' -OutFile 'web_static\chart.umd.js' } catch { exit 1 }"
    if errorlevel 1 (
        if exist "web_static\chart.umd.js" del "web_static\chart.umd.js"
        echo [HINWEIS] Chart.js konnte nicht geladen werden. Der Webserver laedt es dann vom CDN, was Internet auf dem Anzeigegeraet braucht.
        echo           Alternativ die Datei chart.umd.js von chartjs.org manuell nach web_static kopieren.
    )
)
rem ------------------------------------------------------------------ 2c. libplctag (plctag.dll)
rem  Die DLL steckt im Paket libplctag_<Version>_windows_x64.zip des offiziellen Releases; nur sie wird entnommen.
if not exist "plctag.dll" (
    echo [3/6] Lade plctag.dll aus libplctag %PLCTAG_VER% ...
    powershell -NoProfile -Command "try { $z = Join-Path $env:TEMP 'libplctag_win64.zip'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/libplctag/libplctag/releases/download/v%PLCTAG_VER%/libplctag_%PLCTAG_VER%_windows_x64.zip' -OutFile $z; Add-Type -AssemblyName System.IO.Compression.FileSystem; $a = [IO.Compression.ZipFile]::OpenRead($z); $e = $a.Entries | Where-Object { $_.Name -eq 'plctag.dll' } | Select-Object -First 1; [IO.Compression.ZipFileExtensions]::ExtractToFile($e, (Join-Path (Get-Location) 'plctag.dll'), $true); $a.Dispose(); Remove-Item $z } catch { exit 1 }"
    if errorlevel 1 (
        echo [FEHLER] plctag.dll konnte nicht geladen werden. Bitte von https://github.com/libplctag/libplctag/releases
        echo          das Paket libplctag_%PLCTAG_VER%_windows_x64.zip laden und plctag.dll neben build.bat legen.
        goto :fail
    )
)
set ADDDLL=--add-binary "plctag.dll;."
set "ADDWEB="
if exist "web_static\chart.umd.js" set ADDWEB=--add-data "web_static;web_static"

rem ------------------------------------------------------------------ 3. PyInstaller
rem  --windowed        keine Konsole
rem  --collect-submodules plc_treiber  alle Treiber; --collect-all snap7/pycomm3/s7commplus/asyncua/pymodbus/serial  deren Bibliotheken;
rem  --add-binary plctag.dll  libplctag (Logix); --collect-data pyqtgraph
rem  --hidden-import pymysql/psycopg, --collect-all psycopg_binary  Datenbanktreiber (MariaDB, PostgreSQL/TimescaleDB)
rem  --hidden-import PySide6.QtSvg  fuer den SVG-Export und SVG-Logos (wird erst zur Laufzeit importiert)
rem  --exclude-module PyQt6/PyQt5  falls in der Umgebung noch PyQt installiert ist: nur PySide6 einpacken (LGPL)
rem  --hidden-import plc_*  Module, die plc_logger.py erst zur Laufzeit je nach Betriebsart importiert
rem  --collect-all flask/werkzeug  Webserver (Flask) samt Zusatzdateien; --add-data web_static  Chart.js
rem  --hidden-import cryptography.*  selbstsigniertes HTTPS-Zertifikat des Webservers (wird erst bei Bedarf importiert)
echo [4/6] PyInstaller: PLCLogger ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name PLCLogger --icon app.ico ^
    --distpath build\p1 --workpath build\w1 --paths src ^
    --collect-submodules plc_treiber --add-data "src\plc_treiber\_vorlage.py;plc_treiber" --collect-all snap7 --collect-all pycomm3 --collect-all s7commplus --collect-all asyncua --collect-all pymodbus --collect-all serial --collect-data pyqtgraph --hidden-import PySide6.QtSvg --exclude-module PyQt6 --exclude-module PyQt5 ^
    --hidden-import plc_db --hidden-import plc_db_dialog --hidden-import plc_events --hidden-import plc_event_viewer --hidden-import plc_trigger_dialog --hidden-import plc_pid --hidden-import plc_pid_dialog --hidden-import plc_i18n --hidden-import plc_splash --hidden-import plc_about --hidden-import plc_export --collect-all openpyxl --hidden-import plc_block_dialog --add-data "sprachen;sprachen" --add-data "app.ico;." --add-data "logo.png;." --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary %ADDDLL% ^
    --hidden-import plc_gui --hidden-import plc_headless --hidden-import plc_recorder ^
    --hidden-import plc_web --hidden-import plc_svg --hidden-import plc_util --hidden-import plc_webauth ^
    --hidden-import plc_report --hidden-import plc_csvjoin --hidden-import plc_analysis --hidden-import plc_analysis_dialog --hidden-import plc_iocheck --hidden-import plc_iocheck_dialog --hidden-import plc_iocheck_web --hidden-import plc_qr --hidden-import plc_notify --hidden-import plc_notify_dialog --hidden-import plc_opcua_server --hidden-import plc_opcua_dialog --hidden-import plc_web_prozess ^
    --hidden-import cryptography.x509 --hidden-import cryptography.hazmat.primitives.asymmetric.rsa ^
    --collect-all flask --collect-all werkzeug %ADDWEB% ^
    src\plc_logger.py || goto :fail

echo [5/6] PyInstaller: PLCKonfiguration ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name PLCKonfiguration --icon app.ico ^
    --distpath build\p2 --workpath build\w2 --paths src ^
    --collect-submodules plc_treiber --add-data "src\plc_treiber\_vorlage.py;plc_treiber" --collect-all snap7 --collect-all pycomm3 --collect-all s7commplus --collect-all asyncua --collect-all pymodbus --collect-all serial --collect-data pyqtgraph --hidden-import PySide6.QtSvg --exclude-module PyQt6 --exclude-module PyQt5 ^
    --hidden-import plc_db --hidden-import plc_db_dialog --hidden-import plc_events --hidden-import plc_event_viewer --hidden-import plc_trigger_dialog --hidden-import plc_pid --hidden-import plc_pid_dialog --hidden-import plc_i18n --hidden-import plc_splash --hidden-import plc_about --hidden-import plc_export --collect-all openpyxl --hidden-import plc_block_dialog --add-data "sprachen;sprachen" --add-data "app.ico;." --add-data "logo.png;." --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary %ADDDLL% ^
    --hidden-import plc_webauth --hidden-import plc_web_dialog --hidden-import plc_report ^
    src\plc_config.py || goto :fail

echo [5/6] PyInstaller: PLCIOCheck ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name PLCIOCheck --icon app.ico ^
    --distpath build\p3 --workpath build\w3 --paths src ^
    --collect-submodules plc_treiber --collect-all snap7 --collect-all pycomm3 --collect-all s7commplus --collect-all asyncua --collect-all pymodbus --collect-all serial --hidden-import PySide6.QtSvg --exclude-module PyQt6 --exclude-module PyQt5 ^
    --hidden-import plc_i18n --hidden-import plc_splash --hidden-import plc_about --hidden-import plc_export --collect-all openpyxl --add-data "sprachen;sprachen" --add-data "app.ico;." --add-data "logo.png;." %ADDDLL% ^
    --hidden-import plc_iocheck --hidden-import plc_iocheck_dialog --hidden-import plc_iocheck_web --hidden-import plc_qr --hidden-import plc_report ^
    --hidden-import plc_web --hidden-import plc_webauth --hidden-import plc_util ^
    --hidden-import cryptography.x509 --hidden-import cryptography.hazmat.primitives.asymmetric.rsa ^
    --collect-all flask --collect-all werkzeug ^
    src\plc_iocheck_start.py || goto :fail

rem  Beide Programme in einen Ordner zusammenfuehren: erst der Logger komplett, dann nur die
rem  Dateien der Konfiguration, die dort noch fehlen (/XC /XN /XO = vorhandene nicht ueberschreiben).
rem  robocopy meldet mit Rueckgabewerten 0-7 Erfolg.
if exist "dist\PLCDatenlogger" rmdir /s /q "dist\PLCDatenlogger"
robocopy "build\p1\PLCLogger" "dist\PLCDatenlogger" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
robocopy "build\p2\PLCKonfiguration" "dist\PLCDatenlogger" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
robocopy "build\p3\PLCIOCheck" "dist\PLCDatenlogger" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
if not exist "dist\PLCDatenlogger\PLCLogger.exe" goto :fail
if not exist "dist\PLCDatenlogger\PLCKonfiguration.exe" goto :fail
if not exist "dist\PLCDatenlogger\PLCIOCheck.exe" goto :fail
rem  Lizenz (LGPL-3.0-or-later) und Lizenztexte in den Programmordner (gelangen so in Installer und portables ZIP)
for %%F in (LICENSE COPYING THIRD_PARTY_LICENSES.md) do if exist "%%F" copy /y "%%F" "dist\PLCDatenlogger\" >nul
rem  SPS-Vorlagen fuer Ringpuffer (Blockeditor: Knopf "SPS-Vorlagen ...") in den Programmordner
robocopy "vorlagen" "dist\PLCDatenlogger\vorlagen" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail

rem  Bedienungsanleitung (deutsch) und User Manual (englisch) als HTML erzeugen (optional, nur wenn docutils vorhanden ist)
for %%D in (bedienungsanleitung user_manual) do (
  "%VPY%" -c "import docutils.core as d; d.publish_file(source_path='doc/%%D.rst', destination_path='doc/%%D.html', writer_name='html5', settings_overrides={'input_encoding':'utf-8','output_encoding':'utf-8','syntax_highlight':'none'})" >nul 2>nul
  if errorlevel 1 echo [HINWEIS] doc\%%D.html konnte nicht erzeugt werden ^(der Installer enthaelt dann die .rst^).
)

rem  Bedienungsanleitung als PDF (Sphinx + rinohtype, ohne LaTeX; optional: fehlt es, bleibt es bei HTML bzw. .rst)
rem  Feste Namen build\doc\Bedienungsanleitung.pdf und build\doc\User_Manual.pdf fuer installer.iss und das portable ZIP.
set "DOCPDF=build\doc\Bedienungsanleitung.pdf"
set "DOCPDF_EN=build\doc\User_Manual.pdf"
if exist "%DOCPDF%" del "%DOCPDF%"
if exist "%DOCPDF_EN%" del "%DOCPDF_EN%"
echo [5/6] Bedienungsanleitung als PDF ...
if not exist "build\doc" mkdir "build\doc"
"%VPY%" -m pip install -q -r doc\requirements.txt
rem  Meldungen in build\doc\pdf_de.log bzw. pdf_en.log; bei einem Fehler werden die letzten Zeilen angezeigt.
"%VPY%" tools\build_doc.py --copy-to "%DOCPDF%" > "build\doc\pdf_de.log" 2>&1
if not exist "%DOCPDF%" (
    echo [HINWEIS] Das PDF der Anleitung konnte nicht erzeugt werden. Letzte Meldungen ^(vollstaendig: build\doc\pdf_de.log^):
    powershell -NoProfile -Command "Get-Content -Encoding UTF8 'build\doc\pdf_de.log' -Tail 12"
)
"%VPY%" tools\build_doc.py --lang en --copy-to "%DOCPDF_EN%" > "build\doc\pdf_en.log" 2>&1
if not exist "%DOCPDF_EN%" (
    echo [HINWEIS] Das englische PDF konnte nicht erzeugt werden. Letzte Meldungen ^(vollstaendig: build\doc\pdf_en.log^):
    powershell -NoProfile -Command "Get-Content -Encoding UTF8 'build\doc\pdf_en.log' -Tail 12"
)
rem  Kopien mit Versionsnummer in dist\ (zum Weitergeben, Anhang des GitHub-Release)
if not exist "dist" mkdir "dist"
if exist "%DOCPDF%" copy /y "%DOCPDF%" "dist\PLC_Datenlogger_Bedienungsanleitung_%VERSION%.pdf" >nul
if exist "%DOCPDF_EN%" copy /y "%DOCPDF_EN%" "dist\PLC_Datenlogger_User_Manual_%VERSION%.pdf" >nul

echo.
echo [OK] Programme erzeugt: dist\PLCDatenlogger\PLCLogger.exe, PLCKonfiguration.exe und PLCIOCheck.exe
if /I "%STEP%"=="exe" goto :done

rem ------------------------------------------------------------------ 3b. Portables ZIP
call :makezip || goto :fail
if /I "%STEP%"=="portable" goto :done

rem ------------------------------------------------------------------ 4. Inno Setup
:installer
echo [6/6] Inno Setup: Installer erzeugen ...
if not exist "dist\PLCDatenlogger\PLCLogger.exe" (
    echo [FEHLER] dist\PLCDatenlogger fehlt. Zuerst "build.bat exe" ausfuehren.
    goto :fail
)
rem  Inno Setup 7 oder 6 (neuere Version zuerst), fuer alle Benutzer oder nur fuer den eigenen Benutzer installiert
set "ISCC="
for %%V in (7 6) do (
    if not defined ISCC if exist "%ProgramFiles%\Inno Setup %%V\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup %%V\ISCC.exe"
    if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup %%V\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup %%V\ISCC.exe"
    if not defined ISCC if exist "%LocalAppData%\Programs\Inno Setup %%V\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup %%V\ISCC.exe"
)
if not defined ISCC where ISCC >nul 2>nul && set "ISCC=ISCC"
if not defined ISCC (
    echo [HINWEIS] Inno Setup 7 bzw. 6 wurde nicht gefunden - Installer wird nicht erzeugt.
    echo           Installation: https://jrsoftware.org/isinfo.php   danach "build.bat installer"
    goto :done
)
"%ISCC%" /Qp /DAppVersion=%VERSION% installer.iss || goto :fail
echo.
echo [OK] Installer erzeugt: installer\PLCDatenlogger_Setup_%VERSION%.exe

:done
echo.
echo Fertig.
if not defined NOPAUSE pause
endlocal
exit /b 0

:makezip
rem  Portable Fassung: Kopie des Programmordners mit portable.txt (Konfiguration, CSV-Dateien und Archiv liegen
rem  dann neben den .exe-Dateien statt unter %APPDATA%) und der Anleitung, gepackt als ZIP. Die Kopie ist noetig,
rem  weil portable.txt NICHT in den Installer gelangen darf (sonst schriebe die installierte Version in den
rem  schreibgeschuetzten Programmordner).
echo [5b] Portables ZIP erzeugen ...
set "PDIR=dist\portable\PLCDatenlogger"
if exist "dist\portable" rmdir /s /q "dist\portable"
robocopy "dist\PLCDatenlogger" "%PDIR%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
> "%PDIR%\portable.txt" echo Portabler Betrieb: Konfiguration, CSV-Dateien und Archiv liegen in diesem Ordner.
rem  Sprachdateien zum Bearbeiten und Ergaenzen (eigene Uebersetzung: de.txt kopieren, z. B. als fr.txt)
robocopy "sprachen" "%PDIR%\sprachen" /E /NFL /NDL /NJH /NJS /NP >nul
if not exist "%PDIR%\Doku" mkdir "%PDIR%\Doku"
for %%D in (bedienungsanleitung user_manual) do (
  if exist "doc\%%D.html" copy /y "doc\%%D.html" "%PDIR%\Doku\" >nul
  if not exist "doc\%%D.html" copy /y "doc\%%D.rst" "%PDIR%\Doku\" >nul
)
if exist "build\doc\Bedienungsanleitung.pdf" copy /y "build\doc\Bedienungsanleitung.pdf" "%PDIR%\Doku\" >nul
if exist "build\doc\User_Manual.pdf" copy /y "build\doc\User_Manual.pdf" "%PDIR%\Doku\" >nul
if exist "doc\images" robocopy "doc\images" "%PDIR%\Doku\images" /E /NFL /NDL /NJH /NJS /NP >nul
set "ZIP=dist\PLCDatenlogger_portable_%VERSION%.zip"
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\portable\PLCDatenlogger' -DestinationPath '%ZIP%'"
if not exist "%ZIP%" exit /b 1
echo [OK] Portables Paket: %ZIP%  (entpacken und PLCLogger.exe bzw. PLCKonfiguration.exe starten)
exit /b 0

:fail
echo.
echo [FEHLER] Der Build wurde abgebrochen (siehe Meldungen oben).
if not defined NOPAUSE pause
endlocal
exit /b 1
