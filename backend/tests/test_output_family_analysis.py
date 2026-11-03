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


def workbook_bytes(headers, rows):
    workbook = Workbook(); sheet = workbook.active; sheet.append(headers)
    for row in rows: sheet.append(row)
    output = BytesIO(); workbook.save(output); output.seek(0); return output


class OutputFamilyAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Settings(local_storage_root=Path(self.temp.name), openai_api_key=None, openai_model=None))
        self.runner = asyncio.Runner(); self.lifespan = self.app.router.lifespan_context(self.app)
        self.runner.run(self.lifespan.__aenter__()); self.services = self.app.state.services

    def tearDown(self):
        self.runner.run(self.lifespan.__aexit__(None, None, None)); self.runner.close(); self.temp.cleanup()

    def request(self, method, url, body=None):
        parsed = urlsplit(url); raw = b"" if body is None else json.dumps(body).encode(); messages = []; sent = False
        async def receive():
            nonlocal sent
            if not sent: sent = True; return {"type": "http.request", "body": raw, "more_body": False}
            return {"type": "http.disconnect"}
        async def send(message): messages.append(message)
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": parsed.path, "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
                 "root_path": "", "headers": [] if body is None else [(b"content-type", b"application/json")],
                 "client": ("test", 1), "server": ("test", 80)}
        self.runner.run(self.app(scope, receive, send))
        status = next(item["status"] for item in messages if item["type"] == "http.response.start")
        response = b"".join(item.get("body", b"") for item in messages if item["type"] == "http.response.body")
        return status, json.loads(response)

    def create_inputs(self, job_id=None):
        job_id = job_id or self.services.job_service.create_job().job_id
        self.services.cmdb_service.upload(job_id, "current.xlsx", workbook_bytes(
            ["Application Code", "Application Name", "Description", "Business Function", "Dashboard Output", "Downstream Consumers", "Technology"],
            [
                ["A1", "One", "MANAGEMENT REPORT and partner api", None, None, "Executives", "Java"],
                ["A2", "Two", "management report", None, None, None, "Java"],
                ["A3", "Three", "management report and product catalogue", None, None, None, "Java"],
                ["A4", "Four", "management report and product catalogue", None, None, None, "Java"],
                ["A5", "Five", "product catalogue", None, None, None, "Java"],
                ["A6", "Six", "partner api", None, None, None, "Java"],
                ["A7", "Seven", "download available", None, None, None, "Java"],
                ["A8", "Eight", None, None, None, None, "Java"],
            ]))
        self.services.upload_config_service.upload_output_family_config(job_id, "families.xlsx", workbook_bytes(
            ["Output Family", "Members"], [["Reporting", "management report"], ["Product Data", "product catalogue"], ["Data Exchange", "partner api"]]))
        return job_id

    def run_and_get(self, job_id):
        status, _ = self.request("POST", f"/api/jobs/{job_id}/analysis/output-families", {})
        self.assertEqual(status, 200)
        status, result = self.request("GET", f"/api/jobs/{job_id}/analysis/output-families/mvp")
        self.assertEqual(status, 200); return result

    def test_mvp_output_column_detection_keywords(self):
        service = self.services.output_family_analysis_service
        source = {keyword.title(): f"v{index}" for index, keyword in enumerate(service.output_column_keywords)}
        source["Technology"] = "ignored"
        detected = service._detected_output_values(source)
        self.assertEqual(len(detected), len(service.output_column_keywords))
        self.assertNotIn(("Technology", "ignored"), detected)
        self.assertEqual(service._detected_output_values({"Profile": "not an output field"}), [])

    def test_configured_direct_matching_selects_one_best_supported_family(self):
        job_id = self.create_inputs()
        result = self.run_and_get(job_id)
        details = {row["application_key"]: row for row in result["output_details"]}
        self.assertEqual(details["A1"]["output_family_classification"], "Reporting")
        self.assertEqual(details["A3"]["output_family_classification"], "Reporting")
        self.assertEqual(details["A1"]["confidence_level"], "High")
        self.assertTrue(details["A1"]["why_classified"].startswith("Mapped to "))
        mapping = self.services.output_family_analysis_service.get_application_mapping(
            job_id, display_size="all"
        )
        self.assertTrue(all(row["output_family_count"] == 1 for row in mapping["applications"]))
        self.assertTrue(all(len(row["output_families"]) <= 1 for row in mapping["applications"]))

    def test_mandatory_fields_receive_internal_context_weight(self):
        service = self.services.output_family_analysis_service
        self.assertEqual(service._field_weight("Business Function", ["Business Function"]), 4.0)
        self.assertEqual(service._field_weight("Business Function", []), 3.0)

    def test_family_name_match_and_partial_words_do_not_match(self):
        service = self.services.output_family_analysis_service
        taxonomy = [{"name": "API", "description": None, "terms": service._deduplicated_terms(["API"])}]
        matched = service._classify({
            "application_code": "A1", "application_key": "A1", "application_name": "One",
            "portfolio": None, "business_criticality": None,
            "detected_values": [("Description", "API publication")],
            "combined_text": "API publication", "consumers": "",
        }, taxonomy)
        partial = service._classify({
            "application_code": "A2", "application_key": "A2", "application_name": "Two",
            "portfolio": None, "business_criticality": None,
            "detected_values": [("Description", "capital planning")],
            "combined_text": "capital planning", "consumers": "",
        }, taxonomy)
        self.assertEqual(matched["output_families"], ["API"])
        self.assertEqual(partial["assigned_output_family"], "Others")
        self.assertEqual(partial["output_clusters"], ["Others"])
        self.assertTrue(partial["is_other"])

    def test_configured_application_members_match_normalized_identity(self):
        job_id = self.services.job_service.create_job().job_id
        self.services.cmdb_service.upload(job_id, "identity.xlsx", workbook_bytes(
            ["Application Code", "Application Name", "Description"],
            [["APP-001", "Member Application", None]],
        ))
        self.services.upload_config_service.upload_output_family_config(
            job_id,
            "families.xlsx",
            workbook_bytes(
                ["Output Family", "Application Code", "Application Name"],
                [["Regulatory Reporting", " app-001 ", "member application"]],
            ),
        )
        result = self.run_and_get(job_id)
        row = result["family_matrix"]["rows"][0]
        self.assertEqual(row["values"]["Regulatory Reporting"], "Yes")
        mapping = self.services.output_family_analysis_service.get_application_mapping(
            job_id, display_size="all"
        )["applications"][0]
        self.assertTrue(any("member application" in value.casefold() for value in mapping["matched_evidence"]))

    def test_others_reasons_cover_indicator_and_no_relevant_match(self):
        job_id = self.create_inputs()
        result = self.run_and_get(job_id)
        exceptions = {row["application_name"]: row for row in result["exceptions"]}
        self.assertIn("Closest candidate:", exceptions["Seven"]["reason"])
        self.assertIn("Review evidence:", exceptions["Seven"]["comment"])
        self.assertEqual(exceptions["Seven"]["confidence_level"], "Low")
        self.assertEqual(exceptions["Eight"]["confidence_level"], "Low")

        status, summary_result = self.request(
            "GET", f"/api/jobs/{job_id}/analysis/output-families/summary"
        )
        self.assertEqual(status, 200)
        summary = summary_result["summary"]
        self.assertEqual(summary["total_application_count"], 8)
        self.assertEqual(summary["classified_application_count"], 6)
        self.assertEqual(summary["evidence_clustered_application_count"], 0)
        self.assertEqual(summary["insufficient_evidence_application_count"], 2)
        self.assertEqual(summary["unclassified_application_count"], 2)

        mapping = self.services.output_family_analysis_service.get_application_mapping(
            job_id, display_size="all"
        )
        applications = {row["application_code"]: row for row in mapping["applications"]}
        self.assertEqual(mapping["insufficient_evidence_application_count"], 2)
        self.assertEqual(applications["A7"]["assigned_output_cluster"], "Others")
        self.assertEqual(applications["A7"]["classification_status"], "Insufficient Evidence")
        self.assertEqual(applications["A7"]["confidence"], "Low")
        self.assertEqual(applications["A8"]["assigned_output_cluster"], "Others")
        self.assertEqual(applications["A8"]["classification_status"], "Insufficient Evidence")
        self.assertEqual(applications["A8"]["confidence"], "Low")
        self.assertIn("Closest candidate:", applications["A7"]["comment"])

    def test_clusters_have_mvp_fields_and_one_others_cluster(self):
        result = self.run_and_get(self.create_inputs())
        clusters = {row["output_family_name"]: row for row in result["output_family_clusters"]}
        self.assertEqual(clusters["Reporting"]["application_count"], 4)
        self.assertEqual(clusters["Product Data"]["application_count"], 1)
        self.assertEqual(clusters["Data Exchange"]["application_count"], 1)
        self.assertEqual(clusters["Others"]["application_count"], 2)
        self.assertEqual(sum(name == "Others" for name in clusters), 1)
        self.assertIn("weighted CMDB functional context", clusters["Reporting"]["similarity_notes"])
        self.assertIn("source_of_truth_labels_in_cluster", clusters["Reporting"])

    def test_yes_no_matrix_contains_all_configured_families_and_others(self):
        result = self.run_and_get(self.create_inputs()); matrix = result["family_matrix"]
        self.assertEqual(matrix["configured_families"], ["Reporting", "Product Data", "Data Exchange"])
        self.assertEqual(matrix["other_clusters"], ["Others"])
        rows = {row["application_key"]: row["values"] for row in matrix["rows"]}
        self.assertEqual(rows["A1"]["Reporting"], "Yes")
        self.assertEqual(sum(value == "Yes" for value in rows["A1"].values()), 1)
        self.assertEqual(rows["A7"]["Others"], "Yes")
        self.assertEqual(rows["A8"]["Others"], "Yes")

    def test_matrix_normalizes_family_identity_and_one_row_per_application_code(self):
        job_id = self.services.job_service.create_job().job_id
        self.services.cmdb_service.upload(job_id, "duplicates.xlsx", workbook_bytes(
            ["Application Code", "Application Name", "Description"],
            [["A1", "One", "management report"], ["a1", "One", "partner api"]],
        ))
        self.services.upload_config_service.upload_output_family_config(job_id, "families.xlsx", workbook_bytes(
            ["Output Family", "Members"], [["Reporting", "management report"], ["Data Exchange", "partner api"]],
        ))
        result = self.run_and_get(job_id)
        self.assertEqual(len(result["family_matrix"]["rows"]), 1)
        values = result["family_matrix"]["rows"][0]["values"]
        self.assertEqual(sum(value == "Yes" for value in values.values()), 1)
        normalized = self.services.output_family_analysis_service._yes_no_matrix(
            [{"name": "Reporting"}],
            [{"application_key": "A2", "application_name": "Two", "output_families": [" reporting "]}],
        )
        self.assertEqual(normalized["rows"][0]["values"]["Reporting"], "Yes")

    def test_mandatory_cmdb_fields_are_used_as_internal_weights(self):
        job_id = self.services.job_service.create_job().job_id
        self.services.cmdb_service.upload(job_id, "weighted.xlsx", workbook_bytes(
            ["Application Code", "Application Name", "Business Function", "Description"],
            [["A1", "One", "Customer payments", "Account servicing"]],
        ))
        self.services.upload_config_service.upload_mandatory_fields_config(
            job_id, "mandatory.xlsx", workbook_bytes(["Mandatory Field"], [["Business Function"]])
        )
        applications = self.services.output_family_analysis_service._prepare_applications(
            self.services.output_family_analysis_service._load_current_preview(job_id), ["Business Function"]
        )
        scoring_fields = {field["header"]: field for field in applications[0]["scoring_fields"]}
        self.assertEqual(scoring_fields["Business Function"]["weight"], 4.0)
        self.assertEqual(scoring_fields["Description"]["weight"], 3.0)

    def test_redundancy_low_medium_high_rules_and_copy(self):
        result = self.run_and_get(self.create_inputs())
        alerts = {row["shared_output_family"]: row for row in result["redundancy_alerts"]}
        self.assertEqual(alerts["Reporting"]["redundancy_severity"], "High")
        self.assertNotIn("Data Exchange", alerts)
        self.assertNotIn("Product Data", alerts)
        self.assertEqual(alerts["Reporting"]["business_impact"], "Potential duplicated reporting, analytics, API, export, or data-processing capability.")

    def test_output_details_fields_and_exceptions_filter(self):
        result = self.run_and_get(self.create_inputs())
        expected = {"application_key", "application_name", "output_summary", "output_family_classification",
                    "key_evidence_or_keywords_found", "consumers_or_downstream_users", "confidence_level",
                    "why_classified", "comment", "direct_or_inferred", "evidence_type", "missing_data_warnings",
                    "source_of_truth_label", "reliability_label"}
        self.assertEqual(set(result["output_details"][0]), expected)
        self.assertEqual({row["application_name"] for row in result["exceptions"]}, {"Seven", "Eight"})
        self.assertEqual(result["output_details"][0]["consumers_or_downstream_users"], "Executives")

    def test_no_openai_or_api_key_and_downloads(self):
        async def forbidden(**kwargs): raise AssertionError("Output analysis must not invoke OpenAI")
        self.services.analysis_service.openai_service.analyze_json = forbidden
        job = self.create_inputs(); result = self.run_and_get(job)
        self.assertEqual(set(result["downloads"]), {"details", "clusters", "alerts"})
        stored = self.services.job_service.storage.load_json(f"jobs/{job}/results/output_families.json")
        self.assertEqual(stored["classification_provider"], "weighted_contextual_taxonomy_matching")
        self.assertIn("application_key", self.services.output_family_analysis_service.get_output_details_csv(job))

    def test_current_session_isolation_and_taxonomy_freshness(self):
        first = self.create_inputs(); self.run_and_get(first)
        second = self.create_inputs()
        status, _ = self.request("GET", f"/api/jobs/{second}/analysis/output-families/mvp")
        self.assertEqual(status, 404)
        self.services.upload_config_service.upload_output_family_config(first, "replacement.xlsx", workbook_bytes(["Output Family", "Members"], [["Notices", "customer notice"]]))
        status, payload = self.request("GET", f"/api/jobs/{first}/analysis/output-families/mvp")
        self.assertEqual(status, 404); self.assertIn("current Output Family taxonomy", payload["detail"])

    def test_frontend_has_single_matrix_view_and_family_colored_heatmap(self):
        page = (Path(__file__).parents[2] / "frontend/src/app/output-families/page.tsx").read_text()
        self.assertIn("App vs Output Family Matrix", page)
        for label in ("Output Family Clusters", "Redundancy Alerts", "Output Details", "Exceptions / Others"):
            self.assertNotIn(label, page)
        self.assertNotIn('role="tablist"', page)
        self.assertNotIn("Download output", page)
        self.assertIn('data-zmin="0" data-zmax="1"', page)
        self.assertIn("Math.max(400, rows.length * 42 + 90)", page)
        self.assertIn("familyColors(family", page)
        self.assertIn('family.trim().toLowerCase().startsWith("others /")', page)
        self.assertIn('outputFamily ? allMemberOptions.filter', page)
        self.assertIn('setFamilyMember("")', page)
        self.assertIn('.filter((row) => !portfolio || row.portfolio === portfolio)', page)
        self.assertIn('setApplication("")', page)
        self.assertIn("No applications match the selected filters.", page)


if __name__ == "__main__": unittest.main()
