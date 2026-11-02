import asyncio
import csv
from io import BytesIO, StringIO
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


class PortfolioInsightsAPITests(unittest.TestCase):
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
    ) -> tuple[int, dict[str, str], bytes]:
        parsed = urlsplit(url)
        body = b"" if json_body is None else json.dumps(json_body).encode()
        headers = [] if json_body is None else [(b"content-type", b"application/json")]
        messages: list[dict[str, object]] = []
        sent = False

        async def receive() -> dict[str, object]:
            nonlocal sent
            if not sent:
                sent = True
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
            "path": parsed.path,
            "raw_path": parsed.path.encode("ascii"),
            "query_string": parsed.query.encode("ascii"),
            "root_path": "",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        self.runner.run(self.app(scope, receive, send))
        start = next(item for item in messages if item["type"] == "http.response.start")
        response_headers = {
            key.decode("latin1"): value.decode("latin1")
            for key, value in start.get("headers", [])
        }
        response_body = b"".join(
            item.get("body", b"")
            for item in messages
            if item["type"] == "http.response.body"
        )
        return int(start["status"]), response_headers, response_body

    def _json(
        self, method: str, url: str, body: dict[str, object] | None = None
    ) -> tuple[int, dict[str, object]]:
        status, _, payload = self._request(method, url, body)
        return status, json.loads(payload)

    def _create_job(self) -> str:
        return self.services.job_service.create_job().job_id

    def _upload_cmdb(self, job_id: str) -> None:
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                [
                    "Application Code",
                    "Name",
                    "Portfolio",
                    "Business Criticality",
                    "Technology Stack",
                    "API or Webservices",
                    "Support Owner",
                ],
                [
                    ["APP-1", "Payments", "Finance", "High", "Windows Server 2008", "Unknown outbound API", "Finance Support"],
                    ["APP-1", "Payments Copy", "Finance", "High", "Python", None, None],
                    ["app-1", "Lower Case Code", "Finance", "Medium", "Java", None, None],
                    ["APP-2", "People", None, None, "Java", None, None],
                ],
            ),
        )

    def _upload_output_config(self, job_id: str) -> None:
        self.services.upload_config_service.upload_output_family_config(
            job_id,
            "families.xlsx",
            workbook_bytes(
                ["Family Key", "Output Family", "Application Code"],
                [
                    ["payments", "Payments", "APP-1"],
                    ["missing", "Missing Member", "DOES-NOT-EXIST"],
                    ["empty", "Empty Family", None],
                ],
            ),
        )

    def test_prerequisite_and_pre_run_summary_errors_are_clear(self) -> None:
        job_id = self._create_job()
        status, payload = self._json(
            "POST", f"/api/jobs/{job_id}/analysis/portfolio-insights"
        )
        self.assertEqual(status, 422)
        self.assertIn("parsed CMDB preview", payload["detail"])

        self._upload_cmdb(job_id)
        status, payload = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/summary"
        )
        self.assertEqual(status, 404)
        self.assertIn("has not been run", payload["detail"])

    def test_cmdb_only_supports_no_body_and_empty_json(self) -> None:
        for body in (None, {}):
            with self.subTest(body=body):
                job_id = self._create_job()
                self._upload_cmdb(job_id)
                status, result = self._json(
                    "POST",
                    f"/api/jobs/{job_id}/analysis/portfolio-insights",
                    body,
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["summary"]["total_applications"], 4)
                self.assertEqual(result["analysis_status"], "completed_with_warnings")
                self.assertTrue(
                    self.services.job_service.storage.exists(
                        f"jobs/{job_id}/results/portfolio_insights.json"
                    )
                )

                _, capped = self._json(
                    "GET",
                    f"/api/jobs/{job_id}/analysis/portfolio-insights/portfolio-scorecard?limit=999999",
                )
                self.assertEqual(capped["limit"], 500)

                status, stored = self._json(
                    "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/summary"
                )
                self.assertEqual(status, 200)
                self.assertEqual(stored["summary"], result["summary"])

                _, modules = self._json(
                    "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/module-status"
                )
                statuses = {item["module_name"]: item["status"] for item in modules["modules"]}
                self.assertEqual(statuses["cmdb_preview"], "available")
                self.assertTrue(
                    all(statuses[name] == "missing" for name in (
                        "validation", "dashboard", "similarity", "technology", "output_families"
                    ))
                )

    def test_scorecard_risks_actions_and_exact_application_lookup(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._json("POST", f"/api/jobs/{job_id}/analysis/validation")
        self._json("POST", f"/api/jobs/{job_id}/analysis/technology")
        self._json("POST", f"/api/jobs/{job_id}/analysis/similarity", {
            "similar_pair_threshold": 0,
            "possible_duplicate_threshold": 0,
        })
        self._upload_output_config(job_id)
        self._json("POST", f"/api/jobs/{job_id}/analysis/output-families")
        status, result = self._json(
            "POST", f"/api/jobs/{job_id}/analysis/portfolio-insights", {}
        )
        self.assertEqual(status, 200)

        _, modules = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/module-status"
        )
        statuses = {item["module_name"]: item["status"] for item in modules["modules"]}
        self.assertEqual(statuses["dashboard"], "missing")
        self.assertTrue(
            all(statuses[name] == "available" for name in (
                "cmdb_preview", "validation", "similarity", "technology", "output_families"
            ))
        )

        _, executive = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/executive-summary"
        )
        self.assertEqual(executive["job_id"], job_id)
        self.assertEqual(executive["executive_summary"]["total_applications"], 4)
        self.assertIsInstance(executive["executive_summary"]["key_findings"], list)

        _, scorecard = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/portfolio-scorecard"
        )
        portfolios = {item["portfolio"]: item for item in scorecard["portfolios"]}
        self.assertEqual(portfolios["Unassigned"]["application_count"], 1)

        _, register = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/risks?limit=500"
        )
        risk_types = {item["risk_type"] for item in register["risks"]}
        self.assertTrue({
            "duplicate_application_code",
            "obsolete_technology_indicator",
            "missing_portfolio",
            "missing_business_criticality",
            "output_family_unmapped_application",
        }.issubset(risk_types))
        self.assertEqual(
            [item["risk_id"] for item in register["risks"]],
            [f"RISK-{index:06d}" for index in range(1, len(register["risks"]) + 1)],
        )

        _, filtered = self._json(
            "GET",
            f"/api/jobs/{job_id}/analysis/portfolio-insights/risks?limit=500&include_low_severity=false",
        )
        self.assertTrue(all(item["severity"] != "low" for item in filtered["risks"]))
        self.assertLess(filtered["total_risk_count"], register["total_risk_count"])

        _, actions = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/action-items?limit=500"
        )
        risk_ids = {item["risk_id"] for item in register["risks"]}
        self.assertTrue(actions["action_items"])
        self.assertTrue(
            all(item["source_risk_id"] in risk_ids for item in actions["action_items"])
        )
        self.assertTrue(
            any(item["owner_hint"] == "Finance Support" for item in actions["action_items"])
        )

        status, insight = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/applications/app-1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(insight["application"]["application_name"], "Lower Case Code")
        status, payload = self._json(
            "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/applications/App-1"
        )
        self.assertEqual(status, 404)
        self.assertIn("Application Code 'App-1'", payload["detail"])

    def test_csv_exports_have_expected_columns(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._json("POST", f"/api/jobs/{job_id}/analysis/portfolio-insights")
        expected = {
            "risks.csv": [
                "risk_id", "risk_type", "severity", "application_code",
                "application_name", "portfolio", "evidence_module", "evidence",
                "recommended_action", "confidence",
            ],
            "action-items.csv": [
                "action_id", "priority", "action_type", "application_code",
                "application_name", "portfolio", "description", "source_risk_id",
                "owner_hint", "evidence_module",
            ],
            "portfolio-scorecard.csv": [
                "portfolio", "application_count", "completeness_percent",
                "critical_application_count", "high_business_criticality_count",
                "possible_duplicate_count", "obsolete_indicator_count",
                "explicit_integration_count", "unmapped_output_family_application_count",
                "risk_count", "highest_risk_severity", "warnings",
            ],
        }
        for suffix, columns in expected.items():
            with self.subTest(suffix=suffix):
                status, headers, payload = self._request(
                    "GET", f"/api/jobs/{job_id}/analysis/portfolio-insights/{suffix}"
                )
                self.assertEqual(status, 200)
                self.assertTrue(headers["content-type"].startswith("text/csv"))
                self.assertEqual(next(csv.reader(StringIO(payload.decode()))), columns)


if __name__ == "__main__":
    unittest.main()
