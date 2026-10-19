"""Logic tests for DecayWatch."""

from __future__ import annotations

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
    rows = []
    for i in range(5):
        rows.append(snap(f"a{i}", "original", segment="a"))
        rows.append(snap(f"a{i}", "fresh", segment="a"))
    for i in range(5):
        rows.append(snap(f"b{i}", "original", segment="b"))
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
