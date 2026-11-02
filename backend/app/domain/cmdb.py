from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedApplication:
    internal_row_number: int
    application_key: str
    application_name: str
    source_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedCMDB:
    columns: list[str]
    applications: list[NormalizedApplication]
    application_code_column: str | None
    application_name_column: str | None

    @property
    def application_id_column(self) -> str | None:
        """Backward-compatible alias for the selected application identifier."""
        return self.application_code_column

    @property
    def row_count(self) -> int:
        return len(self.applications)

    @property
    def column_count(self) -> int:
        return len(self.columns)
