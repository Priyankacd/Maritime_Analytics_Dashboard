"""Zodiac Maritime vessel KPI investigation dashboard."""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

import pandas as pd
import plotly.express as px
from dash import Dash, Input, Output, State, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate

BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = Path(os.getenv("KPI_CSV_PATH", BASE_DIR / "vessel_kpi_reports.csv"))
DB_PATH = Path(os.getenv("KPI_DB_PATH", BASE_DIR / "vessel_kpi.sqlite"))
PORT = int(os.getenv("PORT", "8050"))

EXPECTED_COLUMNS = [
    "IMO", "Vessel_Name", "Report_ID", "To_Timestamp", "KPI", "Voyage_Type",
    "Report_Duration", "SP_BSL_Start", "SP_BSL_End", "SP_BSL_Reports",
    "PWR_BSL_SAM", "SPD_BSL_SAM", "SPD_BSL_OOS", "Power_ME", "Power_%",
    "Power_Deviation", "Speed_%", "Speed_Deviation", "ME_Running_Hours",
    "Power_Filter_Flag", "Speed_Filter", "Dual_Fuel_Mode_str",
]


@contextmanager
def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Seed SQLite once; subsequent starts keep saved corrections."""
    if not CSV_PATH.exists() and not DB_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {CSV_PATH}. Put vessel_kpi_reports.csv beside app.py "
            "or set KPI_CSV_PATH to its full path."
        )
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS vessel_reports (
            row_key INTEGER PRIMARY KEY,
            IMO TEXT, Vessel_Name TEXT, Report_ID TEXT, To_Timestamp TEXT, KPI TEXT,
            Voyage_Type TEXT, Report_Duration REAL, SP_BSL_Start TEXT, SP_BSL_End TEXT,
            SP_BSL_Reports REAL, PWR_BSL_SAM REAL, SPD_BSL_SAM REAL, SPD_BSL_OOS REAL,
            Power_ME REAL, "Power_%" REAL, Power_Deviation REAL, "Speed_%" REAL,
            Speed_Deviation REAL, ME_Running_Hours REAL, Power_Filter_Flag TEXT,
            Speed_Filter TEXT, Dual_Fuel_Mode_str TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            Report_ID TEXT NOT NULL, row_key INTEGER NOT NULL, field TEXT NOT NULL,
            old_value TEXT, new_value TEXT, user TEXT NOT NULL, changed_at TEXT NOT NULL
        )""")
        count = conn.execute("SELECT COUNT(*) FROM vessel_reports").fetchone()[0]
        if count == 0:
            source = pd.read_csv(CSV_PATH)
            missing = set(EXPECTED_COLUMNS) - set(source.columns)
            if missing:
                raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
            source = source[EXPECTED_COLUMNS].copy()
            source.insert(0, "row_key", range(1, len(source) + 1))
            source.to_sql("vessel_reports", conn, if_exists="append", index=False)


def load_data() -> pd.DataFrame:
    with connect_db() as conn:
        data = pd.read_sql_query("SELECT * FROM vessel_reports ORDER BY row_key", conn)
    data["_timestamp"] = pd.to_datetime(data["To_Timestamp"], errors="coerce")
    return data


def display_value(value):
    if pd.isna(value):
        return None
    if isinstance(value, (np_integer := __import__('numpy').integer,)):
        return int(value)
    if isinstance(value, (float,)) and value.is_integer():
        return int(value)
    return value


def filter_data(data, vessels, start_date, end_date, kpis, voyages):
    result = data.copy()
    if vessels:
        result = result[result["Vessel_Name"].isin(vessels)]
    if start_date:
        result = result[result["_timestamp"] >= pd.Timestamp(start_date)]
    if end_date:
        result = result[result["_timestamp"] < pd.Timestamp(end_date) + pd.Timedelta(days=1)]
    if kpis and len(kpis) < 2:
        result = result[result["KPI"].isin(kpis)]
    if voyages and len(voyages) < 2:
        result = result[result["Voyage_Type"].isin(voyages)]
    return result


def make_figure(data, metric, flag_col, title, selected_keys=None):
    valid = data[data[metric].notna()].copy()
    if valid.empty:
        fig = px.scatter(title=title)
        fig.update_layout(template="plotly_white", height=340, xaxis_title="Report timestamp", yaxis_title=metric)
        return fig
    valid["_flag_display"] = valid[flag_col].fillna("N/A").astype(str)
    valid["_row_key_str"] = valid["row_key"].astype(str)
    fig = px.scatter(
        valid, x="_timestamp", y=metric, color="_flag_display",
        color_discrete_map={"No": "#2878B5", "Yes": "#E6A23C", "N/A": "#9CA3AF"},
        custom_data=["_row_key_str"], hover_data={"Vessel_Name": True, "KPI": True,
            "Voyage_Type": True, "Report_ID": True, "_timestamp": True,
            "_flag_display": True, "_row_key_str": False},
        labels={"_timestamp": "Report timestamp", metric: metric, "_flag_display": "Filter flag"},
        title=title,
    )
    if selected_keys:
        fig.update_traces(selected={"marker": {"opacity": 1, "size": 11}},
                          unselected={"marker": {"opacity": 0.25}})
    fig.update_layout(template="plotly_white", height=340, margin=dict(l=45, r=20, t=55, b=45),
                      legend_title_text="Filter flag", dragmode="select", clickmode="event+select",
                      uirevision="keep-view")
    fig.update_xaxes(showgrid=True, gridcolor="#E8EDF2")
    fig.update_yaxes(showgrid=True, gridcolor="#E8EDF2")
    return fig


def keys_from_selection(selection):
    if not selection or not selection.get("points"):
        return set()
    result = set()
    for point in selection["points"]:
        custom = point.get("customdata")
        if custom:
            try:
                result.add(int(custom[0]))
            except (TypeError, ValueError):
                pass
    return result


init_db()
app = Dash(__name__, title="Zodiac Maritime | Vessel KPI Monitor", suppress_callback_exceptions=True)
server = app.server

initial = load_data()
min_date = initial["_timestamp"].min().date()
max_date = initial["_timestamp"].max().date()

app.layout = html.Div([
    html.Div([
        html.Div([html.Div("ZODIAC MARITIME", className="eyebrow"),
                  html.H1("Vessel Performance Monitor"),
                  html.P("Investigate baseline KPI deviations, select reports, and save validated corrections.", className="subtitle")], className="hero-copy"),
        html.Div([html.Div("LIVE DATASET", className="status-label"), html.Div("SQLite-backed", className="status-value")], className="status-pill")
    ], className="hero"),
    html.Div([
        html.Div([html.Label("Vessel"), dcc.Dropdown(id="vessel-filter", options=[{"label": x, "value": x} for x in sorted(initial.Vessel_Name.unique())], value=sorted(initial.Vessel_Name.unique()), multi=True, clearable=True)]),
        html.Div([html.Label("Date range"), dcc.DatePickerRange(id="date-filter", start_date=min_date, end_date=max_date, min_date_allowed=min_date, max_date_allowed=max_date, display_format="DD MMM YYYY", clearable=True)]),
        html.Div([html.Label("KPI"), dcc.Checklist(id="kpi-filter", options=[{"label": " Power", "value": "Power"}, {"label": " Speed", "value": "Speed"}], value=["Power", "Speed"], inline=True, className="checklist")]),
        html.Div([html.Label("Voyage type"), dcc.Checklist(id="voyage-filter", options=[{"label": " Cargo", "value": "CARGO"}, {"label": " Ballast", "value": "BALLAST"}], value=["CARGO", "BALLAST"], inline=True, className="checklist")]),
    ], className="filter-grid"),
    html.Div(id="kpi-cards", className="metric-grid"),
    html.Div([
        html.Div([html.Div([html.H2("Power performance"), html.Span("POWER KPI", className="chart-tag")], className="section-head"),
                  dcc.Graph(id="power-chart", config={"displaylogo": False, "scrollZoom": True}, clear_on_unhover=True)], className="chart-card"),
        html.Div([html.Div([html.H2("Speed performance"), html.Span("SPEED KPI", className="chart-tag")], className="section-head"),
                  dcc.Graph(id="speed-chart", config={"displaylogo": False, "scrollZoom": True}, clear_on_unhover=True)], className="chart-card"),
    ], className="chart-grid"),
    html.Div([
        html.Div([html.Div([html.H2("Report detail & correction"), html.P("Use box/lasso selection on either chart. With no selection, all rows matching the filters are shown.", className="muted")]),
                  html.Div([html.Label("Audit user"), dcc.Input(id="audit-user", value="analyst", type="text", maxLength=80, className="user-input")], className="audit-user")], className="table-heading"),
        html.Div(id="selection-status", className="selection-status"),
        dash_table.DataTable(id="detail-table", columns=[], data=[], editable=True, row_selectable=False, hidden_columns=["row_key"],
            page_action="native", page_size=15, sort_action="native", filter_action="native",
            fixed_rows={"headers": True}, style_table={"overflowX": "auto", "maxHeight": "520px", "overflowY": "auto"},
            style_header={"backgroundColor": "#F1F5F9", "fontWeight": "700", "color": "#233044", "border": "1px solid #DDE5ED", "whiteSpace": "normal", "height": "auto"},
            style_cell={"fontFamily": "Arial, sans-serif", "fontSize": "12px", "padding": "9px", "minWidth": "95px", "maxWidth": "220px", "overflow": "hidden", "textOverflow": "ellipsis", "border": "1px solid #E6EBF1"},
            style_data_conditional=[
                {"if": {"filter_query": "{Power_Deviation} < 0", "column_id": "Power_Deviation"}, "backgroundColor": "#FEE2E2", "color": "#991B1B", "fontWeight": "700"},
                {"if": {"filter_query": "{Speed_Deviation} < 0", "column_id": "Speed_Deviation"}, "backgroundColor": "#FEE2E2", "color": "#991B1B", "fontWeight": "700"},
                {"if": {"column_id": "Power_%"}, "backgroundColor": "#FFFDF5"},
                {"if": {"column_id": "Speed_%"}, "backgroundColor": "#FFFDF5"},
            ]),
        html.Div([html.Div("Editable fields: Power_% and Speed_%. Valid values are 0–200; the edited value must match the row's KPI.", className="helper-text"),
                  html.Button("Save changes", id="save-button", n_clicks=0, className="primary-button"), html.Div(id="save-message", role="status", className="save-message")], className="save-row"),
    ], className="table-card"),
    html.Div([html.Div([html.H3("Data-quality watch"), html.P("KPI-specific blanks are expected on the other KPI's rows. They are not counted as defects.")], className="quality-copy"), html.Div(id="quality-summary", className="quality-items")], className="quality-card"),
    html.Footer("Zodiac Maritime • Python / Dash / Plotly / SQLite • Demo application for the take-home exercise", className="footer")
], className="page-shell")


@app.callback(
    Output("power-chart", "figure"), Output("speed-chart", "figure"),
    Output("kpi-cards", "children"), Output("quality-summary", "children"),
    Input("vessel-filter", "value"), Input("date-filter", "start_date"), Input("date-filter", "end_date"),
    Input("kpi-filter", "value"), Input("voyage-filter", "value"),
)
def update_dashboard(vessels, start_date, end_date, kpis, voyages):
    data = load_data()
    filtered = filter_data(data, vessels, start_date, end_date, kpis or [], voyages or [])
    power_data = filtered[filtered.KPI.eq("Power")]
    speed_data = filtered[filtered.KPI.eq("Speed")]
    power_fig = make_figure(power_data, "Power_%", "Power_Filter_Flag", "Power % by report timestamp")
    speed_fig = make_figure(speed_data, "Speed_%", "Speed_Filter", "Speed % by report timestamp")
    valid_power = power_data["Power_%"].notna().sum()
    valid_speed = speed_data["Speed_%"].notna().sum()
    cards = [
        html.Div([html.Div("Reports in scope", className="metric-label"), html.Div(f"{len(filtered):,}", className="metric-value"), html.Div("After all active filters", className="metric-foot")], className="metric-card"),
        html.Div([html.Div("Power readings", className="metric-label"), html.Div(f"{valid_power:,}", className="metric-value"), html.Div(f"{int(power_data.Power_Filter_Flag.eq('Yes').sum())} flagged", className="metric-foot")], className="metric-card"),
        html.Div([html.Div("Speed readings", className="metric-label"), html.Div(f"{valid_speed:,}", className="metric-value"), html.Div(f"{int(speed_data.Speed_Filter.eq('Yes').sum())} flagged", className="metric-foot")], className="metric-card"),
        html.Div([html.Div("Negative deviations", className="metric-label"), html.Div(str(int((power_data.Power_Deviation.lt(0).sum()) + (speed_data.Speed_Deviation.lt(0).sum()))), className="metric-value"), html.Div("Power + Speed rows", className="metric-foot")], className="metric-card"),
    ]
    # Dataset quality counts are evaluated against the full stored dataset, not just the current view.
    power_all = data[data.KPI.eq("Power")]
    speed_all = data[data.KPI.eq("Speed")]
    duplicate_ids = int(data.Report_ID.duplicated(keep=False).sum())
    missing_power = int(power_all["Power_%"].isna().sum())
    negative_speed = int(speed_all["Speed_%"].lt(0).sum())
    quality = [
        html.Div([html.Span("●", className="quality-dot warning"), html.Div([html.Strong(str(missing_power)), html.Small(" missing Power % on Power rows")])], className="quality-item"),
        html.Div([html.Span("●", className="quality-dot warning"), html.Div([html.Strong(str(duplicate_ids)), html.Small(" rows with duplicate Report_ID")])], className="quality-item"),
        html.Div([html.Span("●", className="quality-dot danger"), html.Div([html.Strong(str(negative_speed)), html.Small(" negative Speed % reading(s)")])], className="quality-item"),
    ]
    return power_fig, speed_fig, cards, quality


@app.callback(
    Output("detail-table", "data"), Output("detail-table", "columns"), Output("selection-status", "children"),
    Input("vessel-filter", "value"), Input("date-filter", "start_date"), Input("date-filter", "end_date"),
    Input("kpi-filter", "value"), Input("voyage-filter", "value"),
    Input("power-chart", "selectedData"), Input("speed-chart", "selectedData"),
    Input("save-button", "n_clicks"),
)
def update_table(vessels, start_date, end_date, kpis, voyages, power_selected, speed_selected, _save_clicks):
    data = load_data()
    filtered = filter_data(data, vessels, start_date, end_date, kpis or [], voyages or [])
    selected_keys = keys_from_selection(power_selected) | keys_from_selection(speed_selected)
    if selected_keys:
        filtered = filtered[filtered.row_key.isin(selected_keys)]
        status = f"{len(filtered):,} selected report row(s) • selection from either chart is combined"
    else:
        status = f"{len(filtered):,} report row(s) • no chart selection, showing all rows in the current filter scope"
    shown = filtered.drop(columns=["_timestamp"], errors="ignore").copy()
    # Keep internal row identity in the table but hide it from the visible columns.
    for col in shown.columns:
        if col != "row_key":
            shown[col] = shown[col].map(display_value)
    columns = [
        {
            "name": c,
            "id": c,
            "editable": c in ("Power_%", "Speed_%"),
            # Numeric cell type provides immediate UI-side type validation;
            # the save callback independently enforces requiredness and range.
            **({"type": "numeric"} if c in ("Power_%", "Speed_%") else {}),
        }
        for c in shown.columns
    ]
    for col in columns:
        if col["id"] == "row_key":
            col["name"] = "Row key"
    return shown.to_dict("records"), columns, status


@app.callback(
    Output("save-message", "children"), Output("save-message", "className"),
    Input("save-button", "n_clicks"), State("detail-table", "data"), State("audit-user", "value"),
    prevent_initial_call=True,
)
def save_edits(n_clicks, edited_rows, username):
    if not n_clicks:
        raise PreventUpdate
    if not edited_rows:
        return "No rows are available to save.", "save-message error"
    user = (username or "").strip()
    if not user:
        return "Enter an audit user before saving.", "save-message error"
    user = user[:80]
    editable_fields = {"Power_%", "Speed_%"}
    changes = []
    errors = []
    try:
        with connect_db() as conn:
            for row in edited_rows:
                try:
                    row_key = int(row["row_key"])
                except (KeyError, TypeError, ValueError):
                    errors.append("A row is missing its internal key; reload the page and retry.")
                    continue
                original = conn.execute("SELECT * FROM vessel_reports WHERE row_key=?", (row_key,)).fetchone()
                if original is None:
                    errors.append(f"Row {row_key} no longer exists.")
                    continue
                kpi = original["KPI"]
                for field in editable_fields:
                    if field not in row:
                        continue
                    old = original[field]
                    raw = row[field]
                    if raw is None or (isinstance(raw, str) and not raw.strip()):
                        # Missing KPI-specific values are legitimate on the opposite KPI only.
                        if (field == "Power_%" and kpi == "Power") or (field == "Speed_%" and kpi == "Speed"):
                            errors.append(f"Report {original['Report_ID']}: {field} is required for a {kpi} row.")
                        continue
                    try:
                        new = float(raw)
                    except (TypeError, ValueError):
                        errors.append(f"Report {original['Report_ID']}: {field} must be numeric.")
                        continue
                    if not 0 <= new <= 200:
                        errors.append(f"Report {original['Report_ID']}: {field} must be between 0 and 200.")
                        continue
                    if field == "Power_%" and kpi != "Power":
                        errors.append(f"Report {original['Report_ID']}: Power_% cannot be edited on a {kpi} row.")
                        continue
                    if field == "Speed_%" and kpi != "Speed":
                        errors.append(f"Report {original['Report_ID']}: Speed_% cannot be edited on a {kpi} row.")
                        continue
                    old_num = None if old is None else float(old)
                    if old_num is None or abs(old_num - new) > 1e-9:
                        changes.append((row_key, original["Report_ID"], field, old, new))
            if errors:
                return "Save blocked: " + " ".join(errors[:4]) + (f" (+{len(errors)-4} more)" if len(errors) > 4 else ""), "save-message error"
            if not changes:
                return "No changes detected. Edit Power_% or Speed_% before saving.", "save-message neutral"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for row_key, report_id, field, old, new in changes:
                conn.execute(f'UPDATE vessel_reports SET "{field}"=? WHERE row_key=?', (new, row_key))
                conn.execute("INSERT INTO audit_log (Report_ID,row_key,field,old_value,new_value,user,changed_at) VALUES (?,?,?,?,?,?,?)",
                             (str(report_id), row_key, field, None if old is None else str(old), str(new), user, now))
        return f"Saved {len(changes)} change(s) to SQLite and wrote {len(changes)} audit record(s).", "save-message success"
    except sqlite3.Error as exc:
        return f"Database save failed: {exc}", "save-message error"


if __name__ == "__main__":
    app.run(debug=os.getenv("DASH_DEBUG", "false").lower() == "true", host="0.0.0.0", port=PORT)
