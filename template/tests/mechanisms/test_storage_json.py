"""Mechanism packages reject instead of normalizing; each is exercised through its run."""

from pathlib import Path

import pytest

from backend_logic._shared.json._shared.validate import run as validating
from backend_logic._shared.json._shared.validate.contracts import ValidateValue
from backend_logic._shared.json.contracts import JsonValue
from backend_logic._shared.json.decode import run as decoding
from backend_logic._shared.json.decode.contracts import DecodeText
from backend_logic._shared.json.encode import run as encoding
from backend_logic._shared.json.encode.contracts import EncodeValue
from backend_logic.notes._shared.storage._shared.path import run as locating
from backend_logic.notes._shared.storage._shared.path.contracts import ResolvePath
from backend_logic.notes._shared.storage.contracts import FileStore
from backend_logic.notes._shared.storage.read import run as reading
from backend_logic.notes._shared.storage.read.contracts import Found, Missing, ReadDocument
from backend_logic.notes._shared.storage.scan import run as scanning
from backend_logic.notes._shared.storage.scan.contracts import ScanDirectory
from backend_logic.notes._shared.storage.write import run as writing
from backend_logic.notes._shared.storage.write.contracts import (
    AtomicWriteError,
    PublicationStatus,
    WriteDocument,
)


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1, "a": 2}',
        "[NaN]",
        "[Infinity]",
        '["\\ud800"]',
        '{"\\udc00": 1}',
        "[" * 5000 + "]" * 5000,
    ],
)
def test_decode_rejects_hostile_json_as_value_error(text: str) -> None:
    with pytest.raises(ValueError):
        decoding.run(DecodeText(text))


def test_decode_returns_json_null_as_a_real_product() -> None:
    assert decoding.run(DecodeText("null")) is None


def test_encode_refuses_lone_surrogates_before_any_write() -> None:
    with pytest.raises(ValueError):
        encoding.run(EncodeValue({"body": "\ud800"}))


def test_validate_rejects_non_json_types_as_type_error() -> None:
    with pytest.raises(TypeError):
        validating.run(ValidateValue((1, 2)))
    with pytest.raises(TypeError):
        validating.run(ValidateValue({1: "x"}))


def test_encode_then_decode_round_trips() -> None:
    value: JsonValue = {"a": [1, 2.5, None, True, "é"]}
    assert decoding.run(DecodeText(encoding.run(EncodeValue(value)))) == value


def test_store_requires_an_existing_absolute_root(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        FileStore(Path("relative"))
    with pytest.raises(NotADirectoryError):
        FileStore(tmp_path / "missing")


@pytest.mark.parametrize(
    "relative",
    ["", ".", "notes/.", "notes//a.json", "../a.json", "/abs.json", "a\\b.json", "a\x00b"],
)
def test_path_rejects_instead_of_normalizing(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        locating.run(ResolvePath(FileStore(tmp_path), relative))


def test_path_accepts_plain_relative_form(tmp_path: Path) -> None:
    resolved = locating.run(ResolvePath(FileStore(tmp_path), "notes/a.json"))
    assert resolved == tmp_path / "notes" / "a.json"


def test_read_observes_absence_and_write_publishes_durably(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    assert reading.run(ReadDocument(store, "notes/a.json")) == Missing()

    receipt = writing.run(WriteDocument(store, "notes/a.json", None))

    assert receipt.status is PublicationStatus.DURABLE
    assert receipt.size_bytes == len(b"null\n")
    # Stored JSON null is Found(None), distinct from Missing.
    assert reading.run(ReadDocument(store, "notes/a.json")) == Found(None)


def test_unserializable_value_fails_before_publication(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    with pytest.raises(AtomicWriteError) as raised:
        writing.run(WriteDocument(store, "notes/a.json", float("nan")))
    assert (raised.value.phase, raised.value.receipt.status) == (
        "serialize",
        PublicationStatus.NOT_PUBLISHED,
    )
    assert not (tmp_path / "notes").exists()


def test_corrupt_document_propagates_instead_of_reading_as_absent(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        reading.run(ReadDocument(FileStore(tmp_path), "a.json"))


def test_scan_lists_regular_files_without_creating_the_directory(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    assert scanning.run(ScanDirectory(store, "notes")) == ()
    assert not (tmp_path / "notes").exists()
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes" / "sub").mkdir()
    assert scanning.run(ScanDirectory(store, "notes")) == ("a.json",)


@pytest.mark.parametrize("relative", ["", ".", "notes/..", "notes/./x"])
def test_scan_directory_must_be_strictly_beneath_root(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError):
        scanning.run(ScanDirectory(FileStore(tmp_path), relative))
