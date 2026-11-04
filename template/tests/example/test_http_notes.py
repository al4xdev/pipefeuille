"""Isolated HTTP boundary: routes adapt, the logical runs decide."""

from pathlib import Path

import pytest
from wire_client import serving

from http_adapter.application import create_app


def test_app_construction_touches_no_disk_until_the_lifespan_starts(tmp_path: Path) -> None:
    app = create_app(data_root=tmp_path / "data")
    assert not (tmp_path / "data").exists()
    with serving(app):
        assert (tmp_path / "data").is_dir()


def test_http_round_trip_maps_logical_errors_and_hides_internal_ids(tmp_path: Path) -> None:
    with serving(create_app(data_root=tmp_path / "data")) as client:
        created = client.put("/notes/todo", b'{"body": "write the guide"}')
        duplicate = client.put("/notes/todo", b'{"body": "again"}')
        invalid = client.put("/notes/bad name", b'{"body": "x"}')
        listed = client.get("/notes")

    assert created.status == 200
    assert isinstance(created.body, dict)
    assert created.body["revision"] == 1
    assert "author_id" not in created.body
    assert (duplicate.status, duplicate.detail()) == (409, "note_exists")
    assert (invalid.status, invalid.detail()) == (422, "invalid_name")
    assert listed.body == {"names": ["todo"]}


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
    with serving(create_app(data_root=tmp_path / "data")) as client:
        response = client.put("/notes/todo", content)

        assert (response.status, response.detail()) == (422, "invalid_body")
        assert client.get("/notes").body == {"names": []}
