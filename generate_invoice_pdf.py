#!/usr/bin/env python3
"""Generate a simple, readable PDF invoice attachment from Toggl time entries."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, date, time, timezone
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


TOGGL_API_BASE = "https://api.track.toggl.com/api/v9"

# Toggl tag marking work that is not billed to the client.
NON_BILLABLE_TAG = "ei-laskutettava"

# Toggl tag multiplying the logged time, e.g. "x2" when two people attended.
MULTIPLIER_RE = re.compile(r"^x(\d+)$", re.IGNORECASE)

# Toggl reports the earliest allowed start_date in the body of its 400 response.
START_DATE_LIMIT_RE = re.compile(r"start_date must not be earlier than (\d{4}-\d{2}-\d{2})")


class TogglClient:
    def __init__(self, token: str, timeout: int = 30) -> None:
        self.session = requests.Session()
        self.session.headers.update({"content-type": "application/json"})
        self.session.auth = (token, "api_token")
        self.timeout = timeout

    def get(self, path: str, params: Optional[Dict[str, str]] = None):
        url = f"{TOGGL_API_BASE}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        if not resp.ok:
            # raise_for_status() drops the body, which is where Toggl explains itself.
            raise requests.HTTPError(
                f"{resp.status_code} {resp.reason} for url: {resp.url}\n"
                f"Toggl response body: {resp.text}",
                response=resp,
            )
        return resp.json()

    def me(self):
        return self.get("/me")

    def time_entries(self, start_dt: datetime, end_dt: datetime):
        params = {
            "start_date": start_dt.isoformat().replace("+00:00", "Z"),
            "end_date": end_dt.isoformat().replace("+00:00", "Z"),
        }
        return self.get("/me/time_entries", params=params)

    def projects(self, workspace_id: int):
        return self.get(f"/workspaces/{workspace_id}/projects")

    def clients(self, workspace_id: int):
        return self.get(f"/workspaces/{workspace_id}/clients")

    def workspaces(self):
        return self.get("/workspaces")


class CacheStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(self.path)
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY,"
            "created_at TEXT NOT NULL,"
            "json TEXT NOT NULL"
            ")"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS time_entries ("
            "id INTEGER PRIMARY KEY,"
            "date TEXT NOT NULL,"
            "client TEXT NOT NULL,"
            "project TEXT NOT NULL,"
            "description TEXT NOT NULL,"
            "duration INTEGER NOT NULL,"
            "billable INTEGER NOT NULL DEFAULT 1,"
            "tags TEXT NOT NULL DEFAULT '[]'"
            ")"
        )
        self._migrate_time_entries()
        self.conn.commit()

    def _migrate_time_entries(self) -> None:
        """Add columns missing from caches created by earlier versions."""
        cur = self.conn.execute("PRAGMA table_info(time_entries)")
        existing = {row[1] for row in cur.fetchall()}
        for column, definition in (
            ("billable", "INTEGER NOT NULL DEFAULT 1"),
            ("tags", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if column not in existing:
                self.conn.execute(f"ALTER TABLE time_entries ADD COLUMN {column} {definition}")

    def get(self, key: str) -> Optional[dict]:
        cur = self.conn.execute("SELECT json FROM cache WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        return json.loads(row[0])

    def set(self, key: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cache (key, created_at, json) VALUES (?, ?, ?)",
            (key, datetime.utcnow().isoformat(), json.dumps(payload)),
        )
        self.conn.commit()

    def upsert_entries(self, rows: List[dict]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO time_entries "
            "(id, date, client, project, description, duration, billable, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r["id"],
                    r["date"].isoformat(),
                    r["client"],
                    r["project"],
                    r["description"],
                    r["duration"],
                    1 if r.get("billable") else 0,
                    json.dumps(r.get("tags") or [], ensure_ascii=False),
                )
                for r in rows
            ],
        )
        self.conn.commit()

    def list_entries(
        self,
        date_from: date,
        date_to: date,
        client: Optional[str],
        project: Optional[str],
    ) -> List[dict]:
        sql = (
            "SELECT id, date, client, project, description, duration, billable, tags "
            "FROM time_entries WHERE date BETWEEN ? AND ?"
        )
        params: List[str] = [date_from.isoformat(), date_to.isoformat()]
        if client:
            sql += " AND client = ?"
            params.append(client)
        if project:
            sql += " AND project = ?"
            params.append(project)
        sql += " ORDER BY date, project, description"
        cur = self.conn.execute(sql, params)
        rows = []
        for row in cur.fetchall():
            rows.append(
                {
                    "id": row[0],
                    "date": datetime.strptime(row[1], "%Y-%m-%d").date(),
                    "client": row[2],
                    "project": row[3],
                    "description": row[4],
                    "duration": row[5],
                    "billable": bool(row[6]),
                    "tags": json.loads(row[7]) if row[7] else [],
                }
            )
        return rows


def parse_args() -> argparse.Namespace:
    load_dotenv()
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)
    parser = argparse.ArgumentParser(description="Generate a PDF from Toggl time entries.")
    parser.add_argument("--token", default=os.getenv("TOGGL_TOKEN"))
    parser.add_argument("--cache-path", default="toggl_cache.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Fetch time entries from Toggl API into SQLite")
    fetch.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    fetch.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    fetch.add_argument("--workspace-id", type=int, default=None)
    fetch.add_argument("--debug-me", action="store_true", help="Print /me response")

    listing = sub.add_parser("list", help="List cached time entries")
    listing.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    listing.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    listing.add_argument("--client", default=None, help="Filter by client name")
    listing.add_argument("--project", default=None, help="Filter by project name")
    listing.add_argument(
        "--only-billable",
        action="store_true",
        help=f'Hide entries tagged "{NON_BILLABLE_TAG}" instead of listing them separately',
    )

    pdf = sub.add_parser("pdf", help="Generate PDF report from cached entries")
    pdf.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    pdf.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    pdf.add_argument("--client", default=None, help="Filter by client name")
    pdf.add_argument("--project", default=None, help="Filter by project name")
    pdf.add_argument("--title", default="Työraportti")
    pdf.add_argument("--out", default="invoice-attachment.pdf")
    pdf.add_argument("--theme", default="clean", help="PDF theme (clean, monospace)")
    pdf.add_argument(
        "--exact-hours",
        action="store_true",
        help="Show exact logged hours instead of rounding up to 0.5h blocks",
    )
    pdf.add_argument(
        "--only-billable",
        action="store_true",
        help=f'Hide entries tagged "{NON_BILLABLE_TAG}" instead of listing them separately',
    )
    return parser.parse_args()


def to_date(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def fmt_date(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def seconds_to_hours(seconds: int) -> float:
    return round(seconds / 3600.0, 2)


def round_up_half_hour(seconds: int) -> float:
    """Round duration seconds up to the next 0.5 hour block expressed in hours."""
    if seconds <= 0:
        return 0.0
    block_seconds = 30 * 60
    rounded_seconds = math.ceil(seconds / block_seconds) * block_seconds
    return rounded_seconds / 3600.0


def build_mappings(projects: List[dict], clients: List[dict]) -> Tuple[Dict[int, dict], Dict[int, dict]]:
    project_map = {p["id"]: p for p in projects}
    client_map = {c["id"]: c for c in clients}
    return project_map, client_map


def normalize_entry(entry: dict, project_map: Dict[int, dict], client_map: Dict[int, dict]) -> dict:
    start = entry.get("start")
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else None

    pid = entry.get("project_id")
    project = project_map.get(pid) if pid else None
    client = client_map.get(project.get("client_id")) if project and project.get("client_id") else None

    return {
        "id": entry.get("id"),
        "date": start_dt.date() if start_dt else None,
        "client": client.get("name") if client else "—",
        "project": project.get("name") if project else "—",
        "description": entry.get("description") or "(ei kuvausta)",
        "duration": entry.get("duration", 0),
        "billable": bool(entry.get("billable")),
        "tags": entry.get("tags") or [],
    }


def row_tags(row: dict) -> List[str]:
    """Normalized tag names for a row: stripped and lowercased."""
    return [str(t).strip().lower() for t in (row.get("tags") or [])]


def is_non_billable(row: dict) -> bool:
    """True when the row carries the non-billable tag.

    Toggl's own billable checkbox is stored but deliberately ignored: this
    workspace never sets it, so using it would mark every row non-billable.
    """
    return NON_BILLABLE_TAG in row_tags(row)


def multiplier(row: dict) -> int:
    """Head count from an "xN" tag, e.g. "x2" when two people attended."""
    for tag in row_tags(row):
        match = MULTIPLIER_RE.match(tag)
        if match:
            return int(match.group(1))
    return 1


def split_billable(rows: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Partition rows into (billable, non_billable), preserving order."""
    billable: List[dict] = []
    non_billable: List[dict] = []
    for row in rows:
        (non_billable if is_non_billable(row) else billable).append(row)
    return billable, non_billable


def row_hours(row: dict, exact_hours: bool = False) -> Tuple[float, float, int]:
    """Return (per_person, total, multiplier) hours for a row.

    Rounding happens before multiplication so the per-person figure stays a
    clean 0.5 h block and the note on the row adds up as printed.
    """
    seconds = row["duration"]
    per_person = seconds_to_hours(seconds) if exact_hours else round_up_half_hour(seconds)
    mult = multiplier(row)
    return per_person, per_person * mult, mult


def fmt_hours_fi(hours: float) -> str:
    """Format hours the Finnish way: decimal comma, no trailing zeros."""
    return f"{hours:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def format_multiplier_note(per_person: float, total: float, mult: int) -> str:
    """Explain a multiplied row, e.g. "2 hlöä × 1 h, yhteensä 2 h"."""
    return (
        f"{mult} hlöä × {fmt_hours_fi(per_person)} h, "
        f"yhteensä {fmt_hours_fi(total)} h"
    )


def format_list_row(row: dict) -> str:
    """One line of `list` output. Exact hours, no 0.5 h rounding."""
    per_person, hours, mult = row_hours(row, exact_hours=True)
    line = (
        f"{fmt_date(row['date'])} | {row['client']} | {row['project']} "
        f"| {row['description']} | {hours:.2f}h"
    )
    if mult > 1:
        line += f" ({format_multiplier_note(per_person, hours, mult)})"
    return line


@dataclass(frozen=True)
class PdfTheme:
    title_style: str = "Title"
    text_style: str = "Normal"
    desc_style: str = "BodyText"
    body_font: str = "Helvetica"
    desc_font: str = "Helvetica"
    header_bg: str = "#F2F2F2"
    header_text: str = "#111111"
    grid: Optional[str] = "#DDDDDD"
    total_line: Optional[str] = "#999999"
    title_font: str = "Helvetica-Bold"
    header_font: str = "Helvetica-Bold"
    total_font: str = "Helvetica-Bold"
    desc_leading: int = 12
    cell_padding: int = 4
    date_width: float = 26 * mm
    hours_width: float = 20 * mm
    desc_min_width: float = 100 * mm
    client_min_width: float = 32 * mm
    project_min_width: float = 32 * mm
    client_max_width: float = 70 * mm
    project_max_width: float = 70 * mm


def get_theme(name: str) -> PdfTheme:
    if name == "clean":
        return PdfTheme()
    if name == "monospace":
        return PdfTheme(
            title_font="Courier-Bold",
            header_font="Courier-Bold",
            total_font="Courier-Bold",
            body_font="Courier",
            desc_font="Courier",
            header_bg="#EFEFEF",
            desc_leading=11,
            cell_padding=2,
            grid=None,
            total_line=None,
            date_width=24 * mm,
            hours_width=18 * mm,
            desc_min_width=104 * mm,
            client_min_width=30 * mm,
            project_min_width=30 * mm,
            client_max_width=68 * mm,
            project_max_width=68 * mm,
        )
    raise ValueError(f"Unknown theme: {name}")


def compute_col_widths(
    rows: List[dict],
    theme: PdfTheme,
    available_width: float,
    font_size: float,
) -> Tuple[float, float, float, float, float]:
    """Size the columns to fit the widest client and project across all rows.

    Widths are computed once over every row so that the billable and
    non-billable tables line up on the page.
    """
    client_texts = ["Asiakas"] + [r["client"] for r in rows]
    project_texts = ["Projekti"] + [r["project"] for r in rows]
    pad = theme.cell_padding * 2
    client_w = max(stringWidth(t, theme.body_font, font_size) for t in client_texts) + pad
    project_w = max(stringWidth(t, theme.body_font, font_size) for t in project_texts) + pad
    client_w = min(max(client_w, theme.client_min_width), theme.client_max_width)
    project_w = min(max(project_w, theme.project_min_width), theme.project_max_width)

    fixed = theme.date_width + theme.hours_width
    desc_w = available_width - fixed - client_w - project_w
    if desc_w < theme.desc_min_width:
        shrink = theme.desc_min_width - desc_w
        total_flex = (client_w - theme.client_min_width) + (project_w - theme.project_min_width)
        if total_flex > 0:
            client_shrink = min(client_w - theme.client_min_width, shrink * (client_w - theme.client_min_width) / total_flex)
            project_shrink = min(project_w - theme.project_min_width, shrink * (project_w - theme.project_min_width) / total_flex)
            client_w -= client_shrink
            project_w -= project_shrink
        desc_w = max(available_width - fixed - client_w - project_w, theme.desc_min_width)

    return (theme.date_width, client_w, project_w, desc_w, theme.hours_width)


def build_entries_table(
    rows: List[dict],
    theme: PdfTheme,
    col_widths: Tuple[float, float, float, float, float],
    desc_style,
    note_style,
    exact_hours: bool = False,
) -> Table:
    """Build one entries table, ending in its own Yhteensä and HTP rows."""
    table_data = [["Pvm", "Asiakas", "Projekti", "Kuvaus", "Aika (h)"]]
    total_hours = 0.0

    for r in rows:
        if r["date"] is None:
            continue
        per_person, hours, mult = row_hours(r, exact_hours)
        total_hours += hours
        description = [Paragraph(r["description"], desc_style)]
        if mult > 1:
            description.append(
                Paragraph(format_multiplier_note(per_person, hours, mult), note_style)
            )
        table_data.append(
            [
                Paragraph(fmt_date(r["date"]), desc_style),
                Paragraph(r["client"], desc_style),
                Paragraph(r["project"], desc_style),
                description,
                f"{hours:.2f}",
            ]
        )

    table_data.append(["", "", "", "Yhteensä", f"{total_hours:.2f}"])
    total_workdays = total_hours / 7.5 if total_hours else 0.0
    table_data.append(["", "", "", "Yhteensä (HTP)", f"{total_workdays:.2f}"])

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, 0), theme.header_font),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(theme.header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor(theme.header_text)),
        ("FONTNAME", (0, 1), (-1, -1), theme.body_font),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), theme.cell_padding),
        ("RIGHTPADDING", (0, 0), (-1, -1), theme.cell_padding),
        ("TOPPADDING", (0, 0), (-1, -1), theme.cell_padding),
        ("BOTTOMPADDING", (0, 0), (-1, -1), theme.cell_padding),
        ("FONTNAME", (0, -1), (-1, -1), theme.total_font),
    ]
    if theme.grid:
        style_cmds.append(("GRID", (0, 0), (-1, -2), 0.25, colors.HexColor(theme.grid)))
    if theme.total_line:
        style_cmds.append(("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.HexColor(theme.total_line)))

    table.setStyle(TableStyle(style_cmds))
    return table


def generate_pdf(
    rows: List[dict],
    title: str,
    date_from: date,
    date_to: date,
    out_path: str,
    theme: PdfTheme,
    exact_hours: bool = False,
    non_billable_rows: Optional[List[dict]] = None,
) -> None:
    doc = SimpleDocTemplate(
        out_path,
        pagesize=landscape(A4),
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    desc_style = styles[theme.desc_style]
    desc_style.leading = theme.desc_leading
    desc_style.fontName = theme.desc_font
    desc_style.fontSize = 10

    note_style = ParagraphStyle(
        "MultiplierNote",
        parent=desc_style,
        fontSize=desc_style.fontSize - 1,
        leading=theme.desc_leading - 1,
        textColor=colors.HexColor("#666666"),
    )

    body_style = styles[theme.text_style]
    body_style.fontSize = 10

    # keepWithNext stops the heading from being orphaned at the foot of a page
    # when the non-billable table starts on the next one.
    section_style = ParagraphStyle(
        "SectionHeading",
        parent=body_style,
        keepWithNext=True,
        spaceBefore=0,
        # Spacing goes in the style, not a Spacer flowable: keepWithNext binds to
        # the very next flowable, which must be the table itself.
        spaceAfter=4 * mm,
    )

    title_style = styles[theme.title_style]
    title_style.fontSize = 10
    period = Paragraph(
        f"<b>Työraportti</b> — Aikaväli: {fmt_date(date_from)}–{fmt_date(date_to)}",
        body_style,
    )

    non_billable_rows = non_billable_rows or []
    page_width = landscape(A4)[0]
    available_width = page_width - doc.leftMargin - doc.rightMargin
    col_widths = compute_col_widths(
        rows + non_billable_rows, theme, available_width, desc_style.fontSize
    )

    elements = [period, Spacer(1, 8 * mm)]

    # An empty table is just a header and a 0.00 total, so skip it. Only
    # reachable when every entry in the period is non-billable.
    if rows:
        elements.append(
            build_entries_table(rows, theme, col_widths, desc_style, note_style, exact_hours)
        )

    if non_billable_rows:
        if rows:
            elements.append(Spacer(1, 8 * mm))
        elements.append(Paragraph("<b>Ei-laskutettavat</b>", section_style))
        elements.append(
            build_entries_table(
                non_billable_rows, theme, col_widths, desc_style, note_style, exact_hours
            )
        )

    doc.build(elements)


def run_fetch(
    args: argparse.Namespace,
    cache: CacheStore,
    client: TogglClient,
    start_dt: datetime,
    end_dt: datetime,
) -> int:
    me_cache_key = "me"
    me = cache.get(me_cache_key)
    if not me:
        me = client.me()
        cache.set(me_cache_key, me)

    if args.debug_me:
        print(json.dumps(me, indent=2, ensure_ascii=False))

    workspace_id = args.workspace_id or me.get("default_workspace_id")
    if not workspace_id:
        workspaces = client.workspaces()
        if not workspaces:
            print("No workspaces found for this account.", file=sys.stderr)
            return 3
        workspace_id = workspaces[0]["id"]

    projects_cache_key = f"projects:{workspace_id}"
    clients_cache_key = f"clients:{workspace_id}"

    projects = cache.get(projects_cache_key)
    clients = cache.get(clients_cache_key)
    if not projects or not clients:
        projects = client.projects(workspace_id)
        clients = client.clients(workspace_id)
        cache.set(projects_cache_key, projects)
        cache.set(clients_cache_key, clients)

    project_map, client_map = build_mappings(projects, clients)

    entries = client.time_entries(start_dt, end_dt)
    rows = []
    for entry in entries:
        if entry.get("duration", 0) < 0:
            continue
        row = normalize_entry(entry, project_map, client_map)
        if row["date"] is None or row["id"] is None:
            continue
        rows.append(row)

    cache.upsert_entries(rows)
    print(f"Fetched {len(rows)} entries into {args.cache_path}")
    return 0


def load_split_entries(
    cache: CacheStore,
    args: argparse.Namespace,
    date_from: date,
    date_to: date,
) -> Optional[Tuple[List[dict], List[dict]]]:
    """Load cached rows split into (billable, non_billable).

    Returns None when there is nothing to report, so the caller can exit.
    """
    rows = cache.list_entries(date_from, date_to, args.client, args.project)
    billable, non_billable = split_billable(rows)
    if args.only_billable:
        non_billable = []
    if not billable and not non_billable:
        return None
    return billable, non_billable


def report_fetch_error(exc: requests.HTTPError) -> int:
    """Turn a Toggl HTTP error into an actionable message instead of a traceback."""
    body = exc.response.text if exc.response is not None else ""
    match = START_DATE_LIMIT_RE.search(body)
    if match:
        earliest = match.group(1)
        print(
            f"Toggl API rejected the request: start_date must not be earlier than {earliest}",
            file=sys.stderr,
        )
        print(
            "Toggl only serves ~3 months of history via this endpoint.",
            file=sys.stderr,
        )
        print(f"Try: --from {earliest}", file=sys.stderr)
    else:
        print(f"Toggl API request failed: {exc}", file=sys.stderr)
    return 5


def main() -> int:
    args = parse_args()

    cache = CacheStore(args.cache_path)

    date_from = to_date(args.date_from)
    date_to = to_date(args.date_to)

    if args.command == "fetch":
        if not args.token:
            print("TOGGL_TOKEN (or --token) is required.", file=sys.stderr)
            return 2

        start_dt = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(date_to, time.max, tzinfo=timezone.utc)

        client = TogglClient(args.token)
        try:
            return run_fetch(args, cache, client, start_dt, end_dt)
        except requests.HTTPError as exc:
            return report_fetch_error(exc)

    if args.command == "list":
        entries = load_split_entries(cache, args, date_from, date_to)
        if entries is None:
            print("No matching cached entries found.", file=sys.stderr)
            return 4
        billable, non_billable = entries

        for r in billable:
            print(format_list_row(r))
        if non_billable:
            print()
            print("Ei-laskutettavat:")
            for r in non_billable:
                print(format_list_row(r))
        return 0

    if args.command == "pdf":
        entries = load_split_entries(cache, args, date_from, date_to)
        if entries is None:
            print("No matching cached entries found.", file=sys.stderr)
            return 4
        billable, non_billable = entries

        theme = get_theme(args.theme)
        generate_pdf(
            billable,
            args.title,
            date_from,
            date_to,
            args.out,
            theme,
            args.exact_hours,
            non_billable_rows=non_billable,
        )
        print(f"PDF generated: {args.out}")
        return 0

    print("Unknown command.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
