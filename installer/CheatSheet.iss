; Cheat Sheet — Windows installer (Inno Setup 6)
; Build:  iscc installer\CheatSheet.iss        (after building dist\CheatSheet.exe)
; CI passes the version with /DAppVersion=x.y.z

#define AppName "Cheat Sheet"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppExe "CheatSheet.exe"

[Setup]
AppId={{8F3C2B1E-6A4D-4E8B-9C2F-1D7A5B3E9F01}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Cheat Sheet
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=CheatSheet-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern
WizardImageFile=..\assets\installer\wizard.bmp,..\assets\installer\wizard-2x.bmp
WizardSmallImageFile=..\assets\installer\wizard-small.bmp,..\assets\installer\wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Cheat Sheet with Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: startup

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; Your games and settings live in %APPDATA%\Cheat Sheet and are kept on uninstall.
