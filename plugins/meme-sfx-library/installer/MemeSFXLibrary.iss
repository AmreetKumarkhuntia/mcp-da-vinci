; Inno Setup script for the Meme & SFX Library panel.
;
; Build it with:  python.exe scripts/build_installer.py
; which produces the PyInstaller app first and then compiles this.
;
; Installs per-user into %LOCALAPPDATA%\Programs, so there is no UAC prompt and
; no admin account needed — the panel writes only to the user profile anyway.

#define AppName        "Meme & SFX Library"
#define AppShortName   "MemeSFXLibrary"
#define AppVersion     "1.0.0"
#define AppPublisher   "Amreet Khuntia"
#define AppExe         "MemeSFXLibrary.exe"

; Passed in by build_installer.py: /DSourceDir=... /DOutputDir=...
#ifndef SourceDir
  #define SourceDir "..\..\..\dist\MemeSFXLibrary"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{7C1F4E8A-3D6B-4A2E-9F17-2B5C8D3A6E41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir={#OutputDir}
OutputBaseFilename={#AppShortName}-Setup-{#AppVersion}
SetupIconFile=..\panel\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user install: no admin rights, installs under %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes
DisableDirPage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; PyInstaller and Qt drop caches next to the app; leave nothing behind.
Type: filesandordirs; Name: "{app}"

[Code]
// The library index and thumbnail cache live outside {app}, in the user
// profile, and can represent a long scan. Rebuilding them is cheap (~10 s) but
// favourites and hand-written tags are not recoverable — so ask rather than
// assume, and default to keeping them.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // A silent uninstall must never destroy user data. /SUPPRESSMSGBOXES
    // answers this prompt with Yes regardless of MB_DEFBUTTON2, so asking at
    // all in silent mode would delete favourites and tags unattended.
    if UninstallSilent() then
      Exit;

    DataDir := ExpandConstant('{localappdata}\mcp-da-vinci\library');
    if DirExists(DataDir) then
    begin
      if MsgBox('Also delete your library index, thumbnails, favourites and tags?'
                + #13#10 + #13#10
                + DataDir + #13#10 + #13#10
                + 'Choose No to keep them for a future reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
