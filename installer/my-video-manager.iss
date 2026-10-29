; scripts/build.ps1이 pyproject.toml의 버전과 절대 경로를 전달한다.
#ifndef AppVersion
  #error AppVersion is required. Run scripts/build.ps1.
#endif
#ifndef AppDirectory
  #error AppDirectory is required. Run scripts/build.ps1.
#endif
#ifndef InstallerOutput
  #error InstallerOutput is required. Run scripts/build.ps1.
#endif

[Setup]
AppId={{C50CA559-BED4-4FA2-AD83-C399DAEF2FBD}
AppName=My Video Manager
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\MyVideoManager
DefaultGroupName=My Video Manager
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef IsolatedTest
Uninstallable=no
CreateUninstallRegKey=no
UsePreviousAppDir=no
#else
Uninstallable=yes
#endif
; 설치 폴더의 다중 크기 ICO를 가리켜 패치 설치로 아이콘 파일만 바뀌어도 설치된 앱 목록 아이콘이 따라 바뀐다.
UninstallDisplayIcon={app}\my_video_manager\app.ico
SetupIconFile={#AppDirectory}\my_video_manager\app.ico
OutputDir={#InstallerOutput}
#ifdef PatchInclude
OutputBaseFilename=MyVideoManager-Patch-{#AppVersion}
#else
OutputBaseFilename=MyVideoManager-Setup-{#AppVersion}
#endif
CloseApplications=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
#ifdef PatchInclude
#include PatchInclude
#else
Source: "{#AppDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

#ifndef IsolatedTest
[Icons]
Name: "{userprograms}\My Video Manager"; Filename: "{app}\my-video-manager.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\My Video Manager"; Filename: "{app}\my-video-manager.exe"; WorkingDir: "{app}"; Tasks: desktopicon
#endif

; 사용자 데이터(~/.my-video-manager 또는 --data-dir)는 설치 파일에 포함하지 않는다.
; [UninstallDelete]를 두지 않아 제거·업데이트 후에도 사용자 데이터가 남는다.

#ifdef PatchInclude
#include "patch-validation.iss"
#endif
