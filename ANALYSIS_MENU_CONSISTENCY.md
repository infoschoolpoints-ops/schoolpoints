# Menu Consistency Analysis: Desktop vs. Web

## Overview
This document compares the menu items and terminology between the Desktop Application (`admin_station.py`) and the Web UI (`cloud_service/app.py`) to ensure consistency as requested.

## Comparison Table

| Feature Category | Desktop Terminology | Web UI Terminology | Status | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| **Students** | Main Table (No specific button label, just "Add/Edit/Delete") | **תלמידים** (Students) | ✅ Consistent | Keep as is. |
| **Teachers** | **ניהול מורים** (Manage Teachers) | **מורים** (Teachers) | ✅ Consistent | Web "Mores" is shorter, acceptable. |
| **Messages** | **הודעות כלליות** (General Messages) | **הודעות** (Messages) | ✅ Consistent | Web covers all message types. |
| **Upgrades/Colors** | **שדרוגים** (Upgrades) / "מטבעות וצבעים" | **שדרוגים** (Upgrades) | ✅ Fixed | Previously "Bonuses" in Web. Now matches. |
| **Time Bonus** | **בונוס זמנים** (Time Bonus) | **בונוס זמנים** (Time Bonus) | ✅ Consistent | Keep as is. |
| **Special Bonus** | **בונוס מיוחד** (Special Bonus) | **בונוס מיוחד** (Special Bonus) | ✅ Consistent | Keep as is. |
| **Holidays** | **ניהול לוח חופשות** (Manage Closures) [Inside Settings] | **חגים** (Holidays) | ⚠️ Divergent | Desktop hides this inside a dialog. Web promotes it. **Rec:** Promote in Desktop or keep Web accessible. |
| **Purchases/Shop** | **קניות** (Shopping) | **קניות** (Purchases) | ✅ Fixed | Previously "Cashier" in Web. Now matches. |
| **Reports** | **ייצוא** (Export) / "דוחות" mentioned in help | **דוחות** (Reports) | ⚠️ Divergent | Desktop uses "Export". Web "Reports" implies visuals. **Rec:** Rename Web to "Export & Reports" or keep distinct if functionality differs. |
| **Settings** | **הגדרות מערכת** + **הגדרות תצוגה** | **הגדרות** (Settings) | ℹ️ Combined | Web combines both into one Settings area. Good for simplicity. |
| **Personal Area** | "אזור אישי" (Header) / "החלף משתמש" | **אזור אישי** (Personal Area) | ✅ Consistent | |

## Action Items Executed
1.  Renamed Web Tile "Bonuses" -> **"Upgrades" (שדרוגים)** to match Desktop.
2.  Renamed Web Tile "Cashier" -> **"Purchases" (קניות)** to match Desktop.
3.  Ensured "Time Bonus" and "Special Bonus" names align.

## Recommendations for Desktop App
1.  **Holidays Button**: Consider moving the "Manage Holidays" button from the specific settings dialog to the main toolbar if it's frequently used, matching the Web's top-level visibility.
2.  **Reports Naming**: Change "Export" (ייצוא) to "Reports & Export" (דוחות וייצוא) to make it sound more comprehensive like the Web version.

## Recommendations for Web UI
1.  **Reports Page**: Should include both the "Export to Excel" functionality (download) and visual graphs/stats.
