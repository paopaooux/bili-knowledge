from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    source_output = tmp_path / "source-output"
    knowledge = tmp_path / "knowledge"
    data.mkdir()
    source_output.mkdir()
    knowledge.mkdir()
    return Settings(
        data_dir=data,
        source_output_dir=source_output,
        knowledge_base_dir=knowledge,
    )
