"""SchoolPoints license key generator (for internal/developer use only).

Run:
    python license_key_generator.py

This tool is NOT for end users, only for generating license keys.
"""

import os
import csv
import sys
from datetime import datetime
import codecs

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from license_manager import (
    generate_activation_key,
    generate_monthly_activation_key_with_cashier,
    generate_payload_activation_key,
)


def log_issued_license(school: str, system_code: str, ltype: str, key: str) -> None:
    """Log a generated activation key to issued_licenses.csv (UTF-8 with BOM for Excel)."""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, "issued_licenses.csv")
        file_exists = os.path.exists(log_path)

        # Ensure existing file has UTF-8 BOM so Excel will detect encoding correctly
        if file_exists:
            try:
                with open(log_path, "rb") as fb:
                    data = fb.read()
                if not data.startswith(codecs.BOM_UTF8):
                    with open(log_path, "wb") as fb:
                        fb.write(codecs.BOM_UTF8)
                        fb.write(data)
            except Exception:
                # אם אי אפשר לתקן את הקובץ הישן, נמשיך לכתוב קדימה בלבד
                pass

        # utf-8-sig adds BOM so Excel opens Hebrew correctly for new files
        with open(log_path, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow([
                    "timestamp",
                    "school_name",
                    "system_code",
                    "license_type",
                    "activation_key",
                ])
            writer.writerow([
                datetime.now().isoformat(timespec="seconds"),
                school,
                system_code,
                ltype,
                key,
            ])
    except Exception as e:
        print(f"Warning: could not write to license CSV log: {e}")


def choose_license_type() -> str:
    print("Choose license type:")
    print("  1) basic     – up to 2 stations")
    print("  2) extended  – up to 5 stations")
    print("  3) unlimited – many stations")
    while True:
        choice = input("Enter 1/2/3 (or empty to cancel): ").strip()
        if choice == "":
            return ""
        if choice == "1":
            return "basic"
        if choice == "2":
            return "extended"
        if choice == "3":
            return "unlimited"
        print("Invalid choice, please try again.")


def choose_key_scheme() -> str:
    print("Choose key scheme:")
    print("  1) SP5 (term/payload) – validity days start at activation")
    print("  2) monthly            – expiry date in key")
    print("  3) legacy             – old activation key (station limit only)")
    while True:
        choice = input("Enter 1/2/3 (or empty to cancel): ").strip()
        if choice == "":
            return ""
        if choice == "1":
            return "sp5"
        if choice == "2":
            return "monthly"
        if choice == "3":
            return "legacy"
        print("Invalid choice, please try again.")


def _ask_int(prompt: str, default: int) -> int:
    while True:
        raw = input(f"{prompt} (default={default}): ").strip()
        if raw == "":
            return int(default)
        try:
            return int(raw)
        except Exception:
            print("Invalid number, please try again.")


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    suf = "Y/n" if default else "y/N"
    while True:
        ans = input(f"{prompt} ({suf}): ").strip().lower()
        if ans == "":
            return bool(default)
        if ans in ("y", "yes", "1", "true"):
            return True
        if ans in ("n", "no", "0", "false"):
            return False
        print("Invalid choice, please answer y/n.")


def run_cli():
    print("==============================")
    print("   SchoolPoints Activation Key Generator")
    print("==============================")
    print("For developer use only.\n")

    while True:
        school = input("School name (empty to exit, Hebrew allowed): ").strip()
        if not school:
            break

        system_code = input("System code (as shown in the school's registration dialog): ").strip()
        if not system_code:
            print("System code is required.\n")
            continue

        scheme = choose_key_scheme()
        if not scheme:
            print("Canceled.\n")
            continue

        ltype = choose_license_type()
        if not ltype:
            print("Canceled.\n")
            continue

        allow_cashier = True
        days_valid = 0
        max_stations = 0
        expiry_date = ""

        if scheme == "monthly":
            expiry_date = input("Expiry date for MONTHLY license (YYYY-MM-DD): ").strip()
            if not expiry_date:
                print("Expiry date is required for monthly scheme.\n")
                continue
            allow_cashier = _ask_yes_no("Allow cashier station", default=False)
        elif scheme == "sp5":
            days_valid = _ask_int("Days valid", default=7)
            # derive default stations from legacy profile selection
            if ltype == 'basic':
                max_stations = 2
            elif ltype == 'extended':
                max_stations = 5
            else:
                max_stations = 999
            max_stations = _ask_int("Max stations", default=max_stations)
            allow_cashier = _ask_yes_no("Allow cashier station", default=False)

        try:
            if scheme == "monthly":
                key = generate_monthly_activation_key_with_cashier(school, system_code, expiry_date, ltype, allow_cashier)
                log_type = f"monthly:{ltype}"
            elif scheme == "sp5":
                key = generate_payload_activation_key(
                    school,
                    system_code,
                    days_valid=int(days_valid),
                    max_stations=int(max_stations),
                    allow_cashier=bool(allow_cashier),
                )
                log_type = f"sp5:{int(days_valid)}d:{int(max_stations)}st:cashier={1 if allow_cashier else 0}"
            else:
                key = generate_activation_key(school, system_code, ltype)
                log_type = f"legacy:{ltype}"
        except Exception as e:
            print(f"Error generating activation key: {e}\n")
            continue

        print("\n--- Result ---")
        print(f"School name:   {school}")
        print(f"System code:   {system_code}")
        if scheme == "monthly":
            print(f"License type:  monthly ({ltype}), expiry={expiry_date}, cashier={allow_cashier}")
        elif scheme == "sp5":
            print(f"License type:  SP5 term, days={int(days_valid)}, max_stations={int(max_stations)}, cashier={allow_cashier}")
        else:
            print(f"License type:  legacy ({ltype})")
        print(f"Activation key:{key}")
        print("---------------\n")

        # Log to CSV for future lookup
        log_issued_license(school, system_code, log_type, key)

    print("Exiting generator.")


def run_gui():
    root = tk.Tk()
    root.title("מחולל רישיונות – SchoolPoints")

    # UI strings are Hebrew, internal codes remain English for compatibility.
    SCHEME_LABEL_TO_CODE = {
        "SP5 (תוקף בימים)": "sp5",
        "חודשי (תפוגה בתאריך)": "monthly",
        "ישן (Legacy)": "legacy",
    }
    SCHEME_CODE_TO_LABEL = {v: k for k, v in SCHEME_LABEL_TO_CODE.items()}
    LTYPE_LABEL_TO_CODE = {
        "בסיסי (2 עמדות)": "basic",
        "מורחב (5 עמדות)": "extended",
        "ללא הגבלה": "unlimited",
    }
    LTYPE_CODE_TO_LABEL = {v: k for k, v in LTYPE_LABEL_TO_CODE.items()}

    v_school = tk.StringVar()
    v_system = tk.StringVar()
    v_scheme = tk.StringVar(value=SCHEME_CODE_TO_LABEL["sp5"])
    v_ltype = tk.StringVar(value=LTYPE_CODE_TO_LABEL["basic"])
    v_days = tk.StringVar(value="7")
    v_max_stations = tk.StringVar(value="2")
    v_allow_cashier = tk.BooleanVar(value=False)
    v_expiry = tk.StringVar(value="")
    v_key = tk.StringVar(value="")

    frm = ttk.Frame(root, padding=16)
    frm.grid(row=0, column=0, sticky="nsew")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    frm.columnconfigure(1, weight=1)

    ttk.Label(frm, text="מחולל רישיונות", font=("Segoe UI", 14, "bold")).grid(
        row=0,
        column=0,
        columnspan=2,
        sticky="e",
        pady=(0, 12),
    )

    def row(label, widget, r):
        ttk.Label(frm, text=label, anchor="e", justify="right").grid(
            row=r,
            column=0,
            sticky="e",
            padx=(0, 10),
            pady=4,
        )
        widget.grid(row=r, column=1, sticky="ew", pady=4)

    def _install_entry_context_menu(entry: ttk.Entry) -> None:
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="גזור", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_command(label="העתק", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="הדבק", command=lambda: entry.event_generate("<<Paste>>"))

        def _popup(e):
            try:
                menu.tk_popup(e.x_root, e.y_root)
            finally:
                try:
                    menu.grab_release()
                except Exception:
                    pass

        entry.bind("<Button-3>", _popup)
        entry.bind("<Control-v>", lambda e: entry.event_generate("<<Paste>>") or "break")
        entry.bind("<Control-V>", lambda e: entry.event_generate("<<Paste>>") or "break")
        entry.bind("<Shift-Insert>", lambda e: entry.event_generate("<<Paste>>") or "break")
        entry.bind("<Control-c>", lambda e: entry.event_generate("<<Copy>>") or "break")
        entry.bind("<Control-C>", lambda e: entry.event_generate("<<Copy>>") or "break")
        entry.bind("<Control-x>", lambda e: entry.event_generate("<<Cut>>") or "break")
        entry.bind("<Control-X>", lambda e: entry.event_generate("<<Cut>>") or "break")

    ent_school = ttk.Entry(frm, textvariable=v_school, justify="right")
    ent_system = ttk.Entry(frm, textvariable=v_system, justify="right")
    row("שם בית ספר", ent_school, 1)
    row("קוד מערכת", ent_system, 2)
    _install_entry_context_menu(ent_school)
    _install_entry_context_menu(ent_system)
    row(
        "שיטת רישוי",
        ttk.Combobox(
            frm,
            textvariable=v_scheme,
            values=list(SCHEME_LABEL_TO_CODE.keys()),
            state="readonly",
            justify="right",
        ),
        3,
    )
    row(
        "סוג רישיון",
        ttk.Combobox(
            frm,
            textvariable=v_ltype,
            values=list(LTYPE_LABEL_TO_CODE.keys()),
            state="readonly",
            justify="right",
        ),
        4,
    )
    ent_days = ttk.Entry(frm, textvariable=v_days, justify="right")
    ent_st = ttk.Entry(frm, textvariable=v_max_stations, justify="right")
    ent_exp = ttk.Entry(frm, textvariable=v_expiry, justify="right")
    row("ימים לתוקף (SP5)", ent_days, 5)
    row("מקסימום עמדות (SP5)", ent_st, 6)
    row("תאריך תפוגה (חודשי, YYYY-MM-DD)", ent_exp, 7)
    chk = ttk.Checkbutton(frm, text="לאפשר עמדת קופה", variable=v_allow_cashier)
    chk.grid(row=8, column=1, sticky="e", pady=(6, 10))

    row("קוד רישיון", ttk.Entry(frm, textvariable=v_key, state="readonly", justify="right"), 9)

    def _scheme_code() -> str:
        return SCHEME_LABEL_TO_CODE.get((v_scheme.get() or "").strip(), "sp5")

    def _ltype_code() -> str:
        return LTYPE_LABEL_TO_CODE.get((v_ltype.get() or "").strip(), "basic")

    def update_enabled(*_):
        scheme = _scheme_code()
        ent_days.configure(state="normal" if scheme == "sp5" else "disabled")
        ent_st.configure(state="normal" if scheme == "sp5" else "disabled")
        ent_exp.configure(state="normal" if scheme == "monthly" else "disabled")
        chk.configure(state="normal" if scheme in ("sp5", "monthly") else "disabled")

    def generate():
        school = (v_school.get() or "").strip()
        system_code = (v_system.get() or "").strip()
        scheme = _scheme_code()
        ltype = _ltype_code()
        if not school or not system_code:
            messagebox.showerror("שגיאה", "חובה להזין שם בית ספר וקוד מערכת.")
            return
        try:
            if scheme == "monthly":
                expiry = (v_expiry.get() or "").strip()
                if not expiry:
                    messagebox.showerror("שגיאה", "חובה להזין תאריך תפוגה.")
                    return
                allow_cashier = bool(v_allow_cashier.get())
                key = generate_monthly_activation_key_with_cashier(school, system_code, expiry, ltype, allow_cashier)
                log_type = f"monthly:{ltype}"
            elif scheme == "sp5":
                days = int((v_days.get() or "").strip())
                ms = int((v_max_stations.get() or "").strip())
                allow_cashier = bool(v_allow_cashier.get())
                key = generate_payload_activation_key(school, system_code, days_valid=days, max_stations=ms, allow_cashier=allow_cashier)
                log_type = f"sp5:{days}d:{ms}st:cashier={1 if allow_cashier else 0}"
            else:
                key = generate_activation_key(school, system_code, ltype)
                log_type = f"legacy:{ltype}"
        except Exception as e:
            messagebox.showerror("שגיאה", f"שגיאה ביצירת רישיון: {e}")
            return
        v_key.set(str(key))
        try:
            log_issued_license(school, system_code, log_type, str(key))
        except Exception:
            pass

    def copy_key():
        key = (v_key.get() or "").strip()
        if not key:
            messagebox.showwarning("אין מה להעתיק", "עדיין לא נוצר רישיון.")
            return
        root.clipboard_clear()
        root.clipboard_append(key)

    def _safe_filename_part(s: str) -> str:
        s = (s or "").strip()
        s = s.replace("\\", "_").replace("/", "_").replace(":", "_")
        s = s.replace("*", "_").replace("?", "_").replace('"', "_")
        s = s.replace("<", "_").replace(">", "_").replace("|", "_")
        s = s.replace("\n", " ").replace("\r", " ").strip()
        return s[:80] if len(s) > 80 else s

    def save_key():
        key = (v_key.get() or "").strip()
        if not key:
            messagebox.showwarning("אין מה לשמור", "עדיין לא נוצר רישיון.")
            return

        school = _safe_filename_part(v_school.get())
        system_code = _safe_filename_part(v_system.get())
        scheme = _scheme_code()
        ltype = _ltype_code()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")

        default_name = f"רישיון_{school}_{system_code}_{scheme}_{ltype}_{ts}.txt".replace("__", "_")

        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = filedialog.asksaveasfilename(
            title="שמירת רישיון לקובץ",
            initialdir=base_dir,
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("קובץ טקסט", "*.txt"), ("כל הקבצים", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(key)
                f.write("\n")
            messagebox.showinfo("נשמר", "הרישיון נשמר בהצלחה.")
        except Exception as e:
            messagebox.showerror("שגיאה", f"לא ניתן לשמור לקובץ: {e}")

    btns = ttk.Frame(frm)
    btns.grid(row=10, column=0, columnspan=2, sticky="e", pady=(10, 0))
    ttk.Button(btns, text="צור רישיון", command=generate).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(btns, text="העתק", command=copy_key).grid(row=0, column=1)
    ttk.Button(btns, text="שמור לקובץ", command=save_key).grid(row=0, column=2, padx=(8, 0))

    v_scheme.trace_add("write", update_enabled)
    update_enabled()
    root.after(50, lambda: None)
    root.mainloop()


if __name__ == "__main__":
    if any(a.strip().lower() in ("--cli", "/cli") for a in sys.argv[1:]):
        run_cli()
    else:
        # GUI entrypoint (added below)
        run_gui()
