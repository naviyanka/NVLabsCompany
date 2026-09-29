import pytest
from nexus_voice import winspeech


@pytest.fixture(autouse=True)
def no_os_voices(monkeypatch):
    """Tests must not depend on the voices installed on the machine running them."""
    monkeypatch.setattr(winspeech, "available", lambda: False)
    monkeypatch.setattr(winspeech, "_cache", None)
