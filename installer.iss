; DO编辑器 安装脚本 (Inno Setup 6)
#define MyAppName "DO编辑器"
#define MyAppVersion "2.6.2"
#define MyAppPublisher "RAY"
#define MyAppExeName "DO编辑器.exe"

[Setup]
AppId={{8E2F3A1C-5B4D-4E6F-9A7C-1D2E3F4A5B6C}
AppName={cm:AppDisplayName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppCopyright=© 2026 {#MyAppPublisher} <gmy.2811@gmail.com>
VersionInfoProductName=DO Editor
VersionInfoDescription=DO Editor Setup
AppPublisherURL=
AppSupportURL=
AppUpdatesURL=
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={cm:AppDisplayName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename={#MyAppName}-Setup-v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
WizardSizePercent=110
WizardImageFile=installer-assets\wizard-sidebar.bmp
WizardSmallImageFile=installer-assets\wizard-small.bmp
WizardImageStretch=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppName}-v{#MyAppVersion}.ico
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
DisableWelcomePage=no
ShowLanguageDialog=yes
UsePreviousLanguage=no
UsePreviousAppDir=yes
ChangesAssociations=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
chinesesimplified.WelcomeLabel2=此向导将在您的电脑上安装 [name]（版本 {#MyAppVersion}）。%n%n开发者：{#MyAppPublisher}%n联系邮箱：gmy.2811@gmail.com
english.WelcomeLabel2=This wizard will install [name] version {#MyAppVersion}.%n%nDeveloper: {#MyAppPublisher}%nEmail: gmy.2811@gmail.com

[CustomMessages]
chinesesimplified.AppDisplayName=DO编辑器
english.AppDisplayName=DO Editor
chinesesimplified.DesktopIcon=创建桌面快捷方式
english.DesktopIcon=Create a desktop shortcut
chinesesimplified.PdfAssociation=将 PDF 文件关联到 DO编辑器（默认用它打开）
english.PdfAssociation=Associate PDF files with DO Editor
chinesesimplified.AdditionalTasks=附加任务：
english.AdditionalTasks=Additional tasks:
chinesesimplified.RunNow=立即运行 DO编辑器
english.RunNow=Launch DO Editor
chinesesimplified.PdfDocument=PDF 文档
english.PdfDocument=PDF Document

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalTasks}"
Name: "pdfassoc"; Description: "{cm:PdfAssociation}"; GroupDescription: "{cm:AdditionalTasks}"

[Files]
Source: "dist\DO编辑器\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs
Source: "icon.ico"; DestDir: "{app}"; DestName: "{#MyAppName}-v{#MyAppVersion}.ico"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{cm:AppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppName}-v{#MyAppVersion}.ico"
Name: "{autodesktop}\{cm:AppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppName}-v{#MyAppVersion}.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "language"; ValueData: "{code:GetAppLanguage}"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\.pdf"; ValueType: string; ValueName: ""; ValueData: "{#MyAppName}.PDF"; Flags: uninsdeletevalue; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyAppName}.PDF"; ValueType: string; ValueName: ""; ValueData: "{cm:PdfDocument}"; Flags: uninsdeletekey; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyAppName}.PDF\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppName}-v{#MyAppVersion}.ico"; Tasks: pdfassoc
Root: HKA; Subkey: "Software\Classes\{#MyAppName}.PDF\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: pdfassoc

[Run]
Filename: "{sys}\ie4uinit.exe"; Parameters: "-show"; Flags: runhidden waituntilterminated skipifdoesntexist
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:RunNow}"; Flags: nowait postinstall skipifsilent

[Code]
function GetAppLanguage(Param: String): String;
begin
  if ActiveLanguage = 'english' then
    Result := 'en'
  else
    Result := 'zh';
end;
