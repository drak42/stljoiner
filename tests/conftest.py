import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from make_test_parts import make_parts  # noqa: E402


@pytest.fixture(scope="session")
def scattered(tmp_path_factory) -> list[Path]:
    """Three pieces of the test part, each moved and rotated randomly."""
    return make_parts(tmp_path_factory.mktemp("scattered"), scatter=True)


@pytest.fixture(scope="session")
def in_place(tmp_path_factory) -> list[Path]:
    """Three pieces of the test part, still in their original positions."""
    return make_parts(tmp_path_factory.mktemp("in_place"), scatter=False)
