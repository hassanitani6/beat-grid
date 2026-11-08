import json
import math

import numpy as np
import pytest
import soundfile as sf

from beat_grid import grid as G
from beat_grid.grid import BeatGrid, analyze_track, grid_from_dict, load_grid, shot_durations, snap, track_energy
from conftest import drum_loop


def test_analyze_finds_tempo_and_bar_starts(tmp_path):
    g = analyze_track(drum_loop(tmp_path / "a.wav", bpm=120, kick_beat=1))
    assert abs(g.bpm - 120) < 4
    assert len(g.beats) > 30
    gaps = np.diff(g.downbeats)
    assert np.all(np.abs(gaps - 2.0) < 0.1)  # a bar of four beats at 120 BPM lasts two seconds
    # the downbeat phase follows the kick (beat 1 of every 4 here: 0.5 s, 2.5 s, ...)
    assert min(abs((g.downbeats[0] - 0.5) % 2.0), abs((g.downbeats[0] - 0.5) % 2.0 - 2.0)) < 0.08
    assert g.duration == pytest.approx(20, abs=0.01)


def test_analyze_silence_is_a_clean_error(tmp_path):
    p = tmp_path / "quiet.wav"
    sf.write(p, np.zeros(22050 * 5), 22050)
    with pytest.raises(ValueError, match="no beats"):
        analyze_track(p)


def test_analyze_refuses_very_long_tracks_before_decoding(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "MAX_TRACK_SECONDS", 10)
    with pytest.raises(ValueError, match="minutes are supported|minutes long"):
        analyze_track(drum_loop(tmp_path / "long.wav", seconds=20))


def test_snap_lands_on_frame_grid():
    assert snap(1.0, 25, 1) == pytest.approx(0.96)
    assert snap(1.013, 25, 0) == pytest.approx(1.0)
    assert snap(0.01, 25, 1) == 0.0


def test_shot_durations_frame_aligned():
    g = BeatGrid(bpm=120, beats=[i * 0.5 for i in range(40)], downbeats=[i * 2.0 for i in range(10)], duration=20)
    d = shot_durations(g, music_offset=2.0, beat_counts=[4, 2, 2, 1, 1], lead_frames=1, fps=25)
    assert d == [1.96, 1.0, 1.0, 0.48, 0.52]  # half a beat is 12.5 frames at 25 fps; cuts land on whole frames
    assert all(abs(x * 25 - round(x * 25)) < 1e-6 for x in d)
    assert shot_durations(g, 0.0, [2, 2], lead_frames=0, fps=30) == [1.0, 1.0]


def test_shot_durations_follow_measured_not_constant_tempo():
    g = BeatGrid(bpm=120, beats=[0.0, 0.5, 1.04, 1.5, 2.08], downbeats=[0.0], duration=3)
    assert shot_durations(g, 0.0, [2, 2], lead_frames=0, fps=25) == [1.04, 1.04]


def test_shot_durations_track_too_short():
    g = BeatGrid(bpm=120, beats=[i * 0.5 for i in range(8)], downbeats=[0, 2], duration=4)
    with pytest.raises(ValueError, match="too short"):
        shot_durations(g, 0.0, [4, 4, 4])
    with pytest.raises(ValueError, match="no beat after"):
        shot_durations(g, 10.0, [1])


GOOD = {"bpm": 120.0, "beats": [0.5, 1.0, 1.52], "downbeats": [0.5], "duration": 3.0}


@pytest.mark.parametrize("change, message", [
    ({"duration": float("nan")}, "duration"),
    ({"duration": 0}, "duration"),
    ({"duration": 10 ** 9}, "duration"),
    ({"duration": True}, "duration"),
    ({"beats": [1.0, 0.5]}, "increasing"),
    ({"beats": [-1.0, 0.5]}, "negative"),
    ({"beats": [0.5, float("inf")]}, "finite"),
    ({"beats": [0.5, "1"]}, "finite"),
    ({"beats": [0.5, 4.0]}, "after the end"),
    ({"beats": []}, "empty"),
    ({"beats": "0.5"}, "list"),
    ({"downbeats": [2.0, 1.0]}, "increasing"),
    ({"bpm": -5}, "bpm"),
])
def test_grid_validation(change, message):
    with pytest.raises(ValueError, match=message):
        grid_from_dict({**GOOD, **change})


def test_grid_validation_lists_every_problem():
    with pytest.raises(ValueError) as e:
        grid_from_dict({"bpm": -1, "beats": [2.0, 1.0], "duration": 3})
    assert "bpm" in str(e.value) and "increasing" in str(e.value)


def test_grid_accepts_accents_as_downbeats():
    g = grid_from_dict({"bpm": 120.0, "beats": [0.5, 1.0], "accents": [0.5], "duration": 2.0})
    assert g.downbeats == [0.5]


def test_grid_too_many_beats(monkeypatch):
    monkeypatch.setattr(G, "MAX_BEATS", 2)
    with pytest.raises(ValueError, match="at most 2"):
        grid_from_dict(GOOD)


def test_load_grid_bad_json_is_a_clean_error(tmp_path):
    p = tmp_path / "x.beats.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="couldn't read beat grid x.beats.json"):
        load_grid(p)
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="x.beats.json: a beat grid must be a JSON object"):
        load_grid(p)


def test_grid_json_round_trip(tmp_path):
    p = tmp_path / "g.beats.json"
    p.write_text(G.grid_json(grid_from_dict(GOOD)), encoding="utf-8")
    assert json.loads(p.read_text(encoding="utf-8")) == GOOD
    assert load_grid(p) == grid_from_dict(GOOD)


def test_energy_blocks_cover_the_track_and_see_the_build(tmp_path):
    p = tmp_path / "build.wav"
    sr = 22050
    drum_loop(p, bpm=120, seconds=16, sr=sr)
    y, _ = sf.read(p)
    y[len(y) // 2:] *= 3.0  # second half three times louder: a "drop"
    sf.write(p, y, sr, subtype="PCM_16")
    g = BeatGrid(bpm=120, beats=[i * 0.5 for i in range(32)], downbeats=[i * 2.0 for i in range(8)], duration=16)
    rows = track_energy(p, g, bars=2)
    assert [(r["start"], r["end"]) for r in rows] == [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0), (12.0, 16.0)]
    assert rows[3]["rms_db"] - rows[0]["rms_db"] == pytest.approx(20 * math.log10(3), abs=0.5)


def test_energy_pickup_before_first_bar_is_its_own_block():
    g = BeatGrid(bpm=120, beats=[0.5, 1.0], downbeats=[1.0, 3.0], duration=5)
    assert G._blocks(g, 1) == [(0.0, 1.0), (1.0, 3.0), (3.0, 5)]


def test_default_fps_is_30():
    from beat_grid.grid import DEFAULT_FPS
    g = BeatGrid(bpm=120, beats=[i * 0.5 for i in range(40)], downbeats=[i * 2.0 for i in range(10)], duration=20)
    d = shot_durations(g, music_offset=2.0, beat_counts=[1, 1], lead_frames=1)
    assert DEFAULT_FPS == 30
    # whole 30 fps frames; the opening cut cannot move before 0 s, so shot 1 is a frame short
    assert [round(x * 30) for x in d] == [14, 15]
    assert all(abs(x * 30 - round(x * 30)) < 0.01 for x in d)
