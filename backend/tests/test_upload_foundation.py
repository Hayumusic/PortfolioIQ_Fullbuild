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


def workbook_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


class _Response:
    def __init__(
        self,
        status_code: int,
        payload: bytes,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {
            key.decode().casefold(): value.decode()
            for key, value in (headers or [])
        }

    def json(self) -> dict[str, object]:
        return json.loads(self._payload)

    @property
    def text(self) -> str:
        return self._payload.decode("utf-8")


class _ASGIClient:
    def __init__(self, app: object, runner: asyncio.Runner) -> None:
        self.app = app
        self.runner = runner

    def get(self, url: str) -> _Response:
        return self._request("GET", url)

    def post(
        self,
        url: str,
        files: dict[str, tuple[object, ...]]
        | list[tuple[str, tuple[object, ...]]]
        | None = None,
    ) -> _Response:
        body = b""
        headers: list[tuple[bytes, bytes]] = []
        if files is not None:
            boundary = "portfolio-iq-test-boundary"
            items = list(files.items()) if isinstance(files, dict) else files
            parts: list[bytes] = []
            for field_name, file_value in items:
                filename = str(file_value[0])
                content = file_value[1]
                content_type = (
                    str(file_value[2])
                    if len(file_value) > 2
                    else "application/octet-stream"
                )
                parts.extend(
                    [
                        f"--{boundary}\r\n".encode(),
                        (
                            f'Content-Disposition: form-data; name="{field_name}"; '
                            f'filename="{filename}"\r\n'
                        ).encode(),
                        f"Content-Type: {content_type}\r\n\r\n".encode(),
                        bytes(content),
                        b"\r\n",
                    ]
                )
            parts.append(f"--{boundary}--\r\n".encode())
            body = b"".join(parts)
            headers = [
                ("content-type".encode(), f"multipart/form-data; boundary={boundary}".encode()),
                ("content-length".encode(), str(len(body)).encode()),
            ]
        return self._request("POST", url, body=body, headers=headers)

    def _request(
        self,
        method: str,
        url: str,
        *,
        body: bytes = b"",
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> _Response:
        parsed_url = urlsplit(url)
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
            "headers": headers or [],
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
        response_headers = next(
            message.get("headers", [])
            for message in messages
            if message["type"] == "http.response.start"
        )
        return _Response(status_code, response_body, response_headers)


class UploadFoundationAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            Settings(local_storage_root=Path(self.temporary_directory.name))
        )
        self.runner = asyncio.Runner()
        self.lifespan = self.app.router.lifespan_context(self.app)
        self.runner.run(self.lifespan.__aenter__())
        self.client = _ASGIClient(self.app, self.runner)
        self.job_id = self.app.state.services.job_service.create_job().job_id

    def tearDown(self) -> None:
        self.runner.run(self.lifespan.__aexit__(None, None, None))
        self.runner.close()
        self.temporary_directory.cleanup()

    def test_status_before_uploads_and_after_cmdb(self) -> None:
        response = self.client.get(f"/api/jobs/{self.job_id}/uploads/status")

        self.assertEqual(response.status_code, 200)
        initial = response.json()
        self.assertFalse(initial["cmdb_ready"])
        self.assertFalse(initial["can_run_validation"])
        self.assertFalse(initial["can_run_outputs_analysis"])
        self.assertFalse(initial["optional_inputs_available"])
        self.assertEqual(initial["sources"]["cmdb"]["upload_count"], 0)
        self.assertEqual(
            initial["missing_required_inputs"],
            ["cmdb", "mandatory_fields_config", "output_family_config"],
        )

        cmdb = workbook_bytes(
            ["Application Code", "Application Name"], [["APP-1", "Payments"]]
        )
        uploaded = self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={
                "file": (
                    "inventory.xlsx",
                    cmdb,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 200)
        self.assertEqual(uploaded.json()["files"][0]["filename"], "inventory.xlsx")

        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertTrue(status["cmdb_ready"])
        self.assertTrue(status["sources"]["cmdb"]["uploaded"])
        self.assertTrue(status["sources"]["cmdb"]["processed"])
        self.assertEqual(status["sources"]["cmdb"]["latest_filename"], "inventory.xlsx")
        self.assertFalse(status["can_run_validation"])

    def test_mandatory_fields_csv_is_normalized_and_used_by_validation(self) -> None:
        response = self.client.post(
            f"/api/jobs/{self.job_id}/upload/mandatory-fields-config",
            files={
                "file": (
                    "mandatory.csv",
                    b"mandatory fields\nApplication Code\n Owner \nowner\n\n",
                    "text/csv",
                )
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["configured_mandatory_fields"], ["Application Code", "Owner"]
        )
        self.assertEqual(payload["row_count"], 3)
        self.assertTrue(payload["usable"])
        self.assertTrue(any("duplicate" in warning for warning in payload["warnings"]))
        self.assertTrue(
            self.app.state.services.job_service.storage.exists(
                f"jobs/{self.job_id}/processed/config/mandatory_fields.json"
            )
        )

        cmdb = workbook_bytes(
            ["Application Code", "Owner"], [["APP-1", "Team A"]]
        )
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={"file": ("inventory.xlsx", cmdb)},
        )
        validation = self.client.post(
            f"/api/jobs/{self.job_id}/analysis/validation"
        )
        self.assertEqual(validation.status_code, 200)
        self.assertEqual(validation.json()["summary"]["overall_completeness"], 100.0)

        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertTrue(status["mandatory_fields_config_ready"])
        self.assertTrue(status["can_run_validation"])

    def test_mandatory_fields_one_column_excel_is_accepted(self) -> None:
        content = workbook_bytes(
            ["CMDB Column"], [["Application Code"], ["Application Name"]]
        )
        response = self.client.post(
            f"/api/jobs/{self.job_id}/upload/mandatory-fields-config",
            files={"file": ("mandatory.xlsx", content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["configured_mandatory_fields"],
            ["Application Code", "Application Name"],
        )

    def test_unusable_mandatory_fields_config_is_rejected_without_storage(self) -> None:
        response = self.client.post(
            f"/api/jobs/{self.job_id}/upload/mandatory-fields-config",
            files={"file": ("mandatory.csv", b"mandatory_field\n")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("no usable mandatory fields", response.json()["detail"])
        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertFalse(status["sources"]["mandatory_fields_config"]["uploaded"])

    def test_upload_categories_reject_unsupported_file_types(self) -> None:
        response = self.client.post(
            f"/api/jobs/{self.job_id}/upload/confluence",
            files={"files": ("notes.txt", b"not a PDF", "text/plain")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn(".pdf", response.json()["detail"])

    def test_output_family_excel_is_parsed_and_enables_outputs_readiness(self) -> None:
        content = workbook_bytes(
            ["Output Family", "Members", "Description"],
            [
                ["Reports", "PDF, CSV, pdf", "Generated reports"],
                ["APIs", "REST, SOAP", None],
            ],
        )
        response = self.client.post(
            f"/api/jobs/{self.job_id}/upload/output-family-config",
            files={"file": ("families.xlsx", content)},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["family_count"], 2)
        self.assertEqual(payload["families"][0]["keywords"], ["PDF", "CSV"])
        self.assertTrue(payload["usable"])
        self.assertTrue(
            self.app.state.services.job_service.storage.exists(
                f"jobs/{self.job_id}/processed/config/output_families.json"
            )
        )

        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertTrue(status["output_family_config_ready"])
        self.assertFalse(status["can_run_outputs_analysis"])

        cmdb = workbook_bytes(["Application Code"], [["APP-1"]])
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={"file": ("inventory.xlsx", cmdb)},
        )
        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertTrue(status["can_run_outputs_analysis"])

    def test_output_family_csv_and_unusable_config(self) -> None:
        accepted = self.client.post(
            f"/api/jobs/{self.job_id}/upload/output-family-config",
            files={
                "file": (
                    "families.csv",
                    b'family,patterns\nDashboards,"tableau, power bi"\n',
                )
            },
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()["families"][0]["name"], "Dashboards")

        other_job = self.app.state.services.job_service.create_job().job_id
        rejected = self.client.post(
            f"/api/jobs/{other_job}/upload/output-family-config",
            files={"file": ("families.csv", b"family,description\n,blank\n")},
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("no usable output families", rejected.json()["detail"])

    def test_confluence_team_validation_and_cloudwatch_metadata(self) -> None:
        confluence = self.client.post(
            f"/api/jobs/{self.job_id}/upload/confluence",
            files=[
                ("files", ("app-one.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
                ("files", ("app-two.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")),
            ],
        )
        self.assertEqual(confluence.status_code, 200)
        self.assertEqual(confluence.json()["file_count"], 2)
        self.assertTrue(confluence.json()["stored_for_future_analysis"])
        self.assertEqual(confluence.json()["files"][0]["filename"], "app-one.pdf")

        team = self.client.post(
            f"/api/jobs/{self.job_id}/upload/team-validation",
            files={
                "file": (
                    "team.csv",
                    b"Application Code,CMDB Data Up to Date\nAPP-1,Yes\n",
                )
            },
        )
        self.assertEqual(team.status_code, 200)
        self.assertEqual(team.json()["row_count"], 1)
        self.assertEqual(
            team.json()["columns"], ["Application Code", "CMDB Data Up to Date"]
        )

        cloudwatch_content = workbook_bytes(
            ["Application Code", "Metric"], [["APP-1", "Requests"]]
        )
        cloudwatch = self.client.post(
            f"/api/jobs/{self.job_id}/upload/cloudwatch",
            files={"file": ("cloudwatch.xlsx", cloudwatch_content)},
        )
        self.assertEqual(cloudwatch.status_code, 200)
        self.assertEqual(cloudwatch.json()["column_count"], 2)
        self.assertEqual(
            cloudwatch.json()["columns"], ["Application Code", "Metric"]
        )

        storage = self.app.state.services.job_service.storage
        self.assertTrue(
            storage.exists(f"jobs/{self.job_id}/processed/team_validation_preview.json")
        )
        self.assertTrue(
            storage.exists(f"jobs/{self.job_id}/processed/cloudwatch_preview.json")
        )
        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertTrue(status["optional_inputs_available"])
        self.assertEqual(status["sources"]["confluence"]["upload_count"], 2)
        self.assertTrue(status["sources"]["team_validation"]["processed"])
        self.assertTrue(status["sources"]["cloudwatch"]["processed"])

    def test_existing_global_mandatory_fields_remain_a_validation_fallback(self) -> None:
        self.app.state.services.mandatory_field_config_service.set_fields(
            ["Application Code"]
        )
        cmdb = workbook_bytes(["Application Code"], [["APP-1"]])
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={"file": ("inventory.xlsx", cmdb)},
        )

        status = self.client.get(
            f"/api/jobs/{self.job_id}/uploads/status"
        ).json()
        self.assertFalse(status["sources"]["mandatory_fields_config"]["uploaded"])
        self.assertTrue(status["mandatory_fields_config_ready"])
        self.assertTrue(status["can_run_validation"])
        self.assertEqual(
            self.client.post(
                f"/api/jobs/{self.job_id}/analysis/validation"
            ).status_code,
            200,
        )

    def test_validation_reports_job_config_priority_and_complete_mappings(self) -> None:
        self.app.state.services.mandatory_field_config_service.set_fields(["Owner"])
        config = self.client.post(
            f"/api/jobs/{self.job_id}/upload/mandatory-fields-config",
            files={
                "file": (
                    "mandatory.csv",
                    b"field\napplication code\nMissing Field\n",
                )
            },
        ).json()
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={
                "file": (
                    "inventory.xlsx",
                    workbook_bytes(["Application Code", "Owner"], [["APP-1", None]]),
                )
            },
        )

        summary = self.client.post(
            f"/api/jobs/{self.job_id}/analysis/validation"
        ).json()["summary"]

        self.assertEqual(summary["mandatory_fields_config_source"], "job_upload")
        self.assertEqual(
            summary["mandatory_fields_config_upload_id"], config["upload_id"]
        )
        self.assertEqual(summary["overall_completeness"], 50.0)
        self.assertEqual(
            summary["mandatory_field_mappings"],
            [
                {
                    "configured_field": "application code",
                    "cmdb_column": "Application Code",
                    "matched": True,
                    "match_type": "case_insensitive",
                },
                {
                    "configured_field": "Missing Field",
                    "cmdb_column": None,
                    "matched": False,
                    "match_type": "not_found",
                },
            ],
        )

    def test_validation_reports_global_config_fallback(self) -> None:
        self.app.state.services.mandatory_field_config_service.set_fields(
            ["Application Code"]
        )
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={
                "file": (
                    "inventory.xlsx",
                    workbook_bytes(["Application Code"], [["APP-1"]]),
                )
            },
        )

        summary = self.client.post(
            f"/api/jobs/{self.job_id}/analysis/validation"
        ).json()["summary"]

        self.assertEqual(summary["mandatory_fields_config_source"], "global_config")
        self.assertIsNone(summary["mandatory_fields_config_upload_id"])

    def test_completeness_csv_requires_and_exports_current_validation(self) -> None:
        self.app.state.services.mandatory_field_config_service.set_fields(
            ["Application Code", "Owner"]
        )
        before = self.client.get(
            f"/api/jobs/{self.job_id}/analysis/validation/completeness.csv"
        )
        self.assertEqual(before.status_code, 404)
        self.assertIn("has not been run", before.json()["detail"])

        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={
                "file": (
                    "inventory.xlsx",
                    workbook_bytes(
                        ["Application Code", "Application Name", "Owner"],
                        [["APP-1", "Payments", None]],
                    ),
                )
            },
        )
        self.client.post(f"/api/jobs/{self.job_id}/analysis/validation")
        exported = self.client.get(
            f"/api/jobs/{self.job_id}/analysis/validation/completeness.csv"
        )

        self.assertEqual(exported.status_code, 200)
        self.assertTrue(exported.headers["content-type"].startswith("text/csv"))
        self.assertIn("Application Code,Application Name", exported.text)
        self.assertIn("APP-1,Payments,50.0,Owner", exported.text)

    def test_optional_evidence_labels_team_checks_and_cloudwatch_summary(self) -> None:
        self.app.state.services.mandatory_field_config_service.set_fields(
            ["Application Code"]
        )
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/cmdb",
            files={
                "file": (
                    "inventory.xlsx",
                    workbook_bytes(
                        ["Application Code", "Application Name"],
                        [["APP-1", "One"], ["APP-2", "Two"]],
                    ),
                )
            },
        )
        self.client.post(
            f"/api/jobs/{self.job_id}/upload/confluence",
            files={"files": ("evidence.pdf", b"%PDF-1.4\n%%EOF")},
        )
        team = self.client.post(
            f"/api/jobs/{self.job_id}/upload/team-validation",
            files={
                "file": (
                    "team.csv",
                    b"App_Code,Confirmed\nAPP-1,Yes\nAPP-X,Maybe\n,N\n",
                )
            },
        ).json()
        cloudwatch = self.client.post(
            f"/api/jobs/{self.job_id}/upload/cloudwatch",
            files={"file": ("metrics.csv", b"Application Code,Metric\nAPP-1,CPU\n")},
        ).json()

        summary = self.client.post(
            f"/api/jobs/{self.job_id}/analysis/validation"
        ).json()["summary"]
        team_summary = summary["team_validation_summary"]
        optional = summary["optional_input_summary"]

        self.assertEqual(summary["source_of_truth_label"], "Source of Truth 3")
        self.assertEqual(summary["reliability_label"], "High")
        self.assertIn("at least 70%", summary["reliability_reason"])
        self.assertEqual(team_summary["row_count"], 3)
        self.assertEqual(team_summary["column_count"], 2)
        self.assertEqual(team_summary["columns"], ["App_Code", "Confirmed"])
        self.assertEqual(team_summary["application_code_column"], "App_Code")
        self.assertEqual(team_summary["rows_with_application_code"], 2)
        self.assertEqual(team_summary["rows_missing_application_code"], 1)
        self.assertEqual(team_summary["unmatched_team_validation_records"], 1)
        self.assertEqual(
            team_summary["cmdb_applications_missing_team_validation_record"], 1
        )
        self.assertEqual(team_summary["yes_no_column"], "Confirmed")
        self.assertEqual(team_summary["invalid_yes_no_value_count"], 1)
        self.assertEqual(optional["confluence_file_count"], 1)
        self.assertEqual(optional["team_validation_upload_id"], team["upload_id"])
        self.assertTrue(optional["cloudwatch_available"])
        self.assertEqual(optional["cloudwatch_upload_id"], cloudwatch["upload_id"])
        self.assertEqual(
            optional["source_of_truth_inputs_used"],
            ["cmdb", "confluence", "team_validation"],
        )

    def test_source_of_truth_rules_for_optional_evidence_combinations(self) -> None:
        self.app.state.services.mandatory_field_config_service.set_fields(
            ["Application Code"]
        )

        def validated_summary(
            *, confluence: bool, team: bool, cloudwatch: bool = False
        ) -> dict[str, object]:
            job_id = self.app.state.services.job_service.create_job().job_id
            self.client.post(
                f"/api/jobs/{job_id}/upload/cmdb",
                files={
                    "file": (
                        "inventory.xlsx",
                        workbook_bytes(["Application Code"], [["APP-1"]]),
                    )
                },
            )
            if confluence:
                self.client.post(
                    f"/api/jobs/{job_id}/upload/confluence",
                    files={"files": ("evidence.pdf", b"%PDF-1.4\n%%EOF")},
                )
            if team:
                self.client.post(
                    f"/api/jobs/{job_id}/upload/team-validation",
                    files={"file": ("team.csv", b"Application Code\nAPP-1\n")},
                )
            if cloudwatch:
                self.client.post(
                    f"/api/jobs/{job_id}/upload/cloudwatch",
                    files={"file": ("metrics.csv", b"Application Code,Metric\nAPP-1,CPU\n")},
                )
            return self.client.post(
                f"/api/jobs/{job_id}/analysis/validation"
            ).json()["summary"]

        cmdb_only = validated_summary(confluence=False, team=False)
        confluence_only = validated_summary(confluence=True, team=False)
        team_only = validated_summary(confluence=False, team=True)
        cloudwatch_only = validated_summary(
            confluence=False, team=False, cloudwatch=True
        )

        self.assertEqual(cmdb_only["source_of_truth_label"], "Source of Truth 1")
        self.assertEqual(cmdb_only["reliability_label"], "Average")
        self.assertEqual(
            confluence_only["source_of_truth_label"], "Source of Truth 2"
        )
        self.assertEqual(team_only["source_of_truth_label"], "Source of Truth 1")
        self.assertEqual(team_only["reliability_label"], "High")
        self.assertEqual(
            cloudwatch_only["source_of_truth_label"], "Source of Truth 1"
        )
        self.assertTrue(
            cloudwatch_only["optional_input_summary"]["cloudwatch_available"]
        )
        self.assertTrue(
            any(
                "requires both Confluence" in warning
                for warning in team_only["missing_data_warnings"]
            )
        )


if __name__ == "__main__":
    unittest.main()
