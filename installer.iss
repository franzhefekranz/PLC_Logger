; ===========================================================================================
;  Inno-Setup-Skript fuer S7 Datenlogger (Inno Setup 6)
;
;  Packt den von build.bat erzeugten Ordner dist\S7Datenlogger (S7Logger.exe und
;  S7Konfiguration.exe samt Bibliotheken) in eine Setup-Datei. Aufruf normalerweise ueber
;  build.bat; manuell:  ISCC.exe /DAppVersion=1.0.0 installer.iss
;  Das Ergebnis liegt in installer\S7Datenlogger_Setup_<Version>.exe
; ===========================================================================================

#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#define AppName    "S7 Datenlogger"
#define AppFolder  "S7Datenlogger"
#define AppExe     "S7Logger.exe"
#define ConfigExe  "S7Konfiguration.exe"

; Anleitung: HTML, falls von build.bat erzeugt, sonst die .rst-Datei
#if FileExists("bedienungsanleitung.html")
  #define DocFile "bedienungsanleitung.html"
#else
  #define DocFile "bedienungsanleitung.rst"
#endif

[Setup]
; Eindeutige Kennung der Anwendung (Updates erkennen die bestehende Installation daran).
; Die doppelte geschweifte Klammer am Anfang ist die Inno-Schreibweise.
AppId={{029DCDCB-2509-4A24-A1C8-B3A300D8D72F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppFolder}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=app.ico
OutputDir=installer
OutputBaseFilename=S7Datenlogger_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 64-Bit-Installation (PyQt6 gibt es nur fuer 64 Bit)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Standard: Installation fuer alle Benutzer (Administrator); im Dialog auch "nur fuer mich" waehlbar
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "desktopicon_cfg"; Description: "Desktop-Symbol fuer die Konfiguration"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Beide Programme mit allen Bibliotheken (Ergebnis von build.bat)
Source: "dist\{#AppFolder}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Dokumentation
Source: "{#DocFile}"; DestDir: "{app}\Doku"; Flags: ignoreversion
; Bilder der Anleitung (Ordner images neben der Anleitung; fehlt er, wird er übersprungen)
Source: "images\*"; DestDir: "{app}\Doku\images"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\S7 Datenlogger"; Filename: "{app}\{#AppExe}"
Name: "{group}\S7 Konfiguration"; Filename: "{app}\{#ConfigExe}"
Name: "{group}\S7 Datenlogger (Headless, nur Aufzeichnung)"; Filename: "{app}\{#AppExe}"; Parameters: "--headless"
Name: "{group}\S7 Ereignisprotokoll"; Filename: "{app}\{#AppExe}"; Parameters: "--ereignisse"
Name: "{group}\Bedienungsanleitung"; Filename: "{app}\Doku\{#DocFile}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\S7 Datenlogger"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autodesktop}\S7 Konfiguration"; Filename: "{app}\{#ConfigExe}"; Tasks: desktopicon_cfg

[Run]
; Nach der Installation optional die Konfiguration oder den Logger starten
Filename: "{app}\{#ConfigExe}"; Description: "S7 Konfiguration jetzt starten"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Hinweis: Der Logger kann mit einer beliebigen Konfigurationsdatei gestartet werden (S7Logger.exe Datei.json),
; auch ohne Oberflaeche (Parameter --headless). Chart.js fuer den Webserver steckt im Programmordner.
; Konfiguration (s7_config.json), CSV-Dateien und Archiv liegen NICHT im Programmordner,
; sondern unter %APPDATA%\S7Datenlogger. Sie bleiben deshalb beim Deinstallieren und bei
; Updates erhalten. (Portabler Betrieb: Datei portable.txt neben die .exe legen.)
