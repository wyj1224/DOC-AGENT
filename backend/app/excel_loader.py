import csv
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Optional
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from .chunking import excel_row_to_clause_chunks, value_to_text
from .schemas import StandardValidityRecord, TextChunk


MAIN_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
RID_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def inspect_excel(path: str, max_rows: int = 8, export_dir: Optional[str] = None) -> None:
    if is_csv_path(path):
        rows = read_csv_rows(path)
        print_table_preview(rows, source=path, max_rows=max_rows)
        return

    sheets = read_xlsx_sheets(path)
    print("source:", path)
    print("sheets:", list(sheets.keys()))

    export_path = Path(export_dir) if export_dir else None
    if export_path:
        export_path.mkdir(parents=True, exist_ok=True)

    for sheet_name, rows in sheets.items():
        print(f"\n=== {sheet_name} ===")
        print_table_preview(rows, source=f"{Path(path).name}:{sheet_name}", max_rows=max_rows)
        if export_path:
            out_path = export_path / f"{safe_filename(sheet_name)}.csv"
            write_csv_rows(rows, out_path)
            print(f"exported: {out_path}")


def load_clause_chunks(path: str, sheet_name: str = "强条") -> list[TextChunk]:
    rows = read_rows(path, sheet_name=sheet_name)
    return rows_to_clause_chunks(
        rows,
        source_file=Path(path).name,
        sheet_name=sheet_name if not is_csv_path(path) else "csv_region",
    )


def load_standard_validity_records(path: str, sheet_name: str = "清单") -> list[StandardValidityRecord]:
    rows = read_rows(path, sheet_name=sheet_name)
    required = {"过期标准（废止标准）", "新标准", "新标准实施日期"}
    columns = set(rows[0].keys()) if rows else set()
    missing = required - columns
    if missing:
        raise RuntimeError(f"清单 sheet 缺少必要列：{sorted(missing)}；当前列名：{list(columns)}")

    records: list[StandardValidityRecord] = []
    for row_number, row in enumerate(rows, start=1):
        old_standard = value_to_text(row.get("过期标准（废止标准）"))
        new_standard = value_to_text(row.get("新标准"))
        if not old_standard and not new_standard:
            continue
        records.append(
            StandardValidityRecord(
                old_standard_text=old_standard,
                new_standard_text=new_standard,
                new_publish_date=excel_date_to_text(row.get("新标准发布日期")),
                new_effective_date=excel_date_to_text(row.get("新标准实施日期")),
                involved_content=value_to_text(row.get("涉及内容")),
                verified_date=excel_date_to_text(row.get("核实时间")),
                note=value_to_text(row.get("备注")),
                source_url=value_to_text(row.get("发布链接")),
                source_file=Path(path).name,
                sheet_name=sheet_name,
                row_index=row_number,
            )
        )
    return records


def read_rows(path: str, sheet_name: Optional[str]) -> list[dict[str, object]]:
    if is_csv_path(path):
        return read_csv_rows(path)
    sheets = read_xlsx_sheets(path)
    target = sheet_name or next(iter(sheets))
    if target not in sheets:
        raise RuntimeError(f"找不到 sheet：{target}；当前 sheets：{list(sheets.keys())}")
    return sheets[target]


def rows_to_clause_chunks(
    rows: list[dict[str, object]],
    *,
    source_file: str,
    sheet_name: str,
    start_chunk_index: int = 0,
) -> list[TextChunk]:
    if not looks_like_clause_table(rows):
        columns = list(rows[0].keys()) if rows else []
        raise RuntimeError(
            "没有找到强条表格列。需要至少包含列名：标准号、强制性条文内容。\n"
            f"当前列名：{columns}"
        )

    chunks: list[TextChunk] = []
    next_index = start_chunk_index
    for row_number, row in enumerate(rows, start=1):
        row_chunks = excel_row_to_clause_chunks(
            row,
            source_file=source_file,
            sheet_name=sheet_name,
            row_index=row_number,
            start_chunk_index=next_index,
        )
        chunks.extend(row_chunks)
        next_index += len(row_chunks)
    return chunks


def read_csv_rows(path: str) -> list[dict[str, object]]:
    with open(path, newline="", encoding="utf-8-sig") as file:
        return [dict(row) for row in csv.DictReader(file)]


def write_csv_rows(rows: list[dict[str, object]], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def read_xlsx_sheets(path: str) -> dict[str, list[dict[str, object]]]:
    with ZipFile(path) as archive:
        shared_strings = read_shared_strings(archive)
        sheet_targets = read_sheet_targets(archive)
        result: dict[str, list[dict[str, object]]] = {}
        for sheet_name, target in sheet_targets:
            raw_rows = read_sheet_rows(archive, target, shared_strings)
            result[sheet_name] = rows_to_dicts(raw_rows)
        return result


def read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("a:si", MAIN_NS):
        values.append("".join(text.text or "" for text in item.findall(".//a:t", MAIN_NS)))
    return values


def read_sheet_targets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("rel:Relationship", REL_NS)}

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("a:sheets/a:sheet", MAIN_NS):
        rid = sheet.attrib[RID_NS]
        target = rel_targets[rid]
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheets.append((sheet.attrib["name"], target))
    return sheets


def read_sheet_rows(archive: ZipFile, target: str, shared_strings: list[str]) -> list[list[object]]:
    root = ET.fromstring(archive.read(target))
    rows: list[list[object]] = []
    for row in root.findall("a:sheetData/a:row", MAIN_NS):
        values: list[object] = []
        for cell in row.findall("a:c", MAIN_NS):
            index = column_index(cell.attrib.get("r", "A1"))
            while len(values) <= index:
                values.append("")
            values[index] = read_cell_value(cell, shared_strings)
        rows.append(values)
    return rows


def read_cell_value(cell: ET.Element, shared_strings: list[str]) -> object:
    value_node = cell.find("a:v", MAIN_NS)
    inline_node = cell.find("a:is", MAIN_NS)
    cell_type = cell.attrib.get("t")
    if cell_type == "s" and value_node is not None:
        index = int(value_node.text or 0)
        return shared_strings[index] if index < len(shared_strings) else ""
    if cell_type == "inlineStr" and inline_node is not None:
        return "".join(text.text or "" for text in inline_node.findall(".//a:t", MAIN_NS))
    if value_node is not None:
        return value_node.text or ""
    return ""


def rows_to_dicts(raw_rows: list[list[object]]) -> list[dict[str, object]]:
    if not raw_rows:
        return []
    headers = [value_to_text(value) for value in raw_rows[0]]
    rows: list[dict[str, object]] = []
    for raw in raw_rows[1:]:
        row = {headers[i]: raw[i] if i < len(raw) else "" for i in range(len(headers)) if headers[i]}
        if any(value_to_text(value) for value in row.values()):
            rows.append(row)
    return rows


def column_index(cell_ref: str) -> int:
    match = re.match(r"[A-Z]+", cell_ref)
    if not match:
        return 0
    index = 0
    for char in match.group(0):
        index = index * 26 + ord(char) - ord("A") + 1
    return index - 1


def looks_like_clause_table(rows: list[dict[str, object]]) -> bool:
    columns = set(rows[0].keys()) if rows else set()
    return "标准号" in columns and "强制性条文内容" in columns


def print_table_preview(rows: list[dict[str, object]], *, source: str, max_rows: int) -> None:
    columns = list(rows[0].keys()) if rows else []
    print("source:", source)
    print(f"shape: {len(rows)} rows x {len(columns)} cols")
    print("columns:", columns)
    for index, row in enumerate(rows[:max_rows], start=1):
        compact = {key: truncate(value) for key, value in row.items()}
        print(index, compact)


def truncate(value: object, max_len: int = 80) -> str:
    text = value_to_text(value).replace("\n", " ")
    return text[:max_len]


def is_csv_path(path: str) -> bool:
    return Path(path).suffix.lower() == ".csv"


def safe_filename(value: object) -> str:
    text = "" if value is None else str(value)
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in text)
    return safe[:80] or "sheet"


def excel_date_to_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = value_to_text(value)
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if 20000 <= number <= 60000:
        return (datetime(1899, 12, 30) + timedelta(days=number)).strftime("%Y-%m-%d")
    return text
