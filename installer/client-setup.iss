; ============================================================
;  Law Firm Case Management — Client Installer (optional polish)
;  Build with Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;
;  The client needs no real software — just a browser shortcut.
;  This installer asks for the host IP and drops a "Law Firm"
;  shortcut on the desktop. For a quicker path, just run
;  client-setup.bat instead.
;
;  Output: installer\output\LawFirmClientSetup.exe
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0"
#endif
#define MyAppName "Law Firm Case Management (Client)"

[Setup]
AppId={{B4C3D9E2-8E5F-4B1C-9D2E-3F6A7B8C9D1E}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={pf}\LawFirmClient
DefaultGroupName=Law Firm
OutputDir=output
OutputBaseFilename=LawFirmClientSetup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
Uninstallable=no
; nothing to uninstall — it only creates a shortcut

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Code]
var
  HostIPPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  HostIPPage := CreateInputQueryPage(wpSelectDir,
    'Host computer address',
    'Where is the Law Firm server running?',
    'Enter the IP address of the office host computer ' +
    '(the one running LawFirmServer). Example: 192.168.1.100');
  HostIPPage.Add('Host IP address:', False);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = HostIPPage.ID then
  begin
    if Trim(HostIPPage.Values[0]) = '' then
    begin
      MsgBox('Please enter the host computer''s IP address.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ Create the desktop shortcut directly — no files to install. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  URL: String;
begin
  if CurStep = ssPostInstall then
  begin
    URL := 'http://' + Trim(HostIPPage.Values[0]) + ':5000';
    { Internet shortcut on the desktop }
    SaveStringToFile(ExpandConstant('{autodesktop}\Law Firm.url'),
      '[InternetShortcut]' + #13#10 + 'URL=' + URL + #13#10,
      False);
  end;
end;
