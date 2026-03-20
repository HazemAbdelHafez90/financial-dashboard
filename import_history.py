#!/usr/bin/env python3
"""
Import all historical months from Apple Numbers Spendings.numbers into Supabase.
Mar-26 is already imported and will be skipped.
"""

import sys
import warnings
import numbers_parser
import requests
import json
import uuid
from datetime import date, datetime
import calendar

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ── Supabase config ──────────────────────────────────────────────────────────
SUPA_URL = "https://ppxzhhcceivcdxxxwxqh.supabase.co"
SUPA_KEY = "sb_publishable_Bx6XHBQMEnKFJHcv_EEJ6Q_SF9DmA31"
HEADERS = {
    "apikey": SUPA_KEY,
    "Authorization": f"Bearer {SUPA_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}
UPSERT_HEADERS = {**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"}

NUMBERS_PATH = "/Users/hazem/Library/Mobile Documents/com~apple~Numbers/Documents/Spendings.numbers"

# ── Month key mapping ────────────────────────────────────────────────────────
# Sheet name → (YYYY, MM, label)
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
    # Mar-26 is already imported – skip
}

# ── Category name mapping ────────────────────────────────────────────────────
CAT_MAP = {
    "Hazem":  "Hazem Personal",
    "Hazem ": "Hazem Personal",
    "Home ":  "Home",
    "Fuel ":  "Fuel",
}


def normalize_cat(cat):
    if cat is None:
        return None
    cat = cat.strip()
    return CAT_MAP.get(cat, cat)


# ── Helpers ──────────────────────────────────────────────────────────────────

def cell_val(cell):
    """Return the Python value of a Numbers cell, or None."""
    v = cell.value
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    return v


def table_by_name_fuzzy(sheet, *candidates):
    """Find the first table whose name matches any of the candidates (case-insensitive prefix)."""
    names = {t.name: t for t in sheet.tables}
    for c in candidates:
        for name, table in names.items():
            if name.strip().lower() == c.strip().lower():
                return table
        for name, table in names.items():
            if name.strip().lower().startswith(c.strip().lower()):
                return table
    return None


def get_table(sheet, *names):
    t = table_by_name_fuzzy(sheet, *names)
    return t


def rows_as_dicts(table):
    """Return list of {col_header: value} dicts (skips header row)."""
    rows = list(table.rows())
    if not rows:
        return []
    header = [str(c.value).strip() if c.value is not None else f"col{i}"
              for i, c in enumerate(rows[0])]
    result = []
    for row in rows[1:]:
        d = {}
        for i, cell in enumerate(row):
            key = header[i] if i < len(header) else f"col{i}"
            d[key] = cell_val(cell)
        result.append(d)
    return result


def last_day_of_month(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


# ── Income / forex extraction ────────────────────────────────────────────────

def get_income_data(sheet):
    """
    Returns (income_usd, income_egp, income_rate).
    income_usd  = USD salary from Income table
    income_rate = EGP/USD rate from Currencies Details
    income_egp  = income_usd * income_rate
    """
    income_usd = None
    income_rate = None

    # Try Income table
    inc_table = get_table(sheet, "Income")
    if inc_table:
        rows = list(inc_table.rows())
        if len(rows) >= 2:
            # Row 0 = header, Row 1 = values; Salary is col 0
            salary_val = cell_val(rows[1][0])
            income_usd = safe_float(salary_val)

    # Try Currencies Details for USD rate
    curr_table = get_table(sheet, "Currencies Details")
    if curr_table:
        rows = list(curr_table.rows())
        if len(rows) >= 2:
            # Find the header row to know which column is the rate
            header = [str(c.value).strip().lower() if c.value is not None else ""
                      for c in rows[0]]
            # Look for USD row
            for row in rows[1:]:
                currency = str(cell_val(row[0])).strip().upper() if cell_val(row[0]) else ""
                if currency == "USD":
                    # Always prefer "Black market multiplier" — that's the real rate used
                    rate_col = None
                    for priority_col in ["black market multiplier",
                                         "mutiplier", "multiplier",
                                         "bank rate", "conversion rate", "normal value"]:
                        if priority_col in header:
                            rate_col = header.index(priority_col)
                            break
                    if rate_col is not None and rate_col < len(row):
                        income_rate = safe_float(cell_val(row[rate_col]))
                    break

    income_egp = None
    if income_usd and income_rate:
        income_egp = round(income_usd * income_rate, 2)

    return income_usd, income_egp, income_rate


# ── Details extraction (individual expense rows) ─────────────────────────────

def get_detail_categories_from_pivot(sheet):
    """
    Return set of category names that appear in the Details Pivot table.
    Handles both:
      - 2-col pivot:  Category | Amount (Sum)
      - 3-col pivot:  Category | Item | Amount (Sum)
    """
    pivot = get_table(sheet, "Details Pivot", "Table 1 Pivot", "Summary")
    if not pivot:
        return set()

    rows = list(pivot.rows())
    if not rows:
        return set()

    header = [str(c.value).strip().lower() if c.value is not None else ""
              for c in rows[0]]

    cats = set()
    current_cat = None

    # Find category column index
    cat_col = 0  # usually first column

    for row in rows[1:]:
        raw_cat = cell_val(row[cat_col]) if cat_col < len(row) else None
        cat_str = str(raw_cat).strip() if raw_cat is not None else ""

        if cat_str and cat_str.lower() not in ("", "total", "category"):
            current_cat = normalize_cat(cat_str)
            cats.add(current_cat)
        # For 3-col pivot, even rows without category belong to the current one
        # but we only need the category set here

    return cats


def get_detail_expenses(sheet, year, month, month_key):
    """
    Return list of expense dicts from the Details / Table 1 table.
    Column order variants:
      - Item | Category | Date | Amount
      - Item | Amount | Category | Date   (early sheets: Aug-Dec 2023 Details)
      - Item | Category | Amount | Date   (most 2024/2025 sheets)
    """
    details_table = get_table(sheet, "Details", "Table 1")
    if not details_table:
        # Some months have a separate Details sheet
        return []

    rows = list(details_table.rows())
    if not rows:
        return []

    # Parse header
    raw_header = [str(c.value).strip().lower() if c.value is not None else f"col{i}"
                  for i, c in enumerate(rows[0])]

    # Detect column positions
    def find_col(*names):
        for n in names:
            if n in raw_header:
                return raw_header.index(n)
        return None

    item_col   = find_col("item", "description")
    cat_col    = find_col("category")
    amount_col = find_col("amount")
    date_col   = find_col("date")

    # Some sheets have columns differently ordered — fallback by position
    # Known layouts from exploration:
    # "Item | Category | Date | Amount"  → item=0, cat=1, date=2, amount=3
    # "Item | Amount | Category | Date"  → item=0, amount=1, cat=2, date=3
    # "Item | Category | Amount | Date"  → item=0, cat=1, amount=2, date=3

    if item_col is None:
        item_col = 0
    if cat_col is None:
        # If we can't find 'category', skip this table (not a details table)
        return []
    if amount_col is None:
        return []
    if date_col is None:
        return []

    expenses = []
    last_day = last_day_of_month(year, month)

    for idx, row in enumerate(rows[1:], 1):
        if len(row) <= max(item_col, cat_col, amount_col, date_col):
            continue

        item_val   = cell_val(row[item_col])
        cat_val    = cell_val(row[cat_col])
        amount_val = cell_val(row[amount_col])
        date_val   = cell_val(row[date_col])

        # Skip empty rows
        if item_val is None and cat_val is None and amount_val is None:
            continue

        desc  = str(item_val).strip() if item_val is not None else ""
        cat   = normalize_cat(str(cat_val).strip()) if cat_val is not None else None
        amount = safe_float(amount_val)

        if not desc and not cat:
            continue
        if amount is None or amount == 0:
            continue

        # Parse date
        if isinstance(date_val, datetime):
            exp_date = date_val.date().isoformat()
        elif isinstance(date_val, date):
            exp_date = date_val.isoformat()
        else:
            exp_date = last_day.isoformat()

        expenses.append({
            "id": f"{month_key}-d-{idx}-{uuid.uuid4().hex[:6]}",
            "date": exp_date,
            "description": desc,
            "category": cat,
            "amount": amount,
            "month_key": month_key,
            "type": "Planned",
        })

    return expenses


# ── Budget / lump-sum extraction ──────────────────────────────────────────────

def get_budget_expenses(sheet, year, month, month_key, detail_categories):
    """
    Return lump-sum expenses for budget categories NOT covered by detail records.
    Budget table is the one named after the month (e.g. "Jan", "Feb-23", etc.)
    """
    # Possible budget table names
    month_abbrevs = {
        1: ["Jan", "January"],
        2: ["Feb", "February"],
        3: ["Mar", "March"],
        4: ["Apr", "April"],
        5: ["May"],
        6: ["Jun", "June"],
        7: ["Jul", "July"],
        8: ["Aug", "August"],
        9: ["Sept", "Sep", "September"],
        10: ["Oct", "October"],
        11: ["Nov", "November"],
        12: ["Dec", "December"],
    }

    candidates = month_abbrevs.get(month, [])
    budget_table = None
    for c in candidates:
        t = table_by_name_fuzzy(sheet, c)
        if t is not None:
            rows = list(t.rows())
            if rows and len(rows) > 1:
                # Verify it's a budget table: header has Planned/Spent columns
                header_row = [str(cell.value).strip().lower() if cell.value else ""
                              for cell in rows[0]]
                if "planned" in header_row or "spent" in header_row:
                    budget_table = t
                    break

    if budget_table is None:
        return []

    rows = list(budget_table.rows())
    header = [str(c.value).strip().lower() if c.value is not None else f"col{i}"
              for i, c in enumerate(rows[0])]

    # Find spent column
    spent_col = None
    for name in ["spent", "actual", "actuall"]:
        if name in header:
            spent_col = header.index(name)
            break
    if spent_col is None and len(header) >= 3:
        spent_col = 2  # fallback: 3rd column

    last_day = last_day_of_month(year, month)
    expenses = []

    for idx, row in enumerate(rows[1:], 1):
        if not row or not row[0].value:
            continue

        raw_cat = str(cell_val(row[0])).strip()
        if not raw_cat or raw_cat.lower() in ("total", ""):
            continue

        norm_cat = normalize_cat(raw_cat)

        # Skip categories that are in detail_categories (they already have individual records)
        if norm_cat in detail_categories:
            continue

        # Get spent amount
        spent = None
        if spent_col is not None and spent_col < len(row):
            spent = safe_float(cell_val(row[spent_col]))

        if not spent or spent <= 0:
            continue

        expenses.append({
            "id": f"{month_key}-b-{idx}-{uuid.uuid4().hex[:6]}",
            "date": last_day.isoformat(),
            "description": raw_cat,
            "category": norm_cat,
            "amount": spent,
            "month_key": month_key,
            "type": "Planned",
        })

    return expenses


# ── Early sheets (April/May/June/July 2023) ───────────────────────────────────

def process_early_sheet(sheet, year, month, month_key, label):
    """
    April/May/June/July 2023 have simple "Item | Amount" tables with no Details.
    Import all non-empty items as lump-sum budget expenses.
    """
    # Find the main table (named after the month)
    month_abbrevs = {
        4: ["April", "Apr"],
        5: ["May"],
        6: ["June", "Jun"],
        7: ["July", "Jul"],
    }
    candidates = month_abbrevs.get(month, [])
    main_table = None
    for c in candidates:
        t = table_by_name_fuzzy(sheet, c)
        if t is not None:
            rows = list(t.rows())
            if rows and len(rows) > 1:
                main_table = t
                break

    expenses = []
    last_day = last_day_of_month(year, month)

    if main_table:
        rows = list(main_table.rows())
        header = [str(c.value).strip().lower() if c.value is not None else f"col{i}"
                  for i, c in enumerate(rows[0])]

        # Detect if it has Planned/Spent structure or Item/Amount structure
        if "planned" in header or "spent" in header:
            # It's a proper budget table
            spent_col = header.index("spent") if "spent" in header else 2
            for idx, row in enumerate(rows[1:], 1):
                if not row or not row[0].value:
                    continue
                raw_cat = str(cell_val(row[0])).strip()
                if not raw_cat or raw_cat.lower() in ("total", ""):
                    continue
                norm_cat = normalize_cat(raw_cat)
                spent = safe_float(cell_val(row[spent_col])) if spent_col < len(row) else None
                if not spent or spent <= 0:
                    continue
                expenses.append({
                    "id": f"{month_key}-b-{idx}-{uuid.uuid4().hex[:6]}",
                    "date": last_day.isoformat(),
                    "description": raw_cat,
                    "category": norm_cat,
                    "amount": spent,
                    "month_key": month_key,
                    "type": "Planned",
                })
        else:
            # Simple Item | Amount list
            amount_col = header.index("amount") if "amount" in header else 1
            for idx, row in enumerate(rows[1:], 1):
                if not row or not row[0].value:
                    continue
                raw_item = str(cell_val(row[0])).strip()
                if not raw_item or raw_item.lower() in ("total", ""):
                    continue
                amount = safe_float(cell_val(row[amount_col])) if amount_col < len(row) else None
                if not amount or amount <= 0:
                    continue
                expenses.append({
                    "id": f"{month_key}-b-{idx}-{uuid.uuid4().hex[:6]}",
                    "date": last_day.isoformat(),
                    "description": raw_item,
                    "category": raw_item,
                    "amount": amount,
                    "month_key": month_key,
                    "type": "Planned",
                })

    # Income data
    income_usd, income_egp, income_rate = get_income_data(sheet)

    return expenses, income_usd, income_egp, income_rate


# ── Sheets that have Details in a separate tab ────────────────────────────────

SEPARATE_DETAILS_SHEETS = {
    # sheet_name → details_sheet_name
    "July":    "July Details",
    "August":  "August Details",
    "Sept":    "Sept Details",
    "Oct":     "Oct Details",
    "Nov":     "Nov Details",
    "Dec":     "Dec Details",
}


def get_detail_expenses_from_separate_sheet(doc, details_sheet_name, year, month, month_key):
    """
    For Aug-Dec 2023 where details are in a separate sheet.
    Table structure: Item | Amount | Category | Date
    """
    try:
        details_sheet = doc.sheets[details_sheet_name]
    except (KeyError, IndexError):
        return []

    # Find the table (could be 'Table 1-1', 'Sept Details', 'Oct Details', etc.)
    details_table = None
    for t in details_sheet.tables:
        rows = list(t.rows())
        if len(rows) > 1:
            header = [str(c.value).strip().lower() if c.value else ""
                      for c in rows[0]]
            if "item" in header and "category" in header:
                details_table = t
                break

    if details_table is None:
        return []

    rows = list(details_table.rows())
    header = [str(c.value).strip().lower() if c.value is not None else f"col{i}"
              for i, c in enumerate(rows[0])]

    item_col   = header.index("item") if "item" in header else 0
    cat_col    = header.index("category") if "category" in header else 2
    amount_col = header.index("amount") if "amount" in header else 1
    date_col   = header.index("date") if "date" in header else 3

    last_day = last_day_of_month(year, month)
    expenses = []

    for idx, row in enumerate(rows[1:], 1):
        if len(row) <= max(item_col, cat_col, amount_col, date_col):
            continue

        item_val   = cell_val(row[item_col])
        cat_val    = cell_val(row[cat_col])
        amount_val = cell_val(row[amount_col])
        date_val   = cell_val(row[date_col])

        if item_val is None and cat_val is None:
            continue

        desc   = str(item_val).strip() if item_val is not None else ""
        cat    = normalize_cat(str(cat_val).strip()) if cat_val is not None else None
        amount = safe_float(amount_val)

        if not desc and not cat:
            continue
        if amount is None or amount == 0:
            continue

        if isinstance(date_val, datetime):
            exp_date = date_val.date().isoformat()
        elif isinstance(date_val, date):
            exp_date = date_val.isoformat()
        else:
            exp_date = last_day.isoformat()

        expenses.append({
            "id": f"{month_key}-d-{idx}-{uuid.uuid4().hex[:6]}",
            "date": exp_date,
            "description": desc,
            "category": cat,
            "amount": amount,
            "month_key": month_key,
            "type": "Planned",
        })

    return expenses


# ── Supabase helpers ──────────────────────────────────────────────────────────

def delete_month_expenses(month_key):
    """Delete all expenses for the given month_key."""
    r = requests.delete(
        f"{SUPA_URL}/rest/v1/expenses?month_key=eq.{month_key}",
        headers=HEADERS,
    )
    if r.status_code not in (200, 204):
        print(f"  [WARN] DELETE expenses failed for {month_key}: {r.status_code} {r.text[:200]}")


def upsert_month_config(month_key, label, income_egp, income_usd, income_rate):
    payload = {
        "month_key": month_key,
        "label": label,
        "started": False,
    }
    if income_egp is not None:
        payload["income"] = round(income_egp, 2)
    if income_usd is not None:
        payload["income_usd"] = round(income_usd, 2)
    if income_rate is not None:
        payload["income_rate"] = round(income_rate, 4)

    r = requests.post(
        f"{SUPA_URL}/rest/v1/month_configs",
        headers=UPSERT_HEADERS,
        json=payload,
    )
    if r.status_code not in (200, 201, 204):
        print(f"  [WARN] UPSERT month_config failed for {month_key}: {r.status_code} {r.text[:200]}")


def insert_expenses(expenses):
    """Bulk insert expenses in chunks of 500."""
    if not expenses:
        return
    chunk_size = 500
    for i in range(0, len(expenses), chunk_size):
        chunk = expenses[i:i + chunk_size]
        r = requests.post(
            f"{SUPA_URL}/rest/v1/expenses",
            headers=HEADERS,
            json=chunk,
        )
        if r.status_code not in (200, 201, 204):
            print(f"  [ERROR] INSERT expenses failed: {r.status_code} {r.text[:300]}")


# ── Main processing ───────────────────────────────────────────────────────────

def process_month(doc, sheet_name, year, month, month_key, label):
    """Process a single month sheet and return (expense_count, total_amount)."""
    sheet = doc.sheets[sheet_name]

    # ── Special case: early sheets April/May/June/July 2023 ──
    if sheet_name in ("April", "May", "June", "July") and year == 2023:
        expenses, income_usd, income_egp, income_rate = process_early_sheet(
            sheet, year, month, month_key, label
        )
        delete_month_expenses(month_key)
        upsert_month_config(month_key, label, income_egp, income_usd, income_rate)
        insert_expenses(expenses)
        total = sum(e["amount"] for e in expenses)
        return len(expenses), total

    # ── Sheets with separate Details tab (Aug-Dec 2023) ──
    has_separate = sheet_name in SEPARATE_DETAILS_SHEETS

    if has_separate:
        details_sheet_name = SEPARATE_DETAILS_SHEETS[sheet_name]
        detail_expenses = get_detail_expenses_from_separate_sheet(
            doc, details_sheet_name, year, month, month_key
        )
        # Get category set from detail expenses
        detail_categories = set(e["category"] for e in detail_expenses if e["category"])
    else:
        # Normal case: Details Pivot + Details tables in same sheet
        detail_categories = get_detail_categories_from_pivot(sheet)
        detail_expenses = get_detail_expenses(sheet, year, month, month_key)
        # Filter detail expenses to only those in detail_categories
        # (handles case where Details table has extra rows)
        # Actually keep all detail expenses regardless
        # BUT for lump-sum determination use the categories present in pivot
        # (which means we already have the right set)

    # ── Budget lump-sum expenses ──
    budget_expenses = get_budget_expenses(
        sheet, year, month, month_key, detail_categories
    )

    all_expenses = detail_expenses + budget_expenses

    # ── Income ──
    income_usd, income_egp, income_rate = get_income_data(sheet)

    # ── Supabase writes ──
    delete_month_expenses(month_key)
    upsert_month_config(month_key, label, income_egp, income_usd, income_rate)
    insert_expenses(all_expenses)

    total = sum(e["amount"] for e in all_expenses)
    return len(all_expenses), total


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("Loading Numbers document...")
    doc = numbers_parser.Document(NUMBERS_PATH)
    print(f"Loaded. Found {len(doc.sheets)} sheets.\n")

    summary = []
    total_expenses = 0

    for sheet_name, (year, month, label) in SHEET_MONTH_MAP.items():
        month_key = f"{year:04d}-{month:02d}"

        # Skip Mar-26 (already imported)
        if month_key == "2026-03":
            print(f"  SKIP {sheet_name} ({month_key}) — already imported")
            continue

        # Verify sheet exists
        try:
            _ = doc.sheets[sheet_name]
        except (KeyError, IndexError):
            print(f"  SKIP {sheet_name} — sheet not found in document")
            continue

        print(f"Processing {sheet_name} ({month_key})...", end=" ", flush=True)

        try:
            count, total = process_month(doc, sheet_name, year, month, month_key, label)
            summary.append((month_key, label, count, total))
            total_expenses += count
            print(f"OK — {count} expenses, EGP {total:,.0f}")
        except Exception as e:
            import traceback
            print(f"ERROR — {e}")
            traceback.print_exc()
            summary.append((month_key, label, 0, 0))

    # ── Summary ──
    print("\n" + "=" * 70)
    print(f"{'Month Key':<12} {'Label':<22} {'Expenses':>9} {'Total EGP':>14}")
    print("-" * 70)
    grand_total = 0
    for mk, lbl, cnt, tot in summary:
        print(f"{mk:<12} {lbl:<22} {cnt:>9,} {tot:>14,.0f}")
        grand_total += tot
    print("-" * 70)
    print(f"{'TOTAL':<35} {total_expenses:>9,} {grand_total:>14,.0f}")
    print(f"\nImported {len(summary)} months, {total_expenses} total expenses.")


if __name__ == "__main__":
    main()
