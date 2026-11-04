"""Isolated HTTP boundary: routes adapt, the logical runs decide."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend_frontend.application import create_app


def test_app_construction_touches_no_disk_until_the_lifespan_starts(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "data")
    assert not (tmp_path / "data").exists()
    with TestClient(app):
        assert (tmp_path / "data").is_dir()


def test_http_round_trip_maps_logical_errors_and_hides_internal_ids(tmp_path: Path) -> None:
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
        created = client.put("/notes/todo", json={"body": "write the guide"})
        duplicate = client.put("/notes/todo", json={"body": "again"})
        invalid = client.put("/notes/bad name", json={"body": "x"})
        listed = client.get("/notes")

    assert created.status_code == 200
    assert created.json()["revision"] == 1
    assert "author_id" not in created.json()
    assert (duplicate.status_code, duplicate.json()["detail"]) == (409, "note_exists")
    assert (invalid.status_code, invalid.json()["detail"]) == (422, "invalid_name")
    assert listed.json() == {"names": ["todo"]}


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b'["body"]',
        b'{"body": 1}',
        b'{"body": "x", "replace": "yes"}',
        b'{"body": "x", "expected_revision": true}',
        b'{"body": "x", "author_id": "intruder"}',
        b'{"body": "first", "body": "second"}',
        b'{"body": "\\ud800"}',
        b'{"body": "\xff"}',
        b"[" * 5000 + b"]" * 5000,
    ],
)
def test_malformed_wire_body_is_rejected_before_the_logical_run(
    tmp_path: Path, content: bytes
) -> None:
    with TestClient(create_app(data_root=tmp_path / "data")) as client:
        response = client.put("/notes/todo", content=content)

        assert (response.status_code, response.json()["detail"]) == (422, "invalid_body")
        assert client.get("/notes").json() == {"names": []}
