#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

#define MyAppName "Spectra"
#define MyAppPublisher "Vinicius Botelho"
#define MyAppURL "https://github.com/vinibotelho1998/Spectra"
#define MyAppExeName "Spectra.exe"
#define SourceDist "..\dist\Spectra"

[Setup]
AppId={{6C7F2E1A-6B3D-4F2C-9B7E-4A3E2C1D9F0B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=Spectra-Setup-{#MyAppVersion}
SetupIconFile=..\assets\spectra.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "Iniciar o Spectra junto com o Windows"; GroupDescription: "Opcoes:"; Flags: unchecked

[Files]
Source: "{#SourceDist}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDist}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function OpenRGBInstalled: Boolean;
begin
  Result := DirExists('C:\Program Files\OpenRGB') or
            DirExists('C:\Program Files (x86)\OpenRGB');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not OpenRGBInstalled then
  begin
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10 + #13#10 +
      'O OpenRGB nao foi encontrado nesta maquina. O Spectra precisa dele ' +
      'para falar com o hardware -- baixe em openrgb.org e abra o Spectra ' +
      'de novo depois.';
  end;
end;
