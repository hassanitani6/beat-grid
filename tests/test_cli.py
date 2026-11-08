import json
import os

import numpy as np
import pytest
import soundfile as sf

from beat_grid import cli
from beat_grid.cli import main
from conftest import drum_loop

GRID = {"bpm": 120.0, "beats": [i * 0.5 for i in range(20)], "downbeats": [i * 2.0 for i in range(5)], "duration": 10.0}


@pytest.fixture
def grid_file(tmp_path):
    p = tmp_path / "song.beats.json"
    p.write_text(json.dumps(GRID), encoding="utf-8")
    return p


def test_analyze_writes_grid(song, tmp_path, capsys):
    out = tmp_path / "grids"
    assert main(["analyze", str(song), "-o", str(out)]) == 0
    g = json.loads((out / "loop.beats.json").read_text(encoding="utf-8"))
    assert set(g) == {"bpm", "beats", "downbeats", "duration"} and abs(g["bpm"] - 120) < 4
    assert "BPM" in capsys.readouterr().out
    assert not list(out.glob("*.part"))


def test_analyze_refuses_overwrite_then_overwrites(song, tmp_path, capsys):
    out = tmp_path / "g"
    out.mkdir()
    target = out / "loop.beats.json"
    target.write_text("keep", encoding="utf-8")
    assert main(["analyze", str(song), "-o", str(out)]) == 2
    assert "already exist" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "keep"
    assert main(["analyze", str(song), "-o", str(out), "--overwrite"]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["beats"]


def test_output_that_is_the_input_is_refused_even_with_overwrite(song, tmp_path, capsys):
    out = tmp_path / "g"
    out.mkdir()
    os.link(song, out / "loop.beats.json")  # the output name is another name for the song itself
    before = song.read_bytes()
    assert main(["analyze", str(song), "-o", str(out), "--overwrite"]) == 2
    assert "would replace an input" in capsys.readouterr().err
    assert song.read_bytes() == before


def test_two_songs_writing_one_grid_are_refused(tmp_path, capsys):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one = drum_loop(tmp_path / "a" / "Song.wav", seconds=4)
    two = drum_loop(tmp_path / "b" / "song.wav", seconds=4)
    out = tmp_path / "g"
    assert main(["analyze", str(one), str(two), "-o", str(out)]) == 2
    assert "would both write" in capsys.readouterr().err
    assert not out.exists()


def test_windows_reserved_name_is_refused(tmp_path, capsys):
    con = drum_loop(tmp_path / "con.wav", seconds=4)
    assert main(["analyze", str(con), "-o", str(tmp_path / "g")]) == 2
    assert "reserved device name" in capsys.readouterr().err


def test_out_dir_that_is_a_file(song, tmp_path, capsys):
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    assert main(["analyze", str(song), "-o", str(f)]) == 2
    assert "is not a folder" in capsys.readouterr().err


def test_missing_and_non_audio_inputs(tmp_path, capsys):
    assert main(["analyze", str(tmp_path / "nope.wav")]) == 2
    assert "not found" in capsys.readouterr().err
    txt = tmp_path / "notes.txt"
    txt.write_text("hi", encoding="utf-8")
    assert main(["analyze", str(txt)]) == 2
    assert "not an audio file" in capsys.readouterr().err


def test_undecodable_song_is_skipped_cleanly(tmp_path, capsys):
    bad = tmp_path / "broken.wav"
    bad.write_bytes(b"RIFF\x00\x00\x00\x00WAVEjunk")
    assert main(["analyze", str(bad), "-o", str(tmp_path / "g")]) == 1
    err = capsys.readouterr().err
    assert "broken.wav: skipped" in err and "Traceback" not in err
    assert not (tmp_path / "g" / "broken.beats.json").exists()


def test_interrupted_write_keeps_the_old_file_and_leaves_no_part(grid_file, tmp_path, monkeypatch):
    out = tmp_path / "c"
    out.mkdir()
    target = out / "song.click.wav"
    target.write_bytes(b"old")

    def boom(audio, path, sr=48000):
        path.write_bytes(b"half")
        raise KeyboardInterrupt

    monkeypatch.setattr("beat_grid.click.write_wav", boom)
    with pytest.raises(KeyboardInterrupt):
        main(["click", str(grid_file), "-o", str(out), "--overwrite"])
    assert target.read_bytes() == b"old"
    assert not list(out.glob("*.part"))


def test_click_from_grid(grid_file, tmp_path, capsys):
    assert main(["click", str(grid_file), "-o", str(tmp_path / "c")]) == 0
    data, sr = sf.read(tmp_path / "c" / "song.click.wav")
    assert sr == 48000 and len(data) == 10 * sr and np.max(np.abs(data)) > 0.1
    assert "20 clicks (5 accented)" in capsys.readouterr().out
    assert main(["click", str(grid_file), "-o", str(tmp_path / "c")]) == 2


def test_click_bad_grid_lists_problems(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"bpm": 120, "beats": [2, 1], "duration": "long"}), encoding="utf-8")
    assert main(["click", str(p)]) == 2
    err = capsys.readouterr().err
    assert "duration" in err and "Traceback" not in err


def test_cuts_text_and_json(grid_file, capsys):
    assert main(["cuts", str(grid_file), "--beats", "4,2,2,1,1"]) == 0
    out = capsys.readouterr().out
    assert "30 fps" in out  # phone-video default
    assert "4 beats -> 1.97 s (59 frames)" in out and "total 4.97 s" in out  # starts at the first bar, 0 s
    assert main(["cuts", str(grid_file), "--beats", "4,2,2,1,1", "--fps", "25"]) == 0
    out = capsys.readouterr().out
    assert "4 beats -> 1.96 s (49 frames)" in out and "total 4.96 s" in out  # the original tool's 25 fps
    assert main(["cuts", str(grid_file), "--beats", "2,2", "--offset", "1", "--fps", "30", "--lead", "0",
                 "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["shots"] == [{"beats": 2, "seconds": 1.0, "frames": 30}, {"beats": 2, "seconds": 1.0, "frames": 30}]


@pytest.mark.parametrize("args, message", [
    (["--beats", "4,x"], "whole numbers"),
    (["--beats", "4,0"], "1 beat or more"),
    (["--beats", ","], "at least one"),
    (["--beats", "40"], "too short"),
    (["--beats", "1", "--fps", "0"], "--fps"),
    (["--beats", "1", "--lead", "-1"], "--lead"),
])
def test_cuts_errors(grid_file, capsys, args, message):
    assert main(["cuts", str(grid_file), *args]) == 2
    assert message in capsys.readouterr().err


def test_cuts_too_many_shots(grid_file, capsys, monkeypatch):
    monkeypatch.setattr(cli, "MAX_SHOTS", 2)
    assert main(["cuts", str(grid_file), "--beats", "1,1,1"]) == 2
    assert "at most 2" in capsys.readouterr().err


def test_energy_with_and_without_grid(song, tmp_path, capsys):
    g = tmp_path / "loop.beats.json"
    g.write_text(json.dumps({"bpm": 120.0, "beats": [i * 0.5 for i in range(40)],
                             "downbeats": [i * 2.0 for i in range(10)], "duration": 20.0}), encoding="utf-8")
    assert main(["energy", str(song), "--grid", str(g), "--bars", "2", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 5 and rows[-1]["end"] == 20.0
    assert main(["energy", str(song)]) == 0
    assert "4-bar blocks" in capsys.readouterr().out
    assert main(["energy", str(song), "--bars", "0"]) == 2


def test_doctor(capsys):
    assert main(["doctor", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["audio_decoder"] == "ok" and "librosa" in report["packages"]


def test_doctor_redacts_home_and_email():
    from beat_grid.doctor import redact
    text = redact("/Users/someone/x C:\\Users\\someone\\y a.b@example.com token=abc")
    assert "someone" not in text and "example.com" not in text and "abc" not in text
