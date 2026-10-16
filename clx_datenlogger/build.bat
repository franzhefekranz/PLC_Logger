@echo off
rem ====================================================================================
rem  CLX Datenlogger - Build-Skript
rem
rem  Erzeugt mit PyInstaller die beiden Programme (CLXLogger.exe, CLXKonfiguration.exe)
rem  in EINEM gemeinsamen Ordner und baut daraus mit Inno Setup die Setup-Datei.
rem  CLXLogger.exe laeuft mit Oberflaeche oder (Option "Headless" bzw. Parameter --headless) ohne.
rem  Fuer den Webserver wird Chart.js einmalig nach web_static\chart.umd.js geladen und mit eingepackt.
rem
rem  Aufruf:   build.bat              alles: Umgebung, .exe-Dateien, Installer
rem            build.bat exe          nur die .exe-Dateien (dist\CLXDatenlogger)
rem            build.bat portable     .exe-Dateien und portables ZIP (ohne Installer):
rem                                   dist\CLXDatenlogger_portable_<Version>.zip - entpacken, .exe starten
rem            build.bat installer    nur den Installer (setzt vorhandenes dist\ voraus)
rem
rem  libplctag gibt es nicht als pip-Paket: plctag.dll (64 Bit) wird einmalig aus dem offiziellen GitHub-Release
rem  geladen (oder liegt bereits neben diesem Skript) und in die Programme eingepackt.
rem  Voraussetzungen: Python 3.9+ (py-Launcher oder python im PATH), Internetzugang fuer
rem  pip (beim ersten Lauf), Inno Setup 6 (https://jrsoftware.org/isinfo.php) fuer den Installer.
rem  Die Versionsnummer wird unten bei VERSION eingestellt.
rem ====================================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "VERSION=2.1.0"
rem  Version der libplctag-Bibliothek (GitHub-Release), aus der plctag.dll geladen wird.
set "PLCTAG_VER=2.7.2"
set "STEP=%~1"
if "%STEP%"=="" set "STEP=all"

echo ================================================================
echo  CLX Datenlogger - Build (%STEP%), Version %VERSION%
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
    "%VPY%" make_icon.py || goto :fail
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
rem  --add-binary plctag.dll  libplctag (Lesen); --collect-all pycomm3: Tag-Liste; --collect-data pyqtgraph
rem  --hidden-import pymysql/psycopg, --collect-all psycopg_binary  Datenbanktreiber (MariaDB, PostgreSQL/TimescaleDB)
rem  --hidden-import PyQt6.QtSvg  fuer den SVG-Export und SVG-Logos (wird erst zur Laufzeit importiert)
rem  --hidden-import clx_*  Module, die clx_logger.py erst zur Laufzeit je nach Betriebsart importiert
rem  --collect-all flask/werkzeug  Webserver (Flask) samt Zusatzdateien; --add-data web_static  Chart.js
echo [4/6] PyInstaller: CLXLogger ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name CLXLogger --icon app.ico ^
    --distpath build\p1 --workpath build\w1 ^
    --collect-all pycomm3 --collect-data pyqtgraph --hidden-import PyQt6.QtSvg ^
    --hidden-import clx_db --hidden-import clx_db_dialog --hidden-import clx_events --hidden-import clx_event_viewer --hidden-import clx_trigger_dialog --hidden-import clx_pid --hidden-import clx_pid_dialog --hidden-import clx_i18n --hidden-import clx_splash --add-data "sprachen;sprachen" --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary %ADDDLL% ^
    --hidden-import clx_gui --hidden-import clx_headless --hidden-import clx_recorder ^
    --hidden-import clx_web --hidden-import clx_svg --hidden-import clx_util --hidden-import clx_io ^
    --collect-all flask --collect-all werkzeug %ADDWEB% ^
    clx_logger.py || goto :fail

echo [5/6] PyInstaller: CLXKonfiguration ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name CLXKonfiguration --icon app.ico ^
    --distpath build\p2 --workpath build\w2 ^
    --collect-all pycomm3 --collect-data pyqtgraph --hidden-import PyQt6.QtSvg ^
    --hidden-import clx_db --hidden-import clx_db_dialog --hidden-import clx_events --hidden-import clx_event_viewer --hidden-import clx_trigger_dialog --hidden-import clx_pid --hidden-import clx_pid_dialog --hidden-import clx_i18n --hidden-import clx_splash --add-data "sprachen;sprachen" --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary %ADDDLL% ^
    clx_config.py || goto :fail

rem  Beide Programme in einen Ordner zusammenfuehren: erst der Logger komplett, dann nur die
rem  Dateien der Konfiguration, die dort noch fehlen (/XC /XN /XO = vorhandene nicht ueberschreiben).
rem  robocopy meldet mit Rueckgabewerten 0-7 Erfolg.
if exist "dist\CLXDatenlogger" rmdir /s /q "dist\CLXDatenlogger"
robocopy "build\p1\CLXLogger" "dist\CLXDatenlogger" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
robocopy "build\p2\CLXKonfiguration" "dist\CLXDatenlogger" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
if not exist "dist\CLXDatenlogger\CLXLogger.exe" goto :fail
if not exist "dist\CLXDatenlogger\CLXKonfiguration.exe" goto :fail

rem  Bedienungsanleitung als HTML erzeugen (optional, nur wenn docutils vorhanden ist)
"%VPY%" -c "import docutils.core as d; d.publish_file(source_path='bedienungsanleitung.rst', destination_path='bedienungsanleitung.html', writer_name='html5', settings_overrides={'input_encoding':'utf-8','output_encoding':'utf-8'})" >nul 2>nul
if errorlevel 1 echo [HINWEIS] bedienungsanleitung.html konnte nicht erzeugt werden (der Installer enthaelt dann die .rst).

echo.
echo [OK] Programme erzeugt: dist\CLXDatenlogger\CLXLogger.exe und CLXKonfiguration.exe
if /I "%STEP%"=="exe" goto :done

rem ------------------------------------------------------------------ 3b. Portables ZIP
call :makezip || goto :fail
if /I "%STEP%"=="portable" goto :done

rem ------------------------------------------------------------------ 4. Inno Setup
:installer
echo [6/6] Inno Setup: Installer erzeugen ...
if not exist "dist\CLXDatenlogger\CLXLogger.exe" (
    echo [FEHLER] dist\CLXDatenlogger fehlt. Zuerst "build.bat exe" ausfuehren.
    goto :fail
)
set "ISCC="
set "P1=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
set "P2=%ProgramFiles%\Inno Setup 6\ISCC.exe"
set "P3=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if exist "%P1%" set "ISCC=%P1%"
if not defined ISCC if exist "%P2%" set "ISCC=%P2%"
if not defined ISCC if exist "%P3%" set "ISCC=%P3%"
if not defined ISCC where ISCC >nul 2>nul && set "ISCC=ISCC"
if not defined ISCC (
    echo [HINWEIS] Inno Setup 6 wurde nicht gefunden - Installer wird nicht erzeugt.
    echo           Installation: https://jrsoftware.org/isinfo.php   danach "build.bat installer"
    goto :done
)
"%ISCC%" /Qp /DAppVersion=%VERSION% installer.iss || goto :fail
echo.
echo [OK] Installer erzeugt: installer\CLXDatenlogger_Setup_%VERSION%.exe

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
set "PDIR=dist\portable\CLXDatenlogger"
if exist "dist\portable" rmdir /s /q "dist\portable"
robocopy "dist\CLXDatenlogger" "%PDIR%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
> "%PDIR%\portable.txt" echo Portabler Betrieb: Konfiguration, CSV-Dateien und Archiv liegen in diesem Ordner.
rem  Sprachdateien zum Bearbeiten und Ergaenzen (eigene Uebersetzung: de.txt kopieren, z. B. als fr.txt)
robocopy "sprachen" "%PDIR%\sprachen" /E /NFL /NDL /NJH /NJS /NP >nul
if not exist "%PDIR%\Doku" mkdir "%PDIR%\Doku"
if exist "bedienungsanleitung.html" copy /y "bedienungsanleitung.html" "%PDIR%\Doku\" >nul
if not exist "bedienungsanleitung.html" copy /y "bedienungsanleitung.rst" "%PDIR%\Doku\" >nul
if exist "images" robocopy "images" "%PDIR%\Doku\images" /E /NFL /NDL /NJH /NJS /NP >nul
set "ZIP=dist\CLXDatenlogger_portable_%VERSION%.zip"
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\portable\CLXDatenlogger' -DestinationPath '%ZIP%'"
if not exist "%ZIP%" exit /b 1
echo [OK] Portables Paket: %ZIP%  (entpacken und CLXLogger.exe bzw. CLXKonfiguration.exe starten)
exit /b 0

:fail
echo.
echo [FEHLER] Der Build wurde abgebrochen (siehe Meldungen oben).
if not defined NOPAUSE pause
endlocal
exit /b 1
