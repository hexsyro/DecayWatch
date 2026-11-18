"""Logic tests for DecayWatch."""

from __future__ import annotations

import pytest

from decaywatch import RESULT_SCHEMA_VERSION, ToolResult, __version__
from decaywatch.logic import DecayWatchLogic, run


def snap(id_, snapshot, **kw):
    row = {"id": id_, "snapshot": snapshot}
    row.update(kw)
    return row


def test_survival_rate_basic():
    rows = [
        snap("r1", "original"),
        snap("r2", "original"),
        snap("r3", "original"),
        snap("r4", "original"),
        snap("r1", "fresh"),
        snap("r2", "fresh"),
        snap("r3", "fresh"),
    ]
    result = run(rows)
    assert result.summary["original_records"] == 4
    assert result.summary["surviving_records"] == 3
    assert result.summary["survival_rate"] == 0.75


def test_vanished_records_become_purge_candidates():
    rows = [
        snap("r1", "original"),
        snap("r2", "original"),
        snap("r1", "fresh"),
    ]
    result = run(rows)
    purge = [f for f in result.findings if f["metadata"].get("check") == "purge_list"]
    assert purge
    assert any(f["record_id"] == "r2" for f in purge)
    assert result.summary["purge_count"] == 1
    assert "r2" in result.summary["purge_preview"]


def test_low_survival_raises_high_finding():
    rows = [snap("r1", "original"), snap("r2", "original"), snap("r3", "original"), snap("r1", "fresh")]
    result = run(rows)
    high = [f for f in result.findings if f["severity"] == "high" and f["metadata"].get("check") == "survival"]
    assert high
    assert result.summary["survival_rate"] < 0.5


def test_segment_breakdown_reported():
    rows = [
        snap("r1", "original", segment="news"),
        snap("r2", "original", segment="blog"),
        snap("r1", "fresh", segment="news"),
        snap("r2", "fresh", segment="blog"),
    ]
    result = run(rows, {"segment_column": "segment"})
    by_seg = result.summary["by_segment"]
    assert set(by_seg) == {"news", "blog"}
    assert by_seg["news"]["survival_rate"] == 1.0


def test_heavy_segment_decay_flagged():
    rows = [
        snap("a1", "original", segment="news"),
        snap("a2", "original", segment="news"),
        snap("b1", "original", segment="blog"),
        snap("b2", "original", segment="blog"),
        snap("a1", "fresh", segment="news"),
        snap("a2", "fresh", segment="news"),
    ]
    result = run(rows, {"segment_column": "segment"})
    high = [f for f in result.findings if f["severity"] == "high" and f["metadata"].get("check") == "survival"]
    assert any("blog" in f["message"] for f in high)


def test_metadata_drift_flagged():
    rows = [
        snap("r1", "original", author="ann"),
        snap("r2", "original", author="bob"),
        snap("r1", "fresh", author="anne"),
        snap("r2", "fresh", author="bob"),
    ]
    result = run(rows)
    drift = [f for f in result.findings if f["metadata"].get("check") == "metadata_drift"]
    assert any(f["field"] == "author" for f in drift)
    assert result.summary["metadata_drift"][0]["field"] == "author"


def test_status_column_mode():
    rows = [
        {"id": "r1", "status": "present"},
        {"id": "r2", "status": "removed"},
        {"id": "r3", "status": "present"},
    ]
    result = run(rows, {"status_column": "status"})
    assert result.summary["original_records"] == 3
    assert result.summary["surviving_records"] == 2
    assert result.summary["purge_count"] == 1


def test_direct_mode_disabled_with_warning():
    result = run([snap("r1", "original")], {"mode": "direct"})
    assert result.status == "success"
    assert result.summary["rechecks"] == "disabled"
    assert any("terms" in w for w in result.warnings)


def test_no_markers_warns():
    result = run([{"id": "r1", "text": "hello"}])
    assert result.findings == []
    assert any("No snapshot markers" in w for w in result.warnings)


def test_single_snapshot_value_warns():
    rows = [snap("r1", "original"), snap("r2", "original")]
    result = run(rows, {"snapshot_column": "snapshot"})
    assert result.findings == []
    assert any("fewer than 2" in w for w in result.warnings)


def test_fresh_only_records_warned():
    rows = [
        snap("r1", "original"),
        snap("r2", "original"),
        snap("r1", "fresh"),
        snap("x1", "fresh"),
        snap("x2", "fresh"),
    ]
    result = run(rows)
    assert result.summary["fresh_only_count"] == 2
    assert any("only in the fresh snapshot" in w for w in result.warnings)


def test_representativity_fields():
    rows = [
        snap("r1", "original", text="short"),
        snap("r2", "original", text="a much longer piece of text here"),
        snap("r1", "fresh", text="short"),
        snap("r2", "fresh", text="a much longer piece of text here"),
    ]
    rep = run(rows).summary["representativity"]
    assert rep["field"] == "text"
    assert "ks_statistic" in rep
    assert rep["original_count"] == 2


def test_segment_heterogeneity_needs_enough_data():
    rows = [snap("r1", "original", segment="a"), snap("r1", "fresh", segment="a")]
    assert run(rows, {"segment_column": "segment"}).summary["segment_heterogeneity"] is None


def test_segment_heterogeneity_detects_difference():
    # Expected cell counts must be >= 5: 10 originals per segment, split 9/1
    # and 1/9 gives each expected cell exactly 5.
    rows = []
    for i in range(10):
        rows.append(snap(f"a{i}", "original", segment="a"))
        if i < 9:
            rows.append(snap(f"a{i}", "fresh", segment="a"))
    for i in range(10):
        rows.append(snap(f"b{i}", "original", segment="b"))
        if i >= 9:
            rows.append(snap(f"b{i}", "fresh", segment="b"))
    result = run(rows, {"segment_column": "segment"})
    het = result.summary["segment_heterogeneity"]
    assert het is not None
    assert het["heterogeneous"] is True


def test_wilson_bounds_in_summary():
    rows = [snap("r1", "original"), snap("r2", "original"), snap("r1", "fresh")]
    summary = run(rows).summary
    assert summary["survival_wilson_low"] <= summary["survival_rate"] <= summary["survival_wilson_high"]


def test_run_returns_toolresult():
    result = DecayWatchLogic().run([{"id": "r1", "text": "x"}], {})
    assert result.status == "success"
    assert isinstance(result.findings, list)


# --- 0.2.0 shared result contract -----------------------------------------

def test_shared_schema_fields_and_exports():
    assert __version__ == "0.2.0"
    assert RESULT_SCHEMA_VERSION == "1.1"
    result = run([snap("r1", "original"), snap("r1", "fresh")])
    assert isinstance(result, ToolResult)
    assert result.summary["result_schema_version"] == "1.1"
    assert result.summary["skipped"] is False
    assert result.summary["skip_reason"] is None
    assert result.status == "success"


@pytest.mark.parametrize(
    ("rows", "options", "reason"),
    [
        ([snap("r1", "original")], {"mode": "direct"}, "direct_recheck_disabled"),
        ([{"id": "r1", "text": "x"}], {}, "no_snapshot_markers"),
        ([snap("r1", "original")], {}, "single_snapshot_value"),
    ],
)
def test_skipped_runs_keep_success_status(rows, options, reason):
    result = run(rows, options)
    assert result.status == "success"
    assert result.summary["result_schema_version"] == "1.1"
    assert result.summary["skipped"] is True
    assert result.summary["skip_reason"] == reason


# --- Fixed behaviors -------------------------------------------------------

def test_purge_overflow_points_to_purge_ids():
    rows = [snap(f"r{i}", "original") for i in range(7)] + [snap("r0", "fresh")]
    result = run(rows, {"max_examples": 2})
    overflow = [f for f in result.findings if f["metadata"].get("overflow")]
    assert overflow
    assert "summary.purge_ids" in overflow[0]["message"]
    assert "Pro export" not in overflow[0]["message"]
    assert len(result.summary["purge_ids"]) == 6


def test_chi_square_skipped_when_expected_counts_low():
    rows = []
    for i in range(5):
        rows.append(snap(f"a{i}", "original", segment="a"))
        rows.append(snap(f"a{i}", "fresh", segment="a"))
    for i in range(5):
        rows.append(snap(f"b{i}", "original", segment="b"))
    result = run(rows, {"segment_column": "segment"})
    assert result.summary["segment_heterogeneity"] is None
    assert any("expected cell count is below 5" in w for w in result.warnings)


def test_metadata_drift_excludes_structural_columns():
    rows = [
        snap("r1", "original", segment="news", status="present", author="ann", text="a"),
        snap("r1", "fresh", segment="blog", status="removed", author="anne", text="b"),
    ]
    result = run(rows, {"status_column": "status", "segment_column": "segment"})
    fields = {d["field"] for d in result.summary["metadata_drift"]}
    assert fields == {"author", "text"}
    assert "segment" not in fields and "status" not in fields and "snapshot" not in fields


def test_metadata_drift_columns_option_selects_fields():
    rows = [
        snap("r1", "original", author="ann", title="old"),
        snap("r1", "fresh", author="anne", title="new"),
    ]
    result = run(rows, {"drift_columns": ["title"]})
    fields = {d["field"] for d in result.summary["metadata_drift"]}
    assert fields == {"title"}


def test_representativity_text_column_option():
    rows = [
        snap("r1", "original", note="A much longer note than the body", text="hi"),
        snap("r1", "fresh", note="A much longer note than the body", text="hi"),
    ]
    result = run(rows, {"text_column": "text"})
    assert result.summary["representativity"]["field"] == "text"
    assert not any("auto-selected" in w for w in result.warnings)


def test_representativity_auto_select_warns():
    rows = [
        snap("r1", "original", note="A much longer note than the body", text="hi"),
        snap("r1", "fresh", note="A much longer note than the body", text="hi"),
    ]
    result = run(rows)
    assert result.summary["representativity"]["field"] == "note"
    assert any("auto-selected 'note'" in w for w in result.warnings)


# --- New features ----------------------------------------------------------

def test_survival_curve_and_decay_metrics():
    rows = [
        snap("r1", "original", captured_at="2025-01-01"),
        snap("r2", "original", captured_at="2025-01-01"),
        snap("r3", "original", captured_at="2025-01-01"),
        snap("r4", "original", captured_at="2025-01-01"),
        snap("r1", "fresh", captured_at="2025-04-11"),
        snap("r2", "fresh", captured_at="2025-04-11"),
    ]
    summary = run(rows, {"date_column": "captured_at"}).summary
    curve = summary["survival_curve"]
    assert curve == {"day_0": 1.0, "day_30": 1.0, "day_90": 1.0, "day_365": 0.5}
    assert summary["half_life_days"] == pytest.approx(100.0)
    assert summary["annualized_loss_pct"] == pytest.approx((1 - 0.5 ** (365 / 100)) * 100, abs=0.01)


def test_survival_curve_carries_forward_and_interpolates_half_life():
    rows = [
        snap("r1", "original", captured_at="2025-01-01"),
        snap("r2", "original", captured_at="2025-01-01"),
        snap("r3", "original", captured_at="2025-01-01"),
        snap("r4", "original", captured_at="2025-01-01"),
        snap("r1", "fresh", captured_at="2025-04-01"),  # 90 days
        snap("r2", "fresh", captured_at="2025-04-01"),
        snap("r3", "fresh", captured_at="2025-04-01"),
    ]
    summary = run(rows, {"date_column": "captured_at"}).summary
    assert summary["survival_curve"]["day_30"] == 1.0
    assert summary["survival_curve"]["day_90"] == pytest.approx(0.75)
    assert summary["survival_curve"]["day_365"] == pytest.approx(0.75)
    assert summary["half_life_days"] is None  # survival never reached 0.5
    expected = (1 - 0.75 ** (365 / 90)) * 100
    assert summary["annualized_loss_pct"] == pytest.approx(expected, abs=0.01)


def test_survival_curve_warns_on_short_interval():
    rows = [
        snap("r1", "original", captured_at="2025-01-01"),
        snap("r1", "fresh", captured_at="2025-01-11"),
    ]
    result = run(rows, {"date_column": "captured_at"})
    assert result.summary["survival_curve"] is None
    assert result.summary["half_life_days"] is None
    assert result.summary["annualized_loss_pct"] is None
    assert any("<30" in w for w in result.warnings)


def test_survival_curve_warns_on_missing_or_unparsable_dates():
    missing = run([snap("r1", "original"), snap("r1", "fresh")], {"date_column": "captured_at"})
    assert any("date_column" in w for w in missing.warnings)
    assert missing.summary["survival_curve"] is None

    bad = run(
        [snap("r1", "original", captured_at="nope"), snap("r1", "fresh", captured_at="nope")],
        {"date_column": "captured_at"},
    )
    assert any("could not be parsed" in w for w in bad.warnings)
    assert bad.summary["annualized_loss_pct"] is None


def test_content_drift_finding_and_count():
    rows = [
        snap("r1", "original", body="Hello world"),
        snap("r2", "original", body="Same   text"),
        snap("r1", "fresh", body="Hello brave world"),
        snap("r2", "fresh", body=" Same text "),  # whitespace-only difference
    ]
    result = run(rows, {"content_column": "body"})
    assert result.summary["content_drift_count"] == 1
    assert result.summary["content_drift_examples"] == ["r1"]
    drift = [f for f in result.findings if f["metadata"].get("check") == "content_drift"]
    assert len(drift) == 1
    assert drift[0]["severity"] == "low"
    assert "content drift" in drift[0]["message"].lower()
    assert "not link rot" in drift[0]["message"].lower()
    assert drift[0]["metadata"]["examples"] == ["r1"]


def test_content_drift_disabled_without_option():
    rows = [snap("r1", "original", body="a"), snap("r1", "fresh", body="b")]
    result = run(rows)
    assert result.summary["content_drift_count"] == 0
    assert not [f for f in result.findings if f["metadata"].get("check") == "content_drift"]


def test_source_type_risk_stratification_and_warning():
    rows = [
        snap("r1", "original", source_type="example.com"),
        snap("r2", "original", source_type="news.com"),
        snap("r3", "original", source_type="db-driven"),
        snap("r4", "original", source_type="university.edu"),
        snap("r1", "fresh", source_type="example.com"),
    ]
    result = run(rows, {"source_type_column": "source_type"})
    risk = result.summary["source_type_risk"]
    assert risk["column"] == "source_type"
    assert risk["high_risk"] == 3
    assert risk["durable"] == 1
    assert risk["high_risk_share"] == 0.75
    assert risk["by_type"]["example.com"] == "high_risk"
    assert any("Source-type risk" in w for w in result.warnings)


def test_source_type_risk_reuses_segment_column():
    rows = [
        snap("r1", "original", segment="gov"),
        snap("r2", "original", segment="pdf"),
        snap("r1", "fresh", segment="gov"),
        snap("r2", "fresh", segment="pdf"),
    ]
    result = run(rows, {"segment_column": "segment"})
    risk = result.summary["source_type_risk"]
    assert risk["column"] == "segment"
    assert risk["by_type"] == {"gov": "durable", "pdf": "high_risk"}


def test_source_type_risk_durable_sources_do_not_warn():
    rows = [
        snap("r1", "original", source_type="gov"),
        snap("r2", "original", source_type="edu"),
        snap("r1", "fresh", source_type="gov"),
        snap("r2", "fresh", source_type="edu"),
    ]
    result = run(rows, {"source_type_column": "source_type"})
    assert result.summary["source_type_risk"]["high_risk_share"] == 0.0
    assert not any("Source-type risk" in w for w in result.warnings)


def test_malformed_option_values_never_raise():
    options = {
        "mode": 123,
        "id_column": 7,
        "snapshot_column": ["snapshot"],
        "status_column": {"status": 1},
        "segment_column": 4.5,
        "date_column": [],
        "content_column": {"bad": True},
        "text_column": 99,
        "drift_columns": 42,
        "present_values": {"present": 1},
        "original_value": ["original"],
        "fresh_value": {"fresh": 1},
        "max_examples": "not-an-int",
    }
    result = run([snap("r1", "original"), snap("r1", "fresh")], options)
    assert isinstance(result, ToolResult)
    assert result.summary["result_schema_version"] == "1.1"
    assert result.status == "success"
