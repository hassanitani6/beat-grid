import os
import sys
from pathlib import Path

import pytest

from beat_grid.cli import _atomic


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
@pytest.mark.parametrize("umask, expected", [(0o022, 0o644), (0o002, 0o664), (0o077, 0o600)])
def test_outputs_get_the_usual_permissions(tmp_path, umask, expected):
    dest = tmp_path / "song.beats.json"
    old = os.umask(umask)
    try:
        _atomic(dest, lambda p: Path(p).write_text("{}", encoding="utf-8"))
    finally:
        os.umask(old)
    assert dest.stat().st_mode & 0o777 == expected
