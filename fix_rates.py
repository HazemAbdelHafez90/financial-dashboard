#!/usr/bin/env python3
"""
Re-read every month's Currencies Details table and update income_rate in month_configs
to use the Black market multiplier (USD column) for each month.
"""
import warnings, requests, numbers_parser
from datetime import datetime, date

warnings.filterwarnings("ignore", category=RuntimeWarning)

SUPA_URL = "https://ppxzhhcceivcdxxxwxqh.supabase.co"
SUPA_KEY = "sb_publishable_Bx6XHBQMEnKFJHcv_EEJ6Q_SF9DmA31"
HEADERS = {
    "apikey": SUPA_KEY,
    "Authorization": f"Bearer {SUPA_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

NUMBERS_PATH = "/Users/hazem/Library/Mobile Documents/com~apple~Numbers/Documents/Spendings.numbers"

SHEET_MONTH_MAP = {
    "April":     (2023, 4,  "April 2023"),
    "May":       (2023, 5,  "May 2023"),
    "June":      (2023, 6,  "June 2023"),
    "July":      (2023, 7,  "July 2023"),
    "August":    (2023, 8,  "August 2023"),
    "Sept":      (2023, 9,  "September 2023"),
    "Oct":       (2023, 10, "October 2023"),
    "Nov":       (2023, 11, "November 2023"),
    "Dec":       (2023, 12, "December 2023"),
    "Jan-24":    (2024, 1,  "January 2024"),
    "Feb-24":    (2024, 2,  "February 2024"),
    "March-24":  (2024, 3,  "March 2024"),
    "April-24":  (2024, 4,  "April 2024"),
    "May-24":    (2024, 5,  "May 2024"),
    "June-24":   (2024, 6,  "June 2024"),
    "July-24":   (2024, 7,  "July 2024"),
    "August-24": (2024, 8,  "August 2024"),
    "Sept-24":   (2024, 9,  "September 2024"),
    "Oct-24":    (2024, 10, "October 2024"),
    "Nov-24":    (2024, 11, "November 2024"),
    "Dec-24":    (2024, 12, "December 2024"),
    "Jan-25":    (2025, 1,  "January 2025"),
    "Feb-25":    (2025, 2,  "February 2025"),
    "Mar-25":    (2025, 3,  "March 2025"),
    "April-25":  (2025, 4,  "April 2025"),
    "May-25":    (2025, 5,  "May 2025"),
    "June-25":   (2025, 6,  "June 2025"),
    "July-25":   (2025, 7,  "July 2025"),
    "Aug-25":    (2025, 8,  "August 2025"),
    "Sept-25":   (2025, 9,  "September 2025"),
    "Oct-25":    (2025, 10, "October 2025"),
    "Nov-25":    (2025, 11, "November 2025"),
    "Dec-25":    (2025, 12, "December 2025"),
    "Jan-26":    (2026, 1,  "January 2026"),
    "Feb-26":    (2026, 2,  "February 2026"),
    "Mar-26":    (2026, 3,  "March 2026"),  # include Mar-26 for rate fix
}


def cell_val(cell):
    v = cell.value
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v
    return v


def safe_float(v):
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def table_by_name_fuzzy(sheet, *candidates):
    names = {t.name: t for t in sheet.tables}
    for c in candidates:
        for name, table in names.items():
            if name.strip().lower() == c.strip().lower():
                return table
        for name, table in names.items():
            if name.strip().lower().startswith(c.strip().lower()):
                return table
    return None


def get_income_data(sheet):
    """
    Returns (income_usd, income_egp, income_rate).
    Prioritises Black market multiplier for the USD rate.
    """
    income_usd = None
    income_rate = None

    # Income table → USD salary
    inc_table = table_by_name_fuzzy(sheet, "Income")
    if inc_table:
        rows = list(inc_table.rows())
        if len(rows) >= 2:
            salary_val = cell_val(rows[1][0])
            income_usd = safe_float(salary_val)

    # Currencies Details → Black market multiplier for USD
    curr_table = table_by_name_fuzzy(sheet, "Currencies Details")
    if curr_table:
        rows = list(curr_table.rows())
        if len(rows) >= 2:
            header = [str(c.value).strip().lower() if c.value is not None else ""
                      for c in rows[0]]
            for row in rows[1:]:
                currency = str(cell_val(row[0])).strip().upper() if cell_val(row[0]) else ""
                if currency == "USD":
                    # Priority: Black market multiplier first
                    rate_col = None
                    for col_name in ["black market multiplier",
                                     "mutiplier", "multiplier",
                                     "bank rate", "conversion rate", "normal value"]:
                        if col_name in header:
                            rate_col = header.index(col_name)
                            break
                    if rate_col is not None and rate_col < len(row):
                        income_rate = safe_float(cell_val(row[rate_col]))
                    break

    income_egp = round(income_usd * income_rate, 2) if income_usd and income_rate else None
    return income_usd, income_egp, income_rate


def main():
    print("Loading Numbers document...")
    doc = numbers_parser.Document(NUMBERS_PATH)
    print(f"Loaded. {len(doc.sheets)} sheets.\n")

    print(f"{'Sheet':<14} {'Month':<12} {'USD Salary':>12} {'Rate (EGP/USD)':>15} {'EGP Salary':>12}")
    print("-" * 70)

    updated = 0
    skipped = 0

    for sheet_name, (year, month, label) in SHEET_MONTH_MAP.items():
        month_key = f"{year:04d}-{month:02d}"

        try:
            sheet = doc.sheets[sheet_name]
        except (KeyError, IndexError):
            print(f"  SKIP {sheet_name} — not found")
            skipped += 1
            continue

        income_usd, income_egp, income_rate = get_income_data(sheet)

        rate_str  = f"{income_rate:.4f}"  if income_rate  else "—"
        usd_str   = f"${income_usd:,.0f}" if income_usd   else "—"
        egp_str   = f"{income_egp:,.0f}"  if income_egp   else "—"
        print(f"  {sheet_name:<12} {month_key:<12} {usd_str:>12} {rate_str:>15} {egp_str:>12}")

        # Build PATCH payload — only send what we have
        payload = {"month_key": month_key, "label": label, "started": False}
        if income_usd   is not None: payload["income_usd"]  = round(income_usd,  2)
        if income_rate  is not None: payload["income_rate"] = round(income_rate, 4)
        if income_egp   is not None: payload["income"]      = round(income_egp,  2)

        r = requests.post(
            f"{SUPA_URL}/rest/v1/month_configs",
            headers=HEADERS,
            json=payload,
        )
        if r.status_code not in (200, 201, 204):
            print(f"    [ERROR] {r.status_code} {r.text[:200]}")
        else:
            updated += 1

    print("-" * 70)
    print(f"\nDone. {updated} months updated, {skipped} skipped.")


if __name__ == "__main__":
    main()
