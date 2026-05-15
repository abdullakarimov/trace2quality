"""CSV Fixer UI - fix broken ADO Test Plan CSV files for import."""

from __future__ import annotations

import csv
import io
import itertools
import unicodedata
from urllib.parse import quote
import zipfile
from typing import List, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# Core fixer logic (adapted from legacy/csv/fixer.py for in-memory use)
# ---------------------------------------------------------------------------

EXPECTED_HEADERS = [
    "ID", "Work Item Type", "Title", "Test Step", "Step Action", "Step Expected",
    "Priority", "Area Path", "Assigned To", "State",
]
LEGACY_HEADERS = [
    "ID", "Work Item Type", "Title", "Test Step", "Step Action", "Step Expected",
    "Area Path", "Assigned To", "State",
]
N_COLS = len(EXPECTED_HEADERS)

COL_ID       = 0
COL_WTYPE    = 1
COL_TITLE    = 2
COL_STEP     = 3
COL_ACTION   = 4
COL_EXPECTED = 5
COL_PRIORITY = 6
COL_AREA     = 7
COL_ASSIGNED = 8
COL_STATE    = 9

CORP_DOMAIN = "innowise.com"
KNOWN_PREFIXES = ["Guest Innowise "]
FORGOT_ASSIGNEE_NAME = "Guest Innowise Haidysh Alena"
DEFAULT_ASSIGNEE = "Guest Innowise Haidysh Alena <alena.haidysh@innowise.com>"


def _is_all_empty(row: List[str]) -> bool:
    return all(c.strip() == "" for c in row)


def _pad_or_truncate(row: List[str], n: int) -> List[str]:
    if len(row) < n:
        return row + [""] * (n - len(row))
    if len(row) > n:
        head = row[:n - 1]
        tail = row[n - 1:]
        head.append(",".join(tail))
        return head
    return row


def _split_collapsed_metadata(row: List[str]) -> List[str]:
    area = row[COL_AREA].strip()
    assigned = row[COL_ASSIGNED].strip()
    state = row[COL_STATE].strip()
    if "\t" not in area or assigned or state:
        return row
    parts = [p.strip() for p in area.split("\t") if p.strip()]
    if len(parts) < 2:
        return row
    row[COL_AREA] = parts[0]
    if len(parts) >= 2:
        row[COL_ASSIGNED] = parts[1]
    if len(parts) >= 3:
        row[COL_STATE] = parts[2]
    return row


def _to_target_columns(row: List[str]) -> List[str]:
    if len(row) == 9:
        old = _pad_or_truncate(row, 9)
        row = [old[0], old[1], old[2], old[3], old[4], old[5], "", old[6], old[7], old[8]]
    else:
        row = _pad_or_truncate(row, N_COLS)
    return _split_collapsed_metadata(row)


def _flatten_cell_newlines(val: str, mode: Optional[str]) -> str:
    if not mode:
        return val
    if "\r\n" in val or "\n" in val or "\r" in val:
        val = val.replace("\r\n", "\n").replace("\r", "\n")
        if mode == "backslashn":
            return val.replace("\n", r"\n")
        if mode == "space":
            return " ".join(val.split())
    return val


def _normalize_assigned_to(val: str, override: Optional[str] = None) -> str:
    """Normalize assignee format to include corporate email.

    If val is empty and override is provided, use the override directly.
    """
    assignee = val.strip()
    if not assignee:
        return override or ""
    if "<" in assignee and ">" in assignee:
        return assignee
    if assignee == FORGOT_ASSIGNEE_NAME:
        return DEFAULT_ASSIGNEE

    display_name = assignee
    core_name = assignee
    for prefix in KNOWN_PREFIXES:
        if core_name.startswith(prefix):
            core_name = core_name[len(prefix):].strip()
            break

    name_parts = [p for p in core_name.split() if p]
    if len(name_parts) >= 2:
        last_name = name_parts[0].lower()
        first_name = name_parts[1].lower()
        email = f"{first_name}.{last_name}@{CORP_DOMAIN}"
        return f"{display_name} <{email}>"

    return assignee


def fix_csv_content(
    content: str,
    flatten_newlines: str = "backslashn",
    assigned_to_override: Optional[str] = None,
) -> str:
    """Fix CSV content in memory and return the corrected CSV as a string."""

    f_in = io.StringIO(content)
    reader = csv.reader(f_in)

    try:
        first_row = next(reader)
    except StopIteration:
        raise ValueError("Input CSV is empty")

    stripped_first = [c.strip() for c in first_row]
    has_header = stripped_first == EXPECTED_HEADERS or stripped_first == LEGACY_HEADERS
    data_iter = reader if has_header else itertools.chain([first_row], reader)

    raw: List[List[str]] = []
    for row in data_iter:
        row = _to_target_columns(row)
        if _is_all_empty(row):
            continue
        row = [_flatten_cell_newlines(c, flatten_newlines) for c in row]
        row[COL_ASSIGNED] = _normalize_assigned_to(row[COL_ASSIGNED])
        raw.append(row)

    # Structural fixes
    normalized: List[List[str]] = []
    i = 0
    while i < len(raw):
        row = raw[i]
        wtype = row[COL_WTYPE].strip()
        title = row[COL_TITLE].strip()
        step  = row[COL_STEP].strip()

        if wtype.lower() == "test case" and title:
            tc_row = row[:]

            if step:
                tc_header = tc_row[:]
                tc_header[COL_STEP]     = ""
                tc_header[COL_ACTION]   = ""
                tc_header[COL_EXPECTED] = ""
                step_row = [""] * N_COLS
                step_row[COL_STEP]     = tc_row[COL_STEP]
                step_row[COL_ACTION]   = tc_row[COL_ACTION]
                step_row[COL_EXPECTED] = tc_row[COL_EXPECTED]
                normalized.append(tc_header)
                normalized.append(step_row)
                i += 1
                continue

            if not tc_row[COL_AREA].strip() and i + 1 < len(raw):
                nxt = raw[i + 1]
                is_step_row = (not nxt[COL_WTYPE].strip()) and nxt[COL_STEP].strip()
                if is_step_row:
                    if nxt[COL_AREA].strip():
                        tc_row[COL_AREA] = nxt[COL_AREA]
                    if nxt[COL_ASSIGNED].strip():
                        tc_row[COL_ASSIGNED] = _normalize_assigned_to(nxt[COL_ASSIGNED])
                    if nxt[COL_STATE].strip():
                        tc_row[COL_STATE] = nxt[COL_STATE]

            normalized.append(tc_row)
        else:
            normalized.append(row)

        i += 1

    # Carry-forward pass
    carry_priority = ""
    carry_area     = ""
    carry_assigned = assigned_to_override or ""
    carry_state    = ""

    rows_out: List[List[str]] = [EXPECTED_HEADERS]
    for row in normalized:
        is_tc_row   = row[COL_WTYPE].strip().lower() == "test case" and bool(row[COL_TITLE].strip())
        is_step_row = (not row[COL_WTYPE].strip()) and (not row[COL_TITLE].strip()) and bool(row[COL_STEP].strip())

        row[COL_ID] = ""

        if row[COL_PRIORITY].strip():
            carry_priority = row[COL_PRIORITY].strip()
        if row[COL_AREA].strip():
            carry_area = row[COL_AREA].strip()
        if row[COL_ASSIGNED].strip():
            carry_assigned = _normalize_assigned_to(row[COL_ASSIGNED])
            row[COL_ASSIGNED] = carry_assigned
        if row[COL_STATE].strip():
            carry_state = row[COL_STATE].strip()

        if is_tc_row:
            if not row[COL_PRIORITY].strip():
                row[COL_PRIORITY] = carry_priority or "2"
            if not row[COL_AREA].strip() and carry_area:
                row[COL_AREA] = carry_area
            if not row[COL_ASSIGNED].strip() and carry_assigned:
                row[COL_ASSIGNED] = carry_assigned
            if not row[COL_STATE].strip() and carry_state:
                row[COL_STATE] = carry_state

        if is_step_row:
            row[COL_ID]       = ""
            row[COL_WTYPE]    = ""
            row[COL_TITLE]    = ""
            row[COL_PRIORITY] = ""
            row[COL_AREA]     = ""
            row[COL_ASSIGNED] = ""
            row[COL_STATE]    = ""

        rows_out.append(row)

    f_out = io.StringIO()
    writer = csv.writer(f_out, dialect="excel", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerows(rows_out)
    return f_out.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

_FORM_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>CSV Fixer - Trace2Quality</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }
        nav { background: #0066cc; color: white; padding: 15px 30px; }
        nav h1 { margin: 0; font-size: 24px; }
        nav ul { list-style: none; display: flex; gap: 20px; margin-top: 10px; }
        nav a { color: white; text-decoration: none; }
        nav a:hover { text-decoration: underline; }
        .container { max-width: 860px; margin: 0 auto; padding: 30px 20px; }
        h2 { color: #333; margin-bottom: 6px; }
        .subtitle { color: #666; margin-bottom: 24px; }
        .card { background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.10); padding: 28px; margin-bottom: 24px; }
        label { display: block; font-weight: 600; margin-bottom: 6px; color: #333; }
        .hint { font-size: 13px; color: #888; margin-bottom: 10px; font-weight: normal; }
        input[type=text], input[type=file], select {
            width: 100%; padding: 9px 12px; border: 1px solid #ccc; border-radius: 6px;
            font-size: 14px; background: white;
        }
        input[type=file] { padding: 6px; cursor: pointer; }
        .field { margin-bottom: 20px; }
        .row { display: flex; gap: 16px; }
        .row .field { flex: 1; }
        .btn {
            background: linear-gradient(135deg, #0052a3, #0b6bc8);
            color: white; border: none; padding: 11px 28px; border-radius: 7px;
            font-size: 15px; font-weight: 600; cursor: pointer;
        }
        .btn:hover { background: linear-gradient(135deg, #003f82, #0b5fa3); }
        .btn:disabled { background: #b3b3b3; cursor: not-allowed; }
        .back-link { margin-top: 20px; }
        .back-link a { color: #0066cc; text-decoration: none; }
        #status { display: none; margin-top: 16px; padding: 12px 16px; border-radius: 6px; font-size: 14px; }
        #status.info  { background: #e8f0fe; color: #1a4fa8; }
        #status.error { background: #fdecea; color: #b71c1c; }
        #status.ok    { background: #e8f5e9; color: #1b5e20; }
        .file-list { font-size: 13px; color: #555; margin-top: 6px; }
    </style>
</head>
<body>
    <nav>
        <h1>&#128640; Trace2Quality</h1>
        <ul>
            <li><a href="/ui">Dashboard</a></li>
            <li><a href="/ui/workflows">Workflows</a></li>
            <li><a href="/ui/runs">Runs</a></li>
            <li><a href="/docs">API Docs</a></li>
        </ul>
    </nav>

    <div class="container">
        <h2>CSV Fixer</h2>
        <p class="subtitle">Upload one or more Azure DevOps Test Plan CSV files to automatically fix formatting issues and prepare them for import.</p>

        <div class="card">
            <form id="fixerForm">
                <div class="field">
                    <label>CSV Files <span class="hint">(select one or more .csv files)</span></label>
                    <input type="file" id="csvFiles" name="files" accept=".csv" multiple required />
                    <div id="fileList" class="file-list"></div>
                </div>

                <div class="row">
                    <div class="field">
                        <label for="assignedTo">Assigned To <span class="hint">(optional — used as default when CSV rows have no assignee)</span></label>
                        <input type="text" id="assignedTo" name="assigned_to"
                               placeholder='e.g. Doe John &lt;john.doe@innowise.com&gt;' />
                    </div>
                    <div class="field">
                        <label for="flattenNewlines">Embedded Newlines</label>
                        <select id="flattenNewlines" name="flatten_newlines">
                            <option value="backslashn" selected>Replace with \\n (default)</option>
                            <option value="space">Replace with space</option>
                            <option value="">Keep as-is</option>
                        </select>
                    </div>
                </div>

                <button type="submit" class="btn" id="submitBtn">Fix &amp; Download</button>
            </form>
            <div id="status"></div>
        </div>

        <div class="back-link"><a href="/ui">&larr; Back to Dashboard</a></div>
    </div>

    <script>
    const form = document.getElementById('fixerForm');
    const filesInput = document.getElementById('csvFiles');
    const fileListDiv = document.getElementById('fileList');
    const statusDiv = document.getElementById('status');
    const submitBtn = document.getElementById('submitBtn');

    filesInput.addEventListener('change', () => {
        const names = Array.from(filesInput.files).map(f => f.name);
        fileListDiv.textContent = names.length ? names.join(', ') : '';
    });

    function showStatus(msg, type) {
        statusDiv.textContent = msg;
        statusDiv.className = type;
        statusDiv.style.display = 'block';
    }

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        statusDiv.style.display = 'none';

        if (!filesInput.files.length) {
            showStatus('Please select at least one CSV file.', 'error');
            return;
        }

        submitBtn.disabled = true;
        showStatus('Processing...', 'info');

        const data = new FormData();
        for (const file of filesInput.files) {
            data.append('files', file);
        }
        data.append('assigned_to', document.getElementById('assignedTo').value);
        data.append('flatten_newlines', document.getElementById('flattenNewlines').value);

        try {
            const resp = await fetch('/ui/csv-fixer', {
                method: 'POST',
                body: data,
            });

            if (!resp.ok) {
                const text = await resp.text();
                throw new Error(text || 'Server error ' + resp.status);
            }

            const contentDisposition = resp.headers.get('Content-Disposition') || '';
            let filename = 'fixed.csv';
            const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
            if (utf8Match) {
                try {
                    filename = decodeURIComponent(utf8Match[1]);
                } catch (_) {
                    // Fall back to simple filename parsing.
                }
            }
            if (filename === 'fixed.csv') {
                const match = contentDisposition.match(/filename="([^"]+)"/);
                if (match) filename = match[1];
            }

            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);

            const count = filesInput.files.length;
            showStatus(
                count === 1
                    ? 'Done! Fixed file downloaded as "' + filename + '".'
                    : 'Done! ' + count + ' fixed files downloaded as "' + filename + '".',
                'ok'
            );
        } catch (err) {
            showStatus('Error: ' + err.message, 'error');
        } finally {
            submitBtn.disabled = false;
        }
    });
    </script>
</body>
</html>
"""


@router.get("/ui/csv-fixer", response_class=HTMLResponse)
async def csv_fixer_page() -> str:
    """Render the CSV Fixer upload form."""
    return _FORM_PAGE


@router.post("/ui/csv-fixer")
async def csv_fixer_process(
    files: List[UploadFile] = File(...),
    assigned_to: Optional[str] = Form(default=None),
    flatten_newlines: Optional[str] = Form(default="backslashn"),
) -> Response:
    """Accept uploaded CSV files, fix them, and return the result as a download."""
    assigned_to_value = assigned_to.strip() if assigned_to and assigned_to.strip() else None
    flatten_mode = flatten_newlines if flatten_newlines in ("backslashn", "space") else None

    if len(files) == 1:
        upload = files[0]
        raw_bytes = await upload.read()
        try:
            content = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            content = raw_bytes.decode("latin-1")

        fixed = fix_csv_content(content, flatten_newlines=flatten_mode or "backslashn", assigned_to_override=assigned_to_value)
        filename = _fixed_filename(upload.filename or "fixed.csv")
        return Response(
            content=fixed.encode("utf-8-sig"),
            media_type="text/csv",
            headers={"Content-Disposition": _build_content_disposition(filename)},
        )

    # Multiple files → zip archive
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for upload in files:
            raw_bytes = await upload.read()
            try:
                content = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw_bytes.decode("latin-1")

            fixed = fix_csv_content(content, flatten_newlines=flatten_mode or "backslashn", assigned_to_override=assigned_to_value)
            arc_name = _fixed_filename(upload.filename or "fixed.csv")
            zf.writestr(arc_name, fixed.encode("utf-8-sig"))

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="fixed_csvs.zip"'},
    )


def _fixed_filename(original: str) -> str:
    """Return original filename with _fixed suffix before the extension."""
    if "." in original:
        stem, ext = original.rsplit(".", 1)
        return f"{stem}_fixed.{ext}"
    return f"{original}_fixed"


def _ascii_filename_fallback(filename: str) -> str:
    """Build a latin-1-safe fallback filename for HTTP headers.

    Keep readable latin-1 characters when possible, transliterate where we can,
    and only use underscores as a last resort.
    """
    fallback = []
    for ch in filename:
        code = ord(ch)

        # Keep printable latin-1 characters except header-delimiter chars.
        if (32 <= code <= 255) and ch not in {'"', '\\', ';'}:
            fallback.append(ch)
            continue

        # Try transliteration for non-latin-1 characters (e.g., accents/emoji).
        ascii_chunk = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii")
        if ascii_chunk:
            safe_chunk = "".join(c for c in ascii_chunk if 32 <= ord(c) <= 126 and c not in {'"', '\\', ';'})
            fallback.append(safe_chunk or "_")
        else:
            fallback.append("_")

    candidate = "".join(fallback).strip().strip(".") or "download.csv"
    return candidate


def _build_content_disposition(filename: str) -> str:
    """Return RFC 5987 compatible Content-Disposition for UTF-8 filenames.

    If the original filename is latin-1 safe, include classic `filename="..."`
    for older clients. Otherwise, send only `filename*` to avoid lossy
    underscore fallbacks (e.g. Cyrillic names).
    """
    encoded = quote(filename, safe="")
    try:
        filename.encode("latin-1")
        fallback = _ascii_filename_fallback(filename)
        return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
    except UnicodeEncodeError:
        return f"attachment; filename*=UTF-8''{encoded}"
