import hashlib

import numpy as np
import pytest
import soundfile as sf

from beat_grid.click import click_samples, write_wav
from beat_grid.grid import grid_from_dict

GRID = grid_from_dict({"bpm": 120.0, "beats": [0.5, 1.0, 1.52, 2.07], "downbeats": [0.5], "duration": 3.0})


def onsets(data, sr, thresh=0.1):
    above = np.abs(data) > thresh
    rising = np.flatnonzero(above & ~np.concatenate(([False], above[:-1])))
    found, last = [], -1e9
    for i in rising:
        if i - last > 0.05 * sr:
            found.append(i / sr)
        last = i
    return found


def peak_near(data, sr, t, width=0.03):
    return float(np.max(np.abs(data[int(t * sr):int((t + width) * sr)])))


def test_clicks_at_measured_beats_not_constant_bpm(tmp_path):
    data, sr = sf.read(write_wav(click_samples(GRID), tmp_path / "c.wav"))
    assert [round(o, 2) for o in onsets(data, sr)] == [0.5, 1.0, 1.52, 2.07]


def test_downbeat_louder_than_beat(tmp_path):
    data, sr = sf.read(write_wav(click_samples(GRID), tmp_path / "c.wav"))
    assert peak_near(data, sr, 0.5) >= 1.8 * peak_near(data, sr, 1.0)


@pytest.mark.parametrize("sr", [44100, 48000])
def test_length_matches_duration(tmp_path, sr):
    data, got_sr = sf.read(write_wav(click_samples(GRID, sr), tmp_path / "c.wav", sr))
    assert got_sr == sr and data.ndim == 1 and len(data) == 3 * sr


def test_click_past_the_end_is_trimmed():
    g = grid_from_dict({"bpm": 60.0, "beats": [0.0, 0.999], "downbeats": [], "duration": 1.0})
    assert len(click_samples(g)) == 48000


def test_unsupported_sample_rate():
    with pytest.raises(ValueError, match="sample rate"):
        click_samples(GRID, 8000)


def test_click_samples_are_stable(tmp_path):
    """Golden check: the 16-bit samples match the recorded reference click track for this grid."""
    data, _ = sf.read(write_wav(click_samples(GRID), tmp_path / "c.wav"), dtype="int16")
    assert hashlib.sha256(data.tobytes()).hexdigest() == GOLDEN_SHA


GOLDEN_SHA = "f4a9886c2091aa351cb8f99835db1bd5f40417e0e662ecf8c8fb9d10069edb1f"
