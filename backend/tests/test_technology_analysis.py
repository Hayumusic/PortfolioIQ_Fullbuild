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


class TechnologyAnalysisAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.app = create_app(
            Settings(local_storage_root=Path(self.temporary_directory.name))
        )
        self.runner = asyncio.Runner()
        self.lifespan = self.app.router.lifespan_context(self.app)
        self.runner.run(self.lifespan.__aenter__())
        self.services = self.app.state.services

    def tearDown(self) -> None:
        self.runner.run(self.lifespan.__aexit__(None, None, None))
        self.runner.close()
        self.temporary_directory.cleanup()

    def _request(
        self, method: str, url: str, json_body: dict[str, object] | None = None
    ) -> tuple[int, dict[str, str], bytes]:
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
        start = next(item for item in messages if item["type"] == "http.response.start")
        response_headers = {
            key.decode("latin1"): value.decode("latin1")
            for key, value in start.get("headers", [])
        }
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return int(start["status"]), response_headers, response_body

    def _json_request(
        self, method: str, url: str, json_body: dict[str, object] | None = None
    ) -> tuple[int, dict[str, object]]:
        status, _, body = self._request(method, url, json_body)
        return status, json.loads(body)

    def _create_job(self) -> str:
        return self.services.job_service.create_job().job_id

    def _upload(self, job_id: str, rows: list[list[object]]) -> None:
        headers = [
            "Application Code",
            "Name",
            "Portfolio",
            "Business criticality",
            "Technology stack",
            "Application Technology",
            "Platform",
            "Hosting Provider",
            "Hosting type",
            "API or Webservices",
            "Description",
            "Database Technology",
            "AKA",
        ]
        self.services.cmdb_service.upload(
            job_id, "inventory.xlsx", workbook_bytes(headers, rows)
        )

    def test_post_requires_preview_and_summary_exports_require_analysis(self) -> None:
        job_id = self._create_job()
        status, payload = self._json_request(
            "POST", f"/api/jobs/{job_id}/analysis/technology"
        )
        self.assertEqual(status, 422)
        self.assertIn("parsed CMDB preview", payload["detail"])

        self._upload(job_id, [["APP-1", "One", "P", "High", "Python", None, None, None, None, None, None]])
        for suffix in ("summary", "clusters.csv", "integrations.csv"):
            status, _, body = self._request(
                "GET", f"/api/jobs/{job_id}/analysis/technology/{suffix}"
            )
            self.assertEqual(status, 404)
            self.assertIn(b"has not been run", body)

    def test_post_without_body_and_empty_json_store_summary(self) -> None:
        for body in (None, {}):
            with self.subTest(body=body):
                job_id = self._create_job()
                self._upload(job_id, [["APP-1", "One", "P", "High", "Python", "Django", "Linux", "AWS", "Cloud", None, None]])
                status, result = self._json_request(
                    "POST", f"/api/jobs/{job_id}/analysis/technology", body
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["module_name"], "technology")
                self.assertEqual(result["summary"]["total_applications_analyzed"], 1)
                status, stored = self._json_request(
                    "GET", f"/api/jobs/{job_id}/analysis/technology/summary"
                )
                self.assertEqual(status, 200)
                self.assertEqual(stored["summary"], result["summary"])
                self.assertTrue(
                    self.services.job_service.storage.exists(
                        f"jobs/{job_id}/results/technology.json"
                    )
                )

    def test_clusters_filter_placeholders_and_keep_meaningful_fields(self) -> None:
        job_id = self._create_job()
        self._upload(
            job_id,
            [
                ["APP-1", "One", "Finance", "High", "Python, not available; SQL", "Django", "Linux", "AWS", "Cloud", None, None],
                ["APP-2", "Two", "People", "Medium", "unknown", "yes", "Windows", "Azure", "On Premise", None, None],
            ],
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology", {})
        status, payload = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/clusters?limit=50"
        )
        self.assertEqual(status, 200)
        labels = {item["label"].casefold() for item in payload["clusters"]}
        self.assertTrue({"python", "sql", "django", "linux", "aws", "cloud", "windows", "azure", "on premise"}.issubset(labels))
        self.assertTrue(labels.isdisjoint({"not available", "unknown", "yes"}))

        status, capped = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/clusters?limit=999999"
        )
        self.assertEqual(status, 200)
        self.assertEqual(capped["limit"], 500)

    def test_cluster_aggregates_filter_by_portfolio_and_report_deterministic_risk(self) -> None:
        job_id = self._create_job()
        self._upload(
            job_id,
            [
                ["FIN-1", "Legacy Finance", "Finance", "High", "Classic ASP", None, None, None, None, None, None],
                ["FIN-2", "Modern Finance", "Finance", "Medium", "Python", None, None, None, None, None, None],
                ["HR-1", "Legacy HR", "HR", "High", "Classic ASP", None, None, None, None, None, None],
            ],
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")

        status, finance = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/clusters?portfolio=Finance&limit=500",
        )
        self.assertEqual(status, 200)
        self.assertEqual(finance["portfolio"], "Finance")
        self.assertEqual(finance["scope_application_count"], 2)
        self.assertTrue(
            all(
                application["portfolio"] == "Finance"
                for cluster in finance["clusters"]
                for application in cluster["applications"]
            )
        )
        classic_asp = next(
            item for item in finance["clusters"] if item["label"] == "Classic ASP"
        )
        self.assertEqual(classic_asp["application_count"], 1)
        self.assertEqual(classic_asp["risky_application_count"], 1)
        self.assertEqual(classic_asp["lifecycle_status"], "Potential legacy technology concern")
        self.assertTrue(classic_asp["shortcomings"])
        self.assertEqual(classic_asp["concern_evidence"][0]["source_field"], "Technology stack")
        python = next(item for item in finance["clusters"] if item["label"] == "Python")
        self.assertEqual(python["risky_application_count"], 0)
        self.assertEqual(python["lifecycle_status"], "Not Available")
        self.assertEqual(python["shortcomings"], [])

        _, all_portfolios = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/clusters?limit=500"
        )
        self.assertEqual(all_portfolios["scope_application_count"], 3)
        classic_asp = next(
            item for item in all_portfolios["clusters"] if item["label"] == "Classic ASP"
        )
        self.assertEqual(classic_asp["application_count"], 2)
        self.assertEqual(classic_asp["risky_application_count"], 2)

    def test_options_include_every_cmdb_application_for_selector(self) -> None:
        job_id = self._create_job()
        self._upload(
            job_id,
            [
                ["FIN-1", "Finance One", "Finance", "High", "Python", None, None, None, None, None, None],
                ["HR-1", "People One", "HR", "Medium", "Java", None, None, None, None, None, None],
                ["OPS-1", "Operations One", "Operations", "Low", None, None, None, None, None, None, None],
            ],
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        status, options = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/options"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            {item["application_code"] for item in options["applications"]},
            {"FIN-1", "HR-1", "OPS-1"},
        )
        self.assertEqual(options["portfolios"], ["Finance", "HR", "Operations"])

    def test_shared_technology_never_creates_integrations(self) -> None:
        job_id = self._create_job()
        shared = [
            ["APP-1", "One", "Finance", "High", "Python", None, "Linux", "AWS", "Cloud", None, None],
            ["APP-2", "Two", "Finance", "High", "Python", None, "Linux", "AWS", "Cloud", None, None],
        ]
        self._upload(job_id, shared)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        status, payload = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/integrations"
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["integration_data_available"])
        self.assertEqual(payload["integrations"], [])
        self.assertIn(
            "No explicit integration relationships were found in the uploaded CMDB.",
            payload["warnings"],
        )

    def test_explicit_integrations_build_application_and_portfolio_maps(self) -> None:
        job_id = self._create_job()
        self._upload(
            job_id,
            [
                ["APP-1", "Payments", "Finance", "High", "Python", None, "Linux", "AWS", "Cloud", "REST API to APP-2", None],
                ["APP-2", "Ledger", "Core", "High", "Java", None, "Linux", "Azure", "Cloud", None, "Receives feed from Payments integration"],
                ["APP-3", "People", "HR", "Medium", "C#", None, "Windows", None, "On Premise", "SOAP webservice exposed", None],
            ],
        )
        _, result = self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        self.assertTrue(result["summary"]["explicit_integration_data_available"])

        _, integrations = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/integrations"
        )
        identified = [item for item in integrations["integrations"] if item["target_application_code"] == "APP-2"]
        self.assertTrue(identified)
        self.assertEqual(identified[0]["confidence"], "high")
        self.assertTrue(any(item["confidence"] == "low" and item["target_application_code"] is None for item in integrations["integrations"]))

        _, application_map = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/application-map"
        )
        self.assertTrue(application_map["nodes"])
        self.assertTrue(application_map["edges"])
        self.assertIn("evidence", application_map["edges"][0])

        _, portfolio_map = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/portfolio-map"
        )
        self.assertEqual({node["portfolio"] for node in portfolio_map["nodes"]}, {"Finance", "Core", "HR"})
        self.assertTrue(any(edge["source_portfolio"] == "Finance" and edge["target_portfolio"] == "Core" for edge in portfolio_map["edges"]))

        _, finance_scope = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=APP-1&portfolio=Finance&page_size=25",
        )
        self.assertEqual(finance_scope["total_integration_count"], 1)
        _, core_scope = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=APP-1&portfolio=Core&page_size=25",
        )
        self.assertEqual(core_scope["total_integration_count"], 1)

    def test_obsolete_patterns_are_conservative(self) -> None:
        job_id = self._create_job()
        self._upload(
            job_id,
            [
                ["APP-1", "Legacy", "Finance", "High", "VB6", "Classic ASP", "Windows Server 2003", None, "On Premise", None, None],
                ["APP-2", "Modern", "Core", "High", "Python 3", "React", "Linux", "AWS", "Cloud", None, None],
            ],
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        _, payload = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/obsolete"
        )
        self.assertGreaterEqual(payload["obsolete_indicator_count"], 3)
        self.assertTrue(all(item["application_code"] == "APP-1" for item in payload["indicators"]))
        self.assertTrue(all("Potential legacy technology concern" in item["reason"] for item in payload["indicators"]))
        self.assertTrue(all("Review recommended" in item["reason"] for item in payload["indicators"]))

    def test_age_alerts_prioritize_application_evidence_and_respect_later_updates(self) -> None:
        job_id = self._create_job()
        headers = [
            "Application Code", "Name", "Portfolio", "Technology stack",
            "Application Age", "Go Live Date", "Last Updated Date",
            "Technology Age", "Technology Updated Date",
        ]
        rows = [
            ["APP-AGE", "Old Application", "Core", "Python", "15 years", None, None, "30 years", None],
            ["UPDATED", "Updated Application", "Core", "Java", None, "2000-01-01", "2022-01-01", None, None],
            ["TECH-UPDATED", "Updated Technology", "Core", "Go", None, None, None, "20 years", "2020-01-01"],
            ["TECH-OLD", "Old Technology", "Core", "Perl", None, None, None, "20 years", None],
            ["APP-NEW", "New Application", "Core", "Ruby", "5 years", None, None, "20 years", None],
        ]
        self.services.cmdb_service.upload(
            job_id, "ages.xlsx", workbook_bytes(headers, rows)
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        _, payload = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/obsolete?page_size=all"
        )
        by_code = {item["application_code"]: item for item in payload["indicators"]}
        self.assertEqual(set(by_code), {"APP-AGE", "TECH-OLD"})
        self.assertEqual(by_code["APP-AGE"]["field"], "Application Age")
        self.assertEqual(by_code["APP-AGE"]["indicator"], "application age")
        self.assertEqual(by_code["TECH-OLD"]["field"], "Technology Age")
        self.assertIn("Review recommended", by_code["TECH-OLD"]["reason"])

    def test_explicit_technology_version_is_lifecycle_evidence(self) -> None:
        job_id = self._create_job()
        self.services.cmdb_service.upload(
            job_id,
            "version.xlsx",
            workbook_bytes(
                ["Application Code", "Name", "Technology stack", "Technology Version"],
                [["VERSIONED", "Versioned App", "Microsoft", "VB6"]],
            ),
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        _, payload = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/obsolete?page_size=all"
        )
        self.assertEqual(payload["obsolete_indicator_count"], 1)
        self.assertEqual(payload["indicators"][0]["field"], "Technology Version")
        self.assertEqual(payload["indicators"][0]["value"], "VB6")

    def test_csv_exports_have_expected_columns(self) -> None:
        job_id = self._create_job()
        self._upload(job_id, [["APP-1", "One", "P", "High", "Python", None, "Linux", "AWS", "Cloud", "REST API endpoint", None]])
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")

        status, headers, clusters = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/clusters.csv"
        )
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/csv"))
        self.assertEqual(
            clusters.decode().splitlines()[0],
            "cluster_key,label,technology_type,application_count,application_codes,application_names",
        )

        status, headers, integrations = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/integrations.csv"
        )
        self.assertEqual(status, 200)
        self.assertTrue(headers["content-type"].startswith("text/csv"))
        self.assertEqual(
            integrations.decode().splitlines()[0],
            "source_application_code,source_application_name,target_application_code,target_application_name,integration_type,evidence_field,evidence_value,confidence,warning",
        )

    def test_missing_application_code_is_null_not_application_name(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Name", "Technology stack"], [["Named Application", "Python"]]
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        _, clusters = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/clusters"
        )
        self.assertIsNone(clusters["clusters"][0]["applications"][0]["application_code"])

    def test_analysis_storage_is_not_truncated_by_legacy_request_limits(self) -> None:
        job_id = self._create_job()
        rows = []
        for index in range(125):
            rows.append(
                [
                    f"APP-{index:03d}",
                    f"Application {index:03d}",
                    "Portfolio A",
                    "High",
                    f"Technology {index:03d}",
                    None,
                    None,
                    None,
                    None,
                    f"REST API endpoint {index}",
                    None,
                ]
            )
        self._upload(job_id, rows)
        _, result = self._json_request(
            "POST",
            f"/api/jobs/{job_id}/analysis/technology",
            {"cluster_limit": 1, "integration_limit": 1},
        )
        self.assertEqual(result["summary"]["technology_cluster_count"], 125)
        self.assertEqual(result["summary"]["integration_count"], 125)
        stored = self.services.job_service.storage.load_json(
            f"jobs/{job_id}/results/technology.json"
        )
        self.assertEqual(len(stored["technology_clusters"]), 125)
        self.assertEqual(len(stored["integrations"]), 125)
        self.assertFalse(any("limited to" in warning for warning in result["warnings"]))

    def test_landscape_dimension_portfolio_search_and_paging(self) -> None:
        job_id = self._create_job()
        rows = [
            [f"FIN-{index:03d}", f"Finance App {index:03d}", "Finance", "High", "Python", None, None, "AWS", "Cloud", None, None]
            for index in range(55)
        ]
        rows += [
            ["HR-001", "People Hub", "HR", "Medium", "Java", None, None, "Azure", "On Premise", None, None],
            ["BLANK-1", "Blank Technology", "Finance", "Low", "unknown", None, None, None, None, None, None],
        ]
        self._upload(job_id, rows)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")

        status, options = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/options"
        )
        self.assertEqual(status, 200)
        self.assertIn("technology_stack", {item["key"] for item in options["dimensions"]})
        self.assertEqual(options["portfolios"], ["Finance", "HR"])

        status, landscape = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/landscape?dimension=technology_stack&portfolio=Finance&search=FIN-&technology_value=Python&page=2&page_size=25",
        )
        self.assertEqual(status, 200)
        self.assertEqual(landscape["groupings"], [{"label": "Python", "application_count": 55}])
        self.assertEqual(landscape["total_application_count"], 55)
        self.assertEqual(len(landscape["applications"]), 25)
        self.assertEqual(landscape["applications"][0]["application_code"], "FIN-025")
        self.assertTrue(all(item["portfolio"] == "Finance" for item in landscape["applications"]))

        _, searched = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/landscape?dimension=technology_stack&search=Finance%20App%20003&technology_value=Python&page_size=200",
        )
        self.assertEqual(searched["total_application_count"], 1)
        self.assertNotIn("unknown", {item["label"].casefold() for item in searched["groupings"]})

    def test_integration_neighborhood_directions_filters_unknowns_and_limits(self) -> None:
        job_id = self._create_job()
        rows = [
            ["HUB", "Hub", "Core", "High", "Java", None, None, None, None, "REST API to OUT", None],
            ["OUT", "Outbound", "Finance", "Medium", "Python", None, None, None, None, None, None],
            ["IN", "Inbound", "HR", "Medium", "C#", None, None, None, None, "SOAP webservice to HUB", None],
            ["UNKNOWN", "Unknown Target Source", "Core", "Low", "Go", None, None, None, None, "API integration endpoint", None],
        ]
        rows.extend(
            [f"SRC-{index:03d}", f"Source {index:03d}", "Finance", "Low", "Go", None, None, None, None, "REST API to HUB", None]
            for index in range(205)
        )
        self._upload(job_id, rows)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")

        for size in (25, 50, 100, 200):
            with self.subTest(size=size):
                status, payload = self._json_request(
                    "GET",
                    f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=HUB&page_size={size}",
                )
                self.assertEqual(status, 200)
                self.assertEqual(len(payload["integrations"]), min(size, 207))
                self.assertEqual(payload["total_integration_count"], 207)
                self.assertTrue(payload["graph_truncated"])
        directions = {item["direction"] for item in payload["integrations"]}
        self.assertIn("incoming", directions)

        _, outgoing = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=HUB&confidence=high&page_size=25",
        )
        self.assertTrue(any(item["direction"] == "outgoing" for item in outgoing["integrations"]))
        self.assertTrue(all(item["confidence"] == "high" for item in outgoing["integrations"]))

        _, filtered = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=HUB&portfolio=HR&integration_type=webservice&page_size=25",
        )
        self.assertEqual(filtered["total_integration_count"], 1)
        self.assertEqual(filtered["integrations"][0]["source_application_code"], "IN")

        _, unknown = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=UNKNOWN&page_size=25",
        )
        self.assertEqual(unknown["total_integration_count"], 1)
        self.assertIsNone(unknown["integrations"][0]["target_application_code"])
        self.assertIn("target application could not be identified", unknown["integrations"][0]["warning"])
        self.assertEqual(unknown["edges"], [])

    def test_obsolete_filters_search_and_all_supported_limits(self) -> None:
        job_id = self._create_job()
        rows = [
            [f"LEG-{index:03d}", f"Legacy App {index:03d}", "Legacy", "High", "Classic ASP", None, None, None, None, None, None]
            for index in range(205)
        ]
        rows.append(["NEW-1", "Modern", "Modern", "High", "Python", None, None, None, None, None, None])
        self._upload(job_id, rows)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        for size in (25, 50, 100, 200):
            with self.subTest(size=size):
                _, payload = self._json_request(
                    "GET",
                    f"/api/jobs/{job_id}/analysis/technology/obsolete?portfolio=Legacy&indicator=classic%20asp&page_size={size}",
                )
                self.assertEqual(payload["obsolete_indicator_count"], 205)
                self.assertEqual(len(payload["indicators"]), size)
                self.assertTrue(all(item["portfolio"] == "Legacy" for item in payload["indicators"]))
        _, searched = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/obsolete?search=LEG-204&page_size=25",
        )
        self.assertEqual(searched["obsolete_indicator_count"], 1)
        self.assertIn("Potential legacy technology concern", searched["indicators"][0]["reason"])

    def test_results_are_isolated_to_current_session_and_latest_upload(self) -> None:
        first_job = self._create_job()
        second_job = self._create_job()
        self._upload(first_job, [["FIRST", "First Only", "P1", "High", "Python", None, None, None, None, None, None]])
        self._upload(second_job, [["SECOND", "Second Only", "P2", "High", "Java", None, None, None, None, None, None]])
        self._json_request("POST", f"/api/jobs/{first_job}/analysis/technology")
        self._json_request("POST", f"/api/jobs/{second_job}/analysis/technology")
        _, first = self._json_request("GET", f"/api/jobs/{first_job}/analysis/technology/options")
        _, second = self._json_request("GET", f"/api/jobs/{second_job}/analysis/technology/options")
        self.assertEqual([item["application_code"] for item in first["applications"]], ["FIRST"])
        self.assertEqual([item["application_code"] for item in second["applications"]], ["SECOND"])

        self._upload(first_job, [["LATEST", "Latest Only", "P3", "High", "Go", None, None, None, None, None, None]])
        status, _ = self._json_request("GET", f"/api/jobs/{first_job}/analysis/technology/options")
        self.assertEqual(status, 404)

    def test_inventory_contains_every_application_including_blank_technology(self) -> None:
        job_id = self._create_job()
        rows = [
            ["APP-1", "Complete", "Finance", "High", "Java", None, None, "AWS", "Cloud", None, None, "Oracle"],
            ["APP-2", "Blank Technology", "Finance", "Low", None, None, None, None, None, None, None, None],
        ]
        self._upload(job_id, rows)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        status, inventory = self._json_request(
            "GET", f"/api/jobs/{job_id}/analysis/technology/inventory?page_size=all"
        )
        self.assertEqual(status, 200)
        self.assertEqual(inventory["total_application_count"], 2)
        self.assertEqual(inventory["filtered_application_count"], 2)
        self.assertEqual(len(inventory["applications"]), 2)
        blank = next(item for item in inventory["applications"] if item["application_code"] == "APP-2")
        self.assertIsNone(blank["technology_stack"])
        self.assertIsNone(blank["hosting_type"])

    def test_aliases_inbound_outbound_multiple_targets_and_direction(self) -> None:
        job_id = self._create_job()
        self._upload(
            job_id,
            [
                ["GTA-CODE", "Global Tables (GTA)", "Data", "High", "SQL Server", None, None, None, None, None, None, None, "Global Table App"],
                ["A", "Application A", "Finance", "High", "Java", None, None, None, None, None, "Receives data from Global Tables"],
                ["B", "Application B", "Finance", "Medium", "Python", None, None, None, None, None, "receives data from GTA"],
                ["R2-CODE", "R2", "Core", "High", None, None, None, None, None, None, None],
                ["TRACS", "TRACS EU", "Core", "High", None, None, None, None, None, None, None],
                ["ALT-A", "ALT-A", "Ops", "High", None, None, None, None, None, None, "ALT-A takes source data from R2, Global Tables and TRACS EU"],
                ["SEND", "Sender", "Ops", "Medium", None, None, None, None, None, None, "Sender sends data to GTA"],
                ["GEN", "Generic", "Ops", "Low", None, None, None, None, None, None, "Generic integrates with GTA"],
            ],
        )
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        _, gta = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=GTA-CODE&page_size=all",
        )
        related_codes = {
            code
            for item in gta["integrations"]
            for code in (item["source_application_code"], item["target_application_code"])
            if code != "GTA-CODE"
        }
        self.assertTrue({"A", "B", "ALT-A", "SEND", "GEN"}.issubset(related_codes))
        receives = next(item for item in gta["integrations"] if item["target_application_code"] == "A")
        self.assertEqual(receives["source_application_code"], "GTA-CODE")
        self.assertEqual(receives["direction"], "outgoing")
        sends = next(item for item in gta["integrations"] if item["source_application_code"] == "SEND")
        self.assertEqual(sends["target_application_code"], "GTA-CODE")
        self.assertEqual(sends["direction"], "incoming")
        generic = next(item for item in gta["integrations"] if item["source_application_code"] == "GEN")
        self.assertEqual(generic["direction"], "unknown")
        _, alt = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=ALT-A&page_size=all",
        )
        self.assertEqual(
            {item["source_application_code"] for item in alt["integrations"]},
            {"GTA-CODE", "R2-CODE", "TRACS"},
        )

    def test_full_results_all_portfolio_dependencies_and_hubs(self) -> None:
        job_id = self._create_job()
        rows = [["HUB", "Hub", "Core", "High", "Java", None, None, None, None, None, None]]
        rows.extend(
            [f"S-{index:03d}", f"Source {index}", "Finance", "Low", "Python", None, None, None, None, None, "Sends data to HUB"]
            for index in range(125)
        )
        self._upload(job_id, rows)
        self._json_request("POST", f"/api/jobs/{job_id}/analysis/technology")
        _, payload = self._json_request(
            "GET",
            f"/api/jobs/{job_id}/analysis/technology/integration-neighborhood?application_code=HUB&page_size=all",
        )
        self.assertEqual(payload["total_integration_count"], 125)
        self.assertEqual(len(payload["integrations"]), 125)
        dependency = next(
            item for item in payload["portfolio_dependencies"]
            if item["source_portfolio"] == "Finance" and item["target_portfolio"] == "Core"
        )
        self.assertEqual(dependency["integration_count"], 125)
        hub = next(item for item in payload["integration_hubs"] if item["application_code"] == "HUB")
        self.assertEqual(hub["total_connections"], 125)
        self.assertEqual(hub["incoming_connections"], 125)


if __name__ == "__main__":
    unittest.main()
