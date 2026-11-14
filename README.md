# Student Hiring dashboard (Tableau)

A one-page Tableau dashboard of student hiring cases. It's built from `data/student_hiring_cases.csv`: 1,000 cases opened Aug 2025 – Jun 2026, with state, created / closed / desired-start dates, division and department.

`build_dashboard.py` generates `Student Hiring.twbx`. The workbook includes a Hyper extract, so it opens in Tableau Desktop or Tableau Public without the CSV.

## What's on it

| Area | What it shows | How you use it |
|---|---|---|
| Month control (top right) | Picks the month every KPI, chart and the case list use | Drop-down. The default is the latest month. |
| 6 KPI cards | Cases opened, cases closed, avg days to close, resolution rate and % resolved by the desired start date, each vs the previous month (green = better, red = worse); open cases now, with how many are past their desired start | — |
| Metric buttons + trend | Monthly bars of the chosen metric (opened / closed / avg days to close), with the selected month in gold | Click a button |
| By division / by department | The chosen metric for the selected month | Click a division to filter the department chart |
| Case list + page buttons | Cases opened in the selected month, 10 per page, with state in colour | Click the page buttons |

The design reuses the patterns in `~/Tableau Dashboard/E-Commerce Admin Dashboard - reverse engineered.md`:
- month-vs-previous KPI cards with good/bad split fields
- buttons built from sheets, using parameter actions and a "Dummy" highlight
- INDEX() pagination with a 7-button navigator
- a click-to-filter action

It also fixes the issues that report flagged:
- **Month:** the parameter includes the year, so every month in the data can be selected.
- **First month:** has no previous month, so its change shows blank instead of dividing by zero.
- **"As of" date:** comes from the data rather than being typed in.

The dashboard has a fixed size of 1350 × 780, so it fits a laptop screen in Tableau without scrolling. To change it, edit `W, H` at the top of `build_dashboard.py`; the layout rescales to match.

## Publishing to Tableau Public

Open `Student Hiring.twbx` in Tableau Public and choose **File → Save to Tableau Public As…**. On the published page, turn off **Show sheets as tabs** so only the dashboard shows. Viewers can download a Tableau Public workbook together with its data, so check that `data/student_hiring_cases.csv` is cleared for public release before you publish.

## Rebuild

```sh
python3 -m venv .venv && .venv/bin/pip install tableauhyperapi   # one time
.venv/bin/python build_dashboard.py
```

When the CSV changes, rebuild. The month list, header period and "as of" date all come from the data.
