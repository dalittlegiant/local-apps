"""Tests for office-comms-pdf-toolkit/toolkit_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402
from pypdf import PdfReader  # noqa: E402

import toolkit_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


def pages(data: bytes) -> int:
    return len(PdfReader(io.BytesIO(data)).pages)


def make_pdf(n_pages: int = 2, with_table: bool = False) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for i in range(n_pages):
        c.setFont("Helvetica", 12)
        c.drawString(72, 750, f"Page {i + 1} content")
        if with_table and i == 0:
            from reportlab.platypus import Table, TableStyle
            from reportlab.lib import colors
            t = Table([["Name", "Amt"], ["Amy", "10"], ["Bob", "20"]])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1,
                                    colors.black)]))
            t.wrapOn(c, 72, 500)
            t.drawOn(c, 72, 500)
        c.showPage()
    c.save()
    return buf.getvalue()


# --- comms ---------------------------------------------------------------
for key, tpl in core.TEMPLATES.items():
    vals = {name: default for name, _, default in tpl["variables"]}
    out = core.render_comms(key, vals)
    check(f"comms {key}: no unfilled vars",
          "{" not in out["subject"] and "{" not in out["email"]
          and "{" not in out["teams"])
    check(f"comms {key}: checklist non-empty", len(out["checklist"]) >= 3)
check("comms custom values used",
      "Q3 Launch" in core.render_comms(
          "new_dashboard",
          {"dashboard_name": "Q3 Launch", "launch_date": "d", "owner": "o",
           "link": "l", "audience": "a"})["subject"])

# --- pdf merge/split ------------------------------------------------------
p1, p2 = make_pdf(2), make_pdf(3)
merged = core.merge_pdfs([p1, p2])
check("merge page count", pages(merged) == 5)
try:
    core.merge_pdfs([])
    check("merge empty rejected", False)
except ValueError:
    check("merge empty rejected", True)
try:
    core.merge_pdfs([b"not a pdf"])
    check("merge invalid rejected", False)
except ValueError:
    check("merge invalid rejected", True)

check("range parse", core.parse_page_range("1-3,5", 6) == [0, 1, 2, 4])
check("range dedupes", core.parse_page_range("2,2-3", 6) == [1, 2])
for bad in ("0", "3-1", "abc", "7", ""):
    try:
        core.parse_page_range(bad, 6)
        check(f"range rejects '{bad}'", False)
    except ValueError:
        check(f"range rejects '{bad}'", True)

split = core.split_pdf(p1, [0])
check("split keeps 1 page", pages(split) == 1)

# --- watermark --------------------------------------------------------------
wm = core.add_watermark(p1, "CONFIDENTIAL", opacity=0.3, font_size=48)
check("watermark keeps pages", pages(wm) == 2)
check("watermark changes bytes", wm != p1)
try:
    core.add_watermark(p1, "   ")
    check("watermark empty rejected", False)
except ValueError:
    check("watermark empty rejected", True)

# --- table extraction --------------------------------------------------------
pt = make_pdf(2, with_table=True)
tables = core.extract_tables(pt)
check("table found", len(tables) >= 1)
pi, ti, df, strat = tables[0]
check("table header", list(df.columns)[:2] == ["Name", "Amt"], str(list(df.columns)))
check("table rows", len(df) == 2 and df.iloc[0, 0] == "Amy")
check("strategy reported", strat in core.STRATEGY_LABELS, strat)
xl = core.tables_to_excel(tables)
check("tables excel non-empty", len(xl) > 1000)
try:
    core.tables_to_excel([])
    check("tables excel empty rejected", False)
except ValueError:
    check("tables excel empty rejected", True)

# --- multi-strategy table extraction ------------------------------------------
def make_bordered_table_pdf() -> bytes:
    """Real vector grid lines (reportlab Table with GRID style)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Table, TableStyle
    from reportlab.lib import colors
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    t = Table([["Name", "Dept", "Amt"],
               ["Amy", "Sales", "10"],
               ["Bob", "IT", "20"]])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 1, colors.black)]))
    t.wrapOn(c, 72, 500)
    t.drawOn(c, 72, 500)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_borderless_table_pdf() -> bytes:
    """Shaded banding, aligned columns, zero grid lines."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    rows = [["Name", "Dept", "Amt"],
            ["Amy", "Sales", "10"],
            ["Bob", "IT", "20"],
            ["Cat", "HR", "30"]]
    y = 700
    for i, row in enumerate(rows):
        if i % 2 == 0:  # shaded bands, no lines
            c.setFillColor(colors.HexColor("#E8EEF7"))
            c.rect(60, y - 14, 480, 20, stroke=0, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 11)
        c.drawString(70, y, row[0])
        c.drawString(220, y, row[1])
        c.drawString(370, y, row[2])
        y -= 28
    c.showPage()
    c.save()
    return buf.getvalue()


bordered = make_bordered_table_pdf()
bt = core.extract_tables(bordered, mode="auto")
check("auto: bordered table found", len(bt) >= 1)
_, _, bdf, bstrat = bt[0]
check("auto: bordered uses grid strategy", bstrat == "grid", bstrat)
check("auto: bordered content",
      list(bdf.columns) == ["Name", "Dept", "Amt"]
      and len(bdf) == 2 and bdf.iloc[1, 0] == "Bob",
      str(list(bdf.columns)))

borderless = make_borderless_table_pdf()
ut = core.extract_tables(borderless, mode="auto")
check("auto: borderless table found", len(ut) >= 1)
_, _, udf, ustrat = ut[0]
check("auto: borderless falls back past grid",
      ustrat in ("text", "pymupdf-text"), ustrat)
check("auto: borderless content",
      list(udf.columns) == ["Name", "Dept", "Amt"]
      and len(udf) == 3 and udf.iloc[2, 0] == "Cat",
      str(list(udf.columns)) + str(len(udf)))

gt = core.extract_tables(bordered, mode="grid")
check("forced grid: bordered found via grid",
      len(gt) >= 1 and gt[0][3] == "grid",
      str([t[3] for t in gt]))
gt2 = core.extract_tables(borderless, mode="grid")
check("forced grid: borderless yields nothing",
      all(t[3] in ("grid", "pymupdf") for t in gt2) and
      not any(t[3] == "grid" for t in gt2),
      str([t[3] for t in gt2]))

bt2 = core.extract_tables(borderless, mode="borderless")
check("forced borderless: table found, no grid",
      len(bt2) >= 1 and bt2[0][3] in ("text", "pymupdf-text"),
      str([t[3] for t in bt2]))

try:
    core.extract_tables(bordered, mode="bogus")
    check("bad mode rejected", False)
except ValueError:
    check("bad mode rejected", True)

# --- beautify -----------------------------------------------------------------
img = Image.new("RGB", (200, 100), "white")
inner = Image.new("RGB", (160, 70), "navy")
img.paste(inner, (20, 15))

b1 = core.beautify(img, {"trim": True, "padding": 0, "radius": 0,
                         "shadow": False})
check("trim removes border", b1.size == (160, 70), str(b1.size))

b2 = core.beautify(img, {"trim": False, "padding": 10, "pad_color": "#FFFFFF",
                         "radius": 12, "shadow": False})
check("padding grows canvas", b2.size == (220, 120))
check("rounded corners transparent", b2.mode == "RGBA"
      and b2.getpixel((0, 0))[3] == 0)

b3 = core.beautify(img, {"trim": False, "padding": 10, "pad_color": "#FFFFFF",
                         "radius": 12, "shadow": True, "shadow_blur": 18,
                         "shadow_offset": 12, "shadow_opacity": 45})
check("shadow grows canvas", b3.size[0] > 220 and b3.size[1] > 120)

b4 = core.beautify(img, {"trim": False, "crop_l": 10, "crop_t": 10,
                         "crop_r": 10, "crop_b": 10, "padding": 0,
                         "radius": 0, "shadow": False})
check("manual crop", b4.size == (160, 80), str(b4.size))

print(f"\nAll {passed} checks passed.")
