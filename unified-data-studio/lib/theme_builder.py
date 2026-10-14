"""Power BI theme.json builder + PBIP visual.json bulk editor.

Pure logic — no ``st.*`` calls.

Theme schema notes (verified against Microsoft's skills-for-fabric theming
reference and real-world theme files):
- Top level: ``name``, ``dataColors``, ``background``, ``foreground``,
  ``tableAccent``, ``visualStyles``, ``textClasses``.
- ``visualStyles``: ``{visualType: {"*": {objectName: [ {prop: value}, ... ]}}}``,
  with ``"*"`` as the all-visuals wildcard. Container objects available under
  the wildcard: ``title``, ``background``, ``border``, ``dropShadow``,
  ``padding``, ``visualHeader``, ...
- Caveat: ``radius`` inside ``border`` is used by real themes (and by
  Microsoft's own reference), but one third-party source reports Power BI
  Desktop silently ignoring themes that carry it. The builder includes it
  (rounded corners are an explicit requirement) and ``validate_theme``
  does NOT flag it — if a particular Desktop build ignores it, delete the
  ``radius`` key from the exported JSON.
"""

import html
import json
import re

import pandas as pd

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# Curated palettes (8 data colors each). The "Power BI Default" set mirrors
# the stock palette closely enough for preview purposes.
PALETTES: dict[str, list[str]] = {
    "Power BI Default": ["#118DFF", "#12239E", "#E66C37", "#6B007B",
                         "#E044A7", "#744EC2", "#D9B300", "#798E95"],
    "Dav Corporate": ["#0B5394", "#118DFF", "#6BAED6", "#9ECAE1",
                      "#08519C", "#3182BD", "#3A6EA5", "#5B7FA6"],
    "Warm Sunset": ["#E66C37", "#D9B300", "#E044A7", "#8C510A",
                    "#F6A800", "#C65D3B", "#E8A838", "#A66A00"],
    "Colorblind Safe": ["#E69F00", "#56B4E9", "#009E73", "#F0E442",
                        "#0072B2", "#D55E00", "#CC79A7", "#999999"],
    "Monochrome Blue": ["#08306B", "#08519C", "#2171B5", "#4292C6",
                        "#6BAED6", "#9ECAE1", "#C6DBEF", "#DEEBF7"],
}

FONT_FACES = ["Segoe UI", "Arial", "Calibri", "Helvetica Neue", "Verdana",
              "Trebuchet MS", "Georgia"]


def default_settings() -> dict:
    return {
        "name": "Dav Custom Theme",
        "data_colors": list(PALETTES["Power BI Default"]),
        "page_bg": "#FFFFFF",
        "foreground": "#252423",
        "table_accent": "#118DFF",
        "card_bg": "#FFFFFF",
        "card_transparency": 0,
        "border_show": True,
        "border_color": "#E0E0E0",
        "border_width": 1,
        "corner_radius": 8,
        "shadow_show": False,
        "shadow_color": "#000000",
        "shadow_blur": 8,
        "shadow_transparency": 60,
        "padding": 12,
        "title_show": True,
        "title_color": "#252423",
        "title_size": 13,
        "font_face": "Segoe UI",
        "label_color": "#605E5C",
        "label_size": 9,
        "header_color": "#252423",
        "header_size": 11,
        "callout_color": "#252423",
        "callout_size": 28,
    }


def _solid(hex_color: str) -> dict:
    return {"solid": {"color": hex_color}}


def build_theme(s: dict) -> dict:
    """Build the standard Power BI theme.json dict from UI settings."""
    data_colors = [c for c in s["data_colors"] if _HEX_RE.match(c or "")]
    if not data_colors:
        data_colors = list(PALETTES["Power BI Default"])
    theme = {
        "name": s.get("name", "Custom Theme") or "Custom Theme",
        "dataColors": data_colors,
        "background": s["page_bg"],
        "foreground": s["foreground"],
        "tableAccent": s["table_accent"],
        "textClasses": {
            "label": {"color": s["label_color"], "fontSize": s["label_size"],
                      "fontFace": s["font_face"]},
            "callout": {"color": s["callout_color"], "fontSize": s["callout_size"],
                        "fontFace": s["font_face"]},
            "title": {"color": s["title_color"], "fontSize": s["title_size"],
                      "fontFace": s["font_face"]},
            "header": {"color": s["header_color"], "fontSize": s["header_size"],
                       "fontFace": s["font_face"]},
        },
        "visualStyles": {
            "*": {
                "*": {
                    "background": [{
                        "show": True,
                        "color": _solid(s["card_bg"]),
                        "transparency": int(s["card_transparency"]),
                    }],
                    "border": [{
                        "show": bool(s["border_show"]),
                        "color": _solid(s["border_color"]),
                        "width": int(s["border_width"]),
                        "radius": int(s["corner_radius"]),
                    }],
                    "dropShadow": [{
                        "show": bool(s["shadow_show"]),
                        "color": _solid(s["shadow_color"]),
                        "angle": 0,
                        "distance": 0,
                        "blur": int(s["shadow_blur"]),
                        "transparency": int(s["shadow_transparency"]),
                    }],
                    "padding": [{
                        "top": int(s["padding"]), "bottom": int(s["padding"]),
                        "left": int(s["padding"]), "right": int(s["padding"]),
                    }],
                    "title": [{
                        "show": bool(s["title_show"]),
                        "fontColor": _solid(s["title_color"]),
                        "fontSize": int(s["title_size"]),
                        "fontFamily": s["font_face"],
                    }],
                }
            }
        },
    }
    return theme


def theme_to_json(theme: dict) -> str:
    return json.dumps(theme, indent=2, ensure_ascii=False)


def validate_theme(theme: dict) -> list[str]:
    """Sanity checks on a built theme. Returns warnings (may be empty)."""
    warnings: list[str] = []
    if not theme.get("name"):
        warnings.append("Theme has no name.")
    colors = theme.get("dataColors", [])
    if len(colors) < 2:
        warnings.append("dataColors should hold at least 2 colors.")
    for key in ("background", "foreground", "tableAccent"):
        if not _HEX_RE.match(theme.get(key, "")):
            warnings.append(f"Top-level '{key}' is not a #RRGGBB hex color.")
    for i, c in enumerate(colors):
        if not _HEX_RE.match(c or ""):
            warnings.append(f"dataColors[{i}] is not a #RRGGBB hex color.")
    vs = theme.get("visualStyles", {}).get("*", {}).get("*", {})
    for obj in ("background", "border", "dropShadow", "padding", "title"):
        if obj not in vs:
            warnings.append(f"visualStyles is missing the '{obj}' object.")
    return warnings


# ------------------------------------------------- live HTML preview
def render_preview_html(s: dict) -> str:
    """A simulated dashboard mockup that mirrors the theme settings."""
    esc = html.escape
    ff = esc(s["font_face"])
    fg = s["foreground"]
    pad = int(s["padding"])
    radius = int(s["corner_radius"])
    bw = int(s["border_width"]) if s["border_show"] else 0
    border = f"{bw}px solid {s['border_color']}" if bw else "none"
    shadow = (f"0 4px {int(s['shadow_blur'])}px "
              f"rgba(0,0,0,{int(s['shadow_transparency']) / 100:.2f})"
              if s["shadow_show"] else "none")
    card = (f"background:{s['card_bg']};border:{border};border-radius:{radius}px;"
            f"box-shadow:{shadow};padding:{pad}px;")
    colors = s["data_colors"] or PALETTES["Power BI Default"]

    bars = "".join(
        f"<div style='flex:1;display:flex;flex-direction:column;justify-content:flex-end;'>"
        f"<div style='background:{c};border-radius:3px 3px 0 0;height:{h}%;'></div></div>"
        for c, h in zip(colors, [62, 84, 45, 95, 70, 52, 78, 38])
    )
    rows = "".join(
        f"<tr><td style='padding:6px 8px;border-top:1px solid #eee;color:{fg};'>{a}</td>"
        f"<td style='padding:6px 8px;border-top:1px solid #eee;color:{fg};text-align:right;'>{b}</td></tr>"
        for a, b in [("Store A", "$48.2k"), ("Store B", "$36.7k"), ("Store C", "$29.1k")]
    )
    return f"""
<div style="background:{s['page_bg']};padding:16px;font-family:'{ff}';color:{fg};">
  <div style="font-size:18px;font-weight:600;color:{s['title_color']};margin:0 0 12px 4px;">
    {esc(s.get('name') or 'Dashboard Preview')}</div>
  <div style="display:flex;gap:12px;margin-bottom:12px;">
    {''.join(
      f"<div style='{card}flex:1;'><div style='font-size:{s['label_size']}px;color:{s['label_color']};'>"
      f"{label}</div><div style='font-size:{s['callout_size']}px;color:{s['callout_color']};"
      f"font-weight:600;'>{value}</div></div>"
      for label, value in [("Total Sales", "$114k"), ("Orders", "8,432"), ("Avg. Basket", "$13.52")])}
  </div>
  <div style="display:flex;gap:12px;">
    <div style="{card}flex:1.4;">
      <div style="font-size:{s['title_size']}px;color:{s['title_color']};font-weight:600;margin-bottom:8px;">
        Sales by Store</div>
      <div style="display:flex;gap:6px;height:150px;align-items:stretch;">{bars}</div>
    </div>
    <div style="{card}flex:1;">
      <div style="font-size:{s['title_size']}px;color:{s['title_color']};font-weight:600;margin-bottom:8px;">
        Top Stores</div>
      <table style="width:100%;border-collapse:collapse;font-size:{s['label_size'] + 2}px;">
        <tr style="background:{s['table_accent']};color:#fff;">
          <th style="padding:6px 8px;text-align:left;">Store</th>
          <th style="padding:6px 8px;text-align:right;">Sales</th></tr>
        {rows}
      </table>
    </div>
  </div>
  <div style="margin-top:10px;font-size:11px;color:{s['label_color']};">
    Live preview — every control on the left re-renders this mockup instantly.</div>
</div>
"""


# ------------------------------------------- visual.json bulk editor
# Container objects we standardize, with the sub-properties we manage.
VCO_TARGETS = ("background", "border", "padding", "dropShadow", "title",
               "visualHeader")


def _vco_instances(visual: dict) -> dict:
    vco = visual.get("visualContainerObjects")
    return vco if isinstance(vco, dict) else {}


def scan_visual_jsons(files: list[tuple[str, dict]]) -> pd.DataFrame:
    """Summarize container formatting across visual.json files.

    Returns rows: file, container_object, property, current_value.
    """
    rows = []
    for name, visual in files:
        if not isinstance(visual, dict):
            rows.append({"file": name, "container_object": "—",
                         "property": "unreadable", "current_value": "not valid JSON object"})
            continue
        vco = _vco_instances(visual)
        if not vco:
            rows.append({"file": name, "container_object": "—",
                         "property": "visualContainerObjects",
                         "current_value": "(absent — theme defaults apply)"})
            continue
        for obj_name in VCO_TARGETS:
            inst = vco.get(obj_name)
            first = inst[0] if isinstance(inst, list) and inst else {}
            if not isinstance(first, dict) or not first:
                rows.append({"file": name, "container_object": obj_name,
                             "property": "(not set)",
                             "current_value": "(theme default applies)"})
                continue
            for prop, val in first.items():
                rows.append({"file": name, "container_object": obj_name,
                             "property": prop,
                             "current_value": json.dumps(val, ensure_ascii=False)[:120]})
    return pd.DataFrame(rows, columns=["file", "container_object", "property",
                                       "current_value"])


def apply_vco_standard(visual: dict, standard: dict) -> tuple[dict, list[str]]:
    """Apply standard container formatting to one visual.json dict.

    ``standard`` maps container object -> {prop: value}, e.g.
    ``{"padding": {"top": 8, "bottom": 8, "left": 8, "right": 8},
       "border": {"radius": 8}}``.
    Only the listed properties are touched; everything else is preserved.
    Returns (new_visual, change_descriptions).
    """
    visual = json.loads(json.dumps(visual))  # deep copy
    vco = visual.setdefault("visualContainerObjects", {})
    changes: list[str] = []
    for obj_name, props in standard.items():
        inst = vco.get(obj_name)
        if not isinstance(inst, list) or not inst:
            inst = [{}]
            vco[obj_name] = inst
        first = inst[0]
        if not isinstance(first, dict):
            first = {}
            inst[0] = first
        for prop, val in props.items():
            old = first.get(prop, "(unset)")
            if old != val:
                first[prop] = val
                changes.append(f"{obj_name}.{prop}: {old} -> {val}")
    return visual, changes


def standard_presets() -> dict[str, dict]:
    return {
        "Uniform 8px padding": {
            "padding": {"top": 8, "bottom": 8, "left": 8, "right": 8}},
        "Rounded 8px corners": {
            "border": {"show": True, "radius": 8}},
        "Card look (bg + border + radius)": {
            "background": {"show": True, "transparency": 0},
            "border": {"show": True, "width": 1, "radius": 8}},
    }
