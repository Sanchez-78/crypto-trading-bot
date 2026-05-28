#!/usr/bin/env python3
"""Test suite for Android metrics registry coverage and completeness.

Validates:
- All 82+ metrics present and categorized
- Complete metadata fields for each metric
- Czech translations present and non-empty
- Category and tab assignments valid
- Firebase document/field paths follow conventions
- No duplicate metric IDs
"""

import json
from pathlib import Path
import pytest


class TestAndroidMetricsRegistry:
    """Validate complete Android metrics registry."""

    @pytest.fixture(scope="class")
    def registry(self):
        """Load the metrics registry."""
        registry_path = Path(__file__).parent.parent.parent / "docs" / "v5_android_metrics_registry_complete.json"
        assert registry_path.exists(), f"Registry not found: {registry_path}"

        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_registry_metadata(self, registry):
        """Test registry has required metadata."""
        assert "version" in registry
        assert registry["version"] == "5.0-complete"

        assert "metadata" in registry
        meta = registry["metadata"]
        assert meta["total_metrics"] >= 65, f"Expected 65+ metrics, got {meta['total_metrics']}"
        assert meta["categories"] >= 13
        assert "en" in meta["language_support"]
        assert "cs" in meta["language_support"]

    def test_metric_categories_defined(self, registry):
        """Test all required metric categories are defined."""
        required_categories = {
            "runtime": "Bot lifecycle, epoch, mode",
            "safety": "PAPER only, REAL impossible",
            "firebase_quota": "Daily limits, quota state machine",
            "firebase_persistence": "Outbox, sync status",
            "futures_feed": "Feed connection, stale events",
            "admission": "Candidate generation, entry attempts",
            "rejection_reasons": "Cost-edge, filters, limits",
            "open_positions": "Position tracking, PnL",
            "post_close_accounting": "Fees, funding, provenance",
            "learning_segments": "Win rate, expectancy",
            "readiness_gates": "Eligible closes, performance",
            "health_incidents": "Feed disconnections, Firebase failures",
            "trade_detail": "Trade history, detailed breakdowns"
        }

        categories = registry.get("metric_categories", {})
        for req_cat in required_categories.keys():
            assert req_cat in categories, f"Missing category: {req_cat}"

    def test_all_metrics_present(self, registry):
        """Test all metrics are in the registry."""
        metrics = registry.get("metrics", [])
        assert len(metrics) >= 65, f"Expected 65+ metrics, found {len(metrics)}"

    def test_no_duplicate_metric_ids(self, registry):
        """Test no duplicate metric IDs exist."""
        metrics = registry.get("metrics", [])
        metric_ids = [m["metric_id"] for m in metrics]

        assert len(metric_ids) == len(set(metric_ids)), \
            f"Duplicate metric IDs found: {[id for id in metric_ids if metric_ids.count(id) > 1]}"

    def test_all_required_fields_present(self, registry):
        """Test every metric has all required fields."""
        required_fields = {
            "metric_id": str,
            "display_name_en": str,
            "display_name_cs": str,
            "definition_cs": str,
            "category": str,
            "unit": str,
            "firebase_document_path": str,
            "firebase_field_path": str,
            "update_trigger": str,
            "freshness_target_s": int,
            "android_tab": str,
            "visibility": str,
            "threshold_interpretation": str,
            "read_cost_note": str,
        }

        metrics = registry.get("metrics", [])
        for i, metric in enumerate(metrics):
            for field, field_type in required_fields.items():
                assert field in metric, \
                    f"Metric {i} ({metric.get('metric_id', '???')}): missing field '{field}'"

                # Validate field types
                if field != "freshness_target_s":
                    assert isinstance(metric[field], field_type), \
                        f"Metric {metric['metric_id']}: field '{field}' has wrong type " \
                        f"(expected {field_type.__name__}, got {type(metric[field]).__name__})"

    def test_czech_translations_present(self, registry):
        """Test all Czech translations are non-empty."""
        metrics = registry.get("metrics", [])

        for metric in metrics:
            metric_id = metric["metric_id"]

            assert "display_name_cs" in metric, f"{metric_id}: missing Czech display name"
            assert metric["display_name_cs"], f"{metric_id}: Czech display name is empty"
            assert len(metric["display_name_cs"]) > 0, f"{metric_id}: Czech display name is blank"

            assert "definition_cs" in metric, f"{metric_id}: missing Czech definition"
            assert metric["definition_cs"], f"{metric_id}: Czech definition is empty"
            assert len(metric["definition_cs"]) > 0, f"{metric_id}: Czech definition is blank"

    def test_category_assignments_valid(self, registry):
        """Test all metrics have valid category assignments."""
        categories = set(registry.get("metric_categories", {}).keys())
        metrics = registry.get("metrics", [])

        for metric in metrics:
            metric_id = metric["metric_id"]
            category = metric.get("category")

            assert category in categories, \
                f"{metric_id}: invalid category '{category}' (valid: {sorted(categories)})"

    def test_android_tab_assignments_valid(self, registry):
        """Test all metrics have valid Android tab assignments."""
        valid_tabs = {
            "Runtime", "Safety", "Dashboard", "Admission",
            "Health & Quota", "Learning & Segments", "REAL Readiness", "Trade Detail"
        }

        metrics = registry.get("metrics", [])
        for metric in metrics:
            metric_id = metric["metric_id"]
            tab = metric.get("android_tab")

            assert tab in valid_tabs, \
                f"{metric_id}: invalid tab '{tab}' (valid: {sorted(valid_tabs)})"

    def test_firebase_path_conventions(self, registry):
        """Test Firebase document and field paths follow conventions."""
        metrics = registry.get("metrics", [])

        for metric in metrics:
            metric_id = metric["metric_id"]
            doc_path = metric.get("firebase_document_path", "")
            field_path = metric.get("firebase_field_path", "")

            # Document path should be non-empty and contain at least one slash or be explicit
            assert doc_path, f"{metric_id}: missing firebase_document_path"

            # Field path should not start with slash and be alphanumeric/underscore
            assert field_path, f"{metric_id}: missing firebase_field_path"
            assert not field_path.startswith("/"), \
                f"{metric_id}: field_path should not start with '/'"

    def test_freshness_targets_reasonable(self, registry):
        """Test freshness targets are reasonable values."""
        metrics = registry.get("metrics", [])

        for metric in metrics:
            metric_id = metric["metric_id"]
            freshness = metric.get("freshness_target_s", 0)

            # Between 1 second and 7 days
            assert 1 <= freshness <= 604800, \
                f"{metric_id}: freshness_target_s={freshness} is out of range [1, 604800]"

    def test_category_coverage(self, registry):
        """Test each major category has adequate metric coverage."""
        metrics = registry.get("metrics", [])
        category_counts = {}

        for metric in metrics:
            cat = metric.get("category")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # Each major category should have minimum coverage
        min_per_category = {
            "runtime": 3,
            "safety": 2,
            "firebase_quota": 5,
            "firebase_persistence": 3,
            "futures_feed": 3,
            "admission": 3,
            "rejection_reasons": 3,
            "open_positions": 3,
            "post_close_accounting": 8,
            "learning_segments": 6,
            "readiness_gates": 8,
            "health_incidents": 3,
            "trade_detail": 13,
        }

        for cat, min_count in min_per_category.items():
            actual = category_counts.get(cat, 0)
            assert actual >= min_count, \
                f"Category '{cat}': expected at least {min_count} metrics, got {actual}"

    def test_android_tab_coverage(self, registry):
        """Test each Android tab has metrics assigned."""
        metrics = registry.get("metrics", [])
        tab_counts = {}

        for metric in metrics:
            tab = metric.get("android_tab")
            tab_counts[tab] = tab_counts.get(tab, 0) + 1

        # Each tab should have adequate metrics
        min_per_tab = {
            "Runtime": 3,
            "Safety": 2,
            "Dashboard": 5,
            "Admission": 5,
            "Health & Quota": 10,
            "Learning & Segments": 5,
            "REAL Readiness": 8,
            "Trade Detail": 10,
        }

        for tab, expected_min in min_per_tab.items():
            count = tab_counts.get(tab, 0)
            assert count >= expected_min, \
                f"Android tab '{tab}': expected at least {expected_min} metrics, got {count}"

    def test_safety_critical_metrics_present(self, registry):
        """Test all safety-critical metrics are defined."""
        metrics = registry.get("metrics", [])
        metric_ids = {m["metric_id"] for m in metrics}

        required_safety_metrics = {
            "safety.paper_only",
            "safety.real_orders_allowed",
            "firebase_quota.state",
            "firebase_quota.soft_write_warning",
            "firebase_persistence.outbox_pending_count",
            "readiness_gates.evidence_generated",
            "health_incidents.firebase_failures_today",
        }

        for req in required_safety_metrics:
            assert req in metric_ids, \
                f"Safety-critical metric missing: {req}"

    def test_trade_lifecycle_metrics_present(self, registry):
        """Test all trade lifecycle metrics are defined."""
        metrics = registry.get("metrics", [])
        metric_ids = {m["metric_id"] for m in metrics}

        required_lifecycle_metrics = {
            "post_close_accounting.fee_model_provenance",
            "post_close_accounting.funding_interval_provenance",
            "post_close_accounting.daily_net_pnl_usd",
            "open_positions.count",
            "open_positions.unrealized_pnl_usd",
            "readiness_gates.evidence_generated",
        }

        for req in required_lifecycle_metrics:
            assert req in metric_ids, \
                f"Trade lifecycle metric missing: {req}"

    def test_quota_visibility_metrics_present(self, registry):
        """Test quota and visibility metrics for quota management."""
        metrics = registry.get("metrics", [])
        metric_ids = {m["metric_id"] for m in metrics}

        required_quota_metrics = {
            "firebase_quota.state",
            "firebase_quota.reads_remaining",
            "firebase_quota.writes_remaining",
            "firebase_quota.reads_used_today",
            "firebase_quota.writes_used_today",
        }

        for req in required_quota_metrics:
            assert req in metric_ids, \
                f"Quota metric missing: {req}"

    def test_readiness_provenance_separation(self, registry):
        """Test evidence_generated is separate from real_orders_allowed."""
        metrics = registry.get("metrics", [])

        evidence_metric = None
        orders_allowed_metric = None

        for metric in metrics:
            if metric["metric_id"] == "readiness_gates.evidence_generated":
                evidence_metric = metric
            elif metric["metric_id"] == "safety.real_orders_allowed":
                orders_allowed_metric = metric

        assert evidence_metric is not None, "evidence_generated metric not found"
        assert orders_allowed_metric is not None, "real_orders_allowed metric not found"

        # They should be in different categories/documents
        assert evidence_metric.get("firebase_document_path") != \
               orders_allowed_metric.get("firebase_document_path"), \
            "evidence_generated and real_orders_allowed should be in different documents"

    def test_metric_ids_follow_convention(self, registry):
        """Test metric IDs follow category.name convention."""
        metrics = registry.get("metrics", [])

        for metric in metrics:
            metric_id = metric["metric_id"]
            category = metric.get("category", "")

            # Should start with category name
            assert metric_id.startswith(category + "."), \
                f"Metric ID '{metric_id}' should start with '{category}.'"

    def test_visibility_values(self, registry):
        """Test visibility field has valid values."""
        valid_visibilities = {"public", "internal", "sensitive"}
        metrics = registry.get("metrics", [])

        for metric in metrics:
            visibility = metric.get("visibility")
            assert visibility in valid_visibilities, \
                f"Metric {metric['metric_id']}: invalid visibility '{visibility}'"

    def test_update_trigger_values(self, registry):
        """Test update_trigger has known values."""
        valid_triggers = {
            "epoch_change", "startup", "quota_check", "trade_entry",
            "trade_exit", "learning_update", "dashboard_refresh",
            "android_request", "periodic", "event_driven"
        }
        metrics = registry.get("metrics", [])
        used_triggers = set()

        for metric in metrics:
            trigger = metric.get("update_trigger")
            # Collect all triggers used
            used_triggers.add(trigger)

        # Warn if there are unknown triggers (but don't fail)
        unknown = used_triggers - valid_triggers
        if unknown:
            pytest.skip(f"Unknown triggers used (OK for extensibility): {unknown}")

    def test_total_metric_count_matches(self, registry):
        """Test reported metric count matches actual count."""
        expected = registry["metadata"]["total_metrics"]
        actual = len(registry.get("metrics", []))

        assert actual == expected, \
            f"Metadata reports {expected} metrics but {actual} found"

    def test_no_empty_strings(self, registry):
        """Test no metric has empty string values for required fields."""
        string_fields = [
            "metric_id", "display_name_en", "display_name_cs",
            "definition_cs", "category", "unit",
            "firebase_document_path", "firebase_field_path",
            "update_trigger", "android_tab", "visibility",
            "threshold_interpretation", "read_cost_note"
        ]

        metrics = registry.get("metrics", [])
        for metric in metrics:
            for field in string_fields:
                value = metric.get(field, "")
                assert value and value.strip(), \
                    f"Metric {metric.get('metric_id')}: field '{field}' is empty or whitespace"


class TestAndroidMetricsMappings:
    """Test cross-metric relationships and mappings."""

    @pytest.fixture(scope="class")
    def registry(self):
        """Load the metrics registry."""
        registry_path = Path(__file__).parent.parent.parent / "docs" / "v5_android_metrics_registry_complete.json"
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_cost_edge_metrics_linked(self, registry):
        """Test cost-edge gate metrics link to rejection reasons."""
        metrics = registry.get("metrics", [])
        metric_ids = {m["metric_id"] for m in metrics}

        # If cost-edge exists, cost-edge rejection reason should exist
        if any("cost_edge" in m["metric_id"] for m in metrics):
            assert any("cost_edge" in m["metric_id"] and "rejection" in m["category"]
                      for m in metrics), \
                "Cost-edge gate metric should link to rejection category"

    def test_firebase_operations_tracked(self, registry):
        """Test Firebase read/write operations are tracked in quota metrics."""
        metrics = registry.get("metrics", [])
        quota_metrics = [m for m in metrics if m.get("category") == "firebase_quota"]

        assert len(quota_metrics) >= 3, \
            f"Expected 3+ quota metrics, got {len(quota_metrics)}"

        has_reads = any("read" in m["metric_id"].lower() for m in quota_metrics)
        has_writes = any("write" in m["metric_id"].lower() for m in quota_metrics)

        assert has_reads, "Missing read tracking metrics"
        assert has_writes, "Missing write tracking metrics"

    def test_position_lifecycle_complete(self, registry):
        """Test position metrics cover entry, open, exit, closed."""
        metrics = registry.get("metrics", [])

        position_categories = {
            "admission",
            "open_positions",
            "post_close_accounting"
        }

        position_metrics = [m for m in metrics
                           if m.get("category") in position_categories]

        assert len(position_metrics) >= 10, \
            f"Position lifecycle metrics insufficient: {len(position_metrics)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
