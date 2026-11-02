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


class DashboardMetricsAPITests(unittest.TestCase):
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
            ["Application Code", "Portfolio", "Business Criticality"]
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
        headers = [] if json_body is None else [(b"content-type", b"application/json")]
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

    def _upload_cmdb(self, job_id: str) -> None:
        source = workbook_bytes(
            [
                "Application Code",
                "Application Name",
                "Status",
                "Operational Status",
                "Portfolio",
                "Business Criticality",
                "Hosting Type",
                "Hosting Provider",
                "Technology Stack",
                "Application Technology",
                "Platform",
                "User Authentication",
                "MFA",
                "WAF",
            ],
            [
                ["APP-1", "Payments Portal", "Live", "Operational", "Finance", "High", "Cloud", "AWS", "Python, SQL", "React", "Linux", "SSO", "Yes", "Yes"],
                ["APP-2", "Payment Portal", "Live", "Operational", "Finance", "High", "Cloud", "AWS", "Python, not available", "React", "Linux", "SSO", "Yes", "No"],
                ["APP-3", "People Records", "Retired", "Offline", "People", "Medium", "On Premise", None, "Java; none", "other", "Windows", "Local", "No", None],
                ["APP-4", "Travel", None, None, None, None, None, None, "n/a unknown", "true false", None, None, None, None],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

    def test_post_requires_cmdb_preview(self) -> None:
        job_id = self._create_job()

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/dashboard-metrics"
        )

        self.assertEqual(status_code, 422)
        self.assertIn("parsed CMDB preview", payload["detail"])

    def test_post_works_without_body_and_warns_for_missing_results(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/dashboard-metrics"
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["overview"]["total_applications"], 4)
        self.assertFalse(payload["generated_from"]["validation_result_available"])
        self.assertFalse(payload["generated_from"]["similarity_result_available"])
        self.assertTrue(any("validation results are unavailable" in warning for warning in payload["warnings"]))
        self.assertTrue(any("Similarity results are unavailable" in warning for warning in payload["warnings"]))

    def test_post_works_with_empty_json_and_distributions_are_correct(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/dashboard-metrics", {}
        )

        self.assertEqual(status_code, 200)
        distributions = payload["distributions"]
        self.assertEqual(
            distributions["application_status"]["status_counts"],
            {"Live": 2, "Retired": 1},
        )
        self.assertEqual(distributions["portfolio"]["counts"], {"Finance": 2, "People": 1})
        self.assertEqual(distributions["portfolio"]["missing_portfolio_count"], 1)
        self.assertEqual(distributions["hosting"]["hosting_type_counts"], {"Cloud": 2, "On Premise": 1})
        self.assertEqual(distributions["security_access"]["mfa_counts"], {"Yes": 2, "No": 1})

    def test_generic_tokens_are_excluded_from_technology_lists(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        _, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/dashboard-metrics"
        )

        technology = payload["distributions"]["technology"]
        tokens = {
            item["value"].casefold()
            for key in ("top_technology_stack", "top_application_technology")
            for item in technology[key]
        }
        self.assertTrue({"python", "sql", "java", "react"}.issubset(tokens))
        self.assertTrue(
            tokens.isdisjoint(
                {"not", "available", "n/a", "none", "unknown", "yes", "no", "true", "false", "other", "tbd"}
            )
        )

    def test_validation_and_similarity_summaries_are_used_when_available(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/validation")
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0, "possible_duplicate_threshold": 0},
        )

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/dashboard-metrics", {"top_n": 2}
        )

        self.assertEqual(status_code, 200)
        self.assertTrue(payload["generated_from"]["validation_result_available"])
        self.assertTrue(payload["generated_from"]["similarity_result_available"])
        self.assertEqual(payload["data_quality"]["overall_completeness"], 83.33)
        self.assertEqual(payload["data_quality"]["matched_mandatory_columns"], [
            {"configured_field": "Application Code", "cmdb_column": "Application Code"},
            {"configured_field": "Portfolio", "cmdb_column": "Portfolio"},
            {"configured_field": "Business Criticality", "cmdb_column": "Business Criticality"},
        ])
        self.assertEqual(payload["similarity_summary"]["similar_pair_threshold"], 0.0)
        self.assertGreater(payload["similarity_summary"]["similar_pair_count"], 0)
        self.assertLessEqual(len(payload["similarity_summary"]["top_possible_duplicates"]), 2)
        self.assertEqual(payload["warnings"], [])

    def test_summary_returns_stored_result_and_is_404_before_run(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/dashboard-metrics/summary"
        )
        self.assertEqual(status_code, 404)
        self.assertIn("have not been run", payload["detail"])

        _, generated = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/dashboard-metrics", {"top_n": 1}
        )
        status_code, stored = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/dashboard-metrics/summary"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(stored, generated)
        self.assertTrue(
            self.services.job_service.storage.exists(
                f"jobs/{job_id}/results/dashboard_metrics.json"
            )
        )


if __name__ == "__main__":
    unittest.main()
