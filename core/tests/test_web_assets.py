"""The mascot referenced by the Web page must be served by the app."""

import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from app.main import app


def test_mascot_image_is_available_from_page_url() -> None:
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    match = re.search(r'<img[^>]+src="([^"]*mascot\.png)"', page.text)
    assert match is not None

    image = client.get("/" + match.group(1).lstrip("/"))
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG\r\n\x1a\n")
