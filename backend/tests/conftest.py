from pathlib import Path

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    knowledge = tmp_path / "knowledge"
    data.mkdir()
    knowledge.mkdir()
    return Settings(data_dir=data, knowledge_base_dir=knowledge)
