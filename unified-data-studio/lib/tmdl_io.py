"""TMDL parse + line-surgery edit/save.

Pure logic — no ``st.*`` calls. Used by the Metadata & DAX Editor page.

Design notes
------------
Power BI's TMDL is indentation-based and carries ``lineageTag`` values that
must survive a save untouched. A full YAML round-trip (parse -> dump) would
reformat the file and risk breaking the model, so this module NEVER rewrites
a file wholesale. Instead it:

1. parses each ``.tmdl`` file into :class:`TmdlObject` records that remember
   the exact line numbers / indentation of every editable property, then
2. applies user edits as surgical line operations (replace one value,
   replace one ``///`` block, replace one ``expression: |`` block, insert a
   new ``///`` block) — everything else stays byte-identical.

Supported measure shapes (all found in real PBIP projects):

- inline:            ``measure 'Total Sales' = SUM(Sales[Amount])``
                     with optional deeper-indented continuation lines
- property:          ``expression: SUM(Sales[Amount])``
- block scalar:      ``expression: |`` followed by a deeper-indented block

Supported description shapes:

- ``///`` triple-slash block above the object (preferred when both exist)
- ``description: '...'`` property
- absent -> a new ``///`` block is inserted above the declaration
"""

import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- regexes
_TABLE_RE = re.compile(r"^table\s+(.+?)\s*$")
_COLUMN_RE = re.compile(r"^column\s+(.+?)\s*$")
# group(1) = name, group(2) = inline DAX or None
_MEASURE_RE = re.compile(r"^measure\s+(.+?)(?:\s*=\s*(.*))?$")
_PROP_RE = re.compile(r"^([A-Za-z][\w]*)\s*:\s*(.*)$")
_DESC_RE = re.compile(r"^///\s?(.*)$")
# Object types we parse; everything else (partition, hierarchy, ...) is
# skipped as an opaque indented block. NOTE: `expression` is deliberately
# NOT in this list — `expression:` is an editable property.
_SKIP_RE = re.compile(
    r"^(partition|hierarchy|level|annotation|ref\s|variation|calculationGroup|"
    r"calculationItem|perspective|role|tablePermission|relationship|"
    r"culture|model|database|dataSource|providerDataSource)\b"
)
# A `word:` line is treated as a property (not DAX continuation) only when
# the word is a known TMDL property; anything else stays DAX verbatim.
_KNOWN_PROPS = {
    "datatype", "description", "formatstring", "displayfolder", "ishidden",
    "summarizeby", "sourcecolumn", "sourceprovidertype", "iskey", "isnullable",
    "lineagetag", "expression", "datacategory", "sortbycolumn", "ordinal",
}


def _unquote_tmdl_name(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def _unquote_prop_value(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('\\"', '"')
    return raw


def _quote_tmdl_value(value: str, original_raw: str) -> str:
    """Re-quote a new property value, preserving the original quoting style."""
    v = value.strip()
    orig = original_raw.strip()
    if len(orig) >= 2 and orig.startswith("'") and orig.endswith("'"):
        return "'" + v.replace("'", "''") + "'"
    if len(orig) >= 2 and orig.startswith('"') and orig.endswith('"'):
        return '"' + v.replace('"', '\\"') + '"'
    if (not v or v != v.strip() or re.search(r"[:#\[\]{}&,*!|>@`\"']", v)
            or v.lower() in {"true", "false", "null", "~"}):
        return "'" + v.replace("'", "''") + "'"
    return v


def _indent_of(raw_line: str) -> tuple[str, str]:
    stripped = raw_line.lstrip(" \t")
    return raw_line[: len(raw_line) - len(stripped)], stripped


def _indent_len(indent: str) -> int:
    # expandtabs(4) so a tab-indented file and a space-indented file both
    # compare sanely; mixed files are pathological and not supported.
    return len(indent.expandtabs(4))


# ---------------------------------------------------------------- models
@dataclass
class DescLoc:
    form: str  # "slashes" | "property"
    start: int = -1
    end: int = -1          # inclusive; slashes form
    indent: str = ""       # indent of the /// block
    line: int = -1         # property form
    prop_indent: str = ""
    prop_raw_value: str = ""


@dataclass
class ExprLoc:
    form: str  # "inline" | "property" | "block"
    decl_line: int = -1
    decl_indent: str = ""
    decl_prefix: str = ""  # text before the DAX on the declaration line
    dax_start: int = -1
    dax_end: int = -1      # inclusive; inline continuation lines
    cont_indent: str = ""
    prop_line: int = -1    # property / block form
    prop_indent: str = ""
    prop_raw_value: str = ""
    block_start: int = -1
    block_end: int = -1    # inclusive
    block_indent: str = ""


@dataclass
class TmdlObject:
    id: str
    table: str
    kind: str              # "table" | "column" | "measure"
    name: str
    expression: str | None
    expr_loc: ExprLoc | None
    description: str
    desc_loc: DescLoc | None
    has_lineage_tag: bool
    decl_line: int
    decl_indent: str
    child_indent: str = ""  # indent of the first deeper line seen in this object


@dataclass
class TmdlFile:
    source_name: str
    objects: list[TmdlObject] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- parse
def _new_builder(kind, name_raw, decl_line, decl_indent, table, desc_slashes):
    return {
        "kind": kind,
        "name_raw": name_raw,
        "name": _unquote_tmdl_name(name_raw),
        "decl_line": decl_line,
        "decl_indent": decl_indent,
        "table": table,
        "child_indent": "",
        "desc_slashes": list(desc_slashes),   # [(lineno, indent, text)]
        "desc_prop": None,                    # (line, indent, raw_value)
        "expr_inline": None,                  # {prefix, dax_lines:[(lineno,text)], cont_indent}
        "expr_prop": None,                    # {line, indent, raw_value}
        "expr_block": None,                   # {prop_line, prop_indent, lines:[(lineno,text)], block_indent}
        "has_lineage_tag": False,
    }


def _finalize(b, source_name) -> TmdlObject | None:
    # ---- expression
    expression = None
    expr_loc = None
    if b["kind"] == "measure":
        if b["expr_inline"] is not None:
            inl = b["expr_inline"]
            dax_lines = [t for _, t in inl["dax_lines"]]
            expression = "\n".join(dax_lines).strip()
            expr_loc = ExprLoc(
                form="inline", decl_line=b["decl_line"], decl_indent=b["decl_indent"],
                decl_prefix=inl["prefix"],
                dax_start=inl["dax_lines"][0][0] if dax_lines else -1,
                dax_end=inl["dax_lines"][-1][0] if dax_lines else -1,
                cont_indent=inl["cont_indent"],
            )
        elif b["expr_block"] is not None:
            blk = b["expr_block"]
            expression = "\n".join(t for _, t in blk["lines"])
            expr_loc = ExprLoc(
                form="block", prop_line=blk["prop_line"], prop_indent=blk["prop_indent"],
                block_start=blk["lines"][0][0], block_end=blk["lines"][-1][0],
                block_indent=blk["block_indent"],
            )
        elif b["expr_prop"] is not None:
            pr = b["expr_prop"]
            expression = _unquote_prop_value(pr["raw_value"])
            expr_loc = ExprLoc(
                form="property", prop_line=pr["line"], prop_indent=pr["indent"],
                prop_raw_value=pr["raw_value"],
            )
    # ---- description (/// wins over the property, matching the v2 extractor)
    description = ""
    desc_loc = None
    if b["desc_slashes"]:
        description = "\n".join(t for _, _, t in b["desc_slashes"])
        slash_indent = b["desc_slashes"][0][1]
        desc_loc = DescLoc(form="slashes", start=b["desc_slashes"][0][0],
                           end=b["desc_slashes"][-1][0], indent=slash_indent)
    elif b["desc_prop"] is not None:
        line, indent, raw_value = b["desc_prop"]
        description = _unquote_prop_value(raw_value)
        desc_loc = DescLoc(form="property", line=line, prop_indent=indent,
                           prop_raw_value=raw_value)

    obj_id = "\x1f".join([source_name, b["table"] or "", b["kind"], b["name"]])
    return TmdlObject(
        id=obj_id, table=b["table"] or "", kind=b["kind"], name=b["name"],
        expression=expression, expr_loc=expr_loc, description=description,
        desc_loc=desc_loc, has_lineage_tag=b["has_lineage_tag"],
        decl_line=b["decl_line"], decl_indent=b["decl_indent"],
        child_indent=b["child_indent"],
    )


def parse_tmdl_text(text: str, source_name: str = "") -> TmdlFile:
    """Parse one .tmdl file's text into editable objects with line locations."""
    lines = text.splitlines()
    tfile = TmdlFile(source_name=source_name)
    pending_desc: list[tuple[int, str, str]] = []
    current: dict | None = None
    current_ilen = -1
    skip_ilen: int | None = None
    table_name = ""

    def note_child(b, indent_raw):
        if not b["child_indent"]:
            b["child_indent"] = indent_raw

    def flush():
        nonlocal current, current_ilen
        if current is not None:
            obj = _finalize(current, source_name)
            if obj is not None:
                tfile.objects.append(obj)
            current = None
            current_ilen = -1

    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        if not raw.strip():
            i += 1
            continue
        indent_raw, stripped = _indent_of(raw)
        ilen = _indent_len(indent_raw)

        # Comments (non-description) are never content.
        if stripped.startswith("//") and not stripped.startswith("///"):
            i += 1
            continue
        # Triple-slash description block -> attaches to the next object.
        m = _DESC_RE.match(stripped)
        if m:
            pending_desc.append((i, indent_raw, m.group(1)))
            i += 1
            continue

        # Table declaration at indent 0 (anything else at 0 ends the scope).
        if ilen == 0:
            flush()
            tm = _TABLE_RE.match(stripped)
            if tm:
                table_name = _unquote_tmdl_name(tm.group(1))
                current = _new_builder("table", tm.group(1), i, indent_raw,
                                       table_name, pending_desc)
            pending_desc = []
            skip_ilen = None
            i += 1
            continue

        # Inside a skipped subtree: ignore until we dedent out of it.
        if skip_ilen is not None:
            if ilen > skip_ilen:
                i += 1
                continue
            skip_ilen = None

        # Skip whole object types we don't edit (partition, hierarchy, ...).
        if _SKIP_RE.match(stripped):
            flush()
            pending_desc = []
            skip_ilen = ilen
            i += 1
            continue

        # New column / measure declaration always starts a new object.
        m_col = _COLUMN_RE.match(stripped)
        m_meas = _MEASURE_RE.match(stripped)
        if m_col or m_meas:
            flush()
            desc = pending_desc
            pending_desc = []
            if m_col:
                current = _new_builder("column", m_col.group(1), i, indent_raw,
                                       table_name, desc)
            else:
                current = _new_builder("measure", m_meas.group(1), i, indent_raw,
                                       table_name, desc)
                dax_first = (m_meas.group(2) or "").strip()
                prefix = stripped[: m_meas.start(2)] if m_meas.group(2) is not None else stripped
                current["expr_inline"] = {
                    "prefix": prefix,
                    "dax_lines": [(i, dax_first)] if dax_first else [],
                    "cont_indent": "",
                }
            current_ilen = ilen
            i += 1
            continue

        # Inside the current object: property, expression block, or DAX line.
        if current is not None and ilen > current_ilen:
            note_child(current, indent_raw)
            m_prop = _PROP_RE.match(stripped)
            prop_name = m_prop.group(1).lower() if m_prop else ""
            if current["kind"] == "measure" and prop_name == "expression" and m_prop:
                raw_value = m_prop.group(2)
                if raw_value.strip().startswith(("|", ">")):
                    # Block scalar: scan the indented block eagerly.
                    j = i + 1
                    block: list[tuple[int, str]] = []
                    while j < n:
                        r2 = lines[j]
                        if not r2.strip():
                            block.append((j, ""))
                            j += 1
                            continue
                        ind2, _ = _indent_of(r2)
                        if _indent_len(ind2) > ilen:
                            block.append((j, r2.strip()))
                            j += 1
                        else:
                            break
                    # Trailing blank lines belong outside the block.
                    while block and block[-1][1] == "":
                        block.pop()
                        j -= 1
                    if block:
                        blk_indent, _ = _indent_of(lines[block[0][0]])
                        current["expr_block"] = {
                            "prop_line": i, "prop_indent": indent_raw,
                            "lines": block, "block_indent": blk_indent,
                        }
                        # Discard any inline DAX parsed from the declaration;
                        # the expression: property is authoritative.
                        current["expr_inline"] = None
                    i = j
                    continue
                else:
                    current["expr_prop"] = {
                        "line": i, "indent": indent_raw, "raw_value": raw_value.strip(),
                    }
                    current["expr_inline"] = None
                    i += 1
                    continue
            if m_prop and prop_name in _KNOWN_PROPS:
                if prop_name == "description" and current["desc_prop"] is None:
                    current["desc_prop"] = (i, indent_raw, m_prop.group(2).strip())
                elif prop_name == "lineagetag":
                    current["has_lineage_tag"] = True
                elif (current["kind"] == "column" and prop_name == "datatype"):
                    pass  # recorded for summary only; see tables_summary
                i += 1
                continue
            if current["kind"] == "measure":
                inl = current["expr_inline"]
                if inl is not None:
                    if not inl["cont_indent"]:
                        inl["cont_indent"] = indent_raw
                    inl["dax_lines"].append((i, stripped))
                i += 1
                continue
            i += 1
            continue

        # Dedented to an unexpected level: close the current object.
        flush()
        pending_desc = []
        i += 1

    flush()
    return tfile


# ---------------------------------------------------------------- summary
def tables_summary(tfile: TmdlFile) -> list[dict]:
    """Canonical {name, columns, measures} shape (v2-compatible) for export."""
    tables: dict[str, dict] = {}
    order: list[str] = []
    for o in tfile.objects:
        if o.table not in tables:
            tables[o.table] = {"name": o.table, "columns": [], "measures": []}
            order.append(o.table)
        if o.kind == "column":
            tables[o.table]["columns"].append(
                {"Name": o.name, "Data Type": "—", "Description": o.description})
        elif o.kind == "measure":
            tables[o.table]["measures"].append(
                {"Name": o.name, "Expression": o.expression or "—",
                 "Description": o.description})
    return [tables[t] for t in order]


def to_markdown(tables: list[dict], source_name: str, fmt: str) -> str:
    """Render the Data-Dictionary Markdown (ported from the v2 extractor)."""
    total_cols = sum(len(t["columns"]) for t in tables)
    total_meas = sum(len(t["measures"]) for t in tables)
    out = [
        f"# Data Dictionary — {source_name}",
        "",
        f"_Source format: {fmt} · Tables: {len(tables)} · "
        f"Columns: {total_cols} · Measures: {total_meas}_",
        "",
        "---",
        "",
    ]
    for table in tables:
        out += [f"## Table: `{table['name']}`", "", "### Columns", ""]
        if table["columns"]:
            out += ["| Column | Data Type |", "| --- | --- |"]
            out += [f"| `{c['Name']}` | {c['Data Type']} |" for c in table["columns"]]
        else:
            out.append("_No columns found._")
        out += ["", "### Measures", ""]
        if table["measures"]:
            for meas in table["measures"]:
                out += [f"#### `{meas['Name']}`", ""]
                if meas["Description"]:
                    out += [f"> {meas['Description']}", ""]
                out += ["```dax", str(meas["Expression"]), "```", ""]
        else:
            out += ["_No measures found._", ""]
        out += ["---", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- edits
@dataclass
class LineOp:
    kind: str            # "replace" | "replace_range" | "delete_range" | "insert_before"
    line: int
    end: int = -1
    text: list[str] = field(default_factory=list)  # new raw lines


def _child_step(obj: TmdlObject) -> str:
    """One indentation step deeper than the object's declaration."""
    if obj.child_indent and obj.child_indent.startswith(obj.decl_indent) \
            and len(obj.child_indent) > len(obj.decl_indent):
        return obj.child_indent[len(obj.decl_indent):]
    return "\t" if "\t" in obj.decl_indent else "    "


def _desc_ops(obj: TmdlObject, new_desc: str) -> list[LineOp]:
    ops: list[LineOp] = []
    if obj.desc_loc is not None and obj.desc_loc.form == "slashes":
        loc = obj.desc_loc
        if not new_desc.strip():
            ops.append(LineOp("delete_range", loc.start, loc.end))
        else:
            new_lines = [
                (loc.indent + "/// " + l).rstrip() if l.strip() else (loc.indent + "///")
                for l in new_desc.splitlines()
            ] or [loc.indent + "///"]
            ops.append(LineOp("replace_range", loc.start, loc.end, new_lines))
    elif obj.desc_loc is not None and obj.desc_loc.form == "property":
        loc = obj.desc_loc
        if not new_desc.strip():
            ops.append(LineOp("delete_range", loc.line, loc.line))
        else:
            ops.append(LineOp("replace", loc.line, text=[
                loc.prop_indent + "description: " +
                _quote_tmdl_value(new_desc, loc.prop_raw_value)]))
    else:
        # No description yet: insert a /// block above the declaration.
        if new_desc.strip():
            new_lines = [
                (obj.decl_indent + "/// " + l).rstrip() if l.strip()
                else (obj.decl_indent + "///")
                for l in new_desc.splitlines()
            ]
            ops.append(LineOp("insert_before", obj.decl_line, text=new_lines))
    return ops


def _expr_ops(obj: TmdlObject, new_expr: str) -> list[LineOp]:
    """Build line ops replacing a measure's DAX. Caller guarantees change."""
    ops: list[LineOp] = []
    dax_lines = [l.rstrip() for l in new_expr.splitlines()]
    if not dax_lines:
        dax_lines = [""]
    loc = obj.expr_loc
    step = _child_step(obj)

    if loc is None:
        # Measure with no detectable expression (shouldn't happen): turn the
        # declaration into inline form.
        prefix = obj.decl_indent + f"measure '{obj.name}' = "
        ops.append(LineOp("replace", obj.decl_line,
                          text=[prefix + dax_lines[0]]))
        if len(dax_lines) > 1:
            ci = obj.child_indent or (obj.decl_indent + step)
            ops.append(LineOp("insert_before", obj.decl_line + 1,
                              text=[ci + l for l in dax_lines[1:] if l.strip()]))
        return ops

    if loc.form == "inline":
        # Normalize to exactly one space after '=' (the regex may have eaten
        # the original trailing space when the DAX lived on later lines).
        new_decl = (loc.decl_indent + loc.decl_prefix.rstrip() + " "
                    + dax_lines[0]).rstrip()
        ops.append(LineOp("replace", loc.decl_line, text=[new_decl]))
        if loc.dax_start != -1:
            ops.append(LineOp("delete_range", loc.dax_start, loc.dax_end))
        if len(dax_lines) > 1:
            ci = loc.cont_indent or obj.child_indent or (loc.decl_indent + step)
            ops.append(LineOp("insert_before", loc.decl_line + 1, text=[
                (ci + l).rstrip() for l in dax_lines[1:]]))
    elif loc.form == "property":
        if len(dax_lines) == 1:
            ops.append(LineOp("replace", loc.prop_line, text=[
                loc.prop_indent + "expression: " +
                _quote_tmdl_value(dax_lines[0], loc.prop_raw_value)]))
        else:
            ops.append(LineOp("replace", loc.prop_line,
                              text=[loc.prop_indent + "expression: |"]))
            ops.append(LineOp("insert_before", loc.prop_line + 1, text=[
                (loc.prop_indent + step + l).rstrip() for l in dax_lines]))
    elif loc.form == "block":
        new_block = [(loc.block_indent + l).rstrip() if l.strip() else ""
                     for l in dax_lines]
        ops.append(LineOp("replace_range", loc.block_start, loc.block_end,
                          text=new_block))
    return ops


def build_edit_ops(obj: TmdlObject,
                   new_expression: str | None,
                   new_description: str | None) -> list[LineOp]:
    """Diff one object against its parsed state -> line ops (may be empty)."""
    ops: list[LineOp] = []
    if new_description is not None and new_description != obj.description:
        ops.extend(_desc_ops(obj, new_description))
    if (new_expression is not None and obj.kind == "measure"
            and new_expression.strip() != (obj.expression or "").strip()):
        ops.extend(_expr_ops(obj, new_expression))
    return ops


def apply_line_ops(lines: list[str], ops: list[LineOp]) -> list[str]:
    """Apply ops to a copy of ``lines``. Ops must not overlap."""
    order = {"delete_range": 0, "replace_range": 0, "replace": 1, "insert_before": 2}
    out = list(lines)
    for op in sorted(ops, key=lambda o: (-o.line, order[o.kind])):
        if op.kind == "replace":
            out[op.line] = op.text[0]
        elif op.kind == "replace_range":
            out[op.line: op.end + 1] = op.text
        elif op.kind == "delete_range":
            del out[op.line: op.end + 1]
        elif op.kind == "insert_before":
            out[op.line:op.line] = op.text
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unknown op kind: {op.kind}")
    return out


# ---------------------------------------------------------------- io
def read_tmdl_file(path: Path) -> tuple[TmdlFile, dict]:
    """Read a .tmdl file, remembering BOM + newline style for the write-back."""
    raw = path.read_bytes()
    meta = {
        "bom": raw.startswith(codecs.BOM_UTF8),
        "newline": "\r\n" if b"\r\n" in raw else "\n",
        "trailing_newline": raw.endswith(b"\n"),
    }
    text = raw.decode("utf-8-sig")
    return parse_tmdl_text(text, path.name), meta


def render_tmdl_text(lines: list[str], meta: dict) -> bytes:
    text = meta["newline"].join(lines)
    if meta["trailing_newline"] and not text.endswith("\n"):
        text += meta["newline"]
    data = text.encode("utf-8")
    if meta["bom"]:
        data = codecs.BOM_UTF8 + data
    return data


def detect_pbip_format(root: Path) -> tuple[str, list[Path]]:
    """Auto-detect TMDL tables under a PBIP root (ported from v2).

    Returns ("tmdl", [files]). Raises ValueError when nothing is found.
    (The MPA editor is TMDL-only; legacy model.bim stays in the standalone
    v2 extractor app.)
    """
    if not root.exists():
        raise ValueError(f"Path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    tmdl_files: list[Path] = []
    for sem in root.glob("*.SemanticModel"):
        d = sem / "definition" / "tables"
        if d.is_dir():
            tmdl_files.extend(sorted(d.glob("*.tmdl")))
    direct = root / "definition" / "tables"
    if direct.is_dir():
        tmdl_files.extend(sorted(direct.glob("*.tmdl")))
    tmdl_files = [f for f in tmdl_files if f.is_file()]
    if not tmdl_files:
        raise ValueError(
            "No definition/tables/*.tmdl found under this folder. Expected a PBIP "
            "project root (containing *.SemanticModel/). Legacy model.bim is not "
            "editable here — use the standalone Power BI Metadata Extractor v2."
        )
    return "tmdl", tmdl_files


# ---------------------------------------------------------------- validate
def validate_dax(expr: str) -> list[str]:
    """Light sanity checks on edited DAX (warnings only, never blocking)."""
    warnings: list[str] = []
    if not expr.strip():
        return ["DAX expression is empty."]
    stack: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "["}
    in_str: str | None = None
    i = 0
    line = 1
    while i < len(expr):
        ch = expr[i]
        if ch == "\n":
            line += 1
        if in_str:
            if ch == in_str:
                # '' inside a single-quoted string is an escaped quote.
                if in_str == "'" and i + 1 < len(expr) and expr[i + 1] == "'":
                    i += 2
                    continue
                in_str = None
        elif ch in ("'", '"'):
            in_str = ch
        elif ch in "([":
            stack.append((ch, line))
        elif ch in ")]":
            if not stack or stack[-1][0] != pairs[ch]:
                warnings.append(f"Unbalanced '{ch}' near line {line}.")
                break
            stack.pop()
        i += 1
    for ch, ln in stack:
        warnings.append(f"Unclosed '{ch}' opened near line {ln}.")
    if in_str:
        warnings.append("Unterminated string literal.")
    return warnings
