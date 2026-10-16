; ===========================================================================================
;  Inno-Setup-Skript fuer TIA Datenlogger (Inno Setup 6)
;
;  Packt den von build.bat erzeugten Ordner dist\TIADatenlogger (TIALogger.exe und
;  TIAKonfiguration.exe samt Bibliotheken) in eine Setup-Datei. Aufruf normalerweise ueber
;  build.bat; manuell:  ISCC.exe /DAppVersion=1.0.0 installer.iss
;  Das Ergebnis liegt in installer\TIADatenlogger_Setup_<Version>.exe
; ===========================================================================================

#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#define AppName    "TIA Datenlogger"
#define AppFolder  "TIADatenlogger"
#define AppExe     "TIALogger.exe"
#define ConfigExe  "TIAKonfiguration.exe"

; Anleitung: HTML, falls von build.bat erzeugt, sonst die .rst-Datei
#if FileExists("bedienungsanleitung.html")
  #define DocFile "bedienungsanleitung.html"
#else
  #define DocFile "bedienungsanleitung.rst"
#endif

[Setup]
; Eindeutige Kennung der Anwendung (Updates erkennen die bestehende Installation daran).
; Die doppelte geschweifte Klammer am Anfang ist die Inno-Schreibweise.
AppId={{52B5979F-8623-4DED-B55E-34EDF44852D8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppFolder}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=app.ico
OutputDir=installer
OutputBaseFilename=TIADatenlogger_Setup_{#AppVersion}
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
Name: "{group}\TIA Datenlogger"; Filename: "{app}\{#AppExe}"
Name: "{group}\TIA Konfiguration"; Filename: "{app}\{#ConfigExe}"
Name: "{group}\TIA Datenlogger (Headless, nur Aufzeichnung)"; Filename: "{app}\{#AppExe}"; Parameters: "--headless"
Name: "{group}\TIA Ereignisprotokoll"; Filename: "{app}\{#AppExe}"; Parameters: "--ereignisse"
Name: "{group}\Bedienungsanleitung"; Filename: "{app}\Doku\{#DocFile}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\TIA Datenlogger"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autodesktop}\TIA Konfiguration"; Filename: "{app}\{#ConfigExe}"; Tasks: desktopicon_cfg

[Run]
; Nach der Installation optional die Konfiguration oder den Logger starten
Filename: "{app}\{#ConfigExe}"; Description: "TIA Konfiguration jetzt starten"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Hinweis: Der Logger kann mit einer beliebigen Konfigurationsdatei gestartet werden (TIALogger.exe Datei.ini),
; auch ohne Oberflaeche (Parameter --headless). Chart.js fuer den Webserver steckt im Programmordner.
; Konfiguration (tia_config.ini), CSV-Dateien und Archiv liegen NICHT im Programmordner,
; sondern unter %APPDATA%\TIADatenlogger. Sie bleiben deshalb beim Deinstallieren und bei
; Updates erhalten. (Portabler Betrieb: Datei portable.txt neben die .exe legen.)
