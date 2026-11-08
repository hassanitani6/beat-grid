import numpy as np
import pytest
import soundfile as sf


def drum_loop(path, bpm=120, seconds=20, sr=22050, kick_beat=0, seed=0):
    """Synthetic drums: a kick on one beat of every four, hi-hat noise on the others. No recorded audio."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int(seconds * sr))
    period, n = 60 / bpm, int(0.08 * sr)
    t = np.arange(n) / sr
    kick = np.sin(2 * np.pi * (60 + 60 * np.exp(-t * 30)) * t) * np.exp(-t * 25)
    hat = rng.standard_normal(n) * np.exp(-t * 120) * 0.3
    for k in range(int(seconds / period)):
        i = int(k * period * sr)
        seg = y[i:i + n]
        seg += 0.4 * (kick if k % 4 == kick_beat else hat)[:len(seg)]
    sf.write(path, y, sr, subtype="PCM_16")
    return path


@pytest.fixture
def song(tmp_path):
    return drum_loop(tmp_path / "loop.wav")
