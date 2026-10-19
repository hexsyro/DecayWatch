"""CLI tests for DecayWatch."""

from __future__ import annotations

import csv
import json

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
    content = (
        "id,snapshot,segment\n"
        "r1,original,news\n"
        "r2,original,blog\n"
        "r1,fresh,news\n"
        "r2,fresh,blog\n"
    )
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
