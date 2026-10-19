; ============================================================
;  Law Firm Case Management — Host Installer
;  Build with Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;
;  Before compiling:
;    1. Run installer\build-exe.bat to produce dist\LawFirmServer\
;    2. Open this file in Inno Setup and press Compile (Ctrl+F9)
;  Output: installer\output\LawFirmHostSetup.exe
; ============================================================

#define MyAppName "Law Firm Case Management"
#define MyAppVersion "1.0"
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
; NOTE: the instance\ folder (database + keys) is created on first run
; and lives under the install dir. Back it up per MAINTENANCE.md.

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

{ Warn on uninstall that the database will be removed unless backed up. }
function InitializeUninstall(): Boolean;
begin
  Result := MsgBox('Uninstalling will remove the program files.' + #13#10 +
    'Your case database is in the install folder under instance\.' + #13#10 +
    'Make sure you have a backup before continuing. See MAINTENANCE.md.',
    mbConfirmation, MB_OKCANCEL) = IDOK;
end;
