
import pytest


@pytest.fixture
def tmp_store_dir(tmp_path):
    return str(tmp_path)
