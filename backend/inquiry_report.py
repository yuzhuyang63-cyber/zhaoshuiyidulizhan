from __future__ import annotations

import calendar
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python builds without zoneinfo are rare.
    ZoneInfo = None


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai") if ZoneInfo else timezone(timedelta(hours=8))
EXCEL_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

SHEET_INQUIRIES = "\u8be2\u76d8\u660e\u7ec6"
SHEET_MONTH_DAILY = "\u6708\u5ea6\u7edf\u8ba1"
SHEET_WEEKLY = "\u5468\u5ea6\u7edf\u8ba1"
SHEET_MONTHLY_TOTAL = "\u6708\u4efd\u6c47\u603b"
SHEET_QUARTERLY = "\u5b63\u5ea6\u7edf\u8ba1"
SHEET_YEARLY = "\u5e74\u5ea6\u7edf\u8ba1"
SHEET_PRODUCT = "\u4ea7\u54c1\u7edf\u8ba1"

INQUIRY_HEADERS = [
    "\u8be2\u76d8\u7f16\u53f7",
    "\u63d0\u4ea4\u65f6\u95f4",
    "\u5ba2\u6237\u59d3\u540d",
    "\u516c\u53f8\u540d\u79f0",
    "\u90ae\u7bb1",
    "WhatsApp",
    "\u610f\u5411\u4ea7\u54c1",
    "\u5730\u533a\u540d\u79f0",
    "\u8bbf\u5ba2IP",
    "\u6d4f\u89c8\u5668\u4fe1\u606f",
    "\u7559\u8a00\u5185\u5bb9",
]
DAILY_HEADERS = ["\u65e5\u671f", "\u8be2\u76d8\u6570\u91cf"]
WEEKLY_HEADERS = ["\u5468", "\u8be2\u76d8\u6570\u91cf"]
MONTHLY_HEADERS = ["\u6708\u4efd", "\u8be2\u76d8\u6570\u91cf"]
QUARTERLY_HEADERS = ["\u5b63\u5ea6", "\u8be2\u76d8\u6570\u91cf"]
YEARLY_HEADERS = ["\u5e74\u4efd", "\u8be2\u76d8\u6570\u91cf"]
INTEREST_HEADERS = ["\u610f\u5411\u4ea7\u54c1", "\u8be2\u76d8\u6570\u91cf"]
UNSPECIFIED = "\u672a\u586b\u5199"
CHART_TITLE = "\u6708\u5ea6\u6bcf\u65e5\u8be2\u76d8\u6570\u91cf\u67f1\u5f62\u56fe"
COUNT_LABEL = "\u8be2\u76d8\u6570\u91cf"


def parse_inquiry_time(value: str) -> datetime:
    raw_value = str(value or "").strip()
    if raw_value.endswith("Z"):
        raw_value = f"{raw_value[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(raw_value)
    except ValueError:
        parsed = datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(LOCAL_TIMEZONE)


def month_key_for_record(record: dict | None = None) -> str:
    created_at = record.get("created_at", "") if record else ""
    return parse_inquiry_time(created_at).strftime("%Y-%m") if created_at else datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m")


def load_inquiry_records(inquiry_dir: Path) -> list[dict]:
    records: list[dict] = []
    if not inquiry_dir.exists():
        return records

    for path in sorted(inquiry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)

    return sorted(records, key=lambda item: str(item.get("created_at", "")))


def filter_month_records(records: Iterable[dict], month_key: str) -> list[dict]:
    return [record for record in records if month_key_for_record(record) == month_key]


def report_dir_for(inquiry_dir: Path) -> Path:
    report_dir = inquiry_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def month_iter(start: datetime, end: datetime) -> Iterable[str]:
    year = start.year
    month = start.month
    while (year, month) <= (end.year, end.month):
        yield f"{year:04d}-{month:02d}"
        month += 1
        if month > 12:
            year += 1
            month = 1


def quarter_key(value: datetime) -> str:
    quarter = ((value.month - 1) // 3) + 1
    return f"{value.year:04d}-Q{quarter}"


def quarter_iter(start: datetime, end: datetime) -> Iterable[str]:
    year = start.year
    quarter = ((start.month - 1) // 3) + 1
    end_quarter = ((end.month - 1) // 3) + 1
    while (year, quarter) <= (end.year, end_quarter):
        yield f"{year:04d}-Q{quarter}"
        quarter += 1
        if quarter > 4:
            year += 1
            quarter = 1


def week_key(value: datetime) -> str:
    iso_year, iso_week, _ = value.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def week_iter(start: datetime, end: datetime) -> Iterable[str]:
    current = start.date()
    current = current - timedelta(days=current.weekday())
    end_date = end.date()
    while current <= end_date:
        iso_year, iso_week, _ = current.isocalendar()
        yield f"{iso_year:04d}-W{iso_week:02d}"
        current += timedelta(days=7)


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def xml_text(value: object) -> str:
    return escape(str(value if value is not None else ""), {"\"": "&quot;"})


def cell_xml(row_index: int, column_index: int, value: object, *, style: int | None = None) -> str:
    reference = f"{column_name(column_index)}{row_index}"
    style_attr = f' s="{style}"' if style is not None else ""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{reference}"{style_attr}><v>{value}</v></c>'

    text = xml_text(value)
    space_attr = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{reference}" t="inlineStr"{style_attr}><is><t{space_attr}>{text}</t></is></c>'


def rows_xml(rows: list[list[object]], *, header: bool = True) -> str:
    parts: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = [
            cell_xml(row_index, column_index, value, style=1 if header and row_index == 1 else None)
            for column_index, value in enumerate(row, start=1)
        ]
        parts.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return "".join(parts)


def worksheet_xml(
    rows: list[list[object]],
    *,
    column_widths: list[int] | None = None,
    drawing_relationship_id: str | None = None,
) -> str:
    max_columns = max((len(row) for row in rows), default=1)
    max_rows = max(len(rows), 1)
    dimension = f"A1:{column_name(max_columns)}{max_rows}"
    cols = ""
    if column_widths:
        col_parts = []
        for index, width in enumerate(column_widths, start=1):
            col_parts.append(f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>')
        cols = f"<cols>{''.join(col_parts)}</cols>"

    drawing = f'<drawing r:id="{drawing_relationship_id}"/>' if drawing_relationship_id else ""
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="{dimension}"/>
  <sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  {cols}
  <sheetData>{rows_xml(rows)}</sheetData>
  {drawing}
</worksheet>'''


def workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{xml_text(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <workbookPr date1904="false"/>
  <sheets>{sheets}</sheets>
</workbook>'''


def workbook_relationships_xml(sheet_count: int) -> str:
    relationships = [
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    ]
    relationships.append(
        f'<Relationship Id="rId{sheet_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {"".join(relationships)}
</Relationships>'''


def styles_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><color theme="1"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="2">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>'''


def content_types_xml(sheet_count: int) -> str:
    worksheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {worksheet_overrides}
  <Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>
  <Override PartName="/xl/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>'''


def root_relationships_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>'''


def app_properties_xml(sheet_names: list[str]) -> str:
    titles = "".join(f"<vt:lpstr>{xml_text(name)}</vt:lpstr>" for name in sheet_names)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Inquiry Backend</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs><vt:vector size="2" baseType="variant"><vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant><vt:variant><vt:i4>{len(sheet_names)}</vt:i4></vt:variant></vt:vector></HeadingPairs>
  <TitlesOfParts><vt:vector size="{len(sheet_names)}" baseType="lpstr">{titles}</vt:vector></TitlesOfParts>
</Properties>'''


def core_properties_xml() -> str:
    created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>Inquiry Backend</dc:creator>
  <cp:lastModifiedBy>Inquiry Backend</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{created}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{created}</dcterms:modified>
</cp:coreProperties>'''


def drawing_relationships_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart1.xml"/>
</Relationships>'''


def sheet_drawing_relationship_xml() -> str:
    return '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>
</Relationships>'''


def drawing_xml() -> str:
    chart_name = xml_text(CHART_TITLE)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <xdr:twoCellAnchor>
    <xdr:from><xdr:col>3</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>1</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:to><xdr:col>12</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>22</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
    <xdr:graphicFrame macro="">
      <xdr:nvGraphicFramePr><xdr:cNvPr id="2" name="{chart_name}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>
      <xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>
      <a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId1"/></a:graphicData></a:graphic>
    </xdr:graphicFrame>
    <xdr:clientData/>
  </xdr:twoCellAnchor>
</xdr:wsDr>"""


def chart_title_xml(title: str) -> str:
    return f'''<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{xml_text(title)}</a:t></a:r></a:p></c:rich></c:tx><c:layout/></c:title>'''


def chart_xml(daily_rows: list[list[object]], *, source_sheet_name: str = SHEET_MONTH_DAILY) -> str:
    data_rows = daily_rows[1:] if len(daily_rows) > 1 else [["", 0]]
    point_count = len(data_rows)
    quoted_sheet_name = source_sheet_name.replace("'", "''")
    category_points = "".join(
        f'<c:pt idx="{index}"><c:v>{xml_text(row[0])}</c:v></c:pt>' for index, row in enumerate(data_rows)
    )
    value_points = "".join(
        f'<c:pt idx="{index}"><c:v>{int(row[1] or 0)}</c:v></c:pt>' for index, row in enumerate(data_rows)
    )
    end_row = point_count + 1
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <c:chart>
    {chart_title_xml(CHART_TITLE)}
    <c:plotArea>
      <c:layout/>
      <c:barChart>
        <c:barDir val="col"/>
        <c:grouping val="clustered"/>
        <c:varyColors val="0"/>
        <c:ser>
          <c:idx val="0"/><c:order val="0"/>
          <c:tx><c:v>{xml_text(COUNT_LABEL)}</c:v></c:tx>
          <c:cat><c:strRef><c:f>'{quoted_sheet_name}'!$A$2:$A${end_row}</c:f><c:strCache><c:ptCount val="{point_count}"/>{category_points}</c:strCache></c:strRef></c:cat>
          <c:val><c:numRef><c:f>'{quoted_sheet_name}'!$B$2:$B${end_row}</c:f><c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="{point_count}"/>{value_points}</c:numCache></c:numRef></c:val>
        </c:ser>
        <c:axId val="1001"/><c:axId val="1002"/>
      </c:barChart>
      <c:catAx><c:axId val="1001"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="1002"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>
      <c:valAx><c:axId val="1002"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:delete val="0"/><c:axPos val="l"/><c:majorGridlines/><c:numFmt formatCode="General" sourceLinked="1"/><c:tickLblPos val="nextTo"/><c:crossAx val="1001"/><c:crosses val="autoZero"/></c:valAx>
    </c:plotArea>
    <c:legend><c:legendPos val="b"/><c:layout/></c:legend>
    <c:plotVisOnly val="1"/>
  </c:chart>
</c:chartSpace>"""


def inquiry_record_row(record: dict) -> list[object]:
    visitor_ip = record.get("forwarded_for") or record.get("remote_addr") or ""
    return [
        record.get("id", ""),
        parse_inquiry_time(record.get("created_at", "")).strftime("%Y-%m-%d %H:%M:%S"),
        record.get("name", ""),
        record.get("company", ""),
        record.get("email", ""),
        record.get("whatsapp", ""),
        record.get("interest", ""),
        record.get("country") or record.get("region") or "",
        visitor_ip,
        record.get("user_agent", ""),
        record.get("message", ""),
    ]


def build_inquiry_rows(records: list[dict]) -> list[list[object]]:
    rows = [INQUIRY_HEADERS]
    rows.extend(inquiry_record_row(record) for record in records)
    return rows


def build_month_daily_rows(records: list[dict], month_key: str) -> list[list[object]]:
    try:
        year, month = (int(part) for part in month_key.split("-", 1))
    except Exception:
        now = datetime.now(LOCAL_TIMEZONE)
        year, month = now.year, now.month
        month_key = f"{year:04d}-{month:02d}"

    days_in_month = calendar.monthrange(year, month)[1]
    month_records = filter_month_records(records, month_key)
    daily_counts = Counter(
        parse_inquiry_time(record.get("created_at", "")).strftime("%Y-%m-%d")
        for record in month_records
    )
    rows: list[list[object]] = [DAILY_HEADERS]
    for day in range(1, days_in_month + 1):
        date_key = f"{month_key}-{day:02d}"
        rows.append([date_key, daily_counts.get(date_key, 0)])
    return rows


def build_interest_rows(records: list[dict]) -> list[list[object]]:
    interest_counts = Counter((str(record.get("interest") or "").strip() or UNSPECIFIED) for record in records)
    rows: list[list[object]] = [INTEREST_HEADERS]
    for interest, count in sorted(interest_counts.items(), key=lambda item: (-item[1], item[0].lower())):
        rows.append([interest, count])
    if len(rows) == 1:
        rows.append([UNSPECIFIED, 0])
    return rows


def build_report_rows(records: list[dict], month_key: str) -> tuple[list[list[object]], list[list[object]], list[list[object]]]:
    return build_inquiry_rows(records), build_month_daily_rows(records, month_key), build_interest_rows(records)


def build_long_term_summary_rows(records: list[dict]) -> tuple[
    list[list[object]],
    list[list[object]],
    list[list[object]],
    list[list[object]],
]:
    parsed_times = [parse_inquiry_time(record.get("created_at", "")) for record in records]
    if not parsed_times:
        today = datetime.now(LOCAL_TIMEZONE)
        parsed_times = [today]

    start = min(parsed_times)
    end = max(parsed_times)

    weekly_counts = Counter(week_key(value) for value in parsed_times if records)
    weekly_rows: list[list[object]] = [WEEKLY_HEADERS]
    for key in week_iter(start, end):
        weekly_rows.append([key, weekly_counts.get(key, 0)])

    monthly_counts = Counter(value.strftime("%Y-%m") for value in parsed_times if records)
    monthly_rows: list[list[object]] = [MONTHLY_HEADERS]
    for key in month_iter(start, end):
        monthly_rows.append([key, monthly_counts.get(key, 0)])

    quarterly_counts = Counter(quarter_key(value) for value in parsed_times if records)
    quarterly_rows: list[list[object]] = [QUARTERLY_HEADERS]
    for key in quarter_iter(start, end):
        quarterly_rows.append([key, quarterly_counts.get(key, 0)])

    yearly_counts = Counter(str(value.year) for value in parsed_times if records)
    yearly_rows: list[list[object]] = [YEARLY_HEADERS]
    for year in range(start.year, end.year + 1):
        yearly_rows.append([str(year), yearly_counts.get(str(year), 0)])

    return weekly_rows, monthly_rows, quarterly_rows, yearly_rows


def write_inquiry_workbook(
    report_path: Path,
    sheet_names: list[str],
    worksheets: list[str],
    chart_rows: list[list[object]],
) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("wb", delete=False, dir=report_path.parent, suffix=".tmp") as temp_file:
        temp_path = Path(temp_file.name)

    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml(len(sheet_names)))
            archive.writestr("_rels/.rels", root_relationships_xml())
            archive.writestr("docProps/app.xml", app_properties_xml(sheet_names))
            archive.writestr("docProps/core.xml", core_properties_xml())
            archive.writestr("xl/workbook.xml", workbook_xml(sheet_names))
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships_xml(len(sheet_names)))
            archive.writestr("xl/styles.xml", styles_xml())
            for index, worksheet in enumerate(worksheets, start=1):
                archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet)
            archive.writestr("xl/worksheets/_rels/sheet2.xml.rels", sheet_drawing_relationship_xml())
            archive.writestr("xl/drawings/drawing1.xml", drawing_xml())
            archive.writestr("xl/drawings/_rels/drawing1.xml.rels", drawing_relationships_xml())
            archive.writestr("xl/charts/chart1.xml", chart_xml(chart_rows, source_sheet_name=sheet_names[1]))
        temp_path.replace(report_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return report_path


def write_monthly_inquiry_report(inquiry_dir: Path, month_key: str) -> Path:
    records = filter_month_records(load_inquiry_records(inquiry_dir), month_key)
    report_path = report_dir_for(inquiry_dir) / f"inquiry-report-{month_key}.xlsx"

    inquiry_rows, daily_rows, interest_rows = build_report_rows(records, month_key)
    sheet_names = [SHEET_INQUIRIES, SHEET_MONTH_DAILY, SHEET_PRODUCT]
    worksheets = [
        worksheet_xml(inquiry_rows, column_widths=[14, 21, 18, 22, 28, 20, 24, 18, 22, 42, 60]),
        worksheet_xml(daily_rows, column_widths=[16, 16], drawing_relationship_id="rId1"),
        worksheet_xml(interest_rows, column_widths=[30, 16]),
    ]

    return write_inquiry_workbook(report_path, sheet_names, worksheets, daily_rows)


def write_inquiry_statistics_report(inquiry_dir: Path) -> Path:
    records = load_inquiry_records(inquiry_dir)
    report_path = report_dir_for(inquiry_dir) / "inquiry-statistics.xlsx"
    current_month_key = datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m")
    month_daily_rows = build_month_daily_rows(records, current_month_key)
    weekly_rows, monthly_rows, quarterly_rows, yearly_rows = build_long_term_summary_rows(records)
    interest_rows = build_interest_rows(records)
    inquiry_rows = build_inquiry_rows(records)

    sheet_names = [
        SHEET_INQUIRIES,
        SHEET_MONTH_DAILY,
        SHEET_WEEKLY,
        SHEET_MONTHLY_TOTAL,
        SHEET_QUARTERLY,
        SHEET_YEARLY,
        SHEET_PRODUCT,
    ]
    worksheets = [
        worksheet_xml(inquiry_rows, column_widths=[14, 21, 18, 22, 28, 20, 24, 18, 22, 42, 60]),
        worksheet_xml(month_daily_rows, column_widths=[16, 16], drawing_relationship_id="rId1"),
        worksheet_xml(weekly_rows, column_widths=[16, 16]),
        worksheet_xml(monthly_rows, column_widths=[16, 16]),
        worksheet_xml(quarterly_rows, column_widths=[16, 16]),
        worksheet_xml(yearly_rows, column_widths=[16, 16]),
        worksheet_xml(interest_rows, column_widths=[30, 16]),
    ]

    return write_inquiry_workbook(report_path, sheet_names, worksheets, month_daily_rows)
