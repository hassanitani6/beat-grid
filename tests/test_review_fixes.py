"""Regression tests for the pre-release review findings."""

import json
import math

import numpy as np
import pytest
import soundfile as sf

from beat_grid import grid as G
from beat_grid.cli import main


def test_analyze_output_always_reloads():
    # a beat in the final fraction of a millisecond, past the duration once rounded to 3 decimals
    seconds = 10.0004
    g = G.finish_grid(120.0, np.array([0.5, 1.0, 10.00036]), 0, seconds)
    assert G.grid_from_dict(json.loads(G.grid_json(g))) == g
    assert g.beats[-1] <= g.duration


def test_finish_grid_matches_plain_rounding_otherwise():
    g = G.finish_grid(117.4532, np.array([0.51234, 1.02345, 1.53456, 2.04567, 2.55678]), 1, 3.00049)
    assert g == G.BeatGrid(117.45, [0.5123, 1.0234, 1.5346, 2.0457, 2.5568], [1.0234], 3.0)


def test_memory_cap_counts_channels_and_rate(tmp_path, monkeypatch):
    p = tmp_path / "wide.wav"
    sf.write(p, np.zeros((48000, 8)), 48000)  # 1 s, 8 channels = 384,000 samples
    monkeypatch.setattr(G, "MAX_DECODED_SAMPLES", 100_000)
    with pytest.raises(ValueError, match="too large"):
        G.analyze_track(p)


def test_grid_file_size_cap(tmp_path, monkeypatch):
    p = tmp_path / "big.json"
    p.write_text(json.dumps({"bpm": 1, "beats": [0.5], "downbeats": [], "duration": 1.0, "pad": "x" * 500}),
                 encoding="utf-8")
    monkeypatch.setattr(G, "MAX_GRID_BYTES", 100)
    with pytest.raises(ValueError, match="bytes"):
        G.load_grid(p)


def test_deeply_nested_grid_is_a_clean_error(tmp_path, capsys):
    p = tmp_path / "deep.json"
    p.write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
    assert main(["click", str(p), "-o", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "nested too deeply" in err and "Traceback" not in err


GRID = {"bpm": 120.0, "beats": [i * 0.5 for i in range(20)], "downbeats": [i * 2.0 for i in range(5)], "duration": 10.0}


@pytest.fixture
def grid_file(tmp_path):
    p = tmp_path / "song.beats.json"
    p.write_text(json.dumps(GRID), encoding="utf-8")
    return p


@pytest.mark.parametrize("offset", ["-1", "nan", "inf"])
def test_offset_must_be_finite_and_not_negative(grid_file, capsys, offset):
    assert main(["cuts", str(grid_file), "--beats", "1", "--offset", offset]) == 2
    assert "--offset must be" in capsys.readouterr().err


def test_zero_frame_shot_is_refused(grid_file, capsys):
    assert main(["cuts", str(grid_file), "--beats", "1,1", "--fps", "1", "--lead", "1"]) == 2
    assert "0 frames" in capsys.readouterr().err


def test_temp_file_name_is_unique_and_never_clobbers_a_user_file(grid_file, tmp_path):
    out = tmp_path / "c"
    out.mkdir()
    mine = out / "song.click.wav.part"  # a file the user happens to have, with the old fixed temporary name
    mine.write_bytes(b"user data")
    assert main(["click", str(grid_file), "-o", str(out)]) == 0
    assert mine.read_bytes() == b"user data"
    assert sorted(p.name for p in out.iterdir()) == ["song.click.wav", "song.click.wav.part"]


@pytest.mark.parametrize("name", ["con .wav", "nul..wav", "COM1 .flac", "aux"])
def test_reserved_names_with_trailing_dots_or_spaces(name):
    from beat_grid.cli import reserved_on_windows
    assert reserved_on_windows(name.rsplit(".", 1)[0] + ".beats.json" if "." in name else name)


def test_reserved_check_has_no_false_positives():
    from beat_grid.cli import reserved_on_windows
    assert not any(map(reserved_on_windows, ["console.beats.json", "aux_mix.beats.json", "com10.beats.json"]))


def test_accent_count_reports_only_downbeats_on_a_beat(tmp_path, capsys):
    p = tmp_path / "g.json"
    p.write_text(json.dumps({**GRID, "downbeats": [0.0, 2.0, 3.3]}), encoding="utf-8")
    assert main(["click", str(p), "-o", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "(2 accented)" in captured.out and "1 downbeat(s)" in captured.err


def test_energy_does_not_call_memory_errors_decode_errors(tmp_path, monkeypatch, capsys):
    from conftest import drum_loop
    song = drum_loop(tmp_path / "s.wav", seconds=4)

    def no_memory(*a, **k):
        raise MemoryError

    monkeypatch.setattr(G, "analyze_track", no_memory)
    assert main(["energy", str(song)]) == 2
    err = capsys.readouterr().err
    assert "not enough memory" in err and "decode" not in err


def test_energy_warns_when_grid_is_for_another_song(tmp_path, capsys):
    from conftest import drum_loop
    song = drum_loop(tmp_path / "s.wav", seconds=4)
    g = tmp_path / "other.beats.json"
    g.write_text(json.dumps(GRID), encoding="utf-8")  # a 10 s grid for a 4 s song
    assert main(["energy", str(song), "--grid", str(g)]) == 0
    assert "right grid" in capsys.readouterr().err


def test_unexpected_errors_are_not_hidden_as_decode_failures(tmp_path, monkeypatch):
    from conftest import drum_loop
    song = drum_loop(tmp_path / "s.wav", seconds=4)

    def bug(*a, **k):
        raise ZeroDivisionError

    monkeypatch.setattr(G, "analyze_track", bug)
    with pytest.raises(ZeroDivisionError):
        main(["analyze", str(song), "-o", str(tmp_path / "g")])


def test_demo_command_writes_a_loop_and_refuses_overwrite(tmp_path, capsys):
    assert main(["demo", "-o", str(tmp_path)]) == 0
    data, sr = sf.read(tmp_path / "demo.wav")
    assert sr == 44100 and math.isclose(len(data) / sr, 20.0)
    assert main(["demo", "-o", str(tmp_path)]) == 2
