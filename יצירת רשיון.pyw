# -*- coding: utf-8 -*-
"""GUI generator for SchoolPoints activation keys (Hebrew UI).

Intended for developer use only.
Uses the same generate_activation_key and logging logic as the CLI tool.
"""

import tkinter as tk
from tkinter import ttk, messagebox

from license_manager import generate_activation_key, generate_monthly_activation_key
from license_key_generator import log_issued_license


class LicenseGeneratorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("גנרטור קוד הפעלה - SchoolPoints")
        self.root.geometry("480x260")
        self.root.configure(bg="#ecf0f1")
        self.root.resizable(False, False)

        main = tk.Frame(self.root, bg="#ecf0f1")
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        tk.Label(
            main,
            text="יצירת קוד הפעלה (קוד נגדי) לבית ספר",
            font=("Arial", 14, "bold"),
            bg="#ecf0f1",
            fg="#2c3e50",
        ).pack(pady=(0, 10))

        # שורה: שם מוסד
        row_school = tk.Frame(main, bg="#ecf0f1")
        row_school.pack(fill=tk.X, pady=5)

        tk.Label(
            row_school,
            text="שם מוסד:",
            font=("Arial", 11),
            bg="#ecf0f1",
            anchor="e",
            width=12,
        ).pack(side=tk.RIGHT, padx=5)

        self.school_var = tk.StringVar()
        school_entry = tk.Entry(
            row_school,
            textvariable=self.school_var,
            font=("Arial", 11),
            width=30,
            justify="right",
        )
        school_entry.pack(side=tk.RIGHT, padx=5)

        def paste_school():
            try:
                text = self.root.clipboard_get()
                if text:
                    self.school_var.set(text.strip())
            except Exception:
                pass

        tk.Button(
            row_school,
            text="📋 הדבק",
            command=paste_school,
            font=("Arial", 9),
            bg="#bdc3c7",
            fg="#2c3e50",
            padx=6,
            pady=2,
        ).pack(side=tk.LEFT, padx=5)

        # שורה: קוד מערכת
        row_system = tk.Frame(main, bg="#ecf0f1")
        row_system.pack(fill=tk.X, pady=5)

        tk.Label(
            row_system,
            text="קוד מערכת:",
            font=("Arial", 11),
            bg="#ecf0f1",
            anchor="e",
            width=12,
        ).pack(side=tk.RIGHT, padx=5)

        self.system_var = tk.StringVar()
        system_entry = tk.Entry(
            row_system,
            textvariable=self.system_var,
            font=("Consolas", 11),
            width=30,
            justify="left",
        )
        system_entry.pack(side=tk.RIGHT, padx=5)

        def paste_system():
            try:
                text = self.root.clipboard_get()
                if text:
                    self.system_var.set(text.strip())
            except Exception:
                pass

        tk.Button(
            row_system,
            text="📋 הדבק",
            command=paste_system,
            font=("Arial", 9),
            bg="#bdc3c7",
            fg="#2c3e50",
            padx=6,
            pady=2,
        ).pack(side=tk.LEFT, padx=5)

        # שורה: סוג רישיון
        row_type = tk.Frame(main, bg="#ecf0f1")
        row_type.pack(fill=tk.X, pady=5)

        tk.Label(
            row_type,
            text="סוג רישיון:",
            font=("Arial", 11),
            bg="#ecf0f1",
            anchor="e",
            width=12,
        ).pack(side=tk.RIGHT, padx=5)

        self.license_type = tk.StringVar(value="basic")

        types_frame = tk.Frame(row_type, bg="#ecf0f1")
        types_frame.pack(side=tk.RIGHT)

        ttk.Radiobutton(
            types_frame,
            text="בסיסי (2 עמדות)",
            variable=self.license_type,
            value="basic",
        ).pack(side=tk.RIGHT, padx=3)

        ttk.Radiobutton(
            types_frame,
            text="מורחב (5 עמדות)",
            variable=self.license_type,
            value="extended",
        ).pack(side=tk.RIGHT, padx=3)

        ttk.Radiobutton(
            types_frame,
            text="ללא הגבלה",  # unlimited
            variable=self.license_type,
            value="unlimited",
        ).pack(side=tk.RIGHT, padx=3)

        # שורה: רישיון חודשי
        row_monthly = tk.Frame(main, bg="#ecf0f1")
        row_monthly.pack(fill=tk.X, pady=5)

        tk.Label(
            row_monthly,
            text="חודשי עד (YYYY-MM-DD):",
            font=("Arial", 11),
            bg="#ecf0f1",
            anchor="e",
            width=12,
        ).pack(side=tk.RIGHT, padx=5)

        self.monthly_expiry_var = tk.StringVar()
        monthly_entry = tk.Entry(
            row_monthly,
            textvariable=self.monthly_expiry_var,
            font=("Consolas", 11),
            width=30,
            justify="left",
        )
        monthly_entry.pack(side=tk.RIGHT, padx=5)

        tk.Label(
            row_monthly,
            text="(השאר ריק לרישיון רגיל)",
            font=("Arial", 8),
            bg="#ecf0f1",
            fg="#7f8c8d",
        ).pack(side=tk.LEFT, padx=5)

        # שורה: תוצאה
        row_result = tk.Frame(main, bg="#ecf0f1")
        row_result.pack(fill=tk.X, pady=10)

        tk.Label(
            row_result,
            text="קוד הפעלה:",
            font=("Arial", 11),
            bg="#ecf0f1",
            anchor="e",
            width=12,
        ).pack(side=tk.RIGHT, padx=5)

        self.key_var = tk.StringVar()
        key_entry = tk.Entry(
            row_result,
            textvariable=self.key_var,
            font=("Consolas", 11),
            width=30,
            justify="left",
            state="readonly",
        )
        key_entry.pack(side=tk.RIGHT, padx=5)

        def copy_key():
            key = self.key_var.get().strip()
            if key:
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(key)
                    self.root.update_idletasks()
                    messagebox.showinfo("העתקה", "קוד ההפעלה הועתק ללוח.")
                except Exception:
                    pass

        tk.Button(
            row_result,
            text="📋 העתק",
            command=copy_key,
            font=("Arial", 9),
            bg="#27ae60",
            fg="white",
            padx=6,
            pady=2,
        ).pack(side=tk.LEFT, padx=5)

        # כפתור יצירת קוד
        buttons = tk.Frame(main, bg="#ecf0f1")
        buttons.pack(pady=10)

        def generate():
            school = self.school_var.get().strip()
            if not school:
                messagebox.showwarning("שגיאה", "יש להזין שם מוסד.")
                return

            system_code = self.system_var.get().strip()
            if not system_code:
                messagebox.showwarning("שגיאה", "יש להזין קוד מערכת כפי שמופיע בעמדת הניהול.")
                return

            ltype = self.license_type.get()
            try:
                exp = (self.monthly_expiry_var.get() or '').strip()
                if exp:
                    key = generate_monthly_activation_key(school, system_code, exp, ltype)
                    log_type = f"monthly:{ltype}:{exp}"
                else:
                    key = generate_activation_key(school, system_code, ltype)
                    log_type = ltype
            except Exception as e:
                messagebox.showerror("שגיאה", f"שגיאה ביצירת קוד הפעלה:\n{e}")
                return

            self.key_var.set(key)
            # רישום ללוג הרישיונות (כולל קוד מערכת)
            try:
                log_issued_license(school, system_code, log_type, key)
            except Exception:
                log_issued_license(school, system_code, ltype, key)

        tk.Button(
            buttons,
            text="צור קוד",
            command=generate,
            font=("Arial", 11, "bold"),
            bg="#3498db",
            fg="white",
            padx=20,
            pady=6,
        ).pack()

        # הערת הסבר
        tk.Label(
            main,
            text="כל קוד הפעלה שנוצר נרשם בקובץ issued_licenses.csv (כולל שם מוסד, קוד מערכת וסוג רישיון).",
            font=("Arial", 9),
            bg="#ecf0f1",
            fg="#7f8c8d",
            anchor="w",
            justify="right",
        ).pack(fill=tk.X, pady=(5, 0))

        school_entry.focus_set()


def main() -> None:
    root = tk.Tk()
    app = LicenseGeneratorGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
