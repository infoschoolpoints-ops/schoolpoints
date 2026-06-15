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
DefaultDirName={pf}\SchoolPoints
DefaultGroupName=מערכת ניקוד בית ספרית
OutputBaseFilename=SchoolPoints_Setup_v{#MyAppVersion}
Compression=lzma2
SolidCompression=no
DisableProgramGroupPage=no
ArchitecturesInstallIn64BitMode=x64

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
Name: "desktopicon_admin"; Description: "יצירת קיצור דרך לעמדת ניהול על שולחן העבודה"; Components: admin; Flags: unchecked
Name: "desktopicon_public"; Description: "יצירת קיצור דרך לעמדה הציבורית על שולחן העבודה"; Components: public; Flags: unchecked
Name: "desktopicon_cashier"; Description: "יצירת קיצור דרך לעמדת קופה על שולחן העבודה"; Components: cashier; Flags: unchecked

[Files]
; חבילה משולבת - כל הקבצים משותפים מ-SchoolPoints_All
; קבצים משותפים (DLLs, ספריות, נתונים) - מותקנים פעם אחת
Source: "dist\SchoolPoints_All\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "SchoolPoints_Admin.exe,SchoolPoints_Public.exe,SchoolPoints_Cashier.exe"

; EXE של עמדת ניהול
Source: "dist\SchoolPoints_All\SchoolPoints_Admin.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: admin

; EXE של עמדה ציבורית
Source: "dist\SchoolPoints_All\SchoolPoints_Public.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: public

; EXE של עמדת קופה
Source: "dist\SchoolPoints_All\SchoolPoints_Cashier.exe"; DestDir: "{app}"; Flags: ignoreversion; Components: cashier

; קבצי הוראות HTML (חדש!)
Source: "guide_admin.html"; DestDir: "{app}"; Flags: ignoreversion; Components: admin
Source: "guide_teacher.html"; DestDir: "{app}"; Flags: ignoreversion; Components: admin
Source: "guide_index.html"; DestDir: "{app}"; Flags: ignoreversion; Components: admin
Source: "guide_user.html"; DestDir: "{app}"; Flags: ignoreversion; Components: admin
Source: "guide_user_embedded.html"; DestDir: "{app}"; Flags: ignoreversion; Components: admin

; תמונות למדריכים
Source: "תמונות\להוראות\*"; DestDir: "{app}\תמונות\להוראות"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: admin

#ifexist "icons\admin.ico"
Source: "icons\admin.ico"; DestDir: "{app}\icons"; Flags: ignoreversion
#endif
#ifexist "icons\public.ico"
Source: "icons\public.ico"; DestDir: "{app}\icons"; Flags: ignoreversion
#endif
#ifexist "icons\cashier.ico"
Source: "icons\cashier.ico"; DestDir: "{app}\icons"; Flags: ignoreversion
#endif
#ifexist "icons\installer.ico"
Source: "icons\installer.ico"; DestDir: "{app}\icons"; Flags: ignoreversion
#endif

[Icons]
; תפריט התחל

#ifexist "icons\admin.ico"
Name: "{group}\עמדת ניהול"; Filename: "{app}\SchoolPoints_Admin.exe"; IconFilename: "{app}\icons\admin.ico"; Components: admin
#else
Name: "{group}\עמדת ניהול"; Filename: "{app}\SchoolPoints_Admin.exe"; Components: admin
#endif

#ifexist "icons\public.ico"
Name: "{group}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_Public.exe"; IconFilename: "{app}\icons\public.ico"; Components: public
#else
Name: "{group}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_Public.exe"; Components: public
#endif

#ifexist "icons\cashier.ico"
Name: "{group}\עמדת קופה"; Filename: "{app}\SchoolPoints_Cashier.exe"; IconFilename: "{app}\icons\cashier.ico"; Components: cashier
#else
Name: "{group}\עמדת קופה"; Filename: "{app}\SchoolPoints_Cashier.exe"; Components: cashier
#endif

; קיצורים לשולחן עבודה

#ifexist "icons\admin.ico"
Name: "{userdesktop}\עמדת ניהול"; Filename: "{app}\SchoolPoints_Admin.exe"; IconFilename: "{app}\icons\admin.ico"; Tasks: desktopicon_admin; Components: admin
#else
Name: "{userdesktop}\עמדת ניהול"; Filename: "{app}\SchoolPoints_Admin.exe"; Tasks: desktopicon_admin; Components: admin
#endif

#ifexist "icons\public.ico"
Name: "{userdesktop}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_Public.exe"; IconFilename: "{app}\icons\public.ico"; Tasks: desktopicon_public; Components: public
#else
Name: "{userdesktop}\עמדה ציבורית"; Filename: "{app}\SchoolPoints_Public.exe"; Tasks: desktopicon_public; Components: public
#endif

#ifexist "icons\cashier.ico"
Name: "{userdesktop}\עמדת קופה"; Filename: "{app}\SchoolPoints_Cashier.exe"; IconFilename: "{app}\icons\cashier.ico"; Tasks: desktopicon_cashier; Components: cashier
#else
Name: "{userdesktop}\עמדת קופה"; Filename: "{app}\SchoolPoints_Cashier.exe"; Tasks: desktopicon_cashier; Components: cashier
#endif

[Run]
; אפשרות הפעלה מיד אחרי הסיום
Filename: "{app}\SchoolPoints_Admin.exe"; Description: "הפעל עמדת ניהול כעת"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: admin
Filename: "{app}\SchoolPoints_Public.exe"; Description: "הפעל עמדה ציבורית כעת"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: public
Filename: "{app}\SchoolPoints_Cashier.exe"; Description: "הפעל עמדת קופה כעת"; Flags: nowait postinstall skipifsilent runasoriginaluser; Components: cashier
