[Setup]
#ifexist "Output\\version.issinc"
#include "Output\\version.issinc"
#endif
AppName=מערכת ניקוד בית ספרית
#ifdef MyAppVersion
AppVersion={#MyAppVersion}
#else
AppVersion=1.1.0
#endif
AppPublisher=SchoolPoints
DefaultDirName={autopf}\SchoolPoints
DefaultGroupName=מערכת ניקוד בית ספרית
OutputDir=Release
OutputBaseFilename=SchoolPoints_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
UninstallDisplayName=מערכת ניקוד בית ספרית

#ifexist "icons\installer.ico"
SetupIconFile=icons\installer.ico
UninstallDisplayIcon={app}\icons\installer.ico
#endif

[Languages]
Name: "hebrew"; MessagesFile: "compiler:Languages\\Hebrew.isl"

[Types]
Name: "full"; Description: "התקנה מלאה"; Flags: iscustom

[Components]
Name: "admin"; Description: "עמדת ניהול"; Types: full
Name: "public"; Description: "עמדה ציבורית"; Types: full
Name: "cashier"; Description: "עמדת קופה"; Types: full

[Tasks]
Name: "desktopicon_admin"; Description: "יצירת קיצור דרך לעמדת ניהול על שולחן העבודה"; Components: admin
Name: "desktopicon_public"; Description: "יצירת קיצור דרך לעמדה הציבורית על שולחן העבודה"; Components: public
Name: "desktopicon_cashier"; Description: "יצירת קיצור דרך לעמדת קופה על שולחן העבודה"; Components: cashier; Flags: unchecked

[Files]
; קובץ ה-EXE המאוחד (ניהול/ציבורית/קופה, נבחר באמצעות פרמטר שורת פקודה) + כל תלויותיו
Source: "dist\SchoolPoints_v{#MyAppVersion}_Setup\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; תפריט התחל - קיצור נפרד לכל עמדה, כולם מפעילים את אותו EXE עם פרמטר שונה
#ifexist "icons\admin.ico"
Name: "{group}\עמדת ניהול"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--admin"; IconFilename: "{app}\icons\admin.ico"; Components: admin
#else
Name: "{group}\עמדת ניהול"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--admin"; Components: admin
#endif

#ifexist "icons\public.ico"
Name: "{group}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--public"; IconFilename: "{app}\icons\public.ico"; Components: public
#else
Name: "{group}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--public"; Components: public
#endif

#ifexist "icons\cashier.ico"
Name: "{group}\עמדת קופה"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--cashier"; IconFilename: "{app}\icons\cashier.ico"; Components: cashier
#else
Name: "{group}\עמדת קופה"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--cashier"; Components: cashier
#endif

Name: "{group}\הסרת התקנה"; Filename: "{uninstallexe}"

; קיצורים לשולחן עבודה
#ifexist "icons\admin.ico"
Name: "{userdesktop}\עמדת ניהול"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--admin"; IconFilename: "{app}\icons\admin.ico"; Tasks: desktopicon_admin; Components: admin
#else
Name: "{userdesktop}\עמדת ניהול"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--admin"; Tasks: desktopicon_admin; Components: admin
#endif

#ifexist "icons\public.ico"
Name: "{userdesktop}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--public"; IconFilename: "{app}\icons\public.ico"; Tasks: desktopicon_public; Components: public
#else
Name: "{userdesktop}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--public"; Tasks: desktopicon_public; Components: public
#endif

#ifexist "icons\cashier.ico"
Name: "{userdesktop}\עמדת קופה"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--cashier"; IconFilename: "{app}\icons\cashier.ico"; Tasks: desktopicon_cashier; Components: cashier
#else
Name: "{userdesktop}\עמדת קופה"; Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--cashier"; Tasks: desktopicon_cashier; Components: cashier
#endif

[Run]
Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--admin"; Description: "הפעל עמדת ניהול כעת"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: admin
Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--public"; Description: "הפעל עמדה ציבורית כעת"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: public
Filename: "{app}\SchoolPoints_v{#MyAppVersion}_Setup.exe"; Parameters: "--cashier"; Description: "הפעל עמדת קופה כעת"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: cashier
