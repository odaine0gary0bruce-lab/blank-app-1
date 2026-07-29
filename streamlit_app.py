from __future__ import annotations

import io
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from storage import DAYS, Database
try:
    from pdf_reports import build_schedule_pdf
except ModuleNotFoundError as exc:
    if exc.name != "pdf_reports":
        raise

    def build_schedule_pdf(
        assignments,
        crew_name: str | None = None,
        title: str = "Final Maintenance Schedule",
    ) -> bytes:
        """Self-contained fallback for one-file Streamlit Cloud deployments."""
        from collections import defaultdict
        from html import escape

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        rows = [dict(row) for row in assignments]
        if crew_name:
            rows = [row for row in rows if row.get("team_label") == crew_name]
        rows.sort(key=lambda row: (
            str(row.get("team_label", "")).lower(),
            str(row.get("scheduled_date", "")),
            str(row.get("start_at", "")),
            str(row.get("work_order_id", "")),
        ))
        grouped = defaultdict(list)
        for row in rows:
            grouped[str(row.get("team_label") or "Unassigned Crew")].append(row)

        output = io.BytesIO()
        document = SimpleDocTemplate(
            output,
            pagesize=landscape(letter),
            rightMargin=.45 * inch,
            leftMargin=.45 * inch,
            topMargin=.45 * inch,
            bottomMargin=.45 * inch,
            title=title,
            author="Maintainly",
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph(escape(title), styles["Title"]),
            Paragraph(
                f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} - "
                f"{len(rows)} scheduled job{'s' if len(rows) != 1 else ''}",
                styles["BodyText"],
            ),
            Spacer(1, 8),
        ]
        if not grouped:
            story.append(Paragraph("No final schedule assignments are available.", styles["BodyText"]))
        for crew_index, (crew, crew_rows) in enumerate(grouped.items()):
            if crew_index:
                story.append(PageBreak())
            people = []
            for row in crew_rows:
                for person in str(row.get("assigned_technicians", "")).split(","):
                    person = person.strip()
                    if person and person not in people:
                        people.append(person)
            story.extend([
                Paragraph(escape(crew), styles["Heading2"]),
                Paragraph(
                    f"<b>Crew size:</b> {len(people)} &nbsp;&nbsp; "
                    f"<b>People:</b> {escape(', '.join(people) or 'No members listed')}",
                    styles["BodyText"],
                ),
                Spacer(1, 8),
            ])
            table_rows = [[
                "Date / day", "Time", "Work order", "Job", "Location", "Hours", "Status",
            ]]
            for row in crew_rows:
                scheduled_date = str(row.get("scheduled_date", ""))
                day = str(row.get("day", ""))
                start_at = str(row.get("start_at", ""))[11:16]
                end_at = str(row.get("end_at", ""))[11:16]
                table_rows.append([
                    f"{scheduled_date} / {day}" if scheduled_date else day,
                    f"{start_at}-{end_at}" if start_at or end_at else "",
                    str(row.get("work_order_id", "")),
                    str(row.get("title", "")),
                    str(row.get("location", "")),
                    f"{float(row.get('assigned_hours', 0)):.1f}",
                    str(row.get("status", "Scheduled")),
                ])
            table = Table(
                table_rows,
                colWidths=[
                    1.25 * inch, .9 * inch, 1.05 * inch, 2.55 * inch,
                    1.85 * inch, .55 * inch, .9 * inch,
                ],
                repeatRows=1,
            )
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123a70")),
                ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#bfcee3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
                    colors.white, colors.HexColor("#f8fafc"),
                ]),
            ]))
            story.append(table)
        document.build(story)
        return output.getvalue()


st.set_page_config(
    page_title="Maintainly - Maintenance scheduling made clear",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #15223b;
        --muted: #64748b;
        --green: #2563eb;
        --green-dark: #1d4ed8;
        --mint: #dbeafe;
        --paper: #f4f7fb;
        --panel: #ffffff;
        --line: #d7e1ee;
        --coral: #cf765d;
        --gold: #c99443;
    }
    .stApp { background: var(--paper); color: var(--ink); }
    .main .block-container { max-width: 1500px; padding: 1.35rem 2rem 3rem; }
    section[data-testid="stSidebar"] { background: #0f2a55; border-right: 0; }
    section[data-testid="stSidebar"] * { color: #eef7f3; }
    section[data-testid="stSidebar"] div[role="radiogroup"] label {
        border-radius: 10px; padding: .58rem .7rem; margin: .12rem 0;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {
        background: rgba(255,255,255,.14);
    }
    .brand { padding: .35rem .2rem 1.35rem; }
    .brand-mark { display:inline-grid; place-items:center; width:38px; height:38px; border-radius:11px;
        background:#dbeafe; color:#1e3a8a; font-size:20px; margin-right:.55rem; }
    .brand strong { font-size:1.25rem; letter-spacing:-.02em; vertical-align:middle; }
    .brand small { display:block; color:#bfdbfe !important; margin:.45rem 0 0 3rem; }
    .eyebrow { color: var(--green); font-size:.72rem; font-weight:800; letter-spacing:.12em;
        text-transform:uppercase; margin-bottom:.22rem; }
    .page-copy { color:var(--muted); margin-top:-.4rem; margin-bottom:1.2rem; }
    h1,h2,h3 { color:var(--ink); letter-spacing:-.025em; }
    div[data-testid="stMetric"] { background:var(--panel); border:1px solid var(--line); border-radius:15px;
        padding:1rem 1.05rem; box-shadow:0 8px 22px rgba(31,63,53,.045); }
    div[data-testid="stMetric"] label { color:var(--muted); }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { color:var(--ink); }
    div[data-testid="stDataFrame"], div[data-testid="stTable"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
    div[data-testid="stForm"], div[data-testid="stExpander"] { background:var(--panel); border:1px solid var(--line);
        border-radius:15px; padding:.2rem .35rem; }
    .stButton button, .stDownloadButton button, button[kind="primary"] { border-radius:10px; font-weight:700; }
    .stButton button[kind="primary"], .stDownloadButton button[kind="primary"] { background:var(--green); border-color:var(--green); }
    .stButton button[kind="primary"]:hover { background:var(--green-dark); border-color:var(--green-dark); }
    .status-strip { background:#eaf2ff; border:1px solid #cbdcf6; border-radius:13px; padding:.75rem 1rem; margin:.3rem 0 1rem; }
    .status-strip b { color:var(--green-dark); }
    .board-card { background:#fff; border:1px solid var(--line); border-left:4px solid var(--green); border-radius:12px;
        padding:.72rem .78rem; margin:.55rem 0; min-height:106px; }
    .board-card small { color:var(--green); font-weight:800; text-transform:uppercase; }
    .board-card strong { display:block; margin:.35rem 0 .2rem; line-height:1.2; }
    .board-card span { color:var(--muted); font-size:.82rem; }
    .empty { color:var(--muted); border:1px dashed #cbd6d0; border-radius:12px; padding:1rem; text-align:center; }
    [data-testid="stTabs"] button[role="tab"] { font-weight:700; }
    [data-testid="stTabs"] div[role="tablist"] { flex-wrap:wrap; gap:.25rem; }
    [data-testid="stTabs"] button[role="tab"] { flex:0 0 auto; }
    @media (max-width: 900px) {
        .main .block-container { padding:1rem .75rem 2rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("MAINTENANCE_DATA_DIR", APP_DIR / "data")).expanduser()
DB_PATH = DATA_DIR / "maintainly.db"


def configured_database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if value:
        return value
    try:
        return str(st.secrets.get("DATABASE_URL", "")).strip()
    except (FileNotFoundError, KeyError):
        return ""


@st.cache_resource
def get_database(database_url: str) -> Database:
    return Database(DB_PATH, database_url=database_url or None)


db = get_database(configured_database_url())


def refresh(message: str | None = None) -> None:
    if message:
        st.session_state["flash"] = message
    st.rerun()


def show_flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.success(message)


def safe_index(options: list[str], value: str, default: int = 0) -> int:
    return options.index(value) if value in options else default


def table_text(value: Any, default: str = "") -> str:
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return default
    return str(value).strip()


def table_number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def job_import_template_excel() -> bytes:
    """Small optional template; every column and cell may be left incomplete."""
    output = io.BytesIO()
    template = pd.DataFrame(columns=[
        "work_order_number", "description", "location", "due_date",
        "duration_hours", "priority", "allowed_days", "notes",
    ])
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        template.to_excel(writer, index=False, sheet_name="Jobs")
    return output.getvalue()


def table_bool(value: Any, default: bool = True) -> bool:
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def header(title: str, description: str, eyebrow: str = "Operations workspace") -> None:
    st.markdown(f'<div class="eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="page-copy">{description}</p>', unsafe_allow_html=True)


def as_frame(rows: list[dict[str, Any]], columns: list[str] | None = None) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    if columns:
        available = [column for column in columns if column in frame.columns]
        frame = frame[available]
    return frame


def team_payload(prefix: str, member: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    member = member or {}
    availability_options = ["Available", "Limited", "Unavailable"]
    with st.form(f"{prefix}_team_form", clear_on_submit=member == {}):
        left, right = st.columns(2)
        name = left.text_input("Name", value=member.get("name", ""), key=f"{prefix}_name")
        role = right.text_input("Role", value=member.get("role", "Maintenance technician"), key=f"{prefix}_role")
        email = left.text_input("Email (optional)", value=member.get("email") or "", key=f"{prefix}_email")
        skill = right.selectbox(
            "Primary skill",
            ["Mechanical", "Welding", "Electrical", "HVAC", "Instrumentation", "Multi-skill", "General"],
            index=safe_index(["Mechanical", "Welding", "Electrical", "HVAC", "Instrumentation", "Multi-skill", "General"], member.get("skill", "Mechanical")),
            key=f"{prefix}_skill",
        )
        availability = left.selectbox(
            "Availability", availability_options,
            index=safe_index(availability_options, member.get("availability", "Available")),
            key=f"{prefix}_availability",
        )
        weekly_hours = right.number_input(
            "Weekly capacity", min_value=1.0, max_value=84.0, step=1.0,
            value=float(member.get("weekly_hours", 40)), key=f"{prefix}_hours",
        )
        color = left.color_picker("Profile color", value=member.get("color", "#2563eb"), key=f"{prefix}_color")
        active = right.checkbox("Active team member", value=bool(member.get("active", 1)), key=f"{prefix}_active")
        submitted = st.form_submit_button("Save team member", type="primary", use_container_width=True)
    return submitted, {
        "name": name, "role": role, "email": email, "skill": skill,
        "availability": availability, "weekly_hours": weekly_hours,
        "color": color, "active": active,
    }


def crew_payload(prefix: str, team: list[dict[str, Any]], crew: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    crew = crew or {}
    member_ids = [member["id"] for member in team]
    labels = {member["id"]: f"{member['name']} - {member['skill']}" for member in team}
    selected = [
        member_id for member_id in str(crew.get("members") or "").split(",")
        if member_id in labels
    ]
    with st.form(f"{prefix}_crew_form"):
        name = st.text_input("Crew name", value=crew.get("name", ""), key=f"{prefix}_crew_name")
        members = st.multiselect(
            "Who is in this crew?",
            member_ids,
            default=selected,
            format_func=lambda member_id: labels.get(member_id, member_id),
            key=f"{prefix}_crew_members",
        )
        st.info(f"Crew size: {len(members)} person{'s' if len(members) != 1 else ''}")
        active = st.checkbox("Active crew", value=bool(crew.get("active", 1)), key=f"{prefix}_crew_active")
        submitted = st.form_submit_button("Save crew", type="primary", use_container_width=True)
    return submitted, {"name": name.strip(), "members": members, "active": active}


def asset_payload(prefix: str, asset: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    asset = asset or {}
    criticality_options = ["Critical", "High", "Normal", "Low"]
    with st.form(f"{prefix}_asset_form", clear_on_submit=asset == {}):
        left, right = st.columns(2)
        number = left.text_input("Asset number", value=asset.get("asset_number", ""), key=f"{prefix}_asset_number")
        name = right.text_input("Asset name", value=asset.get("asset_name", ""), key=f"{prefix}_asset_name")
        location = left.text_input("Location", value=asset.get("location", ""), key=f"{prefix}_asset_location")
        department = right.text_input("Department", value=asset.get("department", "Operations"), key=f"{prefix}_asset_department")
        criticality = left.selectbox("Criticality", criticality_options, index=safe_index(criticality_options, asset.get("criticality", "Normal")), key=f"{prefix}_asset_criticality")
        manufacturer = right.text_input("Manufacturer", value=asset.get("manufacturer", ""), key=f"{prefix}_asset_manufacturer")
        model = left.text_input("Model", value=asset.get("model", ""), key=f"{prefix}_asset_model")
        active = right.checkbox("Active asset", value=bool(asset.get("active", 1)), key=f"{prefix}_asset_active")
        notes = st.text_area("Notes", value=asset.get("notes", ""), key=f"{prefix}_asset_notes")
        submitted = st.form_submit_button("Save asset", type="primary", use_container_width=True)
    return submitted, {
        "asset_number": number, "asset_name": name, "location": location,
        "department": department, "criticality": criticality, "manufacturer": manufacturer,
        "model": model, "active": active, "notes": notes,
    }


def job_payload(prefix: str, job: dict[str, Any] | None = None) -> tuple[bool, dict[str, Any]]:
    job = job or {}
    priority_options = ["Emergency", "Critical", "Urgent", "High", "Medium", "Low", "Opportunity / Shutdown"]
    status_options = ["Pending", "Scheduled", "Draft Scheduled", "Final Scheduled", "In progress", "Active", "On Hold", "Overdue"]
    if job.get("status") in ("Completed", "Complete"):
        status_options.append("Completed")
    due_value = datetime.now() + timedelta(days=2)
    try:
        due_value = datetime.fromisoformat(str(job.get("due_at", "")))
    except ValueError:
        pass
    default_days = [day for day in str(job.get("allowed_days", ",".join(DAYS[:5]))).split(",") if day in DAYS]
    with st.form(f"{prefix}_job_form", clear_on_submit=job == {}):
        work_order_id = st.text_input(
            "Work order number",
            value=job.get("id", ""),
            disabled=bool(job.get("id")),
            help="Enter the number used by your plant or maintenance system.",
            key=f"{prefix}_work_order_id",
        )
        title = st.text_input("Job name", value=job.get("title", ""), key=f"{prefix}_job_title")
        c1, c2, c3 = st.columns(3)
        asset = c1.text_input("Asset / equipment (optional)", value=job.get("asset", ""), key=f"{prefix}_job_asset")
        location = c2.text_input("Location", value=job.get("location", "Plant"), key=f"{prefix}_job_location")
        department = c3.text_input("Department", value=job.get("department", "Operations"), key=f"{prefix}_job_department")
        due_date = c1.date_input("Due date", value=due_value.date(), key=f"{prefix}_job_date")
        due_time = c2.time_input("Due time", value=due_value.time().replace(second=0, microsecond=0), key=f"{prefix}_job_time")
        duration = c3.number_input("Duration (hours)", min_value=.5, max_value=168.0, step=.5, value=float(job.get("duration_hours", 1)), key=f"{prefix}_job_duration")
        priority = c1.selectbox("Priority", priority_options, index=safe_index(priority_options, job.get("priority", "Medium")), key=f"{prefix}_job_priority")
        priority_score = c2.number_input("Priority score", 1, 20, int(job.get("priority_score", 7)), key=f"{prefix}_job_score")
        status = c3.selectbox("Status", status_options, index=safe_index(status_options, job.get("status", "Pending")), key=f"{prefix}_job_status")
        category = c1.text_input("Category", value=job.get("category", "Mechanical"), key=f"{prefix}_job_category")
        crew = c3.number_input("Crew required", 1, 20, int(job.get("crew_size_required", 1)), key=f"{prefix}_job_crew")
        mechanical = c1.number_input("Mechanical manpower", 0, 20, int(job.get("mechanical_manpower", 0)), key=f"{prefix}_job_mech")
        welding = c2.number_input("Welding manpower", 0, 20, int(job.get("welding_manpower", 0)), key=f"{prefix}_job_weld")
        preferred_options = ["No preference", *DAYS]
        preferred_value = job.get("preferred_day", "") or "No preference"
        preferred = c3.selectbox("Preferred day", preferred_options, index=safe_index(preferred_options, preferred_value), key=f"{prefix}_job_preferred")
        allowed_days = st.multiselect("Allowed days", DAYS, default=default_days, key=f"{prefix}_job_allowed")
        r1, r2, r3, r4, r5 = st.columns(5)
        scope_ready = r1.checkbox("Scope ready", value=bool(job.get("scope_ready", 1)), key=f"{prefix}_scope")
        parts_ready = r2.checkbox("Parts ready", value=bool(job.get("parts_ready", 1)), key=f"{prefix}_parts")
        permits_ready = r3.checkbox("Permits ready", value=bool(job.get("permits_ready", 1)), key=f"{prefix}_permits")
        shutdown_ready = r4.checkbox("Shutdown ready", value=bool(job.get("shutdown_ready", 1)), key=f"{prefix}_shutdown_ready")
        ready_to_schedule = r5.checkbox("Release to scheduler", value=bool(job.get("ready_to_schedule", 1)), key=f"{prefix}_release")
        b1, b2, b3, b4 = st.columns(4)
        weekend_allowed = b1.checkbox("Weekend allowed", value=bool(job.get("weekend_allowed", 0)), key=f"{prefix}_weekend")
        requires_shutdown = b2.checkbox("Requires shutdown", value=bool(job.get("requires_shutdown", 0)), key=f"{prefix}_requires_shutdown")
        fixed_day = b3.checkbox("Fixed-day job", value=bool(job.get("fixed_day_job", 0)), key=f"{prefix}_fixed")
        can_split = b4.checkbox("Can split across days", value=bool(job.get("can_split_across_days", 1)), key=f"{prefix}_split")
        notes = st.text_area("Instructions / notes", value=job.get("notes", ""), key=f"{prefix}_job_notes")
        submitted = st.form_submit_button("Save work order", type="primary", use_container_width=True)
    return submitted, {
        "work_order_id": work_order_id.strip(), "title": title, "asset": asset.strip() or "UNASSIGNED", "location": location, "department": department,
        "due_at": datetime.combine(due_date, due_time).isoformat(), "duration_hours": duration,
        "priority": priority, "priority_score": priority_score, "status": status,
        "category": category, "technician": "Unassigned", "crew_size_required": crew,
        "mechanical_manpower": mechanical, "welding_manpower": welding,
        "preferred_day": "" if preferred == "No preference" else preferred,
        "allowed_days": allowed_days, "scope_ready": scope_ready, "parts_ready": parts_ready,
        "permits_ready": permits_ready, "shutdown_ready": shutdown_ready,
        "ready_to_schedule": ready_to_schedule, "weekend_allowed": weekend_allowed,
        "requires_shutdown": requires_shutdown, "fixed_day_job": fixed_day,
        "can_split_across_days": can_split, "notes": notes,
    }


def assignment_table(rows: list[dict[str, Any]]) -> None:
    display = []
    for row in rows:
        display.append({
            "Date": row.get("scheduled_date", ""), "Day": row["day"],
            "Start": str(row.get("start_at", ""))[11:16],
            "End": str(row.get("end_at", ""))[11:16],
            "Crew": row["team_label"], "Work order": row["work_order_id"],
            "Job": row.get("title", ""), "People in crew": row["assigned_technicians"].replace(",", ", "),
            "Hours": row["assigned_hours"], "Status": row["status"],
        })
    if display:
        st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
    else:
        st.markdown('<div class="empty">No assignments in this schedule yet.</div>', unsafe_allow_html=True)


def draft_assignment_table(rows: list[dict[str, Any]]) -> None:
    """Excel-style Draft editor whose crew-member column follows the crew selection."""
    frame_key = "draft_excel_frame_modular"
    signature_key = "draft_excel_signature_modular"
    revision_key = "draft_excel_revision_modular"
    if not rows:
        st.session_state.pop(frame_key, None)
        st.session_state.pop(signature_key, None)
        st.markdown('<div class="empty">No assignments in this schedule yet.</div>', unsafe_allow_html=True)
        return

    crews = db.list_crews(active_only=True)
    team_lookup = {member["id"]: member["name"] for member in db.list_team()}
    crew_members = {
        crew["name"]: [
            team_lookup[member_id]
            for member_id in crew["members"].split(",")
            if member_id in team_lookup
        ]
        for crew in crews
    }
    active_crew_names = list(crew_members)
    if not active_crew_names:
        st.error("Create an active saved crew in Team → Crews before editing the Draft table.")
        return

    database_frame = pd.DataFrame([{
        "id": row["id"],
        "work_order_id": row["work_order_id"],
        "title": row.get("title", ""),
        "scheduled_date": Database._date_value(row.get("scheduled_date")),
        "day": row["day"],
        "start_time": time.fromisoformat(str(row.get("start_at") or "08:00")[11:16]),
        "end_time": time.fromisoformat(str(row.get("end_at") or "09:00")[11:16]),
        "team_label": row["team_label"],
        "assigned_technicians": row["assigned_technicians"].replace(",", ", "),
        "assigned_hours": float(row["assigned_hours"]),
        "status": row["status"],
        "notes": row["notes"],
    } for row in rows])
    signature = tuple(database_frame["id"].astype(str))
    if (
        st.session_state.get(signature_key) != signature
        or frame_key not in st.session_state
    ):
        st.session_state[frame_key] = database_frame
        st.session_state[signature_key] = signature
        st.session_state[revision_key] = int(st.session_state.get(revision_key, 0)) + 1

    working_frame = st.session_state[frame_key].copy()
    crew_options = list(active_crew_names)
    for crew_name in working_frame["team_label"].astype(str):
        if crew_name not in crew_options:
            crew_options.append(crew_name)

    status_options = ["Scheduled", "In Progress", "Deferred"]
    edited = st.data_editor(
        working_frame,
        key=f"draft_excel_editor_modular_{st.session_state[revision_key]}",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        height=max(180, min(600, 42 + 36 * len(working_frame))),
        column_order=[
            "work_order_id", "title", "scheduled_date", "day", "start_time", "end_time",
            "team_label", "assigned_technicians", "assigned_hours", "status", "notes",
        ],
        disabled=["id", "work_order_id", "title", "day", "end_time", "assigned_technicians"],
        column_config={
            "work_order_id": st.column_config.TextColumn("Work order", width="medium", pinned=True),
            "title": st.column_config.TextColumn("Job", width="large"),
            "scheduled_date": st.column_config.DateColumn("Date", required=True, width="medium"),
            "day": st.column_config.TextColumn("Day", width="small", disabled=True),
            "start_time": st.column_config.TimeColumn("Start", required=True, width="small"),
            "end_time": st.column_config.TimeColumn("End", width="small", disabled=True),
            "team_label": st.column_config.SelectboxColumn("Crew", options=crew_options, required=True, width="medium"),
            "assigned_technicians": st.column_config.TextColumn("People in crew", width="large", disabled=True),
            "assigned_hours": st.column_config.NumberColumn("Hours", min_value=.5, max_value=168.0, step=.5, width="small"),
            "status": st.column_config.SelectboxColumn("Status", options=status_options, required=True, width="medium"),
            "notes": st.column_config.TextColumn("Notes", width="large"),
        },
    )

    synchronized = edited.copy()
    synchronized["scheduled_date"] = [
        value if isinstance(value, date) else pd.to_datetime(value).date()
        for value in synchronized["scheduled_date"]
    ]
    synchronized["day"] = [
        value.strftime("%A") for value in synchronized["scheduled_date"]
    ]
    synchronized["end_time"] = [
        (
            datetime.combine(work_date, start_value)
            + timedelta(hours=max(.5, table_number(hours_value, .5)))
        ).time()
        for work_date, start_value, hours_value in zip(
            synchronized["scheduled_date"],
            synchronized["start_time"],
            synchronized["assigned_hours"],
        )
    ]
    synchronized["assigned_technicians"] = [
        ", ".join(crew_members.get(str(crew_name), []))
        for crew_name in synchronized["team_label"]
    ]
    derived_changed = any(
        not synchronized[column].astype(str).equals(edited[column].astype(str))
        for column in (
            "team_label", "assigned_technicians", "scheduled_date", "day",
            "start_time", "end_time", "assigned_hours",
        )
    )
    if derived_changed:
        st.session_state[frame_key] = synchronized
        st.session_state[revision_key] += 1
        st.rerun()

    if st.button("Save draft table", type="primary", use_container_width=True, key="save_draft_excel"):
        records = synchronized.to_dict("records")
        invalid = [
            record for record in records
            if record["team_label"] not in crew_members
            or not crew_members.get(record["team_label"])
        ]
        if invalid:
            st.error("Every draft job must use an active saved crew that has members.")
            return
        for record in records:
            db.update_assignment(record["id"], {
                "day": record["day"],
                "scheduled_date": record["scheduled_date"],
                "start_at": record["start_time"],
                "team_label": record["team_label"],
                "refresh_crew": True,
                "assigned_hours": record["assigned_hours"],
                "status": record["status"],
                "notes": record["notes"],
            })
        st.session_state[frame_key] = synchronized
        refresh("Draft table saved with the selected crews and their exact members.")


def assignment_editor(state: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    labels = {
        row["id"]: (
            f"{row.get('scheduled_date', row['day'])} - {row['team_label']} - "
            f"{row['work_order_id']} - {row.get('title', '')}"
        )
        for row in rows
    }
    selected_id = st.selectbox("Select assignment to update", list(labels), format_func=labels.get, key=f"{state}_assignment_select")
    row = next(item for item in rows if item["id"] == selected_id)
    crews = db.list_crews(active_only=True)
    team_lookup = {member["id"]: member["name"] for member in db.list_team()}
    crew_members = {
        crew["name"]: [
            team_lookup[member_id]
            for member_id in crew["members"].split(",")
            if member_id in team_lookup
        ]
        for crew in crews
    }
    crew_names = [crew["name"] for crew in crews]
    if row["team_label"] not in crew_names:
        crew_names.append(row["team_label"])
    if state == "Draft":
        label = st.selectbox(
            "Assigned saved crew",
            crew_names,
            index=safe_index(crew_names, row["team_label"]),
            key=f"{state}_assignment_label_{selected_id}",
        )
        selected_people = crew_members.get(
            label,
            [name.strip() for name in row["assigned_technicians"].split(",") if name.strip()],
        )
        st.info(f"People in {label}: {', '.join(selected_people) or 'No saved members'}")
    else:
        label = row["team_label"]
        st.info(f"People in {label}: {row['assigned_technicians'].replace(',', ', ')}")
    with st.form(f"{state}_assignment_editor"):
        c1, c2 = st.columns(2)
        scheduled_date = c1.date_input(
            "Scheduled date",
            value=Database._date_value(row.get("scheduled_date")),
            key=f"{state}_assignment_date",
        )
        c2.text_input("Assigned crew", value=label, disabled=True)
        c1, c2 = st.columns(2)
        start_time = c1.time_input(
            "Start time",
            value=time.fromisoformat(str(row.get("start_at") or "08:00")[11:16]),
            key=f"{state}_assignment_start",
        )
        hours = c2.number_input(
            "Assigned hours", min_value=.5, max_value=168.0, step=.5,
            value=float(row["assigned_hours"]), key=f"{state}_assignment_hours",
        )
        status_options = ["Scheduled", "In Progress", "Deferred"]
        status = st.selectbox("Status", status_options, index=safe_index(status_options, row["status"]), key=f"{state}_assignment_status")
        notes = st.text_area("Notes", value=row["notes"], key=f"{state}_assignment_notes")
        save = st.form_submit_button("Save assignment", type="primary", use_container_width=True)
    if save:
        db.update_assignment(selected_id, {
            "scheduled_date": scheduled_date,
            "start_at": start_time,
            "team_label": label,
            "refresh_crew": state == "Draft",
            "assigned_hours": hours,
            "status": status,
            "notes": notes,
        })
        refresh("Assignment updated.")
    a1, a2, a3 = st.columns(3)
    if state == "Draft" and a1.button("Promote selected", use_container_width=True):
        db.change_assignment_state(selected_id, "Final")
        refresh("Assignment promoted to Final.")
    if state == "Final" and a1.button("Move to draft", use_container_width=True):
        db.change_assignment_state(selected_id, "Draft")
        refresh("Assignment moved to Draft.")
    if state == "Final" and a2.button("Complete selected", type="primary", use_container_width=True):
        db.complete_assignment(selected_id)
        refresh("Assignment completed.")
    if a3.button("Delete assignment", use_container_width=True):
        db.delete_assignment(selected_id)
        refresh("Assignment deleted.")


def manual_assignment_form() -> None:
    jobs = db.list_jobs("Open")
    crews = db.list_crews(active_only=True)
    if not jobs:
        st.info("Add an open work order before creating a manual assignment.")
        return
    if not crews:
        st.info("Create an active crew in Team > Crews before assigning a job.")
        return
    job_labels = {job["id"]: f"{job['id']} - {job['title']} ({job['duration_hours']}h)" for job in jobs}
    with st.form("manual_assignment_form"):
        work_order_id = st.selectbox("Backlog job", list(job_labels), format_func=job_labels.get)
        c1, c2, c3, c4 = st.columns(4)
        scheduled_date = c1.date_input("Date", value=date.today())
        start_time = c2.time_input("Start", value=time(8, 0))
        team_label = c3.selectbox("Assigned crew", [crew["name"] for crew in crews])
        hours = c4.number_input("Assigned hours", min_value=.5, max_value=168.0, step=.5, value=1.0)
        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Add draft assignment", type="primary", use_container_width=True)
    if submitted:
        db.save_manual_assignment({
            "work_order_id": work_order_id,
            "scheduled_date": scheduled_date,
            "start_at": start_time,
            "team_label": team_label,
            "assigned_hours": hours,
            "notes": notes,
        })
        refresh("Manual crew assignment added to Draft.")


def weekly_board(state: str) -> None:
    rows = db.list_assignments(state, include_complete=False)
    for day_group in (DAYS[:5], DAYS[5:]):
        columns = st.columns(len(day_group))
        for column, day in zip(columns, day_group):
            day_rows = [row for row in rows if row["day"] == day]
            with column:
                st.subheader(day[:3])
                dates = sorted({
                    row.get("scheduled_date", "")
                    for row in day_rows
                    if row.get("scheduled_date")
                })
                if dates:
                    st.caption(" / ".join(dates))
                st.caption(f"{sum(float(row['assigned_hours']) for row in day_rows):.1f} planned hours")
                for row in day_rows:
                    st.caption(
                        f"{str(row.get('start_at', ''))[11:16]}–"
                        f"{str(row.get('end_at', ''))[11:16]}"
                    )
                    st.markdown(
                        f'<div class="board-card"><small>{row["team_label"]}</small><strong>{row.get("title", "")}</strong><span>{row["work_order_id"]} · {row["assigned_hours"]:.1f}h<br>{row["assigned_technicians"].replace(",", ", ")}</span></div>',
                        unsafe_allow_html=True,
                    )
                if not day_rows:
                    st.markdown('<div class="empty">No work</div>', unsafe_allow_html=True)


def page_schedule() -> None:
    header("Schedule", "Plan the week, spot risks early and keep your team moving.")
    rows = [row for row in db.list_assignments() if row["status"] != "Complete"]
    jobs = db.list_jobs("Open")
    members = db.list_team(active_only=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Scheduled work", len(rows))
    m2.metric("Planned hours", f"{sum(float(row['assigned_hours']) for row in rows):.1f}h")
    m3.metric("Open backlog", len(jobs))
    m4.metric("Active team", len(members))
    state = st.radio("Schedule state", ["Final", "Draft"], horizontal=True, label_visibility="collapsed")
    weekly_board(state)


def work_order_table_editor(jobs: list[dict[str, Any]]) -> None:
    columns = [
        "id", "title", "asset", "location", "department", "due_at", "duration_hours",
        "priority", "priority_score", "status", "category", "technician",
        "crew_size_required", "mechanical_manpower", "welding_manpower", "allowed_days",
        "preferred_day", "scope_ready", "parts_ready", "permits_ready", "shutdown_ready",
        "ready_to_schedule", "notes",
    ]
    frame = pd.DataFrame(jobs, columns=columns)
    frame.insert(0, "_original_id", frame["id"])
    edited = st.data_editor(
        frame,
        key="work_order_table_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        disabled=["_original_id"],
        height=520,
        column_config={
            "_original_id": None,
            "id": st.column_config.TextColumn("Work order number", required=True),
            "title": st.column_config.TextColumn("Job", required=True),
            "asset": st.column_config.TextColumn("Asset / equipment"),
            "due_at": st.column_config.TextColumn("Due date/time"),
            "duration_hours": st.column_config.NumberColumn("Duration hours", min_value=.5, step=.5),
            "priority": st.column_config.SelectboxColumn(
                "Priority", options=["Emergency", "Critical", "Urgent", "High", "Medium", "Low", "Opportunity / Shutdown"]
            ),
            "priority_score": st.column_config.NumberColumn("Priority score", min_value=1, max_value=20, step=1),
            "status": st.column_config.SelectboxColumn(
                "Status", options=["Pending", "Scheduled", "Draft Scheduled", "Final Scheduled", "In progress", "Active", "On Hold", "Completed", "Overdue"]
            ),
            "crew_size_required": st.column_config.NumberColumn("Crew size", min_value=1, step=1),
            "mechanical_manpower": st.column_config.NumberColumn("Mechanical", min_value=0, step=1),
            "welding_manpower": st.column_config.NumberColumn("Welding", min_value=0, step=1),
            "preferred_day": st.column_config.SelectboxColumn("Preferred day", options=["", *DAYS]),
            "scope_ready": st.column_config.CheckboxColumn("Scope ready"),
            "parts_ready": st.column_config.CheckboxColumn("Parts ready"),
            "permits_ready": st.column_config.CheckboxColumn("Permits ready"),
            "shutdown_ready": st.column_config.CheckboxColumn("Shutdown ready"),
            "ready_to_schedule": st.column_config.CheckboxColumn("Release"),
        },
    )
    if st.button("Save work-order table", type="primary", use_container_width=True):
        records = [
            record for record in edited.to_dict("records")
            if table_text(record.get("id")) or table_text(record.get("title"))
        ]
        numbers = [table_text(record.get("id")) for record in records]
        original_ids = {table_text(job.get("id")) for job in jobs}
        original_statuses = {table_text(job.get("id")): job.get("status") for job in jobs}
        retained_ids = {
            table_text(record.get("_original_id")) for record in records
            if table_text(record.get("_original_id"))
        }
        changed_numbers = [
            record for record in records
            if table_text(record.get("_original_id"))
            and table_text(record.get("_original_id")) != table_text(record.get("id"))
        ]
        new_numbers = {
            table_text(record.get("id")) for record in records
            if not table_text(record.get("_original_id"))
        }
        database_ids = {job["id"] for job in db.list_jobs("All")}
        if any(not number for number in numbers):
            st.error("Every row needs your work order number.")
            return
        if len(numbers) != len(set(numbers)):
            st.error("Work order numbers must be unique.")
            return
        if changed_numbers:
            st.error("Existing work order numbers cannot be changed in the table. Delete the row and add a new one.")
            return
        if new_numbers & database_ids:
            st.error(f"These work order numbers already exist: {', '.join(sorted(new_numbers & database_ids))}")
            return
        if any(not table_text(record.get("title")) for record in records):
            st.error("Every row needs a job name.")
            return
        for record in records:
            original_id = table_text(record.get("_original_id"))
            original_status = original_statuses.get(original_id)
            edited_status = table_text(record.get("status"), "Pending")
            if edited_status in ("Completed", "Complete") and original_status not in ("Completed", "Complete"):
                st.error("Complete work from the Final schedule so the assignment and work order update together.")
                return
            if original_status in ("Completed", "Complete") and edited_status not in ("Completed", "Complete"):
                st.error("Use Planning → History → Reopen selected job to reopen completed work.")
                return
        for record in records:
            payload = {
                "title": table_text(record.get("title")),
                "asset": table_text(record.get("asset"), "UNASSIGNED"),
                "location": table_text(record.get("location"), "Plant"),
                "department": table_text(record.get("department"), "Operations"),
                "due_at": table_text(record.get("due_at"), (datetime.now() + timedelta(days=2)).isoformat()),
                "duration_hours": max(.5, table_number(record.get("duration_hours"), 1)),
                "priority": table_text(record.get("priority"), "Medium"),
                "priority_score": max(1, min(20, int(table_number(record.get("priority_score"), 7)))),
                "status": table_text(record.get("status"), "Pending"),
                "category": table_text(record.get("category"), "Mechanical"),
                "technician": table_text(record.get("technician"), "Unassigned"),
                "crew_size_required": max(1, int(table_number(record.get("crew_size_required"), 1))),
                "mechanical_manpower": max(0, int(table_number(record.get("mechanical_manpower"), 0))),
                "welding_manpower": max(0, int(table_number(record.get("welding_manpower"), 0))),
                "allowed_days": table_text(record.get("allowed_days"), ",".join(DAYS[:5])),
                "preferred_day": table_text(record.get("preferred_day")),
                "scope_ready": table_bool(record.get("scope_ready"), True),
                "parts_ready": table_bool(record.get("parts_ready"), True),
                "permits_ready": table_bool(record.get("permits_ready"), True),
                "shutdown_ready": table_bool(record.get("shutdown_ready"), True),
                "ready_to_schedule": table_bool(record.get("ready_to_schedule"), True),
                "notes": table_text(record.get("notes")),
            }
            db.save_job(payload, table_text(record.get("id")))
        for removed_id in original_ids - retained_ids:
            db.delete_job(removed_id)
        refresh("Work-order table saved.")


def page_work_orders() -> None:
    header("Work orders", "Prioritize, assign and close out maintenance work.")
    table_tab, add_tab, edit_tab = st.tabs(["Table editor", "Add form", "Edit / delete"])
    with table_tab:
        st.caption("Add a row, enter your work order number and job details, then save the table.")
        work_order_table_editor(db.list_jobs("All"))
    with add_tab:
        submitted, payload = job_payload("new")
        if submitted:
            try:
                if not payload["work_order_id"]:
                    st.error("Work order number is required.")
                elif any(job["id"] == payload["work_order_id"] for job in db.list_jobs("All")):
                    st.error("That work order number already exists.")
                else:
                    job_id = db.save_job(payload)
                    refresh(f"{job_id} created.")
            except Exception as exc:
                st.error(str(exc))
    with edit_tab:
        jobs = db.list_jobs("All")
        if not jobs:
            st.info("No work orders to edit.")
        else:
            labels = {job["id"]: f"{job['id']} - {job['title']}" for job in jobs}
            selected_id = st.selectbox("Select work order", list(labels), format_func=labels.get)
            selected = next(job for job in jobs if job["id"] == selected_id)
            submitted, payload = job_payload(f"edit_{selected_id}", selected)
            if submitted:
                try:
                    if (
                        selected["status"] in ("Completed", "Complete")
                        and payload["status"] not in ("Completed", "Complete")
                    ):
                        st.error("Use Planning → History → Reopen selected job to reopen completed work.")
                    else:
                        db.save_job(payload, selected_id)
                        refresh(f"{selected_id} updated.")
                except Exception as exc:
                    st.error(str(exc))
            if st.button("Delete selected work order"):
                db.delete_job(selected_id)
                refresh(f"{selected_id} deleted.")
            st.divider()
            st.subheader("Delete all work orders")
            st.warning("This also removes every draft and final schedule assignment linked to the work orders.")
            confirm_delete_all = st.checkbox("I understand and want to delete all work orders")
            if st.button("Delete all work orders", disabled=not confirm_delete_all, type="primary"):
                count = db.delete_all_jobs()
                refresh(f"{count} work order(s) deleted.")


def page_team() -> None:
    header("Team", "Balance assignments and see who is ready for the next job.")
    members = db.list_team()
    crews = db.list_crews()
    active = [member for member in members if member["active"]]
    total_capacity = sum(float(member["weekly_hours"]) for member in active)
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Active members", len(active))
    t2.metric("Weekly capacity", f"{total_capacity:.0f}h")
    t3.metric("Skills covered", len({member["skill"] for member in active}))
    t4.metric("Saved crews", len(crews))
    roster_tab, add_tab, edit_tab, crew_tab = st.tabs(["Roster", "Add member", "Edit / delete", "Crews"])
    with roster_tab:
        display = [{"Name": m["name"], "Role": m["role"], "Skill": m["skill"], "Availability": m["availability"], "Weekly hours": m["weekly_hours"], "Active": bool(m["active"]), "Email": m["email"]} for m in members]
        st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
    with add_tab:
        submitted, payload = team_payload("add")
        if submitted:
            try:
                db.save_team_member(payload)
                refresh("Team member added.")
            except Exception as exc:
                st.error(str(exc))
    with edit_tab:
        if not members:
            st.info("No team members to edit.")
        else:
            labels = {member["id"]: f"{member['name']} - {member['skill']}" for member in members}
            selected_id = st.selectbox("Select team member", list(labels), format_func=labels.get)
            selected = next(member for member in members if member["id"] == selected_id)
            submitted, payload = team_payload(f"edit_{selected_id}", selected)
            if submitted:
                try:
                    db.save_team_member(payload, selected_id)
                    refresh("Team member updated.")
                except Exception as exc:
                    st.error(str(exc))
            if st.button("Delete selected team member"):
                db.delete_team_member(selected_id)
                refresh("Team member deleted.")
    with crew_tab:
        member_lookup = {member["id"]: member["name"] for member in members}
        display = []
        for crew in crews:
            crew_members = [value for value in crew["members"].split(",") if value]
            display.append({
                "Crew": crew["name"],
                "Persons": len(crew_members),
                "Members": ", ".join(member_lookup.get(member_id, "Removed member") for member_id in crew_members),
                "Active": bool(crew["active"]),
            })
        if display:
            st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
        else:
            st.info("No crews saved yet.")
        create_tab, manage_tab = st.tabs(["Create crew", "Edit / delete crew"])
        with create_tab:
            if not members:
                st.info("Add team members before creating a crew.")
            else:
                submitted, payload = crew_payload("new", members)
                if submitted:
                    try:
                        db.save_crew(payload)
                        refresh(f"{payload['name']} crew saved with {len(payload['members'])} person(s).")
                    except Exception as exc:
                        st.error("That crew name already exists." if "UNIQUE" in str(exc) else str(exc))
        with manage_tab:
            if not crews:
                st.info("Create a crew first.")
            else:
                labels = {
                    crew["id"]: f"{crew['name']} ({len([value for value in crew['members'].split(',') if value])} persons)"
                    for crew in crews
                }
                crew_id = st.selectbox("Select crew", list(labels), format_func=labels.get)
                selected = next(crew for crew in crews if crew["id"] == crew_id)
                submitted, payload = crew_payload(f"edit_{crew_id}", members, selected)
                if submitted:
                    try:
                        db.save_crew(payload, crew_id)
                        refresh(f"{payload['name']} crew updated.")
                    except Exception as exc:
                        st.error("That crew name already exists." if "UNIQUE" in str(exc) else str(exc))
                if st.button("Delete selected crew"):
                    db.delete_crew(crew_id)
                    refresh("Crew deleted.")


def page_assets() -> None:
    header("Assets", "Track asset health, criticality and upcoming maintenance.")
    assets = db.list_assets()
    critical = len([asset for asset in assets if asset["criticality"] == "Critical"])
    a1, a2, a3 = st.columns(3)
    a1.metric("Registered assets", len(assets))
    a2.metric("Active assets", len([asset for asset in assets if asset["active"]]))
    a3.metric("Critical assets", critical)
    register_tab, add_tab, edit_tab = st.tabs(["Asset register", "Add asset", "Edit / delete"])
    with register_tab:
        display = [{"Asset": a["asset_number"], "Name": a["asset_name"], "Location": a["location"], "Department": a["department"], "Criticality": a["criticality"], "Manufacturer": a["manufacturer"], "Model": a["model"], "Active": bool(a["active"])} for a in assets]
        st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
    with add_tab:
        submitted, payload = asset_payload("new")
        if submitted:
            try:
                db.save_asset(payload)
                refresh("Asset added.")
            except Exception as exc:
                st.error(str(exc))
    with edit_tab:
        if not assets:
            st.info("No assets to edit.")
        else:
            labels = {asset["id"]: f"{asset['asset_number']} - {asset['asset_name']}" for asset in assets}
            selected_id = st.selectbox("Select asset", list(labels), format_func=labels.get)
            selected = next(asset for asset in assets if asset["id"] == selected_id)
            submitted, payload = asset_payload(f"edit_{selected_id}", selected)
            if submitted:
                try:
                    db.save_asset(payload, selected_id)
                    refresh("Asset updated.")
                except Exception as exc:
                    st.error(str(exc))
            if st.button("Delete selected asset"):
                db.delete_asset(selected_id)
                refresh("Asset deleted.")


def page_planning() -> None:
    header("Planning", "Turn the maintenance backlog into validated crews and a final weekly plan.")
    jobs = db.list_jobs("All")
    open_jobs = [job for job in jobs if job["status"] not in ("Completed", "Complete")]
    draft = db.list_assignments("Draft", include_complete=False)
    final = db.list_assignments("Final", include_complete=False)
    ready = [job for job in open_jobs if job["scope_ready"] and job["parts_ready"] and job["permits_ready"] and job["shutdown_ready"] and job["ready_to_schedule"]]
    tabs = st.tabs(["Overview", "Backlog", "Readiness", "Draft", "Crews", "Final", "Board", "History", "Data"])
    with tabs[0]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Backlog", len(open_jobs), f"{len(ready)} ready")
        c2.metric("Draft schedule", len(draft), f"{sum(float(row['assigned_hours']) for row in draft):.1f}h")
        c3.metric("Final schedule", len(final), f"{sum(float(row['assigned_hours']) for row in final):.1f}h")
        c4.metric("Completed", len(jobs) - len(open_jobs))
        left, right = st.columns(2)
        with left:
            st.subheader("Backlog by priority")
            counts = pd.Series([job["priority"] for job in open_jobs]).value_counts()
            if not counts.empty:
                st.bar_chart(counts)
            else:
                st.info("No open jobs.")
        with right:
            st.subheader("Planning gate")
            readiness = (len(ready) / len(open_jobs) * 100) if open_jobs else 100
            st.metric("Ready to schedule", f"{readiness:.0f}%")
            st.progress(readiness / 100)
            st.caption(f"{len(open_jobs) - len(ready)} job(s) still need planning checks.")
    with tabs[1]:
        display = [{"Work order": j["id"], "Job": j["title"], "Asset": j["asset"], "Labor": f"{j['duration_hours']}h / {j['crew_size_required']} crew", "Priority": j["priority"], "Status": j["status"]} for j in open_jobs]
        st.dataframe(pd.DataFrame(display), use_container_width=True, hide_index=True)
    with tabs[2]:
        readiness_rows = []
        for job in open_jobs:
            readiness_rows.append({"Work order": job["id"], "Job": job["title"], "Scope": bool(job["scope_ready"]), "Parts": bool(job["parts_ready"]), "Permits": bool(job["permits_ready"]), "Shutdown": bool(job["shutdown_ready"]), "Released": bool(job["ready_to_schedule"]), "Ready": job in ready})
        st.dataframe(pd.DataFrame(readiness_rows), use_container_width=True, hide_index=True)
        st.caption("Update readiness fields from Work orders → Edit / update.")
    with tabs[3]:
        st.caption(
            "Scheduling uses only the exact active crews you built in Team → Crews. "
            "It never creates or changes a crew."
        )
        controls = st.columns([1.4, 1, 1, 1])
        week_default = date.today() - timedelta(days=date.today().weekday())
        week_start = controls[0].date_input("Week starting", value=week_default)
        clear = controls[1].checkbox("Clear existing draft", value=True)
        if controls[2].button("Generate draft", type="primary", use_container_width=True):
            result = db.generate_draft(clear_existing=clear, week_start=week_start)
            st.session_state["draft_warnings"] = result["warnings"]
            refresh(f"{result['created']} draft assignment(s) generated.")
        if controls[3].button("Promote all", use_container_width=True):
            count = db.promote_all()
            refresh(f"{count} assignment(s) promoted to Final.")
        warnings = list(dict.fromkeys([
            *st.session_state.get("draft_warnings", []),
            *db.schedule_warnings("Draft"),
        ]))
        if warnings:
            with st.expander(f"Scheduling warnings ({len(warnings)})"):
                for warning in warnings:
                    st.warning(warning)
        st.caption("Change the Crew cell and the People in crew column updates immediately on that row.")
        draft_assignment_table(draft)
        with st.expander("Add manual assignment"):
            manual_assignment_form()
        if draft and st.button("Reset draft schedule"):
            count = db.reset_schedule("Draft")
            refresh(f"{count} draft assignment(s) cleared.")
    with tabs[4]:
        crew_rows = []
        for row in [*draft, *final]:
            crew_rows.append({
                "State": row["schedule_state"],
                "Date": row.get("scheduled_date", ""),
                "Day": row["day"],
                "Start": str(row.get("start_at", ""))[11:16],
                "End": str(row.get("end_at", ""))[11:16],
                "Crew": row["team_label"],
                "People in crew": row["assigned_technicians"].replace(",", ", "),
                "Work order": row["work_order_id"],
                "Hours": row["assigned_hours"],
            })
        st.dataframe(pd.DataFrame(crew_rows), use_container_width=True, hide_index=True)
    with tabs[5]:
        assignment_table(final)
        if final:
            st.subheader("Download final crew schedules")
            st.download_button(
                "Download complete final schedule PDF",
                data=build_schedule_pdf(final),
                file_name="maintainly-final-schedule.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )
            for crew_name in sorted({row["team_label"] for row in final}):
                safe_name = "".join(character if character.isalnum() else "-" for character in crew_name).strip("-").lower() or "crew"
                st.download_button(
                    f"Download {crew_name} PDF",
                    data=build_schedule_pdf(final, crew_name=crew_name, title=f"{crew_name} - Final Schedule"),
                    file_name=f"{safe_name}-final-schedule.pdf",
                    mime="application/pdf",
                    key=f"download_{safe_name}_final_pdf",
                    use_container_width=True,
                )
        with st.expander("Edit final assignment"):
            assignment_editor("Final", final)
        if final:
            st.divider()
            st.subheader("Clear final schedule")
            st.warning(
                "This removes unfinished Final assignments and returns their work orders "
                "to Pending. Completed work and its history are kept."
            )
            confirm_clear_final = st.checkbox(
                "I understand and want to clear the final schedule",
                key="confirm_clear_final_schedule",
            )
            if st.button(
                "Clear final schedule",
                disabled=not confirm_clear_final,
                key="clear_final_schedule",
            ):
                count = db.clear_final_schedule()
                refresh(f"{count} unfinished final assignment(s) cleared.")
    with tabs[6]:
        board_state = st.radio("Board state", ["Draft", "Final"], horizontal=True)
        weekly_board(board_state)
    with tabs[7]:
        completed = [job for job in jobs if job["status"] in ("Completed", "Complete")]
        st.subheader("Completed jobs")
        if completed:
            labels = {job["id"]: f"{job['id']} - {job['title']}" for job in completed}
            selected_id = st.selectbox("Completed job", list(labels), format_func=labels.get)
            if st.button("Reopen selected job"):
                db.reopen_job(selected_id)
                refresh(f"{selected_id} reopened.")
            st.dataframe(as_frame(completed, ["id", "title", "asset", "completed_at"]), use_container_width=True, hide_index=True)
        else:
            st.info("No completed jobs yet.")
        st.subheader("Schedule audit trail")
        st.dataframe(as_frame(db.list_history(), ["changed_at", "assignment_id", "action_type", "old_value", "new_value"]), use_container_width=True, hide_index=True)
    with tabs[8]:
        left, right = st.columns(2)
        with left:
            st.subheader("Export backlog")
            st.download_button("Download jobs CSV", data=db.jobs_csv(), file_name="maintainly-jobs.csv", mime="text/csv", type="primary")
            st.download_button(
                "Download optional Excel template",
                data=job_import_template_excel(),
                file_name="maintainly-job-import-template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with right:
            st.subheader("Import backlog")
            st.caption(
                "CSV and Excel files are accepted even when columns or values are missing. "
                "Temporary defaults remain editable after import."
            )
            upload = st.file_uploader("Choose jobs CSV or Excel file", type=["csv", "xlsx"])
        if upload:
            try:
                if upload.name.lower().endswith(".csv"):
                    imported_frame = pd.read_csv(io.BytesIO(upload.getvalue()), dtype=object)
                else:
                    imported_frame = pd.read_excel(io.BytesIO(upload.getvalue()), dtype=object)
                st.subheader("Review and edit imported jobs")
                reviewed_frame = st.data_editor(
                    imported_frame,
                    use_container_width=True,
                    hide_index=True,
                    num_rows="dynamic",
                    key=f"planning_import_review_{upload.name}_{upload.size}",
                )
                if st.button("Import reviewed rows", type="primary"):
                    result = db.import_jobs_records(reviewed_frame.to_dict("records"))
                    refresh(f"Import complete: {result['created']} created, {result['updated']} updated.")
            except ImportError:
                st.error(
                    "Excel support is not installed. Add openpyxl>=3.1,<4 to "
                    "requirements.txt and reboot the app."
                )
            except Exception as exc:
                st.error(str(exc))


def page_reports() -> None:
    header("Reports", "Turn maintenance activity into clear operational decisions.")
    jobs = db.list_jobs("All")
    assignments = db.list_assignments()
    completed = [job for job in jobs if job["status"] in ("Completed", "Complete")]
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Total work orders", len(jobs))
    r2.metric("Completed", len(completed))
    r3.metric("Completion rate", f"{(len(completed) / len(jobs) * 100 if jobs else 0):.0f}%")
    r4.metric("Scheduled hours", f"{sum(float(row['assigned_hours']) for row in assignments):.1f}h")
    left, right = st.columns(2)
    with left:
        st.subheader("Jobs by status")
        status_counts = pd.Series([job["status"] for job in jobs]).value_counts()
        if not status_counts.empty:
            st.bar_chart(status_counts)
    with right:
        st.subheader("Jobs by department")
        department_counts = pd.Series([job["department"] for job in jobs]).value_counts()
        if not department_counts.empty:
            st.bar_chart(department_counts)


with st.sidebar:
    st.markdown('<div class="brand"><span class="brand-mark">M</span><strong>Maintainly</strong><small>Plant maintenance</small></div>', unsafe_allow_html=True)
    page = st.radio(
        "Navigation",
        ["Schedule", "Work orders", "Planning", "Team", "Reports"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("Persistent Streamlit edition")
    st.caption(f"Database: {db.backend_label}")
    if db.backend == "sqlite":
        st.warning(
            "Local SQLite mode: records may be reset by hosted redeployments. "
            "Add DATABASE_URL in Streamlit Secrets for managed persistence.",
            icon="⚠️",
        )


show_flash()
{
    "Schedule": page_schedule,
    "Work orders": page_work_orders,
    "Planning": page_planning,
    "Team": page_team,
    "Reports": page_reports,
}[page]()
