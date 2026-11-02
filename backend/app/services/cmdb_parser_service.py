from datetime import date, datetime
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from app.domain.cmdb import NormalizedApplication, ParsedCMDB


class CMDBParseError(ValueError):
    pass


class CMDBRowLimitError(CMDBParseError):
    pass


class CMDBParserService:
    """Parse and normalize the first worksheet of an uploaded CMDB workbook."""

    application_code_aliases = (
        "Application Code",
        "Application ID",
        "App ID",
        "Application Identifier",
        "CMDB ID",
        "CI ID",
    )
    application_id_aliases = application_code_aliases
    application_name_aliases = (
        "Application Name",
        "App Name",
        "Name",
        "System Name",
        "Service Name",
    )

    def __init__(self, max_rows: int) -> None:
        self.max_rows = max_rows

    def parse(self, source: BinaryIO, file_name: str) -> ParsedCMDB:
        extension = Path(file_name).suffix.lower()
        if extension not in {".xlsx", ".xls"}:
            raise CMDBParseError("CMDB uploads must use a .xlsx or .xls extension")

        engine = "openpyxl" if extension == ".xlsx" else "xlrd"
        try:
            source.seek(0)
            frame = pd.read_excel(
                source,
                sheet_name=0,
                engine=engine,
                dtype=object,
            )
        except Exception as error:
            raise CMDBParseError(
                "The uploaded file could not be parsed as an Excel workbook"
            ) from error
        finally:
            source.seek(0)

        frame = frame.dropna(axis=0, how="all")
        if len(frame.index) > self.max_rows:
            raise CMDBRowLimitError(
                f"CMDB contains more than the configured maximum of {self.max_rows} rows"
            )

        columns = [str(column).strip() for column in frame.columns]
        if len(set(columns)) != len(columns):
            raise CMDBParseError("CMDB column headers must be unique")
        frame.columns = columns

        code_column = self._find_column(columns, self.application_code_aliases)
        name_column = self._find_column(columns, self.application_name_aliases)
        applications: list[NormalizedApplication] = []
        for row_number, (_, row) in enumerate(frame.iterrows(), start=1):
            source_data = {
                column: self._json_value(row[column]) for column in columns
            }
            application_code = (
                self._text(source_data.get(code_column)) if code_column else None
            )
            application_name = (
                self._text(source_data.get(name_column)) if name_column else None
            )
            key = application_code or application_name or f"ROW_{row_number}"
            label = application_name or application_code or key
            applications.append(
                NormalizedApplication(
                    internal_row_number=row_number,
                    application_key=key,
                    application_name=label,
                    source_data=source_data,
                )
            )

        return ParsedCMDB(
            columns=columns,
            applications=applications,
            application_code_column=code_column,
            application_name_column=name_column,
        )

    @classmethod
    def normalize_header(cls, value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())

    @classmethod
    def _find_column(cls, columns: list[str], aliases: tuple[str, ...]) -> str | None:
        by_normalized_name = {cls.normalize_header(column): column for column in columns}
        for alias in aliases:
            match = by_normalized_name.get(cls.normalize_header(alias))
            if match is not None:
                return match
        return None

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _json_value(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
