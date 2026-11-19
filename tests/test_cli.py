"""CLI tests for DecayWatch."""

from __future__ import annotations

import csv
import json

import pytest

from decaywatch.cli import main


def write_csv(tmp_path, content: str):
    p = tmp_path / "data.csv"
    p.write_text(content, encoding="utf-8")
    return p


DECAY_CSV = (
    "id,snapshot,text\n"
    "r1,original,first original body\n"
    "r2,original,second original body\n"
    "r3,original,third original body\n"
    "r1,fresh,first original body\n"
)


def test_json_output(tmp_path, capsys):
    p = write_csv(tmp_path, DECAY_CSV)
    assert main([str(p), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool"] == "decaywatch"
    assert abs(payload["summary"]["survival_rate"] - 1 / 3) < 0.001


def test_fail_on_high(tmp_path):
    p = write_csv(tmp_path, DECAY_CSV)
    assert main([str(p), "--fail-on", "high"]) == 1
    assert main([str(p), "--fail-on", "none"]) == 0


def test_csv_output(tmp_path, capsys):
    p = write_csv(tmp_path, DECAY_CSV)
    assert main([str(p), "--format", "csv"]) == 0
    rows = list(csv.DictReader(capsys.readouterr().out.splitlines()))
    assert rows


def test_segment_flag(tmp_path, capsys):
    content = "id,snapshot,segment\nr1,original,news\nr2,original,blog\nr1,fresh,news\nr2,fresh,blog\n"
    p = write_csv(tmp_path, content)
    assert main([str(p), "--segment-column", "segment", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "news" in payload["summary"]["by_segment"]


def test_direct_mode_via_config(tmp_path, capsys):
    p = write_csv(tmp_path, DECAY_CSV)
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"mode": "direct"}), encoding="utf-8")
    assert main([str(p), "--config", str(cfg), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["rechecks"] == "disabled"


def test_missing_file_returns_two(tmp_path):
    assert main([str(tmp_path / "nope.csv")]) == 2


def test_version(capsys):
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0
    assert "decaywatch" in capsys.readouterr().out


# --- 0.2.0 CLI behavior ----------------------------------------------------


def _write_config(tmp_path, options):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps(options), encoding="utf-8")
    return cfg


def test_json_output_has_schema_fields(tmp_path, capsys):
    p = write_csv(tmp_path, DECAY_CSV)
    assert main([str(p), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["result_schema_version"] == "1.1"
    assert payload["summary"]["skipped"] is False
    assert payload["summary"]["skip_reason"] is None


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"max_examples": "many"}, "must be an integer"),
        ({"id_column": ["id"]}, "must be a string"),
        ({"drift_columns": [1, 2]}, "must be a string or a list of strings"),
        ({"mode": 42}, "must be a string"),
    ],
)
def test_invalid_config_value_types_exit_two(tmp_path, capsys, options, expected):
    p = write_csv(tmp_path, DECAY_CSV)
    cfg = _write_config(tmp_path, options)
    assert main([str(p), "--config", str(cfg)]) == 2
    err = capsys.readouterr().err
    assert expected in err
    assert next(iter(options)) in err


def test_new_options_via_cli_flags_and_config(tmp_path, capsys):
    content = (
        "id,snapshot,captured_at,source_type,body,author\n"
        "r1,original,2025-01-01,gov.gov,Hello world,ann\n"
        "r2,original,2025-01-01,example.com,Same text,bob\n"
        "r3,original,2025-01-01,edu.edu,Another body,cat\n"
        "r1,fresh,2025-04-11,gov.gov,Hello brave world,anne\n"
        "r2,fresh,2025-04-11,example.com,Same text,bob\n"
    )
    p = write_csv(tmp_path, content)
    cfg = _write_config(tmp_path, {"text_column": "body", "drift_columns": ["author"]})
    args = [
        str(p),
        "--format",
        "json",
        "--config",
        str(cfg),
        "--date-column",
        "captured_at",
        "--content-column",
        "body",
        "--source-type-column",
        "source_type",
    ]
    assert main(args) == 0
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert summary["content_drift_count"] == 1
    assert summary["survival_curve"]["day_365"] == 0.6667
    assert summary["half_life_days"] is None  # 2/3 survival never reached 0.5
    assert summary["annualized_loss_pct"] > 0
    assert summary["source_type_risk"]["high_risk"] == 1
    assert summary["representativity"]["field"] == "body"
    assert {d["field"] for d in summary["metadata_drift"]} == {"author"}


def test_invalid_config_value_rejected_even_when_flag_overrides(tmp_path, capsys):
    p = write_csv(tmp_path, DECAY_CSV)
    cfg = _write_config(tmp_path, {"id_column": ["id"]})
    assert main([str(p), "--config", str(cfg), "--id-column", "id"]) == 2
    assert "id_column" in capsys.readouterr().err


def test_invalid_config_does_not_print_report(tmp_path, capsys):
    p = write_csv(tmp_path, DECAY_CSV)
    cfg = _write_config(tmp_path, {"max_examples": "many"})
    assert main([str(p), "--config", str(cfg), "--format", "json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "decaywatch:" in captured.err
