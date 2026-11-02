import csv
from io import StringIO
from typing import Any, Iterable


class InvalidLimitError(ValueError):
    """Raised when a list endpoint receives a non-positive limit."""


def bounded_limit(limit: int, maximum: int) -> int:
    """Validate a requested limit and cap it at an endpoint safety maximum."""
    if limit <= 0:
        raise InvalidLimitError("limit must be greater than 0")
    return min(limit, maximum)


def csv_text(
    rows: Iterable[dict[str, Any]],
    columns: list[str],
    *,
    list_columns: set[str] | None = None,
) -> str:
    """Serialize stable CSV columns without turning numeric zero into a blank."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    joined_columns = list_columns or set()
    for row in rows:
        values: list[Any] = []
        for column in columns:
            value = row.get(column)
            if column in joined_columns:
                if isinstance(value, (list, tuple, set)):
                    values.append("; ".join(str(item) for item in value))
                elif value is None:
                    values.append("")
                else:
                    values.append(str(value))
            else:
                values.append("" if value is None else value)
        writer.writerow(values)
    return output.getvalue()
