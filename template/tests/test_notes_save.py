"""Save composition with a real store and locks; only the clock is a finite fake."""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend_logic.json.validate.contracts import JsonValue
from backend_logic.notes.name.contracts import NoteName, NoteValidationError
from backend_logic.notes.save.contracts import (
    AuthorId,
    NoteConflictError,
    NoteRecord,
    NoteResultError,
    Revision,
    SavedNote,
    SaveNote,
)
from backend_logic.notes.save.decode import run as decoding
from backend_logic.notes.save.encode import run as encoding
from backend_logic.notes.save.pipeline import Pipe
from backend_logic.notes.save.run import run
from backend_logic.storage import run as storing
from backend_logic.storage.lock.contracts import LockRegistry, SelectLock
from backend_logic.storage.path.contracts import FileStore
from backend_logic.storage.read.contracts import Found, JsonRead, ReadDocument
from backend_logic.storage.write.contracts import (
    AtomicWriteError,
    PublicationStatus,
    WriteDocument,
)

AUTHOR = AuthorId("author-1")
NOTE_PATH = "notes/groceries.json"


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


def submission(*, body: str, replace: bool = False, revision: int | None = None) -> SaveNote:
    return SaveNote(
        name="groceries",
        body=body,
        author_id=AUTHOR,
        replace=replace,
        expected_revision=None if revision is None else Revision(revision),
    )


def stored_note(store: FileStore) -> JsonRead:
    return storing.run(ReadDocument(store, NOTE_PATH))


def stored_record(store: FileStore) -> NoteRecord:
    stored = stored_note(store)
    assert isinstance(stored, Found)
    return decoding.run(stored.value)


def publish(store: FileStore, value: JsonValue) -> None:
    storing.run(WriteDocument(store, NOTE_PATH, value))


async def test_create_then_replace_increments_revision_once(tmp_path: Path) -> None:
    store, locks = FileStore(tmp_path), LockRegistry()
    first = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    second = FixedClock(datetime(2026, 1, 2, tzinfo=UTC))

    created = await run(submission(body="milk"), store=store, locks=locks, clock=first)
    replaced = await run(
        submission(body="milk, eggs", replace=True, revision=1),
        store=store,
        locks=locks,
        clock=second,
    )

    assert created.record.name == "groceries"
    assert created.publication is PublicationStatus.DURABLE
    assert (replaced.record.revision, replaced.record.body) == (2, "milk, eggs")
    assert replaced.record.updated_at == second.instant
    assert stored_record(store) == replaced.record


@pytest.mark.parametrize(
    ("initial", "code"),
    [
        (submission(body="again"), "note_exists"),
        (submission(body="stale", replace=True, revision=7), "revision_conflict"),
    ],
)
async def test_conflicts_are_rejected_without_writing(
    tmp_path: Path, initial: SaveNote, code: str
) -> None:
    store, locks = FileStore(tmp_path), LockRegistry()
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    await run(submission(body="original"), store=store, locks=locks, clock=clock)

    with pytest.raises(NoteConflictError) as raised:
        await run(initial, store=store, locks=locks, clock=clock)

    assert raised.value.code == code
    assert stored_record(store).body == "original"


# validate_* rejects instead of correcting: padding is not trimmed, and "²½" passes
# str.isalnum() but is outside the declared letters/digits/-/_ set.
@pytest.mark.parametrize("name", ["../etc", "", " groceries ", "a/b", "²½", "Ⅰ"])
async def test_invalid_name_fails_before_any_io(tmp_path: Path, name: str) -> None:
    initial = SaveNote(name=name, body="x", author_id=AUTHOR, replace=False, expected_revision=None)
    with pytest.raises(NoteValidationError) as raised:
        await run(
            initial,
            store=FileStore(tmp_path),
            locks=LockRegistry(),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        )
    assert raised.value.code == "invalid_name"
    assert not list(tmp_path.iterdir())


async def test_corrupt_document_is_not_treated_as_absence(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    (tmp_path / NOTE_PATH).write_text('{"name": "groceries"}', encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected or missing fields"):
        await run(
            submission(body="x"),
            store=FileStore(tmp_path),
            locks=LockRegistry(),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        )


async def test_misfiled_document_is_not_accepted_as_predecessor(tmp_path: Path) -> None:
    store = FileStore(tmp_path)
    other = NoteRecord(
        schema_version=1,
        name=NoteName("other"),
        body="foreign",
        author_id=AUTHOR,
        revision=Revision(1),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    publish(store, encoding.run(other))

    with pytest.raises(ValueError, match="does not match its path"):
        await run(
            submission(body="x", replace=True, revision=1),
            store=store,
            locks=LockRegistry(),
            clock=FixedClock(datetime(2026, 1, 2, tzinfo=UTC)),
        )
    assert stored_record(store) == other


async def test_named_lock_excludes_same_name_and_admits_other_names() -> None:
    # The save stages hold no await, so racing two saves cannot observe the lock;
    # this rehearses the registry itself with an await held inside the lock.
    locks = LockRegistry()
    held, release = asyncio.Event(), asyncio.Event()
    entered: list[str] = []

    async def holder() -> None:
        async with storing.run(SelectLock(locks, kind="note", name="groceries")):
            held.set()
            await release.wait()

    async def contender(kind: str, name: str) -> None:
        async with storing.run(SelectLock(locks, kind=kind, name=name)):
            entered.append(name)

    holding = asyncio.create_task(holder())
    await held.wait()
    same = asyncio.create_task(contender("note", "groceries"))
    other = asyncio.create_task(contender("note", "todo"))
    await other
    await asyncio.sleep(0)

    assert entered == ["todo"]
    release.set()
    await asyncio.gather(holding, same)
    assert entered == ["todo", "groceries"]
    # Never evicted: the same key keeps the same lock after every holder left.
    selected = storing.run(SelectLock(locks, kind="note", name="groceries"))
    assert selected is storing.run(SelectLock(locks, kind="note", name="groceries"))


async def test_sequential_duplicate_creation_conflicts(tmp_path: Path) -> None:
    store, locks = FileStore(tmp_path), LockRegistry()
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))

    outcomes = await asyncio.gather(
        run(submission(body="a"), store=store, locks=locks, clock=clock),
        run(submission(body="b"), store=store, locks=locks, clock=clock),
        return_exceptions=True,
    )

    saved = [outcome for outcome in outcomes if isinstance(outcome, SavedNote)]
    conflicts = [outcome for outcome in outcomes if isinstance(outcome, NoteConflictError)]
    assert len(saved) == 1
    assert len(conflicts) == 1
    assert conflicts[0].code == "note_exists"


async def test_failure_after_commit_keeps_the_receipt_and_never_rewrites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_materialize(self: Pipe) -> SavedNote:
        raise RuntimeError("presentation failed after publication")

    monkeypatch.setattr(Pipe, "materialize", failing_materialize)
    store = FileStore(tmp_path)

    with pytest.raises(NoteResultError) as raised:
        await run(
            submission(body="kept"),
            store=store,
            locks=LockRegistry(),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        )

    assert raised.value.receipt.status is PublicationStatus.DURABLE
    assert isinstance(stored_note(store), Found)


async def test_directory_fsync_failure_reports_published_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Publication failure propagates AtomicWriteError with its receipt, not a ResultError:
    # the receipt says the bytes are visible, so the caller must not retry as if unwritten.
    real_fsync = os.fsync
    calls: list[int] = []

    def failing_directory_fsync(fd: int) -> None:
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("directory fsync failed")
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", failing_directory_fsync)
    store = FileStore(tmp_path)

    with pytest.raises(AtomicWriteError) as raised:
        await run(
            submission(body="visible"),
            store=store,
            locks=LockRegistry(),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        )

    assert raised.value.phase == "directory_fsync"
    assert raised.value.receipt.status is PublicationStatus.PUBLISHED_NOT_DURABLE
    assert raised.value.receipt.size_bytes is not None
    monkeypatch.undo()
    assert stored_record(store).body == "visible"


def test_encode_and_decode_are_inverse_children() -> None:
    record = NoteRecord(
        schema_version=1,
        name=NoteName("n"),
        body="b",
        author_id=AUTHOR,
        revision=Revision(3),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert decoding.run(encoding.run(record)) == record


@pytest.mark.parametrize("stored_name", ["../escaped", " n", ""])
def test_stored_name_passes_the_same_authority_as_save_input(stored_name: str) -> None:
    record = NoteRecord(
        schema_version=1,
        name=NoteName("n"),
        body="b",
        author_id=AUTHOR,
        revision=Revision(1),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    document = encoding.run(record) | {"name": stored_name}
    # Corruption, not the client's invalid_name: a 422 would blame the caller for disk state.
    with pytest.raises(ValueError, match="stored note name is invalid") as raised:
        decoding.run(document)
    assert not isinstance(raised.value, NoteValidationError)
