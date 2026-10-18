; ===========================================================================================
;  Inno-Setup-Skript fuer PLC Datenlogger (Inno Setup 7 oder 6)
;
;  Packt den von build.bat erzeugten Ordner dist\PLCDatenlogger (PLCLogger.exe und
;  PLCKonfiguration.exe samt Bibliotheken) in eine Setup-Datei. Aufruf normalerweise ueber
;  build.bat; manuell:  ISCC.exe /DAppVersion=1.0.0 installer.iss
;  Das Ergebnis liegt in installer\PLCDatenlogger_Setup_<Version>.exe
; ===========================================================================================

#ifndef AppVersion
  #define AppVersion "2.1.0"
#endif
#define AppName    "PLC Datenlogger"
#define AppFolder  "PLCDatenlogger"
#define AppExe     "PLCLogger.exe"
#define ConfigExe  "PLCKonfiguration.exe"

; Anleitung: HTML, falls von build.bat erzeugt, sonst die .rst-Datei
#if FileExists("doc\bedienungsanleitung.html")
  #define DocFile "bedienungsanleitung.html"
#else
  #define DocFile "bedienungsanleitung.rst"
#endif
; zusätzlich das PDF (von build.bat mit tools\build_doc.py erzeugt), falls vorhanden
#if FileExists("build\doc\Bedienungsanleitung.pdf")
  #define DocPdf "Bedienungsanleitung.pdf"
#endif
; Englische Anleitung (User Manual): HTML bzw. .rst und PDF
#if FileExists("doc\user_manual.html")
  #define DocFileEn "user_manual.html"
#else
  #define DocFileEn "user_manual.rst"
#endif
#if FileExists("build\doc\User_Manual.pdf")
  #define DocPdfEn "User_Manual.pdf"
#endif

[Setup]
; Eindeutige Kennung der Anwendung (Updates erkennen die bestehende Installation daran).
; Die doppelte geschweifte Klammer am Anfang ist die Inno-Schreibweise.
AppId={{E0E5B954-B3E7-4699-B8FE-DBD87747E11F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
DefaultDirName={autopf}\{#AppFolder}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
SetupIconFile=app.ico
; Lizenzseite im Setup: GNU LGPL v3 (das Programm steht unter LGPL-3.0-or-later, siehe THIRD_PARTY_LICENSES.md)
LicenseFile=LICENSE
OutputDir=installer
OutputBaseFilename=PLCDatenlogger_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 64-Bit-Installation (PySide6 bzw. Qt 6 gibt es nur fuer 64 Bit)
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
Source: "doc\{#DocFile}"; DestDir: "{app}\Doku"; Flags: ignoreversion
#ifdef DocPdf
Source: "build\doc\{#DocPdf}"; DestDir: "{app}\Doku"; Flags: ignoreversion
#endif
Source: "doc\{#DocFileEn}"; DestDir: "{app}\Doku"; Flags: ignoreversion
#ifdef DocPdfEn
Source: "build\doc\{#DocPdfEn}"; DestDir: "{app}\Doku"; Flags: ignoreversion
#endif
; Bilder der Anleitung (Ordner doc\images; fehlt er, wird er übersprungen)
Source: "doc\images\*"; DestDir: "{app}\Doku\images"; Flags: ignoreversion recursesubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\PLC Datenlogger"; Filename: "{app}\{#AppExe}"
Name: "{group}\PLC Konfiguration"; Filename: "{app}\{#ConfigExe}"
Name: "{group}\PLC Datenlogger (Headless, nur Aufzeichnung)"; Filename: "{app}\{#AppExe}"; Parameters: "--headless"
Name: "{group}\PLC Ereignisprotokoll"; Filename: "{app}\{#AppExe}"; Parameters: "--ereignisse"
Name: "{group}\Bedienungsanleitung"; Filename: "{app}\Doku\{#DocFile}"
#ifdef DocPdf
Name: "{group}\Bedienungsanleitung (PDF)"; Filename: "{app}\Doku\{#DocPdf}"
#endif
Name: "{group}\User Manual (English)"; Filename: "{app}\Doku\{#DocFileEn}"
#ifdef DocPdfEn
Name: "{group}\User Manual (English, PDF)"; Filename: "{app}\Doku\{#DocPdfEn}"
#endif
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PLC Datenlogger"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autodesktop}\PLC Konfiguration"; Filename: "{app}\{#ConfigExe}"; Tasks: desktopicon_cfg

[Run]
; Nach der Installation optional die Konfiguration oder den Logger starten
Filename: "{app}\{#ConfigExe}"; Description: "PLC Konfiguration jetzt starten"; Flags: nowait postinstall skipifsilent unchecked
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Hinweis: Der Logger kann mit einer beliebigen Konfigurationsdatei gestartet werden (PLCLogger.exe Datei.json),
; auch ohne Oberflaeche (Parameter --headless). Chart.js fuer den Webserver steckt im Programmordner.
; Konfiguration (plc_config.json), CSV-Dateien und Archiv liegen NICHT im Programmordner,
; sondern unter %APPDATA%\PLCDatenlogger. Sie bleiben deshalb beim Deinstallieren und bei
; Updates erhalten. (Portabler Betrieb: Datei portable.txt neben die .exe legen.)
