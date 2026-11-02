import tempfile
import unittest
from pathlib import Path

from app.core.config import Settings
from app.domain.models import AnalysisInput, AnalysisResult
from app.main import create_app
from app.modules.base import AnalysisContext
from app.services.analysis_service import AnalysisService
from app.services.job_service import JobService
from app.services.openai_service import OpenAIService
from app.storage.local_storage import LocalStorageProvider


class DuplicateModule:
    name = "duplicate"

    async def execute(
        self, context: AnalysisContext, analysis_input: AnalysisInput
    ) -> AnalysisResult:
        raise AssertionError("This module should not execute")


class ArchitectureTests(unittest.TestCase):
    def test_duplicate_analysis_module_names_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorageProvider(Path(directory))
            settings = Settings(local_storage_root=directory)

            with self.assertRaisesRegex(ValueError, "Duplicate analysis module name"):
                AnalysisService(
                    job_service=JobService(storage),
                    openai_service=OpenAIService(None, None),
                    storage=storage,
                    settings=settings,
                    modules=[DuplicateModule(), DuplicateModule()],
                )

    def test_local_storage_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorageProvider(Path(directory))

            with self.assertRaises(ValueError):
                storage.load_file("../outside.txt")

    def test_api_prefix_is_applied_to_api_routes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                Settings(api_prefix="/portfolio-api", local_storage_root=directory)
            )
            paths = app.openapi()["paths"]

            self.assertIn("/health", paths)
            self.assertIn("/portfolio-api/jobs", paths)
            self.assertNotIn("/api/jobs", paths)


if __name__ == "__main__":
    unittest.main()
