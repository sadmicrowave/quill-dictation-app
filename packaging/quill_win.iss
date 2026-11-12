; Quill's Windows installer (Inno Setup 6.3 or newer).
;
;   pyinstaller --noconfirm packaging\quill_win.spec                  (makes dist\Quill\)
;   ISCC /DAppVersion=0.1.0 packaging\quill_win.iss                   (makes dist\installer\Quill-Setup.exe)
;
; Installs for the current user only (no administrator rights): %LOCALAPPDATA%\Programs\Quill, a Start menu entry, an entry in
; Settings > Apps, and an uninstaller. Running it again over an older Quill replaces it in place (the same AppId), closing a running
; Quill first. The user's settings and speech model live in their own data folder and are left alone by an uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{33741EDA-7E33-45C3-8003-3839F089C0DE}
AppName=Quill
AppVersion={#AppVersion}
AppVerName=Quill {#AppVersion}
AppPublisher=Corey Farmer
AppPublisherURL=https://github.com/sadmicrowave/quill-dictation-app
AppSupportURL=https://github.com/sadmicrowave/quill-dictation-app/issues
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Quill
DisableProgramGroupPage=yes
DisableDirPage=auto
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=Quill-Setup
SetupIconFile=..\quill\assets\Quill.ico
UninstallDisplayIcon={app}\Quill.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Quill shortcut on the desktop"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Quill\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Quill"; Filename: "{app}\Quill.exe"
Name: "{autodesktop}\Quill"; Filename: "{app}\Quill.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Quill.exe"; Description: "Start Quill"; Flags: nowait postinstall skipifsilent
