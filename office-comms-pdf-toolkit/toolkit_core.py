"""Core logic for the Office Comms & PDF Toolkit. Pure — no ``st.*`` calls.

Covers: corporate comms templates, PDF merge/split/watermark/table
extraction, and the screenshot beautifier (Pillow: trim, padding, rounded
corners, drop shadow).

Table extraction is a multi-strategy pipeline (per page):
  1. pdfplumber ``lines``/``lines`` — bordered/grid tables (vector rules).
  2. pdfplumber ``text``/``text`` — borderless, text-aligned tables.
  3. PyMuPDF ``page.find_tables()`` — grid detection.
  4. PyMuPDF ``find_tables(text, text)`` — text-aligned detection.
  5. Legacy pypdf ``layout``-mode heuristic (2+ spaces delimit columns).
pdfplumber / PyMuPDF are optional at runtime: if either is not installed
(e.g. the Stlite/WASM export, where both are dropped — PyMuPDF has no
Pyodide wheel and pdfplumber needs pypdfium2), its strategies are skipped
and the pipeline degrades gracefully to the pure-Python heuristic.
"""

import io
import re

import pandas as pd
from PIL import Image, ImageChops, ImageDraw, ImageFilter


# ============================================================ comms
# Templates use str.format with {variables}. Literal braces must be doubled.
TEMPLATES: dict[str, dict] = {
    "new_dashboard": {
        "title": "New Dashboard Launch",
        "icon": "🚀",
        "variables": [
            ("dashboard_name", "Dashboard name", "Sales Performance Dashboard"),
            ("launch_date", "Launch date", "15 Nov 2026"),
            ("owner", "Owner / team", "Retail Analytics"),
            ("link", "Dashboard link", "https://…"),
            ("audience", "Audience", "all store managers"),
        ],
        "subject": "🚀 New dashboard live: {dashboard_name}",
        "email_body": (
            "Hi team,\n\n"
            "We are pleased to announce that **{dashboard_name}** is now live "
            "as of {launch_date}.\n\n"
            "**What it covers**\n"
            "Built for {audience}, it brings together the key metrics in one "
            "place so you no longer need to reconcile multiple reports.\n\n"
            "**Get started**\n"
            "👉 Open it here: {link}\n\n"
            "Please take 10 minutes to explore it this week. If anything "
            "looks off, reply to this email — {owner} monitors this inbox.\n\n"
            "Best regards,\n{owner}"
        ),
        "teams_message": (
            "🚀 **{dashboard_name}** is now LIVE ({launch_date})!\n"
            "👉 {link}\n"
            "Built for {audience}. Please explore it this week — questions to {owner}."
        ),
        "checklist": [
            "Dashboard published and link verified (open in incognito)",
            "Row-level security / audience filters tested with a viewer account",
            "Scheduled refresh confirmed running",
            "Announcement email drafted and proofread",
            "Teams post scheduled",
            "Owner inbox / support channel staffed for launch week",
        ],
    },
    "training_invite": {
        "title": "Training Invitation",
        "icon": "🎓",
        "variables": [
            ("course_name", "Course name", "Power BI Dashboard Training"),
            ("date_time", "Date & time", "20 Nov 2026, 2:00–4:00 PM"),
            ("venue", "Venue", "Room 1203, Kwun Tong Office"),
            ("trainer", "Trainer", "Retail Analytics team"),
            ("rsvp", "RSVP info", "Reply to this email by 18 Nov"),
        ],
        "subject": "🎓 Invitation: {course_name} — {date_time}",
        "email_body": (
            "Hi all,\n\n"
            "You are invited to **{course_name}**.\n\n"
            "📅 **When:** {date_time}\n"
            "📍 **Where:** {venue}\n"
            "👤 **Trainer:** {trainer}\n\n"
            "Please bring your laptop. Seats are limited — {rsvp}.\n\n"
            "Looking forward to seeing you there!"
        ),
        "teams_message": (
            "🎓 **{course_name}**\n"
            "📅 {date_time} · 📍 {venue}\n"
            "👤 {trainer}\n"
            "{rsvp}"
        ),
        "checklist": [
            "Attendee list finalized",
            "Room / Teams link booked and tested",
            "Training deck and hands-on dataset ready",
            "Laptops / access for attendees confirmed",
            "Calendar invites sent",
            "Reminder scheduled for 1 day before",
        ],
    },
    "schedule_change": {
        "title": "Venue / Schedule Change",
        "icon": "📢",
        "variables": [
            ("event_name", "Event name", "Monthly Business Review"),
            ("old_detail", "Original arrangement", "21 Nov, 10 AM, Room 1203"),
            ("new_detail", "New arrangement", "22 Nov, 2 PM, Room 1501"),
            ("reason", "Reason", "room maintenance"),
            ("contact", "Contact", "Retail Analytics"),
        ],
        "subject": "📢 Change: {event_name} — new arrangement",
        "email_body": (
            "Hi all,\n\n"
            "Please note a change to **{event_name}** due to {reason}.\n\n"
            "❌ **Was:** {old_detail}\n"
            "✅ **Now:** {new_detail}\n\n"
            "Your calendar invite has been updated. Apologies for any "
            "inconvenience — contact {contact} with questions."
        ),
        "teams_message": (
            "📢 **{event_name}** — arrangement changed ({reason})\n"
            "❌ Was: {old_detail}\n"
            "✅ Now: {new_detail}\n"
            "Calendar invite updated. Questions → {contact}."
        ),
        "checklist": [
            "Calendar invites updated for all attendees",
            "Room / link re-booked and confirmed",
            "Announcement sent (email + Teams)",
            "Materials / agenda timing adjusted if needed",
        ],
    },
    "refresh_delay": {
        "title": "Data Refresh Delay Notice",
        "icon": "⏳",
        "variables": [
            ("dataset_name", "Dataset / dashboard", "Daily Sales Dataset"),
            ("expected_time", "Expected recovery", "today 6:00 PM"),
            ("reason", "Reason", "upstream source delay"),
            ("contact", "Contact", "Retail Analytics"),
        ],
        "subject": "⏳ Data delay: {dataset_name}",
        "email_body": (
            "Hi all,\n\n"
            "Heads-up: today's refresh of **{dataset_name}** is delayed due "
            "to {reason}.\n\n"
            "🕐 **Expected recovery:** {expected_time}\n\n"
            "Please treat this morning's figures as yesterday's close until "
            "the refresh completes. We'll send an all-clear once it's done — "
            "no action needed from you. Questions → {contact}."
        ),
        "teams_message": (
            "⏳ **{dataset_name}** refresh delayed ({reason}).\n"
            "🕐 Expected recovery: {expected_time}.\n"
            "Treat current figures as yesterday's close. All-clear to follow."
        ),
        "checklist": [
            "Root cause identified with source owner",
            "Delay notice sent before stakeholders notice",
            "Refresh monitored until green",
            "All-clear message sent after recovery",
            "Incident noted for the next data-quality review",
        ],
    },
    "audit_reminder": {
        "title": "Governance / Audit Reminder",
        "icon": "🛡️",
        "variables": [
            ("audit_name", "Audit / review name", "Q4 Access Review"),
            ("deadline", "Deadline", "30 Nov 2026"),
            ("action", "Action required", "confirm your team's dashboard access list"),
            ("contact", "Contact", "Governance team"),
            ("link", "Review link", "https://…"),
        ],
        "subject": "🛡️ Action required: {audit_name} by {deadline}",
        "email_body": (
            "Hi all,\n\n"
            "Our periodic **{audit_name}** is now open. Please {action} "
            "by **{deadline}**.\n\n"
            "👉 Start here: {link}\n\n"
            "Access that is not confirmed by the deadline may be revoked per "
            "policy. Thank you for keeping our data secure — {contact}."
        ),
        "teams_message": (
            "🛡️ **{audit_name}** — action required by **{deadline}**.\n"
            "Please {action}.\n"
            "👉 {link}\n"
            "Unconfirmed access may be revoked per policy."
        ),
        "checklist": [
            "Review list / link prepared and tested",
            "Reminder sent to all in-scope owners",
            "Escalation path defined for non-responders",
            "Follow-up reminder scheduled mid-window",
            "Completion tracked centrally",
        ],
    },
}


def render_comms(template_key: str, values: dict) -> dict:
    """Fill a template. Returns {subject, email, teams, checklist}."""
    tpl = TEMPLATES[template_key]
    safe = {k: (v if v is not None else "") for k, v in values.items()}
    return {
        "subject": tpl["subject"].format(**safe),
        "email": tpl["email_body"].format(**safe),
        "teams": tpl["teams_message"].format(**safe),
        "checklist": list(tpl["checklist"]),
    }


# ============================================================ pdf
def _reader(data: bytes):
    from pypdf import PdfReader
    return PdfReader(io.BytesIO(data))


def pdf_page_count(data: bytes) -> int:
    return len(_reader(data).pages)


def merge_pdfs(files: list[bytes]) -> bytes:
    """Merge PDFs in order. Raises ValueError on empty/invalid input."""
    from pypdf import PdfWriter
    if not files:
        raise ValueError("No PDFs to merge.")
    writer = PdfWriter()
    for i, data in enumerate(files):
        try:
            reader = _reader(data)
        except Exception as exc:
            raise ValueError(f"File #{i + 1} is not a valid PDF: {exc}") from exc
        for page in reader.pages:
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def parse_page_range(spec: str, n_pages: int) -> list[int]:
    """'1-3,5' -> [0,1,2,4]. 1-based input. Raises ValueError on bad spec."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                start, end = int(a.strip()), int(b.strip())
            except ValueError:
                raise ValueError(f"Bad range '{part}' — use like 1-3.")
            if start < 1 or end < start:
                raise ValueError(f"Bad range '{part}'.")
            pages.update(range(start - 1, end))
        else:
            try:
                p = int(part)
            except ValueError:
                raise ValueError(f"Bad page '{part}' — use numbers like 5.")
            if p < 1:
                raise ValueError(f"Bad page '{part}'.")
            pages.add(p - 1)
    if not pages:
        raise ValueError("No pages selected.")
    bad = sorted(p + 1 for p in pages if p >= n_pages)
    if bad:
        raise ValueError(f"PDF has only {n_pages} page(s); "
                         f"page(s) {bad} out of range.")
    return sorted(pages)


def split_pdf(data: bytes, pages: list[int]) -> bytes:
    from pypdf import PdfWriter
    reader = _reader(data)
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _watermark_page(text: str, width: float, height: float,
                    opacity: float, font_size: int) -> bytes:
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.saveState()
    c.translate(width / 2, height / 2)
    c.rotate(30)
    c.setFillColor(Color(0.55, 0.55, 0.55, alpha=max(0.05, min(1.0, opacity))))
    c.setFont("Helvetica-Bold", font_size)
    c.drawCentredString(0, 0, text)
    c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()


def add_watermark(data: bytes, text: str, opacity: float = 0.25,
                  font_size: int = 48) -> bytes:
    """Diagonal text watermark on every page, sized per page."""
    from pypdf import PdfWriter
    if not text.strip():
        raise ValueError("Watermark text is empty.")
    reader = _reader(data)
    writer = PdfWriter()
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        overlay = _reader(_watermark_page(text, w, h, opacity, font_size))
        page.merge_page(overlay.pages[0])
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _dedupe_cols(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        c = c or ""
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 1
            out.append(c)
    return out


# Per-mode cascade: (backend, vertical_strategy, horizontal_strategy, label).
# Strategies stop at the first one yielding a valid table on each page.
_STRATEGY_ORDER: dict[str, list[tuple[str, str, str, str]]] = {
    "auto": [
        ("pdfplumber", "lines", "lines", "grid"),
        ("pdfplumber", "text", "text", "text"),
        ("pymupdf", "lines", "lines", "pymupdf"),
        ("pymupdf", "text", "text", "pymupdf-text"),
        ("legacy", "", "", "legacy"),
    ],
    "grid": [
        ("pdfplumber", "lines", "lines", "grid"),
        ("pymupdf", "lines", "lines", "pymupdf"),
    ],
    "borderless": [
        ("pdfplumber", "text", "text", "text"),
        ("pymupdf", "text", "text", "pymupdf-text"),
    ],
}

STRATEGY_LABELS = {
    "grid": "Grid / bordered (vector lines)",
    "text": "Borderless / text-aligned",
    "pymupdf": "PyMuPDF grid detection",
    "pymupdf-text": "PyMuPDF text-aligned detection",
    "legacy": "Legacy text-layout heuristic",
}


def extract_tables(data: bytes, mode: str = "auto"
                   ) -> list[tuple[int, int, "pd.DataFrame", str]]:
    """Multi-strategy table extraction → [(page_1based, table_idx, df, strategy)].

    ``mode``: ``"auto"`` (default) runs the full cascade per page —
    pdfplumber ``lines``/``lines`` → pdfplumber ``text``/``text`` →
    PyMuPDF grid → PyMuPDF text → legacy pypdf layout heuristic — and
    stops at the first strategy that yields a valid table on that page.
    ``"grid"`` only tries the bordered strategies (pdfplumber lines,
    PyMuPDF grid); ``"borderless"`` only tries the text-aligned ones
    (pdfplumber text, PyMuPDF text). Forced modes do NOT fall back to the
    legacy heuristic: a page with no matching table simply yields nothing.

    A detected table counts as valid when it has ≥2 non-empty rows and
    ≥2 columns (all-empty spacer rows are dropped first). The first row
    becomes the header (deduped). ``strategy`` is one of ``"grid"``,
    ``"text"``, ``"pymupdf"``, ``"pymupdf-text"``, ``"legacy"`` — see
    ``STRATEGY_LABELS`` for UI display names. Strategies whose library
    is not installed are skipped silently.
    """
    if mode not in _STRATEGY_ORDER:
        raise ValueError(f"Unknown extraction mode {mode!r}; "
                         f"expected one of {sorted(_STRATEGY_ORDER)}.")
    n_pages = len(_reader(data).pages)
    out: list[tuple[int, int, "pd.DataFrame", str]] = []
    pending = set(range(n_pages))
    for backend, v_strat, h_strat, label in _STRATEGY_ORDER[mode]:
        if not pending:
            break
        if backend == "pdfplumber":
            found = _pdfplumber_pass(data, v_strat, h_strat)
        elif backend == "pymupdf":
            found = _pymupdf_pass(data, v_strat)
        else:
            found = _legacy_pass(data)
        for pi in sorted(pending):
            tables = found.get(pi)
            if tables:
                for ti, rows in enumerate(tables, start=1):
                    out.append((pi + 1, ti, _rows_to_df(rows), label))
                pending.discard(pi)
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def _clean_rows(rows: list[list]) -> list[list[str]]:
    """None → "", strip cells, drop all-empty (spacer) rows."""
    cleaned = [[(c if c is not None else "").strip() for c in r]
               for r in rows]
    return [r for r in cleaned if any(r)]


def _valid_table(rows: list[list]) -> bool:
    """A detection counts when ≥2 non-empty rows and ≥2 columns survive."""
    rows = _clean_rows(rows)
    return len(rows) >= 2 and max((len(r) for r in rows), default=0) >= 2


def _rows_to_df(rows: list[list]) -> "pd.DataFrame":
    rows = _clean_rows(rows)
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    return pd.DataFrame(rows[1:], columns=_dedupe_cols(rows[0]))


def _pdfplumber_pass(data: bytes, v_strategy: str, h_strategy: str
                     ) -> dict[int, list[list[list[str]]]]:
    """{page_0based: [cleaned rows]} — {} if pdfplumber is unavailable."""
    try:
        import pdfplumber
    except ImportError:
        return {}
    settings = {"vertical_strategy": v_strategy,
                "horizontal_strategy": h_strategy}
    if v_strategy == "text":
        # Tighter tolerances keep aligned columns together on shaded/
        # banded rows; spacer rows are dropped by _clean_rows.
        settings.update({"text_x_tolerance": 6, "text_y_tolerance": 6})
    out: dict[int, list[list[list[str]]]] = {}
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception:
        return {}
    with pdf:
        for pi, page in enumerate(pdf.pages):
            try:
                raw = page.extract_tables(settings) or []
            except Exception:
                continue
            good = [c for t in raw if _valid_table(t)
                    for c in [_clean_rows(t)]]
            if good:
                out[pi] = good
    return out


def _pymupdf_pass(data: bytes, strategy: str
                  ) -> dict[int, list[list[list[str]]]]:
    """{page_0based: [cleaned rows]} — {} if PyMuPDF is unavailable."""
    try:
        import pymupdf
    except ImportError:
        return {}
    out: dict[int, list[list[list[str]]]] = {}
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return {}
    with doc:
        for pi, page in enumerate(doc):
            try:
                tabs = list(page.find_tables(horizontal_strategy=strategy,
                                             vertical_strategy=strategy))
            except Exception:
                continue
            good = []
            for tab in tabs:
                try:
                    rows = tab.extract()
                except Exception:
                    continue
                if _valid_table(rows):
                    good.append(_clean_rows(rows))
            if good:
                out[pi] = good
    return out


def _legacy_pass(data: bytes) -> dict[int, list[list[list[str]]]]:
    """Original pypdf ``layout``-mode heuristic: runs of 2+ spaces start a
    new column, blank lines separate tables, single-column blocks are
    treated as prose and skipped. Always available (pure Python)."""
    out: dict[int, list[list[list[str]]]] = {}
    reader = _reader(data)
    for pi, page in enumerate(reader.pages):
        text = page.extract_text(extraction_mode="layout") or ""
        blocks: list[list[list[str]]] = []
        cur: list[list[str]] = []
        for line in text.splitlines():
            cells = [c.strip() for c in re.split(r"\s{2,}", line.strip())]
            if any(cells):
                cur.append(cells)
            elif cur:
                blocks.append(cur)
                cur = []
        if cur:
            blocks.append(cur)
        tables = []
        for rows in blocks:
            width = max(len(r) for r in rows)
            if width < 2:  # prose, not a table
                continue
            tables.append(rows)
        if tables:
            out[pi] = tables
    return out


def tables_to_excel(tables: list[tuple[int, int, "pd.DataFrame", str]]) -> bytes:
    if not tables:
        raise ValueError("No tables to export.")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for pi, ti, df, _strat in tables:
            name = re.sub(r"[^\w]+", "_", f"p{pi}_t{ti}")[:31] or "sheet"
            df.to_excel(w, index=False, sheet_name=name)
    return buf.getvalue()


# ============================================================ beautify
def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size[0], size[1]], radius=radius, fill=255)
    return mask


def beautify(img: Image.Image, opts: dict) -> Image.Image:
    """Trim -> crop margins -> padding -> rounded corners -> drop shadow.

    opts: {trim, crop_l, crop_t, crop_r, crop_b (0-40 %),
           padding (px), pad_color, radius (px),
           shadow (bool), shadow_blur, shadow_offset, shadow_opacity (0-100)}
    Returns RGBA.
    """
    w, h = img.size
    work = img.convert("RGB")

    if opts.get("trim"):
        bg = Image.new("RGB", work.size, work.getpixel((0, 0)))
        bbox = ImageChops.difference(work, bg).getbbox()
        if bbox:
            work = work.crop(bbox)
            w, h = work.size

    # manual margin crop (%)
    l = int(w * opts.get("crop_l", 0) / 100)
    t = int(h * opts.get("crop_t", 0) / 100)
    r = int(w * opts.get("crop_r", 0) / 100)
    b = int(h * opts.get("crop_b", 0) / 100)
    if l + r < w and t + b < h and (l or t or r or b):
        work = work.crop((l, t, w - r, h - b))
        w, h = work.size

    pad = int(opts.get("padding", 0))
    if pad:
        canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad),
                           opts.get("pad_color", "#FFFFFF"))
        canvas.paste(work, (pad, pad))
        work, w, h = canvas, w + 2 * pad, h + 2 * pad

    radius = int(opts.get("radius", 0))
    work = work.convert("RGBA")
    if radius:
        work.putalpha(_rounded_mask((w, h), min(radius, min(w, h) // 2)))

    if opts.get("shadow"):
        blur = int(opts.get("shadow_blur", 18))
        off = int(opts.get("shadow_offset", 12))
        op = int(opts.get("shadow_opacity", 45))
        sw, sh = w + blur * 2 + off, h + blur * 2 + off
        shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        rect = Image.new("RGBA", (w, h), (0, 0, 0, int(255 * op / 100)))
        if radius:
            rect.putalpha(_rounded_mask((w, h), min(radius, min(w, h) // 2)))
        shadow.paste(rect, (blur, blur), rect)
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur // 2 or 1))
        shadow.alpha_composite(work, (blur, blur + off))
        return shadow
    return work
