; Instalador de EDWIN CNC 3D (basado en el de IngeTrazo).
;
; En la nube: .github/workflows/edwin-windows.yml
; A mano:     iscc /DMyAppVersion=1.0.0 installer\edwin-cnc-3d.iss
;
; El AppId es FIJO: no cambiarlo nunca, o Windows toma cada versión como otro programa.
; Es distinto al de IngeTrazo: los dos programas se pueden tener instalados a la vez.

#define MyAppName "EDWIN CNC 3D"
#define MyAppPublisher "EDWIN CNC"
#define MyAppURL "https://github.com/INGEMAQSEWING/edwin-cnc-3d"
#define MyAppExeName "ingetrazo.exe"

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{853A02CB-607B-47D2-B83A-CF4C598C4485}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=EDWIN CNC 3D - modelado 3D y desdoblado de laminas para corte CNC
VersionInfoProductName={#MyAppName}

DefaultDirName={autopf}\EDWIN CNC 3D
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Bienvenida y créditos antes de la licencia (GPL-3.0, obligatoria).
InfoBeforeFile=..\edwin\instalador-bienvenida.txt
LicenseFile=..\LICENSE

OutputDir=..\dist
OutputBaseFilename=EDWIN-CNC-3D-{#MyAppVersion}-Windows-64-bits

WizardStyle=modern
ShowLanguageDialog=no
UsePreviousLanguage=no
DisableProgramGroupPage=yes
ChangesAssociations=yes
; Solo 64 bits (decisión del usuario, 2026-11-09).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
SetupIconFile=..\resources\icons\ingetrazo.ico

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
spanish.SkpDefault=Abrir los archivos .skp (SketchUp) con EDWIN CNC 3D al darles doble clic
spanish.FileAssociations=Asociaciones de archivos:
spanish.IgzDocument=Modelo de EDWIN CNC 3D
spanish.SkpModel=Modelo SKP (EDWIN CNC 3D)

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"
Name: "skpdefault"; Description: "{cm:SkpDefault}"; \
    GroupDescription: "{cm:FileAssociations}"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\ingetrazo\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\resources\icons\ingetrazo.ico"; DestDir: "{app}"; DestName: "edwin-cnc-3d.ico"; \
    Flags: ignoreversion
Source: "..\resources\icons\mimetypes\ingetrazo-skp.ico"; DestDir: "{app}"; \
    Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\edwin-cnc-3d.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\edwin-cnc-3d.ico"; \
    Tasks: desktopicon

[Registry]
; Portátiles con dos tarjetas de video: usar la potente.
Root: HKCU; Subkey: "Software\Microsoft\DirectX\UserGpuPreferences"; \
    ValueType: string; ValueName: "{app}\{#MyAppExeName}"; \
    ValueData: "GpuPreference=2;"; Flags: createvalueifdoesntexist uninsdeletevalue

; .igz: «Abrir con» EDWIN CNC 3D (sin quitarle el doble clic a IngeTrazo si ya lo tiene).
Root: HKA; Subkey: "Software\Classes\EdwinCNC3D.Document"; ValueType: string; \
    ValueData: "{cm:IgzDocument}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\EdwinCNC3D.Document\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\edwin-cnc-3d.ico,0"
Root: HKA; Subkey: "Software\Classes\EdwinCNC3D.Document\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.igz"; ValueType: string; \
    ValueData: "EdwinCNC3D.Document"; Flags: createvalueifdoesntexist uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.igz\OpenWithProgids"; \
    ValueType: string; ValueName: "EdwinCNC3D.Document"; ValueData: ""; \
    Flags: uninsdeletevalue uninsdeletekeyifempty

; .skp: aparece en «Abrir con»; doble clic solo si el usuario marca la casilla.
Root: HKA; Subkey: "Software\Classes\.skp"; Flags: uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\EdwinCNC3D.skp"; ValueType: string; \
    ValueData: "{cm:SkpModel}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\EdwinCNC3D.skp\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingetrazo-skp.ico,0"
Root: HKA; Subkey: "Software\Classes\EdwinCNC3D.skp\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.skp\OpenWithProgids"; \
    ValueType: string; ValueName: "EdwinCNC3D.skp"; ValueData: ""; \
    Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.skp"; ValueType: string; \
    ValueData: "EdwinCNC3D.skp"; Tasks: skpdefault; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
