; ClipMorph Windows installer (Inno Setup 6).
;
; Packages the PyInstaller onedir UI build at dist/clipmorph/ (which already
; contains clipmorph-ui.exe, the bundled FFmpeg, and the built web_assets) into
; a per-user installer with a Start Menu entry, an optional run-at-logon task,
; and an uninstaller. The WebView2 Evergreen bootstrapper is staged next to this
; script by the release workflow and invoked silently; it is idempotent, so it
; no-ops when the runtime is already present.
;
; Compile from the repo root (the release workflow does):
;   ISCC.exe /DAppVersion=0.5.0 scripts\installer\clipmorph.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "ClipMorph"
#define AppPublisher "ClipMorph"
#define AppExeName "clipmorph-ui.exe"
#define RunValueName "ClipMorph"

[Setup]
AppId={{1B0D40CF-3C52-456F-98FF-AA31271F710D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=clipmorph-ui-windows-setup
SetupIconFile=..\..\clipmorph\resources\clipmorph.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "Start {#AppName} when I sign in"; GroupDescription: "Additional options:"; Flags: unchecked

[Files]
Source: "..\..\dist\clipmorph\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"

[Registry]
; One run-at-logon mechanism, shared with the tray toggle in clipmorph/desktop_app.py.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#RunValueName}"; ValueData: """{app}\{#AppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing the Microsoft WebView2 runtime..."; Flags: waituntilterminated
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { Remove the Run value unconditionally. uninsdeletevalue on the [Registry]
      entry above only covers the value the install-time task wrote, so a value
      enabled later from the tray menu (same value name) would survive uninstall
      and point at a deleted exe. A missing value is a no-op. }
    try
      RegDeleteValue(HKEY_CURRENT_USER,
        'Software\Microsoft\Windows\CurrentVersion\Run', '{#RunValueName}');
    except
    end;
  end;
end;
