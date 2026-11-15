from __future__ import annotations

from pathlib import Path

import pytest

import export_notes

SOURCE = Path(__file__).parent / "fixtures" / "campaign_source"


@pytest.fixture()
def exported(tmp_path: Path) -> Path:
    dest = tmp_path / "export"
    export_notes.run_export(SOURCE, dest)
    return dest
