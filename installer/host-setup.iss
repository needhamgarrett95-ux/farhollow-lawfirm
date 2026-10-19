; ============================================================
;  Law Firm Case Management — Host Installer
;  Build with Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;
;  Before compiling:
;    1. Run installer\build-exe.bat to produce dist\LawFirmServer\
;    2. Open this file in Inno Setup and press Compile (Ctrl+F9)
;  Output: installer\output\LawFirmHostSetup.exe
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0"
#endif
#define MyAppName "Law Firm Case Management"
#define MyAppPublisher "Farhollow"
#define MyAppExeName "LawFirmServer.exe"
#define BuildDir "..\dist\LawFirmServer"

[Setup]
AppId={{A3F2B8C1-7D4E-4A9B-8C1D-2E5F6A7B8C9D}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={pf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=output
OutputBaseFilename=LawFirmHostSetup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
; admin is required for Program Files install + firewall rule

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start the server automatically when Windows starts"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "firewall"; Description: "Allow office computers to connect (open Windows Firewall for port 5000)"; GroupDescription: "Network:"; Flags: checkedonce

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: the packaged files never include instance\ (it is git-ignored and
; created at install/first run). Upgrades only replace files the installer
; owns, so client data is never touched by an update. See [Dirs] below.

[Dirs]
; The instance\ folder holds the database, encryption keys, documents, and
; backups — everything the office cannot afford to lose.
;   - uninsneveruninstall: uninstalling the program NEVER deletes client data.
;     The folder is left behind; remove it by hand only if you mean it.
;   - users-modify: the server must be able to write its database even when
;     it runs as a normal user (e.g. auto-start from the Startup folder),
;     not only as Administrator.
Name: "{app}\instance"; Flags: uninsneveruninstall; Permissions: users-modify

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Maintenance Manual"; Filename: "{app}\MAINTENANCE.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start the server now"; Flags: nowait postinstall skipifsilent

[Code]
{ Open the firewall for port 5000 so office computers can connect.
  Runs only if the user checked the firewall task. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('firewall') then
  begin
    Exec('netsh', 'advfirewall firewall add rule name="Law Firm Server" dir=in action=allow protocol=TCP localport=5000',
         '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    if ResultCode <> 0 then
      MsgBox('Could not add the firewall rule automatically (code ' + IntToStr(ResultCode) + '). ' +
             'Office computers may not be able to connect until you allow port 5000 manually. ' +
             'See MAINTENANCE.md, section "Firewall".', mbInformation, MB_OK);
  end;
end;

{ Warn on uninstall. Client data is protected: the installer never deletes
  instance\ (see [Dirs] uninsneveruninstall), so this is just a reminder. }
function InitializeUninstall(): Boolean;
begin
  Result := MsgBox('Uninstalling will remove the program files.' + #13#10 +
    'Your case database is kept safe in the install folder under instance\ ' +
    '(it is never deleted by the installer).' + #13#10 +
    'If you want it gone too, delete that folder by hand afterwards.',
    mbInformation, MB_OKCANCEL) = IDOK;
end;
