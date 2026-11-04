lazy from typing import Self

lazy from backend_logic.notes._shared.storage.contracts import FileStore
lazy from backend_logic.notes._shared.storage.lock.contracts import LockRegistry

lazy from .container import Container
lazy from .contracts import PrepareResources, Resources, UtcClock


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: PrepareResources) -> Self:
        """Set input unchanged; no resource exists until its prepare_* step."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def prepare_root(self, *, mode: int) -> Self:
        """Require input; create the data root if needed and set its absolute path."""
        if self.container.input is None:
            raise RuntimeError("application resources require input")
        root = self.container.input.data_root.resolve()
        root.mkdir(mode=mode, parents=True, exist_ok=True)
        self.container.root = root
        return self

    def prepare_store(self) -> Self:
        """Require root; set the one FileStore of this application lifetime. No file I/O."""
        if self.container.root is None:
            raise RuntimeError("store construction requires prepared root")
        self.container.store = FileStore(self.container.root)
        return self

    def prepare_locks(self) -> Self:
        """Set the one LockRegistry every operation of this lifetime must share."""
        self.container.locks = LockRegistry()
        return self

    def prepare_clock(self) -> Self:
        """Set the UTC clock passed to operations; tests supply their own fixed clock."""
        self.container.clock = UtcClock()
        return self

    def materialize(self) -> Resources:
        """Require every prepared resource; return them without constructing new ones."""
        if (
            self.container.input is None
            or self.container.root is None
            or self.container.store is None
            or self.container.locks is None
            or self.container.clock is None
        ):
            raise RuntimeError("application resources are incomplete")
        return Resources(
            data_root=self.container.root,
            store=self.container.store,
            locks=self.container.locks,
            clock=self.container.clock,
            author_id=self.container.input.author_id,
        )
