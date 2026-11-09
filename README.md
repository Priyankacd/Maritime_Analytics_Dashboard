# Zodiac Maritime — Vessel KPI Monitor

A Python Dash + Plotly application for investigating vessel Power % and Speed % readings, selecting chart points, correcting KPI values, and persisting changes with a SQLite audit trail. This project follows the supplied Zodiac Maritime take-home exercise.

## Requirements covered

- Composable Vessel, date-range, KPI (Power/Speed/both), and Voyage type (CARGO/BALLAST/both) filters.
- Two timestamp scatter charts: Power % and Speed %, colored by the supplied filter flags (blue `No`, amber `Yes`).
- Box-select, lasso-select and multi-point chart selection; selected report rows from either chart are combined. With no selection, the table shows all rows in the current filter scope.
- Detail table contains full report rows. Negative `Power_Deviation` and `Speed_Deviation` cells are highlighted red.
- Inline editing of `Power_%` and `Speed_%`. Percentage cells use numeric editing in the UI; backend validation independently checks numeric values, 0–200 inclusive, required active-KPI percentage, and KPI/field match before any write.
- Explicit **Save changes** action writes to SQLite and creates an `audit_log` row for every changed field, including `Report_ID`, internal `row_key`, field, old value, new value, user, and UTC timestamp.
- `app.yaml` uses Gunicorn and the Databricks Apps-provided `$PORT`.
- Data-quality watch reports missing `Power_%` on Power rows, duplicate `Report_ID` rows, and negative `Speed_%` readings. KPI-specific blanks on the opposite KPI row are expected and are not treated as data-quality defects.

## Local setup (Windows PowerShell)

Python 3.10 or newer is recommended. Run these commands from the folder containing `app.py` and `requirements.txt`:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:8050>. Keep the terminal open while using the app. Stop it with `Ctrl+C`.

If PowerShell blocks virtual-environment activation, use Command Prompt and run `.venv\Scripts\activate.bat` instead. If `python` is not recognized, install Python 3.10+ and reopen VS Code.

### Local setup (macOS/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

### If Dash cannot be found

Confirm the virtual environment is active, then run:

```bash
python -m pip show dash
python -m pip install -r requirements.txt
python -c "import dash; print(dash.__version__)"
```

Use `python -m pip` rather than bare `pip` to ensure installation targets the same Python interpreter used to launch the app.

## Databricks Apps deployment

`app.yaml` starts the Dash Flask server using Gunicorn and binds to the runtime-injected port:

```bash
gunicorn app:server --bind 0.0.0.0:$PORT
```

For deployment, ensure `app.py`, `requirements.txt`, `vessel_kpi_reports.csv`, `app.yaml`, and `assets/` are included in the app source. The local command is `python app.py`; the deployment command is Gunicorn, as appropriate for the hosted environment. The PDF asks for a deployment stub, not a completed deployment.

The demo stores data in `vessel_kpi.sqlite` beside the app. For production, do not assume local app storage is durable or shared across replicas; replace the SQLite write layer with a Delta Lake `MERGE`/UPSERT and a Delta audit table, or use a supported persistent storage service.

## How to use the app

1. Choose one or more vessels, a date range, one/both KPIs, and one/both voyage types. These filters drive both charts and the table.
2. Use Plotly's box-select or lasso-select toolbar tools, or select multiple points. The detail table shows the union of selected report rows from either chart.
3. Clear chart selections to return to all rows matching the active filters.
4. Edit the relevant KPI percentage in the table. Values must be numeric and between 0 and 200 inclusive; the Power percentage belongs only to Power rows and Speed percentage only to Speed rows. The active KPI percentage cannot be blanked.
5. Enter an audit user and click **Save changes**. If any proposed edit is invalid, the save is rejected. Successful changes and audit entries are committed to SQLite in a transaction.
6. Restart the app and verify saved changes remain. Inspect the audit table with the query below.

```sql
SELECT Report_ID, row_key, field, old_value, new_value, user, changed_at
FROM audit_log
ORDER BY audit_id DESC;
```

## Data assumptions and quality handling

- One row represents one KPI reading. Power-specific blanks on Speed rows and Speed-specific blanks on Power rows are valid structure.
- `row_key` is a generated internal surrogate key based on CSV row order. This avoids accidentally conflating duplicate `Report_ID` values.
- The supplied filter flags and deviation values are displayed as provided. Editing a percentage does not automatically recompute deviation or anomaly flags because the exercise does not specify the baseline calculation rules.
- A missing `Power_%` on a Power row is surfaced in the quality watch and can be repaired in the table. Negative Speed % is surfaced as a data-quality issue; the 0–200 validation prevents saving negative percentage values.
- SQLite is intended for this single-user take-home demo, not concurrent production writes.

## What I would improve in a second phase

- Replace local SQLite persistence with a Delta `MERGE` and durable audit table.
- Add authenticated identity rather than a manually entered audit user, plus permissions and a required change reason.
- Add automated unit/integration tests for filters, selection, invalid edits, duplicate IDs and persistence; add CI and a deployment smoke test.
- Confirm business rules for recalculating deviations and flags after approved corrections.
- Add server-side pagination and concurrency controls for larger datasets.

## Troubleshooting

- **`Could not find the dash version` / `No module named dash`:** activate `.venv`, then run `python -m pip install -r requirements.txt`.
- **Dataset not found:** make sure `vessel_kpi_reports.csv` is in the same folder as `app.py`, or set `KPI_CSV_PATH` to its full path.
- **Port in use:** set `PORT` to another port before starting, e.g. PowerShell `$env:PORT=8051; python app.py`, then open <http://127.0.0.1:8051>.
- **Reset demo data:** stop the app and delete `vessel_kpi.sqlite` and its `-wal`/`-shm` files if present. This also deletes the audit history; back it up first if needed.
