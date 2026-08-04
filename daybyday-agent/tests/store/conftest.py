"""store 测试共享 fixtures。"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from store.db import init_db


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """每个测试一个临时 db，跑完迁移，结束关闭。"""
    db = tmp_path / "test.sqlite3"
    c = init_db(db)
    yield c
    c.close()
