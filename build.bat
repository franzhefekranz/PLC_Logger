@echo off
rem ====================================================================================
rem  S7 Datenlogger - Build-Skript
rem
rem  Erzeugt mit PyInstaller die beiden Programme (S7Logger.exe, S7Konfiguration.exe)
rem  in EINEM gemeinsamen Ordner und baut daraus mit Inno Setup die Setup-Datei.
rem  S7Logger.exe laeuft mit Oberflaeche oder (Option "Headless" bzw. Parameter --headless) ohne.
rem  Fuer den Webserver wird Chart.js einmalig nach web_static\chart.umd.js geladen und mit eingepackt.
rem
rem  Aufruf:   build.bat              alles: Umgebung, .exe-Dateien, Installer
rem            build.bat exe          nur die .exe-Dateien (dist\S7Datenlogger)
rem            build.bat portable     .exe-Dateien und portables ZIP (ohne Installer):
rem                                   dist\S7Datenlogger_portable_<Version>.zip - entpacken, .exe starten
rem            build.bat installer    nur den Installer (setzt vorhandenes dist\ voraus)
rem
rem  Voraussetzungen: Python 3.9+ (py-Launcher oder python im PATH), Internetzugang fuer
rem  pip (beim ersten Lauf), Inno Setup 6 (https://jrsoftware.org/isinfo.php) fuer den Installer.
rem  Die Versionsnummer wird unten bei VERSION eingestellt.
rem ====================================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "VERSION=2.1.0"
set "STEP=%~1"
if "%STEP%"=="" set "STEP=all"

echo ================================================================
echo  S7 Datenlogger - Build (%STEP%), Version %VERSION%
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
set "ADDWEB="
if exist "web_static\chart.umd.js" set ADDWEB=--add-data "web_static;web_static"

rem ------------------------------------------------------------------ 3. PyInstaller
rem  --windowed        keine Konsole
rem  --collect-all snap7  nimmt die snap7.dll mit; --collect-data pyqtgraph: Zusatzdateien
rem  --hidden-import pymysql/psycopg, --collect-all psycopg_binary  Datenbanktreiber (MariaDB, PostgreSQL/TimescaleDB)
rem  --hidden-import PyQt6.QtSvg  fuer den SVG-Export und SVG-Logos (wird erst zur Laufzeit importiert)
rem  --hidden-import s7_*  Module, die s7_logger.py erst zur Laufzeit je nach Betriebsart importiert
rem  --collect-all flask/werkzeug  Webserver (Flask) samt Zusatzdateien; --add-data web_static  Chart.js
echo [4/6] PyInstaller: S7Logger ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name S7Logger --icon app.ico ^
    --distpath build\p1 --workpath build\w1 ^
    --collect-all snap7 --collect-data pyqtgraph --hidden-import PyQt6.QtSvg ^
    --hidden-import s7_db --hidden-import s7_db_dialog --hidden-import s7_events --hidden-import s7_event_viewer --hidden-import s7_trigger_dialog --hidden-import s7_pid --hidden-import s7_pid_dialog --hidden-import s7_i18n --hidden-import s7_splash --add-data "sprachen;sprachen" --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary ^
    --hidden-import s7_gui --hidden-import s7_headless --hidden-import s7_recorder ^
    --hidden-import s7_web --hidden-import s7_svg --hidden-import s7_util ^
    --collect-all flask --collect-all werkzeug %ADDWEB% ^
    s7_logger.py || goto :fail

echo [5/6] PyInstaller: S7Konfiguration ...
"%VPY%" -m PyInstaller --noconfirm --clean --windowed --onedir --name S7Konfiguration --icon app.ico ^
    --distpath build\p2 --workpath build\w2 ^
    --collect-all snap7 --collect-data pyqtgraph --hidden-import PyQt6.QtSvg ^
    --hidden-import s7_db --hidden-import s7_db_dialog --hidden-import s7_events --hidden-import s7_event_viewer --hidden-import s7_trigger_dialog --hidden-import s7_pid --hidden-import s7_pid_dialog --hidden-import s7_i18n --hidden-import s7_splash --add-data "sprachen;sprachen" --hidden-import pymysql --hidden-import psycopg --collect-all psycopg_binary ^
    s7_config.py || goto :fail

rem  Beide Programme in einen Ordner zusammenfuehren: erst der Logger komplett, dann nur die
rem  Dateien der Konfiguration, die dort noch fehlen (/XC /XN /XO = vorhandene nicht ueberschreiben).
rem  robocopy meldet mit Rueckgabewerten 0-7 Erfolg.
if exist "dist\S7Datenlogger" rmdir /s /q "dist\S7Datenlogger"
robocopy "build\p1\S7Logger" "dist\S7Datenlogger" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
robocopy "build\p2\S7Konfiguration" "dist\S7Datenlogger" /E /XC /XN /XO /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
if not exist "dist\S7Datenlogger\S7Logger.exe" goto :fail
if not exist "dist\S7Datenlogger\S7Konfiguration.exe" goto :fail

rem  Bedienungsanleitung als HTML erzeugen (optional, nur wenn docutils vorhanden ist)
"%VPY%" -c "import docutils.core as d; d.publish_file(source_path='bedienungsanleitung.rst', destination_path='bedienungsanleitung.html', writer_name='html5', settings_overrides={'input_encoding':'utf-8','output_encoding':'utf-8'})" >nul 2>nul
if errorlevel 1 echo [HINWEIS] bedienungsanleitung.html konnte nicht erzeugt werden (der Installer enthaelt dann die .rst).

echo.
echo [OK] Programme erzeugt: dist\S7Datenlogger\S7Logger.exe und S7Konfiguration.exe
if /I "%STEP%"=="exe" goto :done

rem ------------------------------------------------------------------ 3b. Portables ZIP
call :makezip || goto :fail
if /I "%STEP%"=="portable" goto :done

rem ------------------------------------------------------------------ 4. Inno Setup
:installer
echo [6/6] Inno Setup: Installer erzeugen ...
if not exist "dist\S7Datenlogger\S7Logger.exe" (
    echo [FEHLER] dist\S7Datenlogger fehlt. Zuerst "build.bat exe" ausfuehren.
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
echo [OK] Installer erzeugt: installer\S7Datenlogger_Setup_%VERSION%.exe

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
set "PDIR=dist\portable\S7Datenlogger"
if exist "dist\portable" rmdir /s /q "dist\portable"
robocopy "dist\S7Datenlogger" "%PDIR%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
> "%PDIR%\portable.txt" echo Portabler Betrieb: Konfiguration, CSV-Dateien und Archiv liegen in diesem Ordner.
rem  Sprachdateien zum Bearbeiten und Ergaenzen (eigene Uebersetzung: de.txt kopieren, z. B. als fr.txt)
robocopy "sprachen" "%PDIR%\sprachen" /E /NFL /NDL /NJH /NJS /NP >nul
if not exist "%PDIR%\Doku" mkdir "%PDIR%\Doku"
if exist "bedienungsanleitung.html" copy /y "bedienungsanleitung.html" "%PDIR%\Doku\" >nul
if not exist "bedienungsanleitung.html" copy /y "bedienungsanleitung.rst" "%PDIR%\Doku\" >nul
if exist "images" robocopy "images" "%PDIR%\Doku\images" /E /NFL /NDL /NJH /NJS /NP >nul
set "ZIP=dist\S7Datenlogger_portable_%VERSION%.zip"
if exist "%ZIP%" del "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\portable\S7Datenlogger' -DestinationPath '%ZIP%'"
if not exist "%ZIP%" exit /b 1
echo [OK] Portables Paket: %ZIP%  (entpacken und S7Logger.exe bzw. S7Konfiguration.exe starten)
exit /b 0

:fail
echo.
echo [FEHLER] Der Build wurde abgebrochen (siehe Meldungen oben).
if not defined NOPAUSE pause
endlocal
exit /b 1
