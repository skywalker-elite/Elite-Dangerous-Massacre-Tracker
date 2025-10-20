#define AppVersion GetEnv("APP_VERSION")
#define InputDir   GetEnv("INPUT_DIR")
#define OutputDirA GetEnv("OUTPUT_DIR")
#define AppExe      "Elite Dangerous Massacre Tracker.exe"

#pragma message "AppVersion = {#AppVersion}"
#pragma message "InputDir   = {#InputDir}"
#pragma message "OutputDirA = {#OutputDirA}"
#pragma message "AppExe      = {#AppExe}"

[Setup]
AppName=Elite Dangerous Massacre Tracker
AppVersion={#AppVersion}
AppId={{47CE688B-A9D4-4753-B8DE-37F9DBB2A377}}
WizardStyle=modern
WizardImageFile="{#InputDir}\..\..\installer\Inno_wizard_image.png"
SetupIconFile="{#InputDir}\_internal\images\EDMT.ico"
DefaultDirName={autopf}\EDMT
DefaultGroupName=Skywalker-Elite
OutputDir={#OutputDirA}
OutputBaseFilename=EDMT-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Files]
Source: "{#InputDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\EDMT"; Filename: "{app}\{#AppExe}"
Name: "{commondesktop}\EDMT"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Additional shortcuts:"
Name: "quicklaunchicon"; Description: "Create a &Quick Launch shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch EDMT"; Flags: nowait postinstall skipifsilent
