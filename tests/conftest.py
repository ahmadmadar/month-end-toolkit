import pytest

from toolkit.apikey import KEY_NAME


@pytest.fixture
def no_key(monkeypatch):
    """Start with the key unset and remove anything load_dotenv adds once the test ends."""
    monkeypatch.setenv(KEY_NAME, "placeholder")  # recorded, so teardown restores the original
    monkeypatch.delenv(KEY_NAME)
