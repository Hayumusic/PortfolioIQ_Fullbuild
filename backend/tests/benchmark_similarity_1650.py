"""Manual, non-gating benchmark for the Similarity preprocessing architecture.

Run with: PYTHONPATH=. python3 tests/benchmark_similarity_1650.py
"""

from time import perf_counter

from app.services.cmdb_similarity_service import CMDBSimilarityService


RECORD_COUNT = 1_650
FIELDS = ["Business Use Case", "Business Function", "Capability", "Supported Process"]


def run_benchmark() -> dict[str, float | int | bool]:
    preview = {
        "application_code_column": "Application Code",
        "application_name_column": "Application Name",
    }
    resolved = CMDBSimilarityService._resolve_columns(
        ["Application Code", "Application Name", *FIELDS]
    )
    records = []
    for index in range(RECORD_COUNT):
        records.append(
            {
                "internal_row_number": index + 2,
                "source_data": {
                    "Application Code": f"APP-{index:04d}",
                    "Application Name": f"Portfolio Application {index}",
                    "Business Use Case": f"Use case {index % 110} channel {index % 13}",
                    "Business Function": f"Function {index % 55}",
                    "Capability": f"Capability {index % 80}",
                    "Supported Process": f"Process {index % 95}",
                },
            }
        )

    started = perf_counter()
    applications = [
        CMDBSimilarityService._prepare_record(record, preview, resolved)
        for record in records
    ]
    weights = {field: 25.0 for field in FIELDS}
    candidates = CMDBSimilarityService._candidate_pairs(
        applications, FIELDS, weights, minimum_score=60
    )
    redundancy_count = 0
    cluster_edge_count = 0
    for left_index, right_index in candidates:
        pair = CMDBSimilarityService._score_pair(
            applications[left_index],
            applications[right_index],
            85,
            FIELDS,
            weights,
        )
        redundancy_count += int(pair["similarity_score"] >= 85)
        cluster_edge_count += int(pair["similarity_score"] >= 60)
    elapsed = perf_counter() - started
    naive_pair_count = RECORD_COUNT * (RECORD_COUNT - 1) // 2
    return {
        "record_count": RECORD_COUNT,
        "elapsed_seconds": round(elapsed, 4),
        "candidate_pair_count": len(candidates),
        "naive_pair_count": naive_pair_count,
        "redundancy_candidate_count": redundancy_count,
        "cluster_edge_count": cluster_edge_count,
        "avoided_full_naive_fuzzy_scan": len(candidates) < naive_pair_count,
    }


if __name__ == "__main__":
    print(run_benchmark())
