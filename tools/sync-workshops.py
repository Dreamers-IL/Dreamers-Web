#!/usr/bin/env python3
"""Refresh the workshop / practice-group tables on practice.html.

Reads the owner's tables from assets/תוכנית סדנאות/ and writes them to
  - assets/data/workshops.json            (the data, for reference)
  - the inline <script id="events-data"> block in practice.html
    (between the EVENTS-DATA-START / EVENTS-DATA-END markers), so the page
    works from file:// and inside the single-file preview bundle too.

Sources, per dataset (first row of a table = column names, every further
non-empty row = one event; blank cells stay blank):
  workshops  "תוכנית סדנאות 16 המעלות.docx"  (a real Word table), or the
             workshop columns of "תוכנית סדנאות ופעילויות 16 המעלות.xlsx"
  practice   "תכנית התרגול 16 המעלות.docx"   (a real Word table), or the
             practice columns of the same xlsx
The most recently saved source that holds a readable table wins. A docx whose
table is a pasted picture (OLE/EMF object) has nothing to read and is skipped.
If no source can be read for a dataset, its previous data is kept.

Usage (from the repo root):   python tools/sync-workshops.py
Prints CHANGED or UNCHANGED; exit code 0 either way. Standard library only.
"""
import datetime
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "תוכנית סדנאות"
OUT_JSON = ROOT / "assets" / "data" / "workshops.json"
PAGE = ROOT / "practice.html"
START, END = "<!--EVENTS-DATA-START-->", "<!--EVENTS-DATA-END-->"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

DATASETS = {
    "workshops": {"docx": "תוכנית סדנאות 16 המעלות.docx", "xlsx_start": "שם הסדנה"},
    "practice": {"docx": "תכנית התרגול 16 המעלות.docx", "xlsx_start": "תרגול"},
}
XLSX = "תוכנית סדנאות ופעילויות 16 המעלות.xlsx"


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def trim(columns, rows):
    """Drop fully blank rows and trailing columns with no header and no data."""
    rows = [r for r in rows if any(clean(c) for c in r)]
    width = len(columns)
    while width and not clean(columns[width - 1]) and not any(
        clean(r[width - 1]) for r in rows if len(r) >= width
    ):
        width -= 1
    columns = [clean(c) for c in columns[:width]]
    rows = [([clean(c) for c in r] + [""] * width)[:width] for r in rows]
    return columns, rows


def read_docx_table(path):
    try:
        with zipfile.ZipFile(path) as z:
            root = ET.fromstring(z.read("word/document.xml"))
    except Exception as e:  # missing, locked, corrupt
        print("  cannot read %s: %s" % (path.name, e))
        return None
    tbl = root.find(".//" + W + "tbl")
    if tbl is None:
        print("  %s has no Word table (a pasted picture cannot be read)" % path.name)
        return None
    grid = []
    for tr in tbl.findall(W + "tr"):
        cells = []
        for tc in tr.findall(W + "tc"):
            paras = []
            for p in tc.iter(W + "p"):
                paras.append("".join(t.text or "" for t in p.iter(W + "t")))
            cells.append(clean(" ".join(x for x in paras if x.strip())))
            span = tc.find(W + "tcPr/" + W + "gridSpan")
            if span is not None:
                cells.extend([""] * (int(span.get(W + "val", "1")) - 1))
        grid.append(cells)
    if not grid:
        return None
    return trim(grid[0], grid[1:])


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx_grid(path):
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
                for si in sroot.findall(S + "si"):
                    shared.append("".join(t.text or "" for t in si.iter(S + "t")))
            sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    except Exception as e:
        print("  cannot read %s: %s" % (path.name, e))
        return None
    grid = []
    for row in sheet.iter(S + "row"):
        cells = {}
        for c in row.findall(S + "c"):
            ref = c.get("r")
            if not ref:
                continue
            t = c.get("t")
            v = c.find(S + "v")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter(S + "t"))
            elif v is None or v.text is None:
                val = ""
            elif t == "s":
                val = shared[int(v.text)]
            else:
                val = v.text
            cells[col_index(ref)] = val
        width = max(cells) + 1 if cells else 0
        grid.append([cells.get(i, "") for i in range(width)])
    return grid


def pretty_cell(header, value):
    """Excel stores dates and times as numbers; show them the way people read them."""
    v = clean(value)
    try:
        num = float(v)
    except ValueError:
        return v
    h = clean(header)
    if h == "תאריך" and num > 30000:
        d = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(num))
        return d.strftime("%d.%m.%Y")
    if h == "שעה" and 0 <= num < 1:
        minutes = round(num * 24 * 60)
        return "%02d:%02d" % divmod(minutes, 60)
    return v


def xlsx_block(grid, start_header, all_starts):
    if not grid:
        return None
    header = [clean(c) for c in grid[0]]
    if start_header not in header:
        return None
    a = header.index(start_header)
    later = [header.index(h) for h in all_starts if h != start_header and h in header and header.index(h) > a]
    b = min(later) if later else len(header)
    cols = header[a:b]
    rows = []
    for r in grid[1:]:
        r = r + [""] * (len(header) - len(r))
        rows.append([pretty_cell(cols[i], r[a + i]) for i in range(len(cols))])
    return trim(cols, rows)


def load_previous():
    try:
        return json.loads(OUT_JSON.read_text(encoding="utf-8")).get("datasets", {})
    except Exception:
        return {}


def build():
    previous = load_previous()
    xlsx_path = SRC / XLSX
    xlsx_grid = read_xlsx_grid(xlsx_path) if xlsx_path.exists() else None
    all_starts = [d["xlsx_start"] for d in DATASETS.values()]
    result = {}
    for name, cfg in DATASETS.items():
        print("%s:" % name)
        candidates = []
        docx_path = SRC / cfg["docx"]
        if docx_path.exists():
            t = read_docx_table(docx_path)
            if t:
                candidates.append((docx_path.stat().st_mtime, docx_path.name, t))
        else:
            print("  missing %s" % docx_path.name)
        if xlsx_grid:
            t = xlsx_block(xlsx_grid, cfg["xlsx_start"], all_starts)
            if t:
                candidates.append((xlsx_path.stat().st_mtime, xlsx_path.name, t))
        if candidates:
            candidates.sort(key=lambda c: c[0])
            _, source, (cols, rows) = candidates[-1]
            result[name] = {"source": source, "columns": cols, "rows": rows}
            print("  using %s: %d event row(s)" % (source, len(rows)))
        elif name in previous:
            result[name] = previous[name]
            print("  no readable source, keeping previous data")
        else:
            result[name] = {"source": "", "columns": [], "rows": []}
            print("  no readable source and no previous data: empty")
    return {"datasets": result}


def inline_block(data):
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    blob = blob.replace("</", "<\\/").replace("<!--", "<\\!--")
    return '%s<script type="application/json" id="events-data">%s</script>%s' % (
        START, blob, END)


def main():
    data = build()
    changed = False

    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    old = OUT_JSON.read_text(encoding="utf-8") if OUT_JSON.exists() else None
    if old != text:
        OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(text, encoding="utf-8", newline="\n")
        changed = True

    if PAGE.exists():
        html = PAGE.read_text(encoding="utf-8")
        i, j = html.find(START), html.find(END)
        if i == -1 or j == -1:
            print("practice.html has no %s / %s markers: page not updated" % (START, END))
        else:
            new = html[:i] + inline_block(data) + html[j + len(END):]
            if new != html:
                PAGE.write_text(new, encoding="utf-8", newline="\n")
                changed = True
    print("CHANGED" if changed else "UNCHANGED")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
