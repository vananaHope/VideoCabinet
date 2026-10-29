; scripts/build.ps1이 pyproject.toml의 버전, 앱 표시 이름(#306)과 절대 경로를 전달한다.
#ifndef AppVersion
  #error AppVersion is required. Run scripts/build.ps1.
#endif
#ifndef AppDirectory
  #error AppDirectory is required. Run scripts/build.ps1.
#endif
#ifndef InstallerOutput
  #error InstallerOutput is required. Run scripts/build.ps1.
#endif
; 표시 이름은 앱의 단일 원본(app_version.DISPLAY_NAME)에서 build.ps1이 만든 UTF-8(BOM) include가 정한다.
; 한글을 /D 명령줄 인자로 넘겨 코드 페이지에서 깨지지 않게 한다.
#ifndef DisplayNameInclude
  #error DisplayNameInclude is required. Run scripts/build.ps1.
#endif
#include DisplayNameInclude
#ifndef AppDisplayName
  #error AppDisplayName is required in DisplayNameInclude. Run scripts/build.ps1.
#endif

; 바로 가기 폴더: 제품 빌드는 사용자 시작 메뉴·바탕 화면, 격리 설치 테스트는 임시 폴더(ShortcutRoot)를 쓴다.
#ifdef IsolatedTest
  #ifndef ShortcutRoot
    #error ShortcutRoot is required for isolated tests.
  #endif
  #define ShortcutPrograms ShortcutRoot + "\Programs"
  #define ShortcutDesktop ShortcutRoot + "\Desktop"
#else
  #define ShortcutPrograms "{userprograms}"
  #define ShortcutDesktop "{userdesktop}"
#endif

[Setup]
AppId={{C50CA559-BED4-4FA2-AD83-C399DAEF2FBD}
AppName={#AppDisplayName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\MyVideoManager
DefaultGroupName={#AppDisplayName}
DisableProgramGroupPage=yes
; 바로 가기 작업은 이전 선택을 기억하지 않는다. 바탕 화면 바로 가기는 [Code]가 설치 전 존재를 보고 다시 만들고,
; 지운 바로 가기를 설치가 되살리지 않는다(격리 설치 테스트가 이 PC의 실제 설치 기록과 섞이지 않는 효과도 있다).
UsePreviousTasks=no
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
; "설치된 앱" 목록 이름도 표시 이름을 따른다.
UninstallDisplayName={#AppDisplayName}
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

[InstallDelete]
; 덮어 설치와 패치 설치 모두 옛 이름의 바로 가기를 지운다. 새 이름 바로 가기는 [Icons]가 만든다.
Type: files; Name: "{#ShortcutPrograms}\My Video Manager.lnk"
Type: files; Name: "{#ShortcutDesktop}\My Video Manager.lnk"

[Icons]
Name: "{#ShortcutPrograms}\{#AppDisplayName}"; Filename: "{app}\my-video-manager.exe"; WorkingDir: "{app}"; IconFilename: "{app}\my_video_manager\app.ico"
Name: "{#ShortcutDesktop}\{#AppDisplayName}"; Filename: "{app}\my-video-manager.exe"; WorkingDir: "{app}"; IconFilename: "{app}\my_video_manager\app.ico"; Tasks: desktopicon
; 옛 이름 또는 새 이름 바탕 화면 바로 가기가 이미 있던 사용자는 작업 선택과 무관하게(패치·조용한 설치 포함) 하나를 다시 만든다.
Name: "{#ShortcutDesktop}\{#AppDisplayName}"; Filename: "{app}\my-video-manager.exe"; WorkingDir: "{app}"; IconFilename: "{app}\my_video_manager\app.ico"; Check: HadDesktopShortcut

; 사용자 데이터(~/.my-video-manager 또는 --data-dir)는 설치 파일에 포함하지 않는다.
; [UninstallDelete]를 두지 않아 제거·업데이트 후에도 사용자 데이터가 남는다.

[Code]
var
  HadDesktopShortcutBeforeInstall: Boolean;

function HadDesktopShortcut: Boolean;
begin
  Result := HadDesktopShortcutBeforeInstall;
end;

function InitializeSetup: Boolean;
begin
  // [InstallDelete]가 옛 바로 가기를 지우기 전에 바탕 화면 바로 가기가 있었는지 기억한다.
  // 패치·조용한 설치에서는 이전 작업 선택(UsePreviousTasks)에 기대지 않는다.
  HadDesktopShortcutBeforeInstall :=
    FileExists(ExpandConstant('{#ShortcutDesktop}\My Video Manager.lnk')) or
    FileExists(ExpandConstant('{#ShortcutDesktop}\{#AppDisplayName}.lnk'));
  Result := True;
end;

#ifdef PatchInclude
#include "patch-validation.iss"
#endif
