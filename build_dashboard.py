"""Generates "Student Hiring.twbx": a native Tableau dashboard over data/student_hiring_cases.csv.

Design follows the patterns documented in
"~/Tableau Dashboard/E-Commerce Admin Dashboard - reverse engineered.md":
  * KPI cards: selected month vs previous month, change split into green (good) / red (bad) fields
  * Metric buttons: sheets on MIN(0) axes + parameter actions + a "Dummy" highlight action
  * Selected-month highlight on the trend
  * Paginated case list: INDEX() / Page Size / Current Page / Page Filter + a 7-button navigator
  * Click-to-filter: Division bars filter the Department bars
and fixes the issues that report found (year-aware month, January/first-month guard, no hard-coded dates).

XML conventions that Tableau needs (learned on the CSAT dashboard):
  * colour-mapped fields are also declared as column-instances at data-source level
  * the primary data source is listed before Parameters in each worksheet
  * every sheet is fitted with <zoom type='entire-view' />
  * Table (down) = ordering-type 'Columns', Table (across) = 'Rows'

Run: python3 build_dashboard.py   (needs tableauhyperapi; see README.md)
"""
import csv
import os
import re
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape, quoteattr as a

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "data", "student_hiring_cases.csv")
OUT = os.path.join(HERE, "Student Hiring.twbx")
TWB = "Student Hiring.twb"
HYPER_IN_PACKAGE = "Data/Extracts/student_hiring_cases.hyper"
HYPER_TMP = os.path.join(HERE, ".build", "student_hiring_cases.hyper")
DS, DS_CAPTION = "federated.0studenthire00001", "Student Hiring Cases"
DASH = "Student Hiring"
W, H = 1350, 780   # dashboard size in px; fits a laptop screen under Tableau's toolbars

# Georgia Tech palette (same as the CSAT dashboard)
NAVY, GOLD, MUTED = "#051e39", "#b39051", "#5c6b7a"
PAGE, WHITE, LIGHT = "#f9f6e5", "#ffffff", "#d9dce1"
GOOD, BAD = "#2e7d32", "#b3261e"
FONT, FONT_SEMI, FONT_BOLD = "Tableau Book", "Tableau Semibold", "Tableau Bold"

# ------------------------------------------------------------------ data facts used at build time
with open(CSV, newline="", encoding="utf-8-sig") as f:
    _rows = list(csv.DictReader(f))
_created = [date.fromisoformat(r["Create Date"]) for r in _rows]
FIRST = date(min(_created).year, min(_created).month, 1)
LAST = date(max(_created).year, max(_created).month, 1)
MONTHS = []
_d = FIRST
while _d <= LAST:
    MONTHS.append(_d)
    _d = date(_d.year + (_d.month == 12), _d.month % 12 + 1, 1)
STATES = sorted({r["State"] for r in _rows})

RAW = [  # name, datatype, remote-type, role, type
    ("Case Number", "string", 129, "dimension", "nominal"),
    ("State", "string", 129, "dimension", "nominal"),
    ("Create Date", "date", 133, "dimension", "ordinal"),
    ("Closed Date", "date", 133, "dimension", "ordinal"),
    ("Desired Start Date", "date", 133, "dimension", "ordinal"),
    ("Division", "string", 129, "dimension", "nominal"),
    ("Department", "string", 129, "dimension", "nominal"),
]

# ------------------------------------------------------------------ parameters
PARAMS = {
    # [id]: (caption, datatype, current, members{value: alias} or None, range or None)
    "Parameter 1": ("Month", "integer", str(len(MONTHS)),
                    {str(i + 1): m.strftime("%b %Y") for i, m in enumerate(MONTHS)}, None),
    "Parameter 2": ("Metric", "integer", "1", {"1": "Cases opened", "2": "Cases closed", "3": "Avg days to close"}, None),
    "Parameter 3": ("Current Page", "integer", "1", None, ("1", "100", "1")),
    "Parameter 4": ("Page Size", "integer", "10", None, ("5", "50", "5")),
}
P = {cap: f"[Parameters].[{pid}]" for pid, (cap, *_r) in PARAMS.items()}


def param_col(pid):
    cap, dt, cur, members, rng = PARAMS[pid]
    if members:
        mem = "".join(f"<member alias={a(al)} value={a(v)} />" for v, al in members.items())
        ali = "".join(f"<alias key={a(k)} value={a(v)} />" for k, v in members.items())
        body = f"<calculation class='tableau' formula={a(cur)} /><aliases>{ali}</aliases><members>{mem}</members>"
        dom = "list"
    else:
        body = (f"<calculation class='tableau' formula={a(cur)} />"
                f"<range granularity={a(rng[2])} max={a(rng[1])} min={a(rng[0])} />")
        dom = "range"
    alias = f" alias={a(members[cur])}" if members else ""
    return (f"<column{alias} caption={a(cap)} datatype={a(dt)} name={a('[' + pid + ']')} param-domain-type={a(dom)} "
            f"role='measure' type='quantitative' value={a(cur)}>{body}</column>")


# ------------------------------------------------------------------ calculations
CM = "[Calc_CreatedMonth]"
XM = "[Calc_ClosedMonth]"
SEL = "[Calc_SelMonth]"
PREV = "[Calc_PrevMonth]"


def cnt(cond):
    return f"COUNTD(IF {cond} THEN [Case Number] END)"


CALCS = {  # id: (caption, datatype, role, default-format, formula)
    # --- row level
    "Calc_SelMonth": ("Selected Month", "date", "dimension", "",
                      f"DATE(DATEADD('month', {P['Month']} - 1, #{FIRST.isoformat()}#))"),
    "Calc_PrevMonth": ("Previous Month", "date", "dimension", "", f"DATE(DATEADD('month', -1, {SEL}))"),
    "Calc_CreatedMonth": ("Created Month", "date", "dimension", "", "DATE(DATETRUNC('month', [Create Date]))"),
    "Calc_ClosedMonth": ("Closed Month", "date", "dimension", "", "DATE(DATETRUNC('month', [Closed Date]))"),
    "Calc_DaysToClose": ("Days to Close", "integer", "measure", "n#,##0",
                         "DATEDIFF('day', [Create Date], [Closed Date])"),
    "Calc_OnTime": ("Resolved by Desired Start", "boolean", "dimension", "",
                    "[State] = 'Closed Resolved' AND [Closed Date] <= [Desired Start Date]"),
    "Calc_AsOf": ("Data As Of", "date", "dimension", "", "{MAX(IFNULL([Closed Date], [Create Date]))}"),
    "Calc_CreatedInSel": ("Created in Selected Month", "boolean", "dimension", "", f"{CM} = {SEL}"),
    # --- KPI: selected month and previous month
    "Calc_Opened": ("Cases Opened", "integer", "measure", "n#,##0", cnt(f"{CM} = {SEL}")),
    "Calc_OpenedPM": ("Cases Opened PM", "integer", "measure", "n#,##0", cnt(f"{CM} = {PREV}")),
    "Calc_Closed": ("Cases Closed", "integer", "measure", "n#,##0", cnt(f"{XM} = {SEL}")),
    "Calc_ClosedPM": ("Cases Closed PM", "integer", "measure", "n#,##0", cnt(f"{XM} = {PREV}")),
    "Calc_AvgDays": ("Avg Days to Close", "real", "measure", "n#,##0.0",
                     f"AVG(IF {XM} = {SEL} THEN [Calc_DaysToClose] END)"),
    "Calc_AvgDaysPM": ("Avg Days to Close PM", "real", "measure", "n#,##0.0",
                       f"AVG(IF {XM} = {PREV} THEN [Calc_DaysToClose] END)"),
    "Calc_ResRate": ("Resolution Rate", "real", "measure", "p0.0%",
                     f"{cnt(f'{XM} = {SEL} AND [State] = ' + chr(39) + 'Closed Resolved' + chr(39))} / [Calc_Closed]"),
    "Calc_ResRatePM": ("Resolution Rate PM", "real", "measure", "p0.0%",
                       f"{cnt(f'{XM} = {PREV} AND [State] = ' + chr(39) + 'Closed Resolved' + chr(39))} / [Calc_ClosedPM]"),
    "Calc_OnTimeRate": ("On-time Rate", "real", "measure", "p0.0%",
                        f"{cnt(f'{XM} = {SEL} AND [Calc_OnTime]')} / "
                        f"{cnt(f'{XM} = {SEL} AND [State] = ' + chr(39) + 'Closed Resolved' + chr(39))}"),
    "Calc_OnTimeRatePM": ("On-time Rate PM", "real", "measure", "p0.0%",
                          f"{cnt(f'{XM} = {PREV} AND [Calc_OnTime]')} / "
                          f"{cnt(f'{XM} = {PREV} AND [State] = ' + chr(39) + 'Closed Resolved' + chr(39))}"),
    "Calc_OpenNow": ("Open Cases", "integer", "measure", "n#,##0", cnt("[State] = 'Work in Progress'")),
    "Calc_PastStart": ("Open Past Desired Start", "integer", "measure", "n#,##0",
                       cnt("[State] = 'Work in Progress' AND [Desired Start Date] < [Calc_AsOf]")),
    # --- changes vs previous month (guarded: the first month has no previous month)
    "Calc_OpenedChg": ("Cases Opened Change %", "real", "measure", "p0.0%",
                       "IF [Calc_OpenedPM] > 0 THEN ([Calc_Opened] - [Calc_OpenedPM]) / [Calc_OpenedPM] END"),
    "Calc_ClosedChg": ("Cases Closed Change %", "real", "measure", "p0.0%",
                       "IF [Calc_ClosedPM] > 0 THEN ([Calc_Closed] - [Calc_ClosedPM]) / [Calc_ClosedPM] END"),
    "Calc_AvgDaysChg": ("Avg Days Change", "real", "measure", "n#,##0.0", "[Calc_AvgDays] - [Calc_AvgDaysPM]"),
    "Calc_ResRateChg": ("Resolution Rate Change (pts)", "real", "measure", "n#,##0.0",
                        "([Calc_ResRate] - [Calc_ResRatePM]) * 100"),
    "Calc_OnTimeChg": ("On-time Rate Change (pts)", "real", "measure", "n#,##0.0",
                       "([Calc_OnTimeRate] - [Calc_OnTimeRatePM]) * 100"),
    # --- metric switch (buttons)
    "Calc_TrendMonth": ("Trend Month", "date", "dimension", "", f"IF {P['Metric']} = 1 THEN {CM} ELSE {XM} END"),
    "Calc_HasTrendMonth": ("Has Trend Month", "boolean", "dimension", "", "NOT ISNULL([Calc_TrendMonth])"),
    "Calc_IsSelTrend": ("Is Selected Month", "boolean", "dimension", "", f"[Calc_TrendMonth] = {SEL}"),
    "Calc_MetricValue": ("Metric Value", "real", "measure", "n#,##0.#",
                         f"CASE {P['Metric']} WHEN 1 THEN COUNTD([Case Number]) "
                         "WHEN 2 THEN COUNTD(IF NOT ISNULL([Closed Date]) THEN [Case Number] END) "
                         "ELSE AVG([Calc_DaysToClose]) END"),
    "Calc_Zero1": ("Btn Axis 1", "real", "measure", "", "MIN(0)"),
    "Calc_Zero2": ("Btn Axis 2", "real", "measure", "", "MIN(0)"),
    "Calc_Zero3": ("Btn Axis 3", "real", "measure", "", "MIN(0)"),
    "Calc_Btn1": ("Btn Opened", "string", "dimension", "", "'Cases opened'"),
    "Calc_Btn2": ("Btn Closed", "string", "dimension", "", "'Cases closed'"),
    "Calc_Btn3": ("Btn Days", "string", "dimension", "", "'Avg days to close'"),
    "Calc_BtnVal1": ("Btn Value 1", "integer", "measure", "", "1"),
    "Calc_BtnVal2": ("Btn Value 2", "integer", "measure", "", "2"),
    "Calc_BtnVal3": ("Btn Value 3", "integer", "measure", "", "3"),
    "Calc_BtnOn1": ("Btn Active 1", "boolean", "dimension", "", f"{P['Metric']} = 1"),
    "Calc_BtnOn2": ("Btn Active 2", "boolean", "dimension", "", f"{P['Metric']} = 2"),
    "Calc_BtnOn3": ("Btn Active 3", "boolean", "dimension", "", f"{P['Metric']} = 3"),
    "Calc_Dummy": ("Dummy", "string", "dimension", "", "'Dummy'"),
    # --- pagination (report section 3, "Pagination")
    "Calc_Index": ("Row Index", "integer", "measure", "", "INDEX()"),
    "Calc_PageNumber": ("Page Number", "integer", "measure", "", f"INT(([Calc_Index] - 1) / {P['Page Size']}) + 1"),
    "Calc_PageFilter": ("Page Filter", "boolean", "measure", "", f"{P['Current Page']} = [Calc_PageNumber]"),
    "Calc_ListZero": ("Zero Axis", "real", "measure", "", "MIN(0)"),
    "Calc_StateHeader": ("State Header", "string", "dimension", "", "'State'"),
    "Calc_LastPage": ("Last Page", "integer", "measure", "",
                      f"CEILING({{COUNTD(IF {CM} = {SEL} THEN [Case Number] END)}} / {P['Page Size']})"),
    # 7 navigator marks: borrow MONTH(Desired Start Date) 1-7 as slots (report: "Label")
    "Calc_NavSlot": ("Nav Slot", "integer", "dimension", "", "MONTH([Desired Start Date])"),
    "Calc_IsNavSlot": ("Is Nav Slot", "boolean", "dimension", "", "[Calc_NavSlot] <= 7"),
    "Calc_NavLabel": ("Nav Label", "string", "dimension", "",
                      "CASE [Calc_NavSlot] WHEN 1 THEN '|◄' WHEN 2 THEN '◄' "
                      f"WHEN 3 THEN STR(IF {P['Current Page']} <= 2 OR [Calc_LastPage] <= 3 THEN 1 "
                      f"ELSEIF {P['Current Page']} >= [Calc_LastPage] - 1 THEN [Calc_LastPage] - 2 "
                      f"ELSE {P['Current Page']} - 1 END) "
                      f"WHEN 4 THEN STR(IF {P['Current Page']} <= 2 OR [Calc_LastPage] <= 3 THEN 2 "
                      f"ELSEIF {P['Current Page']} >= [Calc_LastPage] - 1 THEN [Calc_LastPage] - 1 "
                      f"ELSE {P['Current Page']} END) "
                      f"WHEN 5 THEN STR(IF [Calc_LastPage] <= 3 THEN [Calc_LastPage] "
                      f"ELSEIF {P['Current Page']} <= 2 THEN 3 "
                      f"ELSEIF {P['Current Page']} >= [Calc_LastPage] - 1 THEN [Calc_LastPage] "
                      f"ELSE {P['Current Page']} + 1 END) "
                      "WHEN 6 THEN '►' ELSE '►|' END"),
    "Calc_NavValue": ("Nav Value", "integer", "measure", "",
                      "CASE [Calc_NavLabel] WHEN '|◄' THEN 1 "
                      f"WHEN '◄' THEN IIF({P['Current Page']} = 1, 1, {P['Current Page']} - 1) "
                      f"WHEN '►' THEN IIF({P['Current Page']} >= [Calc_LastPage], [Calc_LastPage], {P['Current Page']} + 1) "
                      "WHEN '►|' THEN [Calc_LastPage] ELSE INT([Calc_NavLabel]) END"),
    "Calc_NavActive": ("Nav Active", "boolean", "dimension", "",
                       f"IFNULL({P['Current Page']} = INT([Calc_NavLabel]), FALSE)"),
}
TABLE_CALCS = {"Calc_Index", "Calc_PageNumber", "Calc_PageFilter"}

# change -> (good-direction-is-up?) ; each gets _Good / _Bad split fields (green / red label runs)
SPLITS = {"Calc_OpenedChg": True, "Calc_ClosedChg": True, "Calc_AvgDaysChg": False,
          "Calc_ResRateChg": True, "Calc_OnTimeChg": True}
for _k, _up in SPLITS.items():
    _cap, _dt, _role, _fmt, _ = CALCS[_k]
    _g, _b = (">= 0", "< 0") if _up else ("<= 0", "> 0")
    CALCS[_k + "_Good"] = (_cap + " (good)", "real", "measure", _fmt, f"IF [{_k}] {_g} THEN [{_k}] END")
    CALCS[_k + "_Bad"] = (_cap + " (bad)", "real", "measure", _fmt, f"IF [{_k}] {_b} THEN [{_k}] END")

# colour palettes (data-source level). field instance -> {bucket: colour}
BOOL_PAL = {"Calc_IsSelTrend": (GOLD, LIGHT), "Calc_BtnOn1": (GOLD, MUTED), "Calc_BtnOn2": (GOLD, MUTED),
            "Calc_BtnOn3": (GOLD, MUTED), "Calc_NavActive": (GOLD, MUTED)}
STATE_PAL = {"Closed Resolved": GOOD, "Work in Progress": GOLD, "Closed Not Resolved": BAD}


def deps_of(keys):
    out, todo = [], list(keys)
    while todo:
        k = todo.pop()
        if k in out or k not in CALCS:
            continue
        out.append(k)
        todo += re.findall(r"\[(Calc_\w+)\]", CALCS[k][4])
    return out


def raw_in(keys):
    names = [n for n, *_ in RAW]
    return sorted({n for k in keys for n in names if f"[{n}]" in CALCS[k][4]}, key=names.index)


def raw_col(name):
    _, dt, _, role, typ = next(r for r in RAW if r[0] == name)
    return f"<column datatype={a(dt)} name={a('[' + name + ']')} role={a(role)} type={a(typ)} />"


def calc_col(k):
    cap, dt, role, fmt, formula = CALCS[k]
    typ = {"string": "nominal", "boolean": "nominal", "date": "ordinal"}.get(dt, "quantitative")
    if role == "dimension" and dt in ("integer", "real"):
        typ = "ordinal"
    fmt_attr = f" default-format={a(fmt)}" if fmt else ""
    calc = (f"<calculation class='tableau' formula={a(formula)}><table-calc ordering-type='Columns' /></calculation>"
            if k in TABLE_CALCS else f"<calculation class='tableau' formula={a(formula)} />")
    return (f"<column caption={a(cap)} datatype={a(dt)}{fmt_attr} name={a('[' + k + ']')} role={a(role)} "
            f"type={a(typ)}>{calc}</column>")


def q(inst_name):
    return f"[{DS}].{inst_name}"


def inst(kind, field, extra=""):
    """kind: usr (agg measure, quantitative) | usrn (agg string/boolean) | nk (dimension nominal) |
    ok (dimension ordinal) | qk (row-level measure, disaggregated) | mdy (exact date discrete) | tmn (month discrete)"""
    col = a("[" + field + "]")
    spec = {"usr": ("User", "usr", "qk", "quantitative"), "usrn": ("User", "usr", "nk", "nominal"),
            "nk": ("None", "none", "nk", "nominal"), "ok": ("None", "none", "ok", "ordinal"),
            "qk": ("None", "none", "qk", "quantitative"), "mdy": ("MDY", "mdy", "ok", "ordinal"),
            "tmn": ("Month-Trunc", "tmn", "ok", "ordinal")}[kind]
    deriv, pre, suf, typ = spec
    name = f"[{pre}:{field}:{suf}]"
    body = f"<column-instance column={col} derivation={a(deriv)} name={a(name)} pivot='key' type={a(typ)}"
    return name, (body + f">{extra}</column-instance>" if extra else body + " />")


def palette_xml():
    enc = []
    for f, (on, off) in BOOL_PAL.items():
        enc.append(f"<encoding attr='color' field={a('[none:' + f + ':nk]')} type='palette'>"
                   f"<map to={a(on)}><bucket>true</bucket></map><map to={a(off)}><bucket>false</bucket></map></encoding>")
    maps = "".join(f"<map to={a(c)}><bucket>&quot;{escape(s)}&quot;</bucket></map>" for s, c in STATE_PAL.items())
    enc.append(f"<encoding attr='color' field='[none:State:nk]' type='palette'>{maps}</encoding>")
    insts = [inst("nk", f)[1] for f in BOOL_PAL] + [inst("nk", "State")[1]]
    return "\n".join(insts), "\n".join(enc)


# ------------------------------------------------------------------ extract
def build_hyper():
    from tableauhyperapi import (HyperProcess, Telemetry, Connection, CreateMode, TableDefinition,
                                 TableName, SqlType, escape_string_literal)
    types = {"string": SqlType.text(), "date": SqlType.date()}
    os.makedirs(os.path.dirname(HYPER_TMP), exist_ok=True)
    table = TableDefinition(TableName("Extract", "Extract"),
                            [TableDefinition.Column(n, types[dt]) for n, dt, *_ in RAW])
    with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
        with Connection(hyper.endpoint, HYPER_TMP, CreateMode.CREATE_AND_REPLACE) as con:
            con.catalog.create_schema("Extract")
            con.catalog.create_table(table)
            n = con.execute_command(f"COPY {table.table_name} FROM {escape_string_literal(CSV)} "
                                    "WITH (format csv, header, null '')")
    print(f"extract: {n} rows")


def metadata(parent):
    return "\n".join(f"""<metadata-record class='column'>
  <remote-name>{escape(n)}</remote-name><remote-type>{rt}</remote-type><local-name>[{escape(n)}]</local-name>
  <parent-name>{parent}</parent-name><remote-alias>{escape(n)}</remote-alias><ordinal>{i}</ordinal>
  <local-type>{dt}</local-type><aggregation>{'Count' if dt == 'string' else 'Year'}</aggregation>
  <contains-null>true</contains-null>
</metadata-record>""" for i, (n, dt, rt, *_r) in enumerate(RAW))


def datasource():
    cols = "\n".join(f"<column datatype={a(dt)} name={a(n)} ordinal='{i}' />" for i, (n, dt, *_r) in enumerate(RAW))
    stamp = datetime.now().strftime("%m/%d/%Y %I:%M:%S %p")
    pinst, penc = palette_xml()
    return f"""<datasource hasconnection='false' inline='true' name='Parameters' version='18.1'>
  <aliases enabled='yes' />
  {"".join(param_col(p) for p in PARAMS)}
</datasource>
<datasource caption={a(DS_CAPTION)} inline='true' name={a(DS)} version='18.1'>
  <connection class='federated'>
    <named-connections>
      <named-connection caption='student_hiring_cases' name='textscan.hireleaf'>
        <connection class='textscan' directory={a(os.path.dirname(CSV))} filename='student_hiring_cases.csv' password='' server='' />
      </named-connection>
    </named-connections>
    <relation connection='textscan.hireleaf' name='student_hiring_cases.csv' table='[student_hiring_cases#csv]' type='table'>
      <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>
{cols}
      </columns>
    </relation>
    <metadata-records>
{metadata('[student_hiring_cases#csv]')}
    </metadata-records>
  </connection>
  <aliases enabled='yes' />
{chr(10).join(calc_col(k) for k in CALCS)}
{chr(10).join(raw_col(n) for n, *_r in RAW)}
{pinst}
  <extract count='-1' enabled='true' units='records'>
    <connection access_mode='readonly' authentication='auth-none' author-locale='en_US' class='hyper' dbname={a(HYPER_IN_PACKAGE)} default-settings='yes' schema='Extract' sslmode='' tablename='Extract' update-time={a(stamp)} username='tableau_internal_user'>
      <relation name='Extract' table='[Extract].[Extract]' type='table' />
      <metadata-records>
{metadata('[Extract]')}
      </metadata-records>
    </connection>
  </extract>
  <layout dim-ordering='alphabetic' dim-percentage='0.5' measure-ordering='alphabetic' measure-percentage='0.4' show-structure='true' />
  <style><style-rule element='mark'>
{penc}
  </style-rule></style>
</datasource>"""


# ------------------------------------------------------------------ worksheets
def run(text, color=None, size=11, font=FONT, bold=False):
    attrs = (f" fontcolor={a(color)}" if color else "") + f" fontname={a(font)} fontsize='{size}'"
    return f"<run{' bold=' + chr(39) + 'true' + chr(39) if bold else ''}{attrs}>{text}</run>"


def ref(inst_name):
    return f"&lt;{escape(q(inst_name))}&gt;"


def pane(mark, encodings="", label_runs=None, mark_style="", pid=None, axis=None, axis_kind="x", center=False):
    attrs = "" if pid is None else f" id='{pid}' {axis_kind}-axis-name={a(q(axis))}"
    lab = f"<customized-label><formatted-text>{''.join(label_runs)}</formatted-text></customized-label>" if label_runs else ""
    show = "<format attr='mark-labels-show' value='true' />" if label_runs else ""
    return (f"<pane selection-relaxation-option='selection-relaxation-allow'{attrs}><view><breakdown value='auto' /></view>"
            f"<mark class={a(mark)} />{f'<encodings>{encodings}</encodings>' if encodings else ''}{lab}"
            f"<style>{CENTER if center else ''}<style-rule element='mark'>{mark_style}{show}</style-rule></style></pane>")


CENTER = ("<style-rule element='cell'><format attr='text-align' value='center' />"
          "<format attr='vertical-align' value='center' /></style-rule>")


def sheet(name, calcs, instances, panes, rows="", cols="", title=None, style="", view_extra="",
          raw=(), formats=None, field_labels=False, tooltip=True):
    calcs = deps_of(calcs)
    raw = sorted(set(raw) | set(raw_in(calcs)), key=[n for n, *_r in RAW].index)
    uses_param = any("[Parameters]" in CALCS[k][4] for k in calcs) or "Parameters" in (title or "")
    pdeps = ("<datasource-dependencies datasource='Parameters'>" + "".join(param_col(p) for p in PARAMS)
             + "</datasource-dependencies>") if uses_param else ""
    deps = "\n".join([raw_col(n) for n in raw] + [calc_col(k) for k in calcs] + [x for _, x in instances])
    fmt = "".join(f"<format attr='text-format' field={a(q(f))} value={a(v)} />" for f, v in (formats or {}).items())
    title_xml = (f"<layout-options><title><formatted-text>{title}</formatted-text></title></layout-options>"
                 if title else "")
    return f"""<worksheet name={a(name)}>
{title_xml}
<table>
  <view>
    <datasources>
      <datasource caption={a(DS_CAPTION)} name={a(DS)} />
      {"<datasource name='Parameters' />" if uses_param else ""}
    </datasources>
    {pdeps}
    <datasource-dependencies datasource={a(DS)}>
{deps}
    </datasource-dependencies>
    {view_extra}
    <aggregation value='true' />
  </view>
  <style>
    {style}
    <style-rule element='cell'>{fmt}<format attr='font-family' value={a(FONT)} /><format attr='color' value={a(NAVY)} /></style-rule>
    <style-rule element='label'>{fmt}<format attr='font-family' value={a(FONT)} /><format attr='color' value={a(MUTED)} /><format attr='font-size' value='9' /></style-rule>
    <style-rule element='header'><format attr='font-family' value={a(FONT)} /><format attr='font-size' value='9' /><format attr='color' value={a(NAVY)} /></style-rule>
    <style-rule element='worksheet'><format attr='display-field-labels' scope='cols' value='false' />
      <format attr='display-field-labels' scope='rows' value={a('true' if field_labels else 'false')} /></style-rule>
    <style-rule element='field-labels'><format attr='font-family' value={a(FONT_SEMI)} /><format attr='color' value={a(MUTED)} /><format attr='font-size' value='9' /></style-rule>
    <style-rule element='table'><format attr='background-color' value='#00000000' /><format attr='show-null-value-warning' value='false' /></style-rule>
    <style-rule element='table-div'><format attr='stroke-size' scope='rows' value='0' /><format attr='line-visibility' scope='rows' value='off' />
      <format attr='stroke-size' scope='cols' value='0' /><format attr='line-visibility' scope='cols' value='off' /></style-rule>
    <style-rule element='tooltip'><format attr='font-size' value='11' /><format attr='color' value={a(NAVY)} /></style-rule>
  </style>
  <panes>
{chr(10).join(panes)}
  </panes>
  <rows>{escape(rows)}</rows>
  <cols>{escape(cols)}</cols>
  {"" if tooltip else "<tooltip-style tooltip-mode='none' />"}
</table>
</worksheet>"""


def hide_axis(*fields, scope="cols"):
    return ("<style-rule element='axis'>" + "".join(
        f"<format attr='display' class='0' field={a(q(f))} scope={a(scope)} value='false' />" for f in fields)
        + "</style-rule>")


def no_grid():
    return "".join(f"<style-rule element={a(e)}><format attr='line-visibility' value='off' /><format attr='stroke-size' value='0' /></style-rule>"
                   for e in ("gridline", "zeroline"))


def bool_filter(inst_name, level, member="true"):
    f = q(inst_name)
    return (f"<filter class='categorical' column={a(f)}><groupfilter function='member' level={a(level)} member={a(member)} "
            "user:ui-domain='relevant' user:ui-enumeration='inclusive' user:ui-marker='enumerate' /></filter>")


def slices(*inst_names):
    return "<slices>" + "".join(f"<column>{escape(q(n))}</column>" for n in inst_names) + "</slices>"


KPI_VALUE_PT, KPI_CHANGE_PT, KPI_TITLE_PT = 18, 10, 10   # sized to fit the 102 px card row


def kpi(name, caption, value, value_fmt, change=None, change_fmt=None, suffix="", sub=None, sub_fmt=None):
    """KPI card (report section 3): value, then the change split into green 'good' / red 'bad' runs."""
    insts, fmts, calcs = [], {}, []

    def add(field, fmt, kind="usr"):
        n, x = inst(kind, field)
        insts.append((n, x)); calcs.append(field)
        if fmt:
            fmts[n] = fmt
        return n
    v = add(value, value_fmt)
    runs = [run(ref(v) + ("&#10;" if change or sub else ""), NAVY, KPI_VALUE_PT, FONT_BOLD)]
    if change:
        g, b = add(change + "_Good", change_fmt), add(change + "_Bad", change_fmt)
        runs += [run(ref(g), GOOD, KPI_CHANGE_PT, FONT_SEMI), run(ref(b), BAD, KPI_CHANGE_PT, FONT_SEMI),
                 run(escape(suffix), MUTED, KPI_CHANGE_PT - 1)]
    if sub:
        s = add(sub, sub_fmt)
        runs += [run(ref(s), BAD, KPI_CHANGE_PT, FONT_SEMI)]
    enc = "".join(f"<text column={a(q(n))} />" for n, _ in insts)
    # Put the text on a hidden MIN(0) axis (VOTD 'Sales KPI 1' style). A plain text-table cell shows ####
    # when the number is wider than the cell under Entire View; a label on an axis mark is not truncated.
    z, zx = inst("usr", "Calc_ListZero")
    insts.append((z, zx)); calcs.append("Calc_ListZero")
    return sheet(name, calcs, insts, [pane("Text", enc, runs)], rows=q(z),
                 style=hide_axis(z, scope="rows") + no_grid(),
                 title=run(escape(caption), MUTED, KPI_TITLE_PT, FONT_SEMI), formats=fmts, tooltip=False)


def metric_buttons():
    """Report technique 2: three MIN(0) axes, one Text mark each; parameter actions set Metric."""
    insts, panes, cols = [], [pane("Text")], []
    for i in (1, 2, 3):
        z, zx = inst("usr", f"Calc_Zero{i}")
        t, tx = inst("nk", f"Calc_Btn{i}")
        c, cx = inst("nk", f"Calc_BtnOn{i}")
        v, vx = inst("qk", f"Calc_BtnVal{i}")
        d, dx = inst("nk", "Calc_Dummy")
        insts += [(z, zx), (t, tx), (c, cx), (v, vx)] + ([(d, dx)] if i == 1 else [])
        cols.append(q(z))
        panes.append(pane("Text", f"<color column={a(q(c))} /><text column={a(q(t))} /><lod column={a(q(v))} />"
                                  f"<lod column={a(q(d))} />",
                          [run(ref(t), None, 11, FONT_BOLD)], pid=i, axis=z))
    style = hide_axis(*[n for n, _ in insts if n.startswith("[usr:Calc_Zero")]) + no_grid()
    return sheet("Metric Buttons", [f"Calc_{p}{i}" for i in (1, 2, 3) for p in ("Zero", "Btn", "BtnOn", "BtnVal")]
                 + ["Calc_Dummy"], insts, panes, cols="(" + " + ".join(cols) + ")", style=style, tooltip=False)


def trend():
    m, mx = inst("tmn", "Calc_TrendMonth")
    v, vx = inst("usr", "Calc_MetricValue")
    h, hx = inst("nk", "Calc_IsSelTrend")
    f, fx = inst("nk", "Calc_HasTrendMonth")
    style = ("<style-rule element='axis'>"
             f"<format attr='title' class='0' field={a(q(v))} scope='rows' value='' /></style-rule>"
             f"<style-rule element='label'><format attr='text-format' field={a(q(m))} value='*MMM yy' /></style-rule>"
             "<style-rule element='gridline'><format attr='line-pattern-only' scope='rows' value='dotted' /></style-rule>")
    title = run("Monthly trend · ", NAVY, 12, FONT_SEMI) + run("&lt;[Parameters].[Parameter 2]&gt;", NAVY, 12, FONT_SEMI) \
        + run(" · gold = selected month", MUTED, 10)
    return sheet("Trend", ["Calc_TrendMonth", "Calc_MetricValue", "Calc_IsSelTrend", "Calc_HasTrendMonth"],
                 [(m, mx), (v, vx), (h, hx), (f, fx)],
                 [pane("Bar", f"<color column={a(q(h))} /><text column={a(q(v))} />",
                       [run(ref(v), MUTED, 9)], "<format attr='size' value='0.6' />")],
                 rows=q(v), cols=q(m), title=title, style=style,
                 view_extra=bool_filter(f, "[none:Calc_HasTrendMonth:nk]") + slices(f))


def bars_by(dim, name, title_text):
    d, dx = inst("nk", dim)
    v, vx = inst("usr", "Calc_MetricValue")
    s, sx = inst("nk", "Calc_IsSelTrend")
    title = run(title_text + " · ", NAVY, 12, FONT_SEMI) + run("&lt;[Parameters].[Parameter 2]&gt;", NAVY, 12, FONT_SEMI) \
        + run(", &lt;[Parameters].[Parameter 1]&gt;", MUTED, 10)
    return sheet(name, ["Calc_MetricValue", "Calc_IsSelTrend"], [(d, dx), (v, vx), (s, sx)],
                 [pane("Bar", f"<text column={a(q(v))} />", [run(ref(v), NAVY, 9)],
                       f"<format attr='mark-color' value={a(NAVY)} /><format attr='size' value='0.7' />")],
                 rows=q(d), cols=q(v), raw=[dim], title=title,
                 style=hide_axis(v) + no_grid(),
                 view_extra=bool_filter(s, "[none:Calc_IsSelTrend:nk]")
                 + f"<sort class='computed' column={a(q(d))} direction='DESC' using={a(q(v))} />" + slices(s))


LIST_ROWS = [("nk", "Case Number", "Case"), ("ok", "Create Date", "Created"),
             ("nk", "Department", "Department"), ("ok", "Desired Start Date", "Desired start"),
             ("ok", "Closed Date", "Closed")]
DATE_FMT = "*MM/dd/yyyy"
LIST_WIDTHS = {"Case Number": 120, "Create Date": 105, "Department": 250, "Desired Start Date": 135,
               "Closed Date": 105}   # px; the State column fills what's left (~85-100 px + padding)   # Tableau date formats use ICU codes: MM = month, mm = minutes


def case_list():
    """Report technique 4: INDEX / Page Number / Page Filter, filtered to the selected month."""
    insts = [inst(k, f) for k, f, _ in LIST_ROWS]
    z, zx = inst("nk", "Calc_StateHeader")
    s, sx = inst("nk", "State")   # on Color + Text, so INDEX has to address it too (see orders)
    c, cx = inst("nk", "Calc_CreatedInSel")
    # INDEX() must run along ALL row fields (E-Commerce 'Product_Listing'); with the default it restarted
    # at each created date, so nearly every case was "row 1-10" and the page filter kept them all.
    orders = "".join(f"<order field={a(q(n))} />" for n in [n for n, _ in insts] + [z, s])
    pf_extra = ("<table-calc ordering-type='Columns' />"
                f"<table-calc field={a(q('[Calc_PageNumber]'))} ordering-type='Columns' />"
                f"<table-calc field={a(q('[Calc_Index]'))} ordering-type='Field'>{orders}</table-calc>")
    p, px = inst("usrn", "Calc_PageFilter", pf_extra)
    insts += [(z, zx), (s, sx), (c, cx), (p, px)]
    rows = " / ".join(q(n) for n, _ in insts[:len(LIST_ROWS)])
    rows = "(" + rows + ")" if len(LIST_ROWS) > 1 else rows
    last_row = insts[len(LIST_ROWS) - 1][0]
    style = (no_grid()
             + f"<style-rule element='cell'><format attr='height' field={a(q(last_row))} value='24' /></style-rule>"
             + "<style-rule element='header'>" + "".join(
                 f"<format attr='width' field={a(q(n))} value={a(str(LIST_WIDTHS[f]))} />"
                 for (n, _), (k, f, _l) in zip(insts, LIST_ROWS)) + "</style-rule>"
             + "<style-rule element='label'>" + "".join(
                 f"<format attr='text-format' field={a(q(n))} value={a(DATE_FMT)} />"
                 for (n, _), (k, f, _l) in zip(insts, LIST_ROWS) if "Date" in f)
             # 'State' column header styled like the row field labels next to it
             + f"<format attr='font-family' field={a(q(z))} value={a(FONT_SEMI)} />"
             + f"<format attr='color' field={a(q(z))} value={a(MUTED)} />"
             + f"<format attr='font-size' field={a(q(z))} value='9' />"
             + "</style-rule>")
    title = run("Cases opened in ", NAVY, 12, FONT_SEMI) + run("&lt;[Parameters].[Parameter 1]&gt;", NAVY, 12, FONT_SEMI) \
        + run(" · page ", MUTED, 10) + run("&lt;[Parameters].[Parameter 3]&gt;", MUTED, 10)
    return sheet("Case List", ["Calc_StateHeader", "Calc_CreatedInSel", "Calc_PageFilter"], insts,
                 [pane("Text", f"<color column={a(q(s))} /><text column={a(q(s))} />",
                       [run(ref(s), None, 9, FONT_SEMI)])],
                 rows=rows, cols=q(z), raw=[f for _, f, _ in LIST_ROWS] + ["State"], title=title, style=style,
                 field_labels=True,
                 view_extra=bool_filter(c, "[none:Calc_CreatedInSel:nk]")
                 + bool_filter(p, p)
                 + slices(c, p))


def page_nav():
    """Report technique 4: the |◄ ◄ n-1 n n+1 ► ►| navigator; a parameter action sets Current Page."""
    sl, slx = inst("ok", "Calc_NavSlot")
    lb, lbx = inst("nk", "Calc_NavLabel")
    ac, acx = inst("nk", "Calc_NavActive")
    nv, nvx = inst("qk", "Calc_NavValue")
    ok, okx = inst("nk", "Calc_IsNavSlot")
    d, dx = inst("nk", "Calc_Dummy")
    style = ("<style-rule element='label'>"
             f"<format attr='display' field={a(q(sl))} value='false' /></style-rule>")
    return sheet("Page Navigator", ["Calc_NavSlot", "Calc_NavLabel", "Calc_NavActive", "Calc_NavValue",
                                    "Calc_IsNavSlot", "Calc_Dummy"],
                 [(sl, slx), (lb, lbx), (ac, acx), (nv, nvx), (ok, okx), (d, dx)],
                 [pane("Text", f"<color column={a(q(ac))} /><text column={a(q(lb))} /><lod column={a(q(nv))} />"
                               f"<lod column={a(q(d))} />", [run(ref(lb), None, 12, FONT_BOLD)], center=True)],
                 cols=q(sl), style=style, tooltip=False,
                 view_extra=bool_filter(ok, "[none:Calc_IsNavSlot:nk]") + slices(ok))


def sheets():
    pts = '*▲0.0" pts";▼0.0" pts"'
    return [
        kpi("KPI Opened", "Cases opened", "Calc_Opened", "n#,##0", "Calc_OpenedChg", "*▲0.0%;▼0.0%", " vs prev mo"),
        kpi("KPI Closed", "Cases closed", "Calc_Closed", "n#,##0", "Calc_ClosedChg", "*▲0.0%;▼0.0%", " vs prev mo"),
        kpi("KPI Days", "Avg days to close", "Calc_AvgDays", "n0.0", "Calc_AvgDaysChg", '*▲0.0" d";▼0.0" d"',
            " vs prev mo"),
        kpi("KPI Resolution", "Resolution rate", "Calc_ResRate", "p0.0%", "Calc_ResRateChg", pts, " vs prev mo"),
        kpi("KPI On-time", "Resolved by desired start", "Calc_OnTimeRate", "p0.0%", "Calc_OnTimeChg", pts,
            " vs prev mo"),
        kpi("KPI Open", "Open cases (now)", "Calc_OpenNow", "n#,##0", sub="Calc_PastStart",
            sub_fmt='*#,##0" past desired start"'),
        metric_buttons(), trend(),
        bars_by("Division", "By Division", "By division"),
        bars_by("Department", "By Department", "By department"),
        case_list(), page_nav(),
    ]


SHEETS = ["KPI Opened", "KPI Closed", "KPI Days", "KPI Resolution", "KPI On-time", "KPI Open", "Metric Buttons",
          "Trend", "By Division", "By Department", "Case List", "Page Navigator"]


# ------------------------------------------------------------------ dashboard
def dashboard():
    ids = iter(range(2, 200))

    def style(bg, margin=6, padding=8):
        return ("<zone-style><format attr='border-color' value='#000000' /><format attr='border-style' value='none' />"
                f"<format attr='border-width' value='0' /><format attr='margin' value='{margin}' />"
                f"<format attr='padding' value='{padding}' /><format attr='background-color' value={a(bg)} /></zone-style>")

    def z(x, y, w, h, name, title=True, bg=WHITE, margin=6, padding=8):
        return (f"<zone h='{h}' id='{next(ids)}' name={a(name)} show-title={a('true' if title else 'false')} "
                f"w='{w}' x='{x}' y='{y}'>{style(bg, margin, padding)}</zone>")

    def card(x, y, w, h, children):
        return (f"<zone h='{h}' id='{next(ids)}' param='vert' type-v2='layout-flow' w='{w}' x='{x}' y='{y}'>"
                + "".join(children) + style(WHITE) + "</zone>")

    # Layout in pixels for a W x H dashboard, converted to Tableau's 0-100000 zone units.
    # Heights are sized to content so no sheet needs to scroll:
    #   header 66 | KPI cards 102 (title + 24pt value + change line) | buttons 32 + trend 188 |
    #   case list 332 (title + header + 10 rows x 24 px) + page arrows 60
    Y = lambda px: round(px * 100000 / H)
    hdr, kpi_h, btn_h, trend_h, list_h, nav_h = 66, 102, 32, 188, 332, 60
    y_kpi, y_mid = Y(hdr), Y(hdr + kpi_h)
    y_bot = Y(hdr + kpi_h + btn_h + trend_h)
    y_nav = Y(hdr + kpi_h + btn_h + trend_h + list_h)
    assert hdr + kpi_h + btn_h + trend_h + list_h + nav_h == H

    out = []
    period = f"{MONTHS[0]:%b %Y} – {MONTHS[-1]:%b %Y}"
    out.append(f"<zone h='{y_kpi}' id='{next(ids)}' type-v2='text' w='76000' x='0' y='0'><formatted-text>"
               + run("Student Hiring Cases", WHITE, 20, FONT_BOLD)
               + run(f"&#10;Hiring requests by month · {len(_rows):,} cases, {escape(period)} · "
                     "pick a month, a metric, or a division to drill in", GOLD, 11, FONT_SEMI)
               + "</formatted-text>" + style(NAVY, 0, 10) + "</zone>")
    out.append(f"<zone h='{y_kpi}' id='{next(ids)}' mode='compact' param='[Parameters].[Parameter 1]' type-v2='paramctrl' "
               f"w='24000' x='76000' y='0'><formatted-text>{run('Select month', GOLD, 10, FONT_SEMI)}</formatted-text>"
               + style(NAVY, 0, 10) + "</zone>")
    kw = 100000 // 6
    for i, s in enumerate(SHEETS[:6]):
        out.append(z(i * kw, y_kpi, kw if i < 5 else 100000 - 5 * kw, y_mid - y_kpi, s, padding=4))
    out.append(card(0, y_mid, 62000, y_bot - y_mid, [
        z(0, y_mid, 62000, Y(btn_h), "Metric Buttons", title=False, margin=0, padding=2),
        z(0, y_mid + Y(btn_h), 62000, y_bot - y_mid - Y(btn_h), "Trend", margin=0, padding=4)]))
    out.append(z(62000, y_mid, 38000, y_bot - y_mid, "By Division"))
    nav = 100000 - y_nav
    out.append(card(0, y_bot, 62000, 100000 - y_bot, [
        z(0, y_bot, 62000, y_nav - y_bot, "Case List", margin=0, padding=4),
        f"<zone h='{nav}' id='{next(ids)}' param='horz' type-v2='layout-flow' w='62000' x='0' y='{y_nav}'>"
        + f"<zone h='{nav}' id='{next(ids)}' type-v2='empty' w='19000' x='0' y='{y_nav}'>{style(WHITE, 0, 0)}</zone>"
        + z(19000, y_nav, 24000, nav, "Page Navigator", title=False, margin=0, padding=6)
        + f"<zone h='{nav}' id='{next(ids)}' type-v2='empty' w='19000' x='43000' y='{y_nav}'>{style(WHITE, 0, 0)}</zone>"
        + style(WHITE, 0, 0) + "</zone>"]))
    out.append(z(62000, y_bot, 38000, 100000 - y_bot, "By Department"))
    return f"""<dashboard name={a(DASH)}>
  <style />
  <size maxheight='{H}' maxwidth='{W}' minheight='{H}' minwidth='{W}' sizing-mode='fixed' />
  <zones>
    <zone h='100000' id='1' type-v2='layout-basic' w='100000' x='0' y='0'>
{chr(10).join(out)}
      {style(PAGE, 0, 6)}
    </zone>
  </zones>
</dashboard>"""


# ------------------------------------------------------------------ actions (report section 5)
def actions():
    def pa(n, caption, sheet_name, source, target, agg):
        return f"""<edit-parameter-action caption={a(caption)} name={a(f'[Action{n}_HIRE{n:028d}]')}>
  <activation type='on-select' />
  <source dashboard={a(DASH)} type='sheet' worksheet={a(sheet_name)} />
  <agg-type type={a(agg)} />
  <clear-option type='do-nothing' value='i:1' />
  <params><param name='source-field' value={a(q(source))} /><param name='target-parameter' value={a(target)} /></params>
</edit-parameter-action>"""
    params = [pa(i, f"Metric: {CALCS[f'Calc_Btn{i}'][4].strip(chr(39))}", "Metric Buttons",
                 f"[none:Calc_BtnVal{i}:qk]", P["Metric"], "sum") for i in (1, 2, 3)]
    params.append(pa(4, "Go to page", "Page Navigator", "[none:Calc_NavValue:qk]", P["Current Page"], "sum"))
    out = []
    # no grey-out on button sheets: highlight on Dummy, everything else excluded (report section 5)
    others = [s for s in SHEETS]
    for n, src in ((5, "Metric Buttons"), (6, "Page Navigator")):
        out.append(f"""<action caption={a('No highlight: ' + src)} name={a(f'[Action{n}_HIRE{n:028d}]')}>
  <activation auto-clear='true' type='on-select' />
  <source dashboard={a(DASH)} type='sheet' worksheet={a(src)} />
  <command command='tsc:brush'>
    <param name='exclude' value={a(','.join(s for s in others if s != src))} />
    <param name='field-captions' value='Dummy' />
    <param name='target' value={a(DASH)} />
  </command>
</action>""")
    # click a division -> filter the department bars (report: "Name Filter")
    link = f"tsl:{DASH}?%5B{DS}%5D.%5BDivision%5D~s0=&lt;[Division]~na&gt;".replace(" ", "%20")
    out.append(f"""<action caption='Division filter' name='[Action7_HIRE0000000000000000000000000007]'>
  <activation auto-clear='true' type='on-select' />
  <source dashboard={a(DASH)} type='sheet' worksheet='By Division' />
  <link caption='Division filter' delimiter=',' escape='\\' expression="{link}" include-null='true' multi-select='true' url-escape='true' />
  <command command='tsc:tsl-filter'>
    <param name='exclude' value={a(','.join(s for s in SHEETS if s not in ('By Department',)))} />
    <param name='target' value={a(DASH)} />
  </command>
</action>""")
    return "<actions>\n" + "\n".join(out + params) + "\n</actions>"   # Tableau: <action>s before parameter actions


def windows():
    fit = {"Case List": "fit-width"}   # entire-view would squeeze rows to the zone height
    vps = "".join(f"<viewpoint name={a(s)}><zoom type={a(fit.get(s, 'entire-view'))} /></viewpoint>" for s in SHEETS)
    wins = [f"<window class='dashboard' maximized='true' name={a(DASH)}><viewpoints>{vps}</viewpoints>"
            "<active id='-1' /></window>"]
    wins += [f"<window class='worksheet' hidden='true' name={a(s)}><cards><edge name='left'><strip size='160'>"
             "<card type='pages' /><card type='filters' /><card type='marks' /></strip></edge></cards></window>"
             for s in SHEETS]
    return "<windows source-height='32'>\n" + "\n".join(wins) + "\n</windows>"


def workbook():
    return f"""<?xml version='1.0' encoding='utf-8' ?>

<workbook locale='en_US' source-build='0.0.0 (0000.0.0.0)' source-platform='mac' version='18.1' xmlns:user='http://www.tableausoftware.com/xml/user'>
  <document-format-change-manifest>
    <ParameterAction />
    <ParameterActionClearSelection />
  </document-format-change-manifest>
  <preferences><preference name='ui.encoding.shelf.height' value='24' /><preference name='ui.shelf.height' value='26' /></preferences>
  <style-theme name='smooth' />
  <datasources>
{datasource()}
  </datasources>
{actions()}
  <worksheets>
{chr(10).join(sheets())}
  </worksheets>
  <dashboards>
{dashboard()}
  </dashboards>
{windows()}
</workbook>
"""


if __name__ == "__main__":
    build_hyper()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(TWB, workbook())
        zf.write(HYPER_TMP, HYPER_IN_PACKAGE)
    print("wrote", OUT)
