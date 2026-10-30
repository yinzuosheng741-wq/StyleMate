import socket
from io import BytesIO

import pytest
from PIL import Image

from stylemate.demo.sample_data import sample_garments as build_sample_garments
from stylemate.repositories.session import SessionWardrobeRepository


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    """Fail even if application fallback code catches an accidental network call."""
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("network_disabled_in_offline_tests")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for key in ("LLM_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "VISION_API_KEY",
                "EMBEDDING_API_KEY", "AMAP_API_KEY", "GAODE_API_KEY"):
        monkeypatch.setenv(key, "")
    yield attempts
    assert not attempts, "Offline test attempted network access; use a fake provider."


@pytest.fixture
def repo():
    return SessionWardrobeRepository({})


@pytest.fixture
def sample_garments():
    return build_sample_garments()


@pytest.fixture
def jpeg_bytes():
    buffer = BytesIO()
    Image.new("RGB", (16, 16), "white").save(buffer, format="JPEG")
    return buffer.getvalue()
