import asyncio
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from openpyxl import Workbook

from app.core.config import Settings
from app.main import create_app
from app.services.cmdb_similarity_service import CMDBSimilarityService


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


class SimilarityAPITests(unittest.TestCase):
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

    def _raw_request(self, method: str, url: str) -> tuple[int, dict[str, str], bytes]:
        parsed_url = urlsplit(url)
        messages: list[dict[str, object]] = []
        request_sent = False

        async def receive() -> dict[str, object]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": b"", "more_body": False}
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
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        self.runner.run(self.app(scope, receive, send))
        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        headers = {
            key.decode("latin-1"): value.decode("latin-1")
            for key, value in start.get("headers", [])
        }
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return int(start["status"]), headers, body

    def _upload_cmdb(self, job_id: str) -> None:
        source = workbook_bytes(
            [
                "Application Code",
                "Application Name",
                "Description",
                "Portfolio",
                "Technology Stack",
                "Hosting Provider",
                "Department",
                "App Classification",
            ],
            [
                ["APP-1", "Payments Portal", "Customer payment portal", "Finance", "Python, SQL", "AWS", "Finance", "Web"],
                ["APP-2", "Payment Portal", "Portal for customer payments", "Finance", "Python, SQL", "AWS", "Finance", "Web"],
                ["APP-3", "HR Records", "Employee record management", "People", "Java", "Azure", "HR", "Service"],
                ["APP-4", "Travel Booking", "Corporate travel reservations", "Operations", "C#", "Azure", "Travel", "Web"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

    def test_post_requires_parsed_cmdb_preview(self) -> None:
        job_id = self._create_job()

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/similarity"
        )

        self.assertEqual(status_code, 422)
        self.assertIn("parsed CMDB upload", payload["detail"])

    def test_post_accepts_no_body_and_warns_when_validation_has_not_run(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/similarity"
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["summary"]["total_applications_analyzed"], 4)
        self.assertGreater(payload["summary"]["analysis_elapsed_seconds"], 0)
        self.assertTrue(any("validation has not been run" in warning for warning in payload["warnings"]))

    def test_heatmap_uses_strongest_non_self_score_and_deterministic_ties(self) -> None:
        job_id = self._create_job()
        self.services.cmdb_service.upload(
            job_id,
            "ranking.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Capability"],
                [
                    ["Z-1", "Zeta", "alpha beta"],
                    ["A-1", "Alpha", "alpha beta"],
                    ["B-1", "Bravo", "alpha"],
                    ["C-1", "Charlie", "gamma"],
                ],
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"selected_fields": ["Capability"], "field_weights": {"Capability": 1}},
        )

        _, heatmap = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25"
        )

        ranked = heatmap["anchor_applications"]
        self.assertEqual(
            [item["application_code"] for item in ranked],
            ["A-1", "Z-1", "B-1", "C-1"],
        )
        self.assertEqual(ranked[0]["strongest_similarity_score"], 100)
        self.assertEqual(ranked[1]["strongest_similarity_score"], 100)
        self.assertEqual(ranked[-1]["strongest_similarity_score"], 0)
        self.assertNotEqual(ranked[-1]["strongest_similarity_score"], 100)

    def test_missing_dimensions_are_not_comparable_and_weights_renormalize(self) -> None:
        job_id = self._create_job()
        headers = [
            "Application Code",
            "Application Name",
            "Business Use Case",
            "Business Function",
            "Capability",
            "Supported Process",
        ]
        self.services.cmdb_service.upload(
            job_id,
            "dimensions.xlsx",
            workbook_bytes(
                headers,
                [
                    ["APP-1", "Complete", "Licensing", "Rights Management", "Copyright", "Publication"],
                    ["APP-2", "Function Only", None, "Rights Management", None, None],
                    ["APP-3", "Capability Only", None, None, "Copyright", None],
                ],
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": headers[2:],
                "field_weights": {field: 1 for field in headers[2:]},
                "similar_pair_threshold": 0,
            },
        )
        _, apps = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/apps?application_key=app-0&limit=5",
        )
        by_code = {
            item["application_code"]: item
            for item in apps["applications"][0]["similar_applications"]
        }
        function_only = by_code["APP-2"]
        self.assertEqual(function_only["similarity_score"], 100)
        self.assertIn("Business Function", function_only["similarity_reason"])
        self.assertIn("shared terms: management, rights", function_only["similarity_reason"])
        _, excluded = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/apps?application_key=app-0&limit=5&excluded_application_keys=app-1",
        )
        self.assertNotIn(
            "APP-2",
            [item["application_code"] for item in excluded["applications"][0]["similar_applications"]],
        )
        for field in ("Business Use Case", "Capability", "Supported Process"):
            self.assertIsNone(function_only["component_scores"][field])
            self.assertFalse(function_only["component_details"][field]["comparable"])
            self.assertIn("missing", function_only["component_details"][field]["reason"])
        capability_only = by_code["APP-3"]
        self.assertIsNone(capability_only["component_scores"]["Business Function"])
        self.assertEqual(capability_only["component_scores"]["Capability"], 100)

    def test_clusters_include_common_function_and_analysis_evidence(self) -> None:
        job_id = self._create_job()
        self.services.cmdb_service.upload(
            job_id,
            "clusters.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Business Function", "Capability", "Supported Process"],
                [
                    ["APP-1", "Rights One", "Rights Management", "Copyright", "Licensing"],
                    ["APP-2", "Rights Two", "Rights Management", "Copyright", "Licensing"],
                ],
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Business Function", "Capability", "Supported Process"],
                "field_weights": {"Business Function": 1, "Capability": 1, "Supported Process": 1},
            },
        )
        _, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/clusters"
        )
        cluster = payload["clusters"][0]
        self.assertEqual(cluster["common_cluster_function"], "Rights Management")
        self.assertIn("Business Function: Rights Management", cluster["evidence_used_for_analysis"])
        self.assertIn("Capability: Copyright", cluster["evidence_used_for_analysis"])
        self.assertIn("all 2 applications share", cluster["cluster_reason"])

    def test_post_accepts_empty_json_and_similar_apps_finds_close_match(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST", f"/api/jobs/{job_id}/analysis/similarity", {}
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["analysis_status"], "completed_with_warnings")
        _, apps = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/apps?application_key=app-0&limit=5",
        )
        pair = apps["applications"][0]["similar_applications"][0]
        self.assertEqual(
            pair["application_code"],
            "APP-2",
        )
        self.assertGreater(pair["similarity_score"], 0)
        self.assertTrue(any("Application Name" in item for item in pair["evidence"]))

    def test_post_rejects_configured_fields_not_in_current_cmdb(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": [
                    "Application Name",
                    "Technology Stack",
                    "Unsupported Field",
                ],
                "field_weights": {
                    "Application Name": 70,
                    "Technology Stack": 30,
                    "Portfolio": 0,
                    "Description": "heavy",
                },
            },
        )

        self.assertEqual(status_code, 422)
        self.assertIn("not available in the current CMDB", payload["detail"])

    def test_invalid_selected_weight_is_rejected(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Application Name", "Description"],
                "field_weights": {"Application Name": -5, "Description": "invalid"},
            },
        )

        self.assertEqual(status_code, 422)
        self.assertIn("must be a non-negative number", payload["detail"])

    def test_post_scores_current_cmdb_columns_and_keeps_cluster_rule_internal(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            [
                "Application Code",
                "Application Name",
                "Business Use Case",
                "Supported Process",
            ],
            [
                ["APP-1", "Payments One", "Customer payment processing", "Billing"],
                ["APP-2", "Payments Two", "Customer payments processing", "Claims"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        status_code, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Business Use Case", "Supported Process"],
                "field_weights": {
                    "Business Use Case": 90,
                    "Supported Process": 10,
                },
                "cluster_threshold": 72,
                "similar_pair_threshold": 0,
            },
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(
            payload["selected_fields_used"],
            ["Business Use Case", "Supported Process"],
        )
        self.assertEqual(
            payload["field_weights_used"],
            {"Business Use Case": 90.0, "Supported Process": 10.0},
        )
        self.assertEqual(payload["top_similar_pairs"][0]["similarity_score"], 45.0)
        self.assertEqual(payload["rules_config"]["cluster_threshold"], 60.0)

        rules_status, rules_payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/rules"
        )
        self.assertEqual(rules_status, 200)
        self.assertEqual(rules_payload["rules_config"]["cluster_threshold"], 60.0)

    def test_pairs_do_not_include_self_or_repeat_reverse_order(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        ordered_pairs = [
            (pair["application_code_a"], pair["application_code_b"])
            for pair in payload["top_similar_pairs"]
        ]
        self.assertTrue(all(left != right for left, right in ordered_pairs))
        unordered_pairs = {frozenset(pair) for pair in ordered_pairs}
        self.assertEqual(len(ordered_pairs), len(unordered_pairs))

    def test_rows_with_the_same_application_code_are_not_compared(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name"],
            [["APP-1", "Payment Portal"], ["app-1", "Payments Portal"]],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        self.assertEqual(payload["summary"]["total_candidate_pairs_evaluated"], 0)
        self.assertEqual(payload["top_similar_pairs"], [])

    def test_generic_tokens_do_not_create_technology_overlap_evidence(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name", "Technology Stack", "Application Technology"],
            [
                ["APP-1", "Payments One", "not available", "Python, to be provided"],
                ["APP-2", "Payments Two", "available, not", "Python, not provided"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        pair = payload["top_similar_pairs"][0]
        self.assertFalse(
            any(
                item.startswith("Technology stack overlap")
                for item in pair["evidence"]
            )
        )
        self.assertNotIn("Technology stack", pair["matched_fields"])
        self.assertTrue(
            any("Application Technology" in item and "match" in item for item in pair["evidence"])
        )
        self.assertIn("Application Technology", pair["matched_fields"])
        self.assertFalse(
            any(
                generic in " ".join(pair["evidence"]).casefold()
                for generic in ("not", "available", "provided")
            )
        )

    def test_placeholder_exact_fields_are_missing_but_valid_matches_remain(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            [
                "Application Code",
                "Application Name",
                "Platform",
                "Hosting Type",
                "Hosting Provider",
                "Portfolio",
                "Department",
                "App Classification",
                "Technology Stack",
                "Application Technology",
                "Description",
            ],
            [
                [
                    "APP-1",
                    "Reporting One",
                    "Not provided",
                    "Unavailable",
                    "GCP",
                    "Unknown",
                    "TBD",
                    "Data Application",
                    "Not available",
                    "yes",
                    "To be provided",
                ],
                [
                    "APP-2",
                    "Reporting Two",
                    "Not provided",
                    "Unavailable",
                    "GCP",
                    "Unknown",
                    "TBD",
                    "Data Application",
                    "Not available",
                    "yes",
                    "To be provided",
                ],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        pair = payload["top_similar_pairs"][0]
        self.assertNotIn("Same platform", pair["evidence"])
        self.assertNotIn("Same hosting type", pair["evidence"])
        self.assertNotIn("Technology stack", pair["matched_fields"])
        self.assertNotIn("Application Technology", pair["matched_fields"])
        self.assertNotIn("Description similarity", pair["matched_fields"])
        self.assertTrue(any("Platform / Hosting" in item for item in pair["evidence"]))
        self.assertTrue(any("App Classification" in item for item in pair["evidence"]))
        self.assertIn("Platform / Hosting", pair["matched_fields"])
        self.assertIn("App Classification", pair["matched_fields"])
        for field in (
            "Portfolio",
            "Department",
            "Technology Stack",
            "Application Technology",
            "Description",
        ):
            self.assertIn(field, pair["missing_fields"])

        status_code, comparison = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/compare?application_code_a=APP-1&application_code_b=APP-2",
        )
        self.assertEqual(status_code, 200)
        self.assertNotIn("Same platform", comparison["evidence"])
        self.assertIn("Description", comparison["missing_fields"])

    def test_placeholder_only_description_and_technology_overlap_is_missing(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            [
                "Application Code",
                "Application Name",
                "Technology Stack",
                "Application Technology",
                "Description",
            ],
            [
                ["APP-1", "Records One", "unavailable", "none", "blank"],
                ["APP-2", "Records Two", "unavailable", "none", "blank"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        pair = payload["top_similar_pairs"][0]
        self.assertFalse(any("Technology" in item for item in pair["evidence"]))
        self.assertTrue(
            {
                "Technology Stack",
                "Application Technology",
                "Description",
            }.issubset(pair["missing_fields"])
        )

    def test_missing_application_codes_are_empty_and_self_like_rows_are_omitted(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name", "Description"],
            [
                [None, "Test Solution", "First record"],
                [None, "Test Solution", "Second record"],
                [None, "Related Solution", "Third record"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        pairs = payload["top_similar_pairs"]
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["application_code_a"], "")
        self.assertEqual(pairs[0]["application_code_b"], "")
        self.assertNotEqual(
            pairs[0]["application_code_a"], pairs[0]["application_name_a"]
        )
        self.assertFalse(
            any(
                pair["application_name_a"] == pair["application_name_b"]
                for pair in pairs
            )
        )

    def test_distinct_application_codes_allow_the_same_application_name(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name"],
            [["APP-1", "Test Solution"], ["APP-2", "Test Solution"]],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)

        _, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        self.assertEqual(len(payload["top_similar_pairs"]), 1)
        self.assertEqual(
            {
                payload["top_similar_pairs"][0]["application_code_a"],
                payload["top_similar_pairs"][0]["application_code_b"],
            },
            {"APP-1", "APP-2"},
        )

    def test_summary_is_compact_and_pairs_are_paginated_with_cap(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        status_code, summary = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/summary"
        )
        self.assertEqual(status_code, 200)
        self.assertNotIn("top_similar_pairs", summary)
        self.assertNotIn("similar_apps_by_application", summary)

        status_code, pairs = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/pairs?page=2&page_size=2"
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(pairs["page"], 2)
        self.assertEqual(pairs["page_size"], 2)
        self.assertEqual(len(pairs["records"]), 2)
        self.assertEqual(
            self._request(
                "GET", f"/api/jobs/{job_id}/analysis/similarity/pairs?page_size=200"
            )[0],
            200,
        )
        self.assertEqual(
            self._request(
                "GET", f"/api/jobs/{job_id}/analysis/similarity/pairs?page_size=201"
            )[0],
            422,
        )

    def test_apps_group_matches_by_application_code(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/similarity")

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/apps"
        )

        self.assertEqual(status_code, 200)
        by_code = {item["application_code"]: item for item in payload["applications"]}
        self.assertIn("APP-1", by_code)
        self.assertEqual(
            by_code["APP-1"]["similar_applications"][0]["application_code"],
            "APP-2",
        )
        self.assertLessEqual(
            len(by_code["APP-1"]["similar_applications"]),
            payload["per_application_limit"],
        )
        self.assertGreater(by_code["APP-1"]["highest_similarity_score"], 0)
        self.assertGreaterEqual(by_code["APP-1"]["possible_duplicate_count"], 0)

    def test_rules_endpoint_returns_stored_configuration(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"heatmap_limit": 25, "alert_limit": 20},
        )

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/rules"
        )

        self.assertEqual(status_code, 200)
        rules = payload["rules_config"]
        self.assertEqual(rules["scoring_method"], "deterministic")
        self.assertEqual(rules["heatmap_limit"], 25)
        self.assertEqual(rules["alert_limit"], 200)
        self.assertTrue(rules["stop_words_applied"])

    def test_heatmap_is_bounded_capped_and_contains_no_self_pairs(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0},
        )

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=999"
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["limit"], 100)
        self.assertLessEqual(len(payload["anchor_applications"]), 100)
        self.assertLessEqual(len(payload["candidate_applications"]), 100)
        self.assertTrue(
            all(
                not (
                    cell["anchor_application_key"]
                    == cell["candidate_application_key"]
                )
                for cell in payload["matrix"]
            )
        )

        invalid_status, invalid = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=0"
        )
        self.assertEqual(invalid_status, 422)
        self.assertIn("greater than or equal to 1", str(invalid))

    def test_alerts_use_critical_severity_and_conservative_recommendations(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0, "possible_duplicate_threshold": 50},
        )

        status_code, payload = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/alerts?limit=50"
        )

        self.assertEqual(status_code, 200)
        duplicate_alerts = [
            alert for alert in payload["alerts"] if alert["alert_type"] == "possible_duplicate"
        ]
        self.assertTrue(duplicate_alerts)
        self.assertTrue(all(alert["severity"] == "critical" for alert in duplicate_alerts))
        recommendations = {alert["recommendation"] for alert in payload["alerts"]}
        self.assertTrue(all("retire" not in item.casefold() for item in recommendations))
        self.assertTrue(all("consolidat" not in item.casefold() for item in recommendations))

    def test_compare_uses_stored_pair_and_computes_pair_outside_stored_top_results(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"similar_pair_threshold": 0, "max_pairs": 1},
        )

        status_code, stored = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/compare?application_code_a=APP-1&application_code_b=APP-2",
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(stored["from_stored_result"])
        self.assertIn("Application Name", stored["application_a"]["key_fields"])

        status_code, calculated = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/compare?application_code_a=APP-3&application_code_b=APP-4",
        )
        self.assertEqual(status_code, 200)
        self.assertFalse(calculated["from_stored_result"])
        self.assertIsInstance(calculated["differing_fields"], list)

    def test_compare_returns_404_for_unknown_application_code(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/similarity")

        status_code, payload = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/compare?application_code_a=APP-1&application_code_b=UNKNOWN",
        )

        self.assertEqual(status_code, 404)
        self.assertIn("Unknown Application Code", payload["detail"])

    def test_csv_export_has_expected_columns_and_requires_analysis(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        status_code, _, body = self._raw_request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/results.csv"
        )
        self.assertEqual(status_code, 404)
        self.assertIn(b"has not been run", body)

        self._request("POST", f"/api/jobs/{job_id}/analysis/similarity")
        status_code, headers, body = self._raw_request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/results.csv"
        )
        self.assertEqual(status_code, 200)
        self.assertTrue(headers["content-type"].startswith("text/csv"))
        expected_header = (
            b"application_code_a,application_name_a,application_code_b,"
            b"application_name_b,similarity_score,possible_duplicate,evidence,"
            b"matched_fields,missing_fields"
        )
        self.assertTrue(body.startswith(expected_header))

    def test_stored_result_reads_fail_before_analysis_runs(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)

        for endpoint in ("summary", "pairs", "apps", "rules"):
            with self.subTest(endpoint=endpoint):
                status_code, payload = self._request(
                    "GET", f"/api/jobs/{job_id}/analysis/similarity/{endpoint}"
                )
                self.assertEqual(status_code, 404)
                self.assertIn("has not been run", payload["detail"])

    def test_weights_are_normalized_without_requiring_total_100(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name", "Business Use Case", "Business Function", "Capability", "Supported Process"],
            [
                ["APP-1", "One", "Payments", "Finance", "Billing", "Collect"],
                ["APP-2", "Two", "Payments", "Finance", "Billing", "Collect"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)
        status_code, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Business Use Case", "Business Function", "Capability", "Supported Process"],
                "field_weights": {"Business Use Case": 30, "Business Function": 30, "Capability": 20, "Supported Process": 10},
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(
            payload["field_weights_used"],
            {"Business Use Case": 33.333333, "Business Function": 33.333333, "Capability": 22.222222, "Supported Process": 11.111111},
        )
        self.assertAlmostEqual(sum(payload["field_weights_used"].values()), 100, places=5)
        self.assertEqual(payload["top_similar_pairs"][0]["similarity_score"], 100)

    def test_all_zero_weights_are_rejected(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        status_code, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"selected_fields": ["Application Name", "Description"], "field_weights": {"Application Name": 0, "Description": 0}},
        )
        self.assertEqual(status_code, 422)
        self.assertIn("At least one similarity weight", payload["detail"])

    def test_legacy_top_pairs_can_be_bounded_and_apps_default_to_five(self) -> None:
        job_id = self._create_job()
        rows = [[f"APP-{index}", f"Payments {index}", "Shared payment capability"] for index in range(1, 9)]
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(["Application Code", "Application Name", "Business Use Case"], rows),
        )
        _, overview = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"selected_fields": ["Business Use Case"], "field_weights": {"Business Use Case": 1}, "max_pairs": 5},
        )
        self.assertEqual(len(overview["top_similar_pairs"]), 5)
        _, apps = self._request("GET", f"/api/jobs/{job_id}/analysis/similarity/apps")
        self.assertTrue(all(len(group["similar_applications"]) == 5 for group in apps["applications"]))

    def test_redundancy_alerts_apply_85_percent_threshold(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name", "Business Use Case", "Capability"],
            [
                ["APP-1", "One", "Customer payments", "Billing"],
                ["APP-2", "Two", "Customer payments", "Billing"],
                ["APP-3", "Three", "Employee records", "HR"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"selected_fields": ["Business Use Case", "Capability"], "field_weights": {"Business Use Case": 1, "Capability": 1}},
        )
        _, payload = self._request("GET", f"/api/jobs/{job_id}/analysis/similarity/alerts")
        self.assertEqual(len(payload["alerts"]), 1)
        self.assertGreaterEqual(payload["alerts"][0]["similarity_score"], 85)

    def test_cluster_threshold_compatibility_input_does_not_change_internal_rule(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name", "Business Use Case", "Capability"],
            [
                ["APP-1", "One", "Customer payment", "Billing"],
                ["APP-2", "Two", "Customer payment", "Billing"],
                ["APP-3", "Three", "Employee records", "HR"],
            ],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)
        request = {"selected_fields": ["Business Use Case", "Capability"], "field_weights": {"Business Use Case": 80, "Capability": 20}}
        self._request("POST", f"/api/jobs/{job_id}/analysis/similarity", {**request, "cluster_threshold": 60})
        _, lower = self._request("GET", f"/api/jobs/{job_id}/analysis/similarity/clusters")
        self._request("POST", f"/api/jobs/{job_id}/analysis/similarity", {**request, "cluster_threshold": 95})
        _, higher = self._request("GET", f"/api/jobs/{job_id}/analysis/similarity/clusters")
        self.assertEqual(lower["clusters"], higher["clusters"])
        self.assertNotIn("cluster_threshold", lower)

    def test_blank_configured_fields_are_safe_and_not_perfect_matches(self) -> None:
        job_id = self._create_job()
        source = workbook_bytes(
            ["Application Code", "Application Name", "Business Use Case", "Capability"],
            [["APP-1", "One", None, None], ["APP-2", "Two", None, None]],
        )
        self.services.cmdb_service.upload(job_id, "inventory.xlsx", source)
        status_code, payload = self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"selected_fields": ["Business Use Case", "Capability"], "field_weights": {"Business Use Case": 1, "Capability": 1}},
        )
        self.assertEqual(status_code, 422)
        self.assertIn("no comparable values", payload["detail"])

    def test_results_only_contain_current_cmdb_application_records(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        _, payload = self._request("POST", f"/api/jobs/{job_id}/analysis/similarity", {"similar_pair_threshold": 0})
        allowed = {"APP-1", "APP-2", "APP-3", "APP-4"}
        returned = {
            code
            for pair in payload["top_similar_pairs"]
            for code in (pair["application_code_a"], pair["application_code_b"])
        }
        self.assertTrue(returned)
        self.assertLessEqual(returned, allowed)

    def test_heatmap_filters_and_supported_display_limits_reuse_analysis(self) -> None:
        job_id = self._create_job()
        rows = [
            [f"APP-{index:03d}", f"Finance Tool {index}", "Finance", "Payments"]
            for index in range(1, 121)
        ] + [["APP-999", "People Hub", "People", "HR"]]
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Portfolio", "Capability"],
                rows,
            ),
        )
        request = {
            "selected_fields": ["Portfolio", "Capability"],
            "field_weights": {"Portfolio": 1, "Capability": 1},
        }
        self.assertEqual(
            self._request("POST", f"/api/jobs/{job_id}/analysis/similarity", request)[0],
            200,
        )
        with patch.object(
            CMDBSimilarityService,
            "_prepare_record",
            side_effect=AssertionError("heatmap endpoint rebuilt preprocessing"),
        ):
            for limit in (25, 50, 100):
                _, payload = self._request(
                    "GET",
                    f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit={limit}&portfolio=Finance",
                )
                self.assertEqual(len(payload["anchor_applications"]), limit)
                self.assertLessEqual(len(payload["candidate_applications"]), limit)
                self.assertEqual(payload["matched_anchor_count"], 120)
        _, searched = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25&search=app-999",
        )
        self.assertEqual(
            [item["application_code"] for item in searched["anchor_applications"]],
            ["APP-999"],
        )
        self.assertIn("Finance", searched["portfolio_options"])
        self.assertIn("People", searched["portfolio_options"])

    def test_heatmap_ranking_stays_within_selected_portfolio_scope(self) -> None:
        job_id = self._create_job()
        rows = [
            ["ANCHOR-1", "Mercury Billing", "Anchor Portfolio", "customer payments billing"],
            ["ANCHOR-2", "Orchid Catalog", "Anchor Portfolio", "asset catalog metadata"],
            ["SAME-1", "Regional Billing", "Anchor Portfolio", "customer payments"],
            ["OTHER-1", "Global Billing", "Other Portfolio", "customer payments billing"],
            ["OTHER-2", "Enterprise Catalog", "Other Portfolio", "asset catalog metadata"],
            ["NONE-1", "Catalog Lite", None, "asset catalog"],
            ["ZERO-1", "People Directory", "People", "human resources directory"],
        ]
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Portfolio", "Capability"],
                rows,
            ),
        )
        self.assertEqual(
            self._request(
                "POST",
                f"/api/jobs/{job_id}/analysis/similarity",
                {
                    "selected_fields": ["Capability"],
                    "field_weights": {"Capability": 1},
                },
            )[0],
            200,
        )

        _, filtered = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25&portfolio=Anchor%20Portfolio",
        )
        self.assertEqual(
            {app["application_code"] for app in filtered["anchor_applications"]},
            {"ANCHOR-1", "ANCHOR-2", "SAME-1"},
        )
        candidate_codes = [
            app["application_code"] for app in filtered["candidate_applications"]
        ]
        self.assertNotIn("OTHER-1", candidate_codes)
        self.assertNotIn("OTHER-2", candidate_codes)
        self.assertIn("SAME-1", candidate_codes)
        self.assertNotIn("ZERO-1", candidate_codes)
        self.assertEqual(set(candidate_codes), {"ANCHOR-1", "ANCHOR-2", "SAME-1"})
        self.assertEqual(filtered["candidate_count"], len(candidate_codes))
        self.assertEqual(
            len(filtered["anchor_applications"]),
            len(filtered["candidate_applications"]),
        )
        self.assertTrue(
            all(
                cell["anchor_application_key"] != cell["candidate_application_key"]
                for cell in filtered["matrix"]
            )
        )

        _, searched = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25&search=anchor-1",
        )
        self.assertEqual(
            [app["application_code"] for app in searched["anchor_applications"]],
            ["ANCHOR-1"],
        )
        self.assertEqual(searched["candidate_applications"], [])

        _, all_portfolios = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25"
        )
        self.assertEqual(
            [app["application_key"] for app in all_portfolios["anchor_applications"]],
            [app["application_key"] for app in all_portfolios["candidate_applications"]],
        )
        self.assertIn("ZERO-1", {
            app["application_code"] for app in all_portfolios["anchor_applications"]
        })
        self.assertIn("ZERO-1", {
            app["application_code"] for app in all_portfolios["candidate_applications"]
        })

    def test_heatmap_search_ranks_only_the_current_filtered_scope(self) -> None:
        job_id = self._create_job()
        rows = [["ANCHOR", "Anchor", "Source", "shared exact"]]
        rows.extend(
            [f"MATCH-{index:03d}", f"Match {index}", "Candidate", "shared exact"]
            for index in range(30)
        )
        rows.extend(
            [f"ZERO-{index:03d}", f"Zero {index}", "Candidate", f"unique{index}"]
            for index in range(30)
        )
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Portfolio", "Capability"],
                rows,
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Capability"],
                "field_weights": {"Capability": 1},
            },
        )
        _, payload = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25&search=anchor",
        )
        self.assertEqual(len(payload["anchor_applications"]), 1)
        self.assertEqual(len(payload["candidate_applications"]), 25)
        self.assertTrue(payload["matrix"])
        self.assertTrue(all(cell["similarity_score"] == 100 for cell in payload["matrix"]))

        _, filtered = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25&search=anchor&score_range=21-30",
        )
        self.assertEqual(filtered["candidate_applications"], [])
        self.assertEqual(filtered["matrix"], [])
        self.assertTrue(filtered["no_comparable_data"])

    def test_heatmap_returns_distinct_empty_states_for_anchors_and_candidates(self) -> None:
        job_id = self._create_job()
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Capability"],
                [["ONLY-1", "Only Application", "unique capability"]],
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {"selected_fields": ["Capability"], "field_weights": {"Capability": 1}},
        )
        _, no_anchors = self._request(
            "GET",
            f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25&search=missing",
        )
        self.assertEqual(no_anchors["matched_anchor_count"], 0)
        self.assertEqual(no_anchors["anchor_applications"], [])
        self.assertEqual(no_anchors["candidate_applications"], [])
        self.assertFalse(no_anchors["no_comparable_data"])

        _, no_candidates = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25"
        )
        self.assertEqual(len(no_candidates["anchor_applications"]), 1)
        self.assertEqual(no_candidates["candidate_applications"], [])
        self.assertEqual(no_candidates["matrix"], [])
        self.assertTrue(no_candidates["no_comparable_data"])

    def test_similar_apps_supported_limits_exclude_selected_application(self) -> None:
        job_id = self._create_job()
        rows = [
            [f"APP-{index:03d}", f"Payments {index}", "Customer payments"]
            for index in range(55)
        ]
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Business Use Case"], rows
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Business Use Case"],
                "field_weights": {"Business Use Case": 1},
            },
        )
        for limit in (5, 10, 25, 50):
            _, payload = self._request(
                "GET",
                f"/api/jobs/{job_id}/analysis/similarity/apps?application_key=app-0&limit={limit}",
            )
            matches = payload["applications"][0]["similar_applications"]
            self.assertEqual(len(matches), limit)
            self.assertNotIn("APP-000", {item["application_code"] for item in matches})

    def test_redundancy_limits_are_ranked_and_never_manufacture_rows(self) -> None:
        job_id = self._create_job()
        rows = [
            [f"APP-{index:03d}", f"Tool {index}", "Shared purpose", "Shared process"]
            for index in range(21)
        ]
        self.services.cmdb_service.upload(
            job_id,
            "inventory.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Business Use Case", "Supported Process"],
                rows,
            ),
        )
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Business Use Case", "Supported Process"],
                "field_weights": {"Business Use Case": 1, "Supported Process": 1},
            },
        )
        expected_total = 21 * 20 // 2
        for limit in (25, 50, 100, 200):
            _, payload = self._request(
                "GET",
                f"/api/jobs/{job_id}/analysis/similarity/alerts?limit={limit}",
            )
            scores = [item["similarity_score"] for item in payload["alerts"]]
            self.assertEqual(len(scores), min(limit, expected_total))
            self.assertEqual(scores, sorted(scores, reverse=True))
            pairs = {
                frozenset((item["application_code_a"], item["application_code_b"]))
                for item in payload["alerts"]
            }
            self.assertEqual(len(pairs), len(scores))

    def test_pair_scoring_uses_preprocessed_values_without_renormalizing(self) -> None:
        preview = {
            "application_code_column": "Application Code",
            "application_name_column": "Application Name",
        }
        resolved = CMDBSimilarityService._resolve_columns(
            ["Application Code", "Application Name", "Capability"]
        )
        records = [
            {"source_data": {"Application Code": "A", "Application Name": "One", "Capability": "Billing"}},
            {"source_data": {"Application Code": "B", "Application Name": "Two", "Capability": "Billing"}},
        ]
        prepared = [
            CMDBSimilarityService._prepare_record(record, preview, resolved)
            for record in records
        ]
        with patch.object(
            CMDBSimilarityService,
            "_normalize_text",
            side_effect=AssertionError("pair loop normalized text again"),
        ):
            pair = CMDBSimilarityService._score_pair(
                prepared[0], prepared[1], 85, ["Capability"], {"Capability": 100}
            )
        self.assertEqual(pair["similarity_score"], 100)

    def test_cluster_endpoint_reuses_stored_analysis_state(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request("POST", f"/api/jobs/{job_id}/analysis/similarity")
        with patch.object(
            CMDBSimilarityService,
            "_prepare_record",
            side_effect=AssertionError("cluster endpoint rebuilt preprocessing"),
        ):
            status, payload = self._request(
                "GET", f"/api/jobs/{job_id}/analysis/similarity/clusters"
            )
        self.assertEqual(status, 200)
        self.assertIn("clusters", payload)

    def test_latest_upload_and_rerun_configuration_isolate_analysis_state(self) -> None:
        job_id = self._create_job()
        self._upload_cmdb(job_id)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Portfolio"],
                "field_weights": {"Portfolio": 1},
            },
        )
        _, first_rules = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/rules"
        )
        self.assertEqual(first_rules["rules_config"]["selected_fields_used"], ["portfolio"])

        self.services.cmdb_service.upload(
            job_id,
            "replacement.xlsx",
            workbook_bytes(
                ["Application Code", "Application Name", "Capability"],
                [["NEW-1", "New One", "Billing"], ["NEW-2", "New Two", "Billing"]],
            ),
        )
        status, _ = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/rules"
        )
        self.assertEqual(status, 404)
        self._request(
            "POST",
            f"/api/jobs/{job_id}/analysis/similarity",
            {
                "selected_fields": ["Capability"],
                "field_weights": {"Capability": 7},
            },
        )
        _, current_rules = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/rules"
        )
        self.assertEqual(current_rules["rules_config"]["selected_fields_used"], ["Capability"])
        self.assertEqual(
            {item["application_code"] for item in current_rules["applications"]},
            {"NEW-1", "NEW-2"},
        )
        _, current_heatmap = self._request(
            "GET", f"/api/jobs/{job_id}/analysis/similarity/heatmap?limit=25"
        )
        heatmap_codes = {
            item["application_code"]
            for key in ("anchor_applications", "candidate_applications")
            for item in current_heatmap[key]
        }
        self.assertEqual(heatmap_codes, {"NEW-1", "NEW-2"})
        self.assertFalse(any(code.startswith("APP-") for code in heatmap_codes))

    def test_frontend_declares_exact_four_tabs_without_removed_controls(self) -> None:
        page = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "app"
            / "similarity"
            / "page.tsx"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'similarityTabs = ["App vs App Heatmap", "Similar Apps Panel", "Cluster Map", "Redundancy Alerts"]',
            page,
        )
        self.assertNotIn("Top 5 List", page)
        self.assertNotIn("Direct Compare", page)
        self.assertNotIn("Cluster Threshold", page)
        self.assertNotIn("cluster_threshold", page)


if __name__ == "__main__":
    unittest.main()
