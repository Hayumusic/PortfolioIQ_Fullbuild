import asyncio
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

from openpyxl import Workbook

from app.core.config import Settings
from app.main import create_app
from app.services.cmdb_parser_service import (
    CMDBParseError,
    CMDBParserService,
    CMDBRowLimitError,
)
from app.services.cmdb_service import CMDBService
from app.services.cmdb_validation_service import CMDBValidationService
from app.services.file_service import FileService
from app.services.job_service import JobService
from app.services.mandatory_field_config_service import (
    MandatoryFieldConfigError,
    MandatoryFieldConfigService,
)
from app.storage.local_storage import LocalStorageProvider


def workbook_bytes(headers: list[str], rows: list[list[object]]) -> BytesIO:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


class CMDBValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = CMDBParserService(max_rows=5_000)
        self.validator = CMDBValidationService()

    def test_mandatory_field_completeness_calculation(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(
                ["Application Code", "Application Name", "Owner"],
                [["A-1", "Alpha", "Team A"], ["A-2", "Beta", None]],
            ),
            "cmdb.xlsx",
        )

        result = self.validator.validate(
            parsed, ["application name", "OWNER"], "upload-1"
        )

        self.assertEqual(result["summary"]["overall_completeness"], 75.0)
        self.assertEqual(
            [item["completeness_percentage"] for item in result["applications"]],
            [100.0, 50.0],
        )
        self.assertEqual(
            result["applications"][1]["missing_mandatory_fields"], ["OWNER"]
        )

    def test_missing_mandatory_columns_count_as_missing_for_every_row(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(["App Name"], [["Alpha"], ["Beta"]]), "cmdb.xlsx"
        )

        result = self.validator.validate(parsed, ["App Name", "Owner"], "upload-1")

        self.assertEqual(result["summary"]["missing_mandatory_columns"], ["Owner"])
        self.assertEqual(result["summary"]["overall_completeness"], 50.0)
        self.assertTrue(
            all(
                item["missing_mandatory_fields"] == ["Owner"]
                for item in result["applications"]
            )
        )

    def test_duplicate_application_codes_and_names_are_reported(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(
                ["Application Code", "Application Name"],
                [["A-1", "Alpha"], ["a-1", "alpha"], ["A-2", "Beta"]],
            ),
            "cmdb.xlsx",
        )

        summary = self.validator.validate(parsed, ["Application Code"], "upload-1")[
            "summary"
        ]

        self.assertEqual(
            summary["duplicate_application_codes"],
            [{"value": "A-1", "row_numbers": [1, 2]}],
        )
        self.assertEqual(
            summary["duplicate_application_ids"],
            summary["duplicate_application_codes"],
        )
        self.assertEqual(summary["application_code_column"], "Application Code")
        self.assertIn(
            "Duplicate Application Code groups were detected",
            summary["missing_data_warnings"],
        )
        self.assertEqual(
            summary["duplicate_application_names"],
            [{"value": "Alpha", "row_numbers": [1, 2]}],
        )

    def test_application_identity_uses_name_then_row_fallback(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(
                ["Application Name", "Owner"],
                [["Alpha", "Team A"], [None, "Team B"]],
            ),
            "cmdb.xlsx",
        )

        self.assertEqual(parsed.applications[0].application_key, "Alpha")
        self.assertEqual(parsed.applications[0].application_name, "Alpha")
        self.assertEqual(parsed.applications[1].application_key, "ROW_2")
        self.assertEqual(parsed.applications[1].application_name, "ROW_2")

    def test_legacy_identifier_is_preferred_over_name_for_key(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(
                ["CMDB ID", "Service Name"], [["CI-9", "Payments"]]
            ),
            "cmdb.xlsx",
        )

        self.assertEqual(parsed.applications[0].application_key, "CI-9")
        self.assertEqual(parsed.applications[0].application_name, "Payments")

    def test_application_code_is_primary_identifier(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(
                ["Application Code", "Application Name"], [["APP-9", "Payments"]]
            ),
            "cmdb.xlsx",
        )

        self.assertEqual(parsed.application_code_column, "Application Code")
        self.assertEqual(parsed.applications[0].application_key, "APP-9")

    def test_application_code_is_preferred_when_application_id_also_exists(self) -> None:
        parsed = self.parser.parse(
            workbook_bytes(
                ["Application ID", "Application Code", "Name"],
                [["LEGACY-1", "APP-1", "Payments"]],
            ),
            "cmdb.xlsx",
        )

        self.assertEqual(parsed.application_code_column, "Application Code")
        self.assertEqual(parsed.application_id_column, "Application Code")
        self.assertEqual(parsed.applications[0].application_key, "APP-1")
        self.assertEqual(parsed.application_name_column, "Name")

    def test_more_than_max_cmdb_rows_is_rejected(self) -> None:
        parser = CMDBParserService(max_rows=2)
        source = workbook_bytes(["Name"], [["One"], ["Two"], ["Three"]])

        with self.assertRaisesRegex(CMDBRowLimitError, "maximum of 2 rows"):
            parser.parse(source, "cmdb.xlsx")

    def test_invalid_excel_content_is_rejected(self) -> None:
        with self.assertRaisesRegex(CMDBParseError, "could not be parsed"):
            self.parser.parse(BytesIO(b"not an excel workbook"), "cmdb.xlsx")

    def test_invalid_mandatory_field_configuration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = MandatoryFieldConfigService(
                LocalStorageProvider(Path(directory))
            )

            with self.assertRaisesRegex(
                MandatoryFieldConfigError, "unique after normalized matching"
            ):
                service.set_fields(["Application ID", "application-id"])

            with self.assertRaisesRegex(MandatoryFieldConfigError, "At least one"):
                service.set_fields(["  "])

    def test_upload_preview_and_latest_validation_use_storage_abstraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorageProvider(Path(directory))
            job_service = JobService(storage)
            file_service = FileService(storage, job_service, max_upload_bytes=1_000_000)
            config_service = MandatoryFieldConfigService(storage)
            service = CMDBService(
                storage=storage,
                job_service=job_service,
                file_service=file_service,
                parser_service=self.parser,
                validation_service=self.validator,
                config_service=config_service,
            )
            job = job_service.create_job()
            source = workbook_bytes(
                ["Application Code", "Application Name"], [["A-1", "Alpha"]]
            )
            original_bytes = source.getvalue()
            config_service.set_fields(["Application Code", "Application Name"])

            upload = service.upload(job.job_id, "inventory.xlsx", source)
            stored_file = storage.load_file(
                f"jobs/{job.job_id}/uploads/cmdb/{upload['upload_id']}"
            )
            result = service.run_validation(job.job_id)

            self.assertEqual(stored_file, original_bytes)
            self.assertTrue(storage.exists(f"jobs/{job.job_id}/processed/cmdb_preview.json"))
            self.assertEqual(service.get_validation(job.job_id), result)
            self.assertEqual(result["summary"]["overall_completeness"], 100.0)


class CMDBValidationAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            Settings(local_storage_root=Path(self.temporary_directory.name))
        )
        self.runner = asyncio.Runner()
        self.lifespan = self.app.router.lifespan_context(self.app)
        self.runner.run(self.lifespan.__aenter__())
        self.services = self.app.state.services
        self.services.mandatory_field_config_service.set_fields(
            ["Application Code", "Owner"]
        )

    def tearDown(self) -> None:
        self.runner.run(self.lifespan.__aexit__(None, None, None))
        self.runner.close()
        self.temporary_directory.cleanup()

    def _request(
        self, method: str, url: str, json_body: dict[str, object] | None = None
    ) -> tuple[int, dict[str, object]]:
        parsed_url = urlsplit(url)
        body = b"" if json_body is None else json.dumps(json_body).encode("utf-8")
        headers = []
        if json_body is not None:
            headers.append((b"content-type", b"application/json"))
        messages: list[dict[str, object]] = []
        request_sent = False

        async def receive() -> dict[str, object]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": parsed_url.path,
            "raw_path": parsed_url.path.encode("ascii"),
            "query_string": parsed_url.query.encode("ascii"),
            "root_path": "",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        self.runner.run(self.app(scope, receive, send))
        status_code = next(
            int(message["status"])
            for message in messages
            if message["type"] == "http.response.start"
        )
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return status_code, json.loads(response_body)

    def _create_job(self) -> str:
        return self.services.job_service.create_job().job_id

    def _upload_cmdb(self, job_id: str) -> dict[str, object]:
        source = workbook_bytes(
            [
                "Application Name",
                "Owner",
                "Application ID",
                "Application Code",
                "Context",
            ],
            [
                ["Alpha", "Team A", "legacy-1", "A-1", "One"],
                ["alpha", "Team B", "legacy-2", "a-1", "Two"],
                ["Beta", None, "legacy-3", "A-2", "Three"],
                ["Gamma", "Team C", "legacy-4", "A-3", "Four"],
                ["Delta", "Team D", "legacy-5", "A-4", "Five"],
            ],
        )
        return self.services.cmdb_service.upload(
            job_id, "inventory.xlsx", source
        )

    def test_validation_post_accepts_no_body_and_returns_compact_summary(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/validation"
        )

        self.assertEqual(status_code, 200)
        self.assertNotIn("applications", payload)
        self.assertEqual(payload["summary"]["total_row_count"], 5)
        self.assertEqual(payload["summary"]["application_code_column"], "Application Code")
        self.assertEqual(payload["summary"]["duplicate_application_code_group_count"], 1)
        self.assertEqual(payload["summary"]["duplicate_application_id_group_count"], 1)

    def test_validation_post_accepts_empty_json_body(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, _ = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/validation", json_body={}
        )

        self.assertEqual(status_code, 200)

    def test_summary_has_no_row_level_records(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/validation")

        _, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/validation/summary"
        )

        self.assertNotIn("applications", payload)
        self.assertNotIn("records", payload)
        self.assertNotIn("duplicate_application_ids", payload["summary"])
        self.assertEqual(payload["summary"]["total_column_count"], 5)
        self.assertEqual(payload["summary"]["missing_mandatory_columns"], [])

    def test_columns_preserve_order_and_detect_identity_columns(self) -> None:
        job_id = self._create_job()
        upload = self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/cmdb/columns"
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["upload_id"], upload["upload_id"])
        self.assertEqual(
            payload["columns"],
            [
                "Application Name",
                "Owner",
                "Application ID",
                "Application Code",
                "Context",
            ],
        )
        self.assertEqual(payload["application_code_column"], "Application Code")
        self.assertEqual(payload["application_id_column"], "Application Code")
        self.assertEqual(payload["application_name_column"], "Application Name")

    def test_details_are_paginated_and_page_size_has_a_maximum(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/validation")

        status_code, payload = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/validation/details?page=2&page_size=2",
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["page"], 2)
        self.assertEqual(payload["page_size"], 2)
        self.assertEqual(payload["total_records"], 5)
        self.assertEqual(payload["total_pages"], 3)
        self.assertEqual(len(payload["records"]), 2)
        self.assertEqual(
            self._request(
                "GET",
                f"/api/jobs/{job_id}/analysis/validation/details?page_size=200",
            )[0],
            200,
        )
        self.assertEqual(
            self._request(
                "GET",
                f"/api/jobs/{job_id}/analysis/validation/details?page_size=201",
            )[0],
            422,
        )

    def test_duplicates_return_groups_and_counts(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/validation")

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/validation/duplicates"
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["duplicate_application_code_group_count"], 1)
        self.assertEqual(payload["duplicate_application_id_group_count"], 1)
        self.assertEqual(payload["duplicate_application_name_group_count"], 1)
        self.assertEqual(
            payload["duplicate_application_codes"][0]["row_numbers"], [1, 2]
        )
        self.assertEqual(
            payload["duplicate_application_ids"],
            payload["duplicate_application_codes"],
        )
        self.assertEqual(
            payload["duplicate_application_names"][0]["row_numbers"], [1, 2]
        )

    def test_validation_reads_fail_clearly_before_validation_runs(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        for suffix in ("summary", "details", "duplicates"):
            with self.subTest(suffix=suffix):
                status_code, payload = self._request(
                    "GET", f"/api/jobs/{job_id}/analysis/validation/{suffix}"
                )
                self.assertEqual(status_code, 404)
                self.assertIn("has not been run", payload["detail"])


if __name__ == "__main__":
    unittest.main()
