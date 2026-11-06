import os
import shutil
import tempfile
from pathlib import Path

import pytest

# The package reads BIOSIGNAL_DATA when it is imported: point it to a temporary folder before any test imports it.
_TMP = Path(tempfile.mkdtemp(prefix="biosignal-test-"))
os.environ["BIOSIGNAL_DATA"] = str(_TMP)
os.environ.setdefault("BIOSIGNAL_CONTACT", "BioSignal-test test@example.org")


@pytest.fixture(autouse=True)
def clean_data():
    yield
    for p in _TMP.iterdir():
        shutil.rmtree(p) if p.is_dir() else p.unlink()
