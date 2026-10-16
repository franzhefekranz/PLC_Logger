; ===========================================================================================
;  Inno-Setup-Skript fuer CLX Datenlogger (Inno Setup 6)
;
;  Packt den von build.bat erzeugten Ordner dist\CLXDatenlogger (CLXLogger.exe und
;  CLXKonfiguration.exe samt Bibliotheken) in eine Setup-Datei. Aufruf normalerweise ueber
;  build.bat; manuell:  ISCC.exe /DAppVersion=1.0.0 installer.iss
;  Das Ergebnis liegt in installer\CLXDatenlogger_Setup_<Version>.exe
; ===========================================================================================

#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#define AppName    "CLX Datenlogger"
#define AppFolder  "CLXDatenlogger"
#define AppExe     "CLXLogger.exe"
#define ConfigExe  "CLXKonfiguration.exe"

; Anleitung: HTML, falls von build.bat erzeugt, sonst die .rst-Datei
#if FileExists("bedienungsanleitung.html")
  #define DocFile "bedienungsanleitung.html"
#else
  #define DocFile "bedienungsanleitung.rst"
#endif

[Setup]
; Eindeutige Kennung der Anwendung (Updates erkennen die bestehende Installation daran).
; Die doppelte geschweifte Klammer am Anfang ist die Inno-Schreibweise.
AppId={{567D4907-45D9-420A-BBFC-759205D5158E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppFolder}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=app.ico
OutputDir=installer
OutputBaseFilename=CLXDatenlogger_Setup_{#AppVersion}
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
Name: "{group}\CLX Datenlogger"; Filename: "{app}\{#AppExe}"
Name: "{group}\CLX Konfiguration"; Filename: "{app}\{#ConfigExe}"
Name: "{group}\CLX Datenlogger (Headless, nur Aufzeichnung)"; Filename: "{app}\{#AppExe}"; Parameters: "--headless"
Name: "{group}\CLX Ereignisprotokoll"; Filename: "{app}\{#AppExe}"; Parameters: "--ereignisse"
Name: "{group}\Bedienungsanleitung"; Filename: "{app}\Doku\{#DocFile}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CLX Datenlogger"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autodesktop}\CLX Konfiguration"; Filename: "{app}\{#ConfigExe}"; Tasks: desktopicon_cfg

[Run]
; Nach der Installation optional die Konfiguration oder den Logger starten
Filename: "{app}\{#ConfigExe}"; Description: "CLX Konfiguration jetzt starten"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Hinweis: Der Logger kann mit einer beliebigen Konfigurationsdatei gestartet werden (CLXLogger.exe Datei.json),
; auch ohne Oberflaeche (Parameter --headless). Chart.js fuer den Webserver steckt im Programmordner.
; Konfiguration (clx_config.json), CSV-Dateien und Archiv liegen NICHT im Programmordner,
; sondern unter %APPDATA%\CLXDatenlogger. Sie bleiben deshalb beim Deinstallieren und bei
; Updates erhalten. (Portabler Betrieb: Datei portable.txt neben die .exe legen.)
