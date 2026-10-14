# Dav Data Studio (unified-data-studio)

One Streamlit multi-page app housing three local productivity & governance
tools. Run the launcher — the sidebar navigates between the apps:

```bash
pip install -r requirements.txt
streamlit run launcher.py
```

| # | App | Page | What it does |
|---|-----|------|--------------|
| 1 | 📊 PBIP Metadata & DAX Editor | `pages/metadata_dax_editor.py` | Parse TMDL tables from a PBIP folder, edit DAX formulas & descriptions in the browser, save back to the `.tmdl` files with lineageTag-safe line surgery. |
| 2 | 🛡️ Security Command Center | `pages/security_command_center.py` | Platform-agnostic governance: rule-book access engine, joiner/leaver/mover delta tracking, audit register + gap analysis, effective-access query tool. |
| 3 | 🎨 Theme & UI Studio | `pages/theme_ui_studio.py` | Theme generator with live dashboard preview → `theme.json` export; bulk visual.json editor to standardize padding/corners across a report. |

Shared pure logic lives in `lib/` (no Streamlit imports — unit-testable):

| Module | Contents |
|--------|----------|
| `lib/tmdl_io.py` | TMDL parser with line locations, line-surgery edit/save, PBIP detection, Markdown export, DAX sanity checks |
| `lib/csv_loader.py` | Encoding-robust CSV/Excel loading, HR schema mapping |
| `lib/rules_engine.py` | RLS-style rule engine (`:` explode), delta tracking, gap analysis |
| `lib/theme_builder.py` | theme.json builder + palettes, live-preview HTML, visual.json bulk editor |

App-specific schema, methodology and tests: [`DEVELOPER_GUIDELINES.md`](DEVELOPER_GUIDELINES.md).
Shared repo conventions: [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md).
