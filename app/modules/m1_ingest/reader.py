"""采信：读字节、定编码、严格解析 CSV、保留原始行号。

处理四类真实问题：
- 编码混用：BOM/UTF-8/GB18030 回退链，失败时保留已解出的部分并给原因码；
- 重复表头：分段导出常见，识别后计数并跳过，不当数据；
- 列数不齐：保留原字段，由列契约判原因码，不静默补空；
- 截断文件：csv 严格模式下引号未闭合抛错，记为截断行而不是有效数据。
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from ... import config
from ...errors import BadRequest


@dataclass
class RawRow:
    row_no: int
    fields: list[str]
    raw: str

    @property
    def blank(self) -> bool:
        return all(cell.strip() == "" for cell in self.fields)


@dataclass
class Table:
    """一份 CSV 的采信结果：表头、数据行、空白行、重复表头、截断行。"""

    name: str
    encoding: str
    sha256: str
    size: int
    header: list[str] = field(default_factory=list)
    rows: list[RawRow] = field(default_factory=list)
    blank_rows: int = 0
    repeated_headers: int = 0
    truncated_rows: int = 0
    truncated_row_no: int = 0
    state_code: str | None = None
    delimiter: str = ","

    @property
    def data_rows(self) -> int:
        return len(self.rows) + self.blank_rows + self.truncated_rows + self.repeated_headers


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BadRequest(f"无法读取样例文件：{path.name}", code="E_FILE_READ") from exc


def decode(data: bytes) -> tuple[str, str]:
    """按回退链解码，返回 (文本, 实际编码)。全部失败时抛 400。"""
    if not data:
        return "", "utf-8-sig"
    for encoding in config.ENCODING_CHAIN:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise BadRequest("文件编码不在支持范围（UTF-8 / GB18030）", code="E_ENCODING")


def _clean_header(fields: list[str]) -> list[str]:
    cleaned = [cell.strip() for cell in fields]
    if cleaned:
        cleaned[0] = cleaned[0].lstrip("\ufeff")
    return cleaned


def parse_table(name: str, data: bytes) -> Table:
    text, encoding = decode(data)
    table = Table(name=name, encoding=encoding, sha256=hashlib.sha256(data).hexdigest(),
                  size=len(data))
    if not text.strip():
        table.state_code = "R_EMPTY_FILE"
        return table

    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    header: list[str] | None = None
    line_start = 1
    try:
        for fields in reader:
            row_no = line_start
            line_start = reader.line_num + 1
            if header is None:
                if all(cell.strip() == "" for cell in fields):
                    continue  # 文件开头的空行不计入数据
                header = _clean_header(fields)
                table.header = header
                continue
            cleaned = [cell.strip() for cell in fields]
            if all(cell == "" for cell in cleaned):
                table.blank_rows += 1
                continue
            if _clean_header(fields) == header:
                table.repeated_headers += 1
                continue
            table.rows.append(RawRow(row_no=row_no, fields=cleaned, raw=",".join(cleaned)))
    except csv.Error:
        # 引号未闭合：最后一条是不完整的半行，计截断，不进有效数据
        table.truncated_rows += 1
        table.truncated_row_no = line_start

    if header is None:
        table.state_code = "R_EMPTY_FILE"
    elif not table.rows and not table.truncated_rows:
        table.state_code = "R_BLANK_ROWS" if table.blank_rows else "R_HEADER_ONLY"
    return table


def load(sample_dir: str, name: str) -> Table:
    """从样例目录读一份 CSV；只接受纯文件名，禁止路径穿越。"""
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise BadRequest("样例文件名不合法", code="E_BAD_FILE_NAME")
    path = Path(sample_dir) / name
    if not path.is_file():
        raise BadRequest(f"样例文件不存在：{name}", code="E_FILE_MISSING")
    return parse_table(name, read_bytes(path))
