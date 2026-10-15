"""Pure logic for the Stlite Sandbox Builder. No ``st.*`` calls.

Scans the repo for standalone ``app.py`` tools, bundles each app's Python
modules, and renders a single self-contained ``.html`` file that boots the
app in the browser via the ``@stlite/mountable`` CDN build (Pyodide +
a stlite Streamlit runtime — no server, no Python install needed).
"""

import json
import re
from pathlib import Path

STLITE_VERSION = "0.75.0"
STLITE_JS = (f"https://cdn.jsdelivr.net/npm/@stlite/mountable@"
             f"{STLITE_VERSION}/build/stlite.js")
STLITE_CSS = (f"https://cdn.jsdelivr.net/npm/@stlite/mountable@"
              f"{STLITE_VERSION}/build/stlite.css")
ENTRY_NAME = "streamlit_app.py"

DISCLAIMER = (    "📵 **Browser-sandbox limits — read before exporting.**\n\n"
    "1. **“Read from Local Path” will NOT work** in the generated HTML. "
    "Browsers cannot see your PC/iPhone filesystem, so always switch the "
    "app to its **“Upload File”** toggle when running on mobile.\n"
    "2. **First load needs internet** — the page fetches the stlite runtime, "
    "Pyodide, and the listed packages from CDNs. After everything is "
    "cached by the browser it runs locally.\n"
    "3. **Exotic packages may fail** — only wheels with Pyodide (WASM) "
    "builds install (pandas, numpy, Pillow, matplotlib and pure-Python "
    "packages are fine; e.g. `duckdb` may not be). If an install fails, "
    "remove that package from the requirements list below and retry."
)


def scan_apps(repo_root) -> list:
    """Find standalone tools: ``<dir>/app.py`` directly under *repo_root*.

    Returns [{"dir", "path", "label", "py_files"}]. Suite pages
    (``unified-data-studio/pages/``) are intentionally excluded — they
    import the ``lib/`` package, which the flat bundle cannot provide.
    """
    root = Path(repo_root)
    apps = []
    for app_py in sorted(root.glob("*/app.py")):
        d = app_py.parent
        if d.name.startswith("."):
            continue
        py_files = sorted(p for p in d.glob("*.py"))
        if not py_files:
            continue
        apps.append({"dir": d.name, "path": str(d),
                     "label": f"{d.name}/app.py",
                     "py_files": py_files, "entry": app_py})
    return apps


def read_requirements(app_path) -> list:
    """Bare package names from the app's requirements.txt.

    Version pins are stripped (micropip resolves Pyodide wheels best with
    bare names) and ``streamlit`` is dropped — stlite ships its own.
    """
    req = Path(app_path) / "requirements.txt"
    names: list = []
    if not req.exists():
        return names
    for line in req.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!~\s;\[]", line, 1)[0].strip()
        if not name or name.lower() == "streamlit":
            continue
        names.append(name)
    return list(dict.fromkeys(names))


# Packages that can never install under Pyodide (no WASM wheel) and their
# pure-Python replacements. Applied to the generated HTML requirements so
# an export keeps working even if a desktop requirements.txt lists them.
WASM_REQ_SUBSTITUTIONS = {
    "pypdfium2": "pypdf",   # pdfplumber's C-extension backend
    "pdfplumber": None,     # dropped — table extraction uses pypdf now
}


def apply_wasm_substitutions(requirements: list) -> list:
    """Rewrite a requirements list for Pyodide: swap WASM-unsafe packages
    for pure-Python equivalents, drop those with no replacement."""
    out: list = []
    for r in requirements:
        sub = WASM_REQ_SUBSTITUTIONS.get(r.strip().lower(), r)
        if sub is None:
            continue
        if sub not in out:
            out.append(sub)
    return out


def bundle_files(app: dict) -> dict:
    """Map virtual filename → source for the stlite ``files`` dict.

    The entry ``app.py`` becomes ``streamlit_app.py``; sibling ``*_core``
    modules keep their names so ``import diff_core``-style imports work.
    """
    files: dict = {}
    for p in app["py_files"]:
        name = ENTRY_NAME if p == app["entry"] else p.name
        files[name] = p.read_text(encoding="utf-8")
    return files


def js_escape(s: str) -> str:
    """Escape Python source for embedding in a JS template literal.

    Also neutralizes ``</script`` so bundled sources containing embedded
    HTML/JS can never break out of the outer ``<script>`` block
    (``<\\/script`` is valid inside a JS string literal).
    """
    return (s.replace("\\", "\\\\")
             .replace("`", "\\`")
             .replace("${", "\\${")
             .replace("</script", "<\\/script"))


def _safe_requirement(name: str) -> str | None:
    """A requirement name as a JSON string literal, or None if the name
    contains characters outside the safe package-name alphabet (blocks
    JS string-breakout via the extra-packages input)."""
    if not re.fullmatch(r"[A-Za-z0-9_.\-+]+", name):
        return None
    return json.dumps(name)


def build_html(title: str, files: dict, requirements: list) -> str:
    """Render the standalone stlite ``.html``."""
    files_js = ",\n".join(
        f'      "{name}": `{js_escape(content)}`'
        for name, content in files.items()
    )
    reqs = [_safe_requirement(r) for r in requirements]
    reqs_js = ", ".join(r for r in reqs if r)
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="X-UA-Compatible" content="IE=edge" />
<meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
<title>{safe_title} — stlite</title>
<link rel="stylesheet" href="{STLITE_CSS}" />
<style>html,body{{margin:0;height:100%}}#root{{height:100vh}}</style>
</head>
<body>
<div id="root"></div>
<script src="{STLITE_JS}"></script>
<script>
stlite.mount(
  {{
    requirements: [{reqs_js}],
    entrypoint: "{ENTRY_NAME}",
    files: {{
{files_js}
    }},
  }},
  document.getElementById("root")
);
</script>
</body>
</html>
"""
