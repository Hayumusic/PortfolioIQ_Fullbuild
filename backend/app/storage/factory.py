from app.core.config import Settings
from app.storage.base import StorageProvider
from app.storage.local_storage import LocalStorageProvider


def create_storage_provider(settings: Settings) -> StorageProvider:
    """Select the configured adapter without leaking storage details to services."""

    if settings.storage_mode.casefold() == "local":
        return LocalStorageProvider(settings.local_storage_root)
    raise ValueError(f"Unsupported storage mode: {settings.storage_mode}")
