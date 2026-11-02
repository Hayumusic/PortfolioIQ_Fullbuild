from abc import ABC, abstractmethod
from typing import Any, BinaryIO


class StorageProvider(ABC):
    """Storage contract for job artifacts and future cloud adapters."""

    @abstractmethod
    def create_directory(self, relative_path: str) -> None: ...

    @abstractmethod
    def save_file(self, relative_path: str, source: BinaryIO) -> int: ...

    @abstractmethod
    def load_file(self, relative_path: str) -> bytes: ...

    @abstractmethod
    def save_json(self, relative_path: str, value: dict[str, Any]) -> None: ...

    @abstractmethod
    def load_json(self, relative_path: str) -> dict[str, Any]: ...

    @abstractmethod
    def list_files(self, relative_path: str) -> list[str]: ...

    @abstractmethod
    def delete_directory(self, relative_path: str) -> None: ...

    @abstractmethod
    def exists(self, relative_path: str) -> bool: ...
