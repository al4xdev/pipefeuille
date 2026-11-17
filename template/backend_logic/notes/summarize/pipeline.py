lazy from typing import Self

lazy from backend_logic._shared.agents.contracts import AgentRuns, AgentWork, Submission
lazy from backend_logic._shared.note_name import run as naming
lazy from backend_logic.notes._shared.record.decode import run as decoding
lazy from backend_logic.notes._shared.storage.contracts import FileStore
lazy from backend_logic.notes._shared.storage.read import run as reading
lazy from backend_logic.notes._shared.storage.read.contracts import Found, ReadDocument

lazy from .container import Container
lazy from .contracts import DispatchedSummary, DispatchSummary, NoteMissingError


class Pipe:
    def __init__(self) -> None:
        self.container = Container()

    @classmethod
    def get(cls, initial: DispatchSummary) -> Self:
        """Set input unchanged; nothing is read or handed over yet."""
        pipe = cls()
        pipe.container.input = initial
        return pipe

    def validate_name(self) -> Self:
        """Require input; set name admitted by the shared note_name authority.

        Propagate NoteValidationError("invalid_name"); no I/O, no correction.
        """
        if self.container.input is None:
            raise RuntimeError("summary dispatch requires input")
        self.container.name = naming.run(self.container.input.name)
        return self

    def resolve_path(self, *, directory: str, suffix: str) -> Self:
        """Require name; set confined store-relative path. No I/O."""
        if self.container.name is None:
            raise RuntimeError("note path requires validated name")
        self.container.relative_path = f"{directory}/{self.container.name}{suffix}"
        return self

    def read_note(self, *, store: FileStore) -> Self:
        """Require name/path; set record through the shared record decoder. Read-only I/O.

        Absence is NoteMissingError; a corrupt or misfiled document is ValueError.
        """
        if self.container.name is None or self.container.relative_path is None:
            raise RuntimeError("note lookup requires name and path")
        read = reading.run(ReadDocument(store, self.container.relative_path))
        if not isinstance(read, Found):
            raise NoteMissingError("note_missing")
        record = decoding.run(read.value)
        if record.name != self.container.name:
            raise ValueError("stored note name does not match its path")
        self.container.record = record
        return self

    def project_note(self) -> Self:
        """Require record; set view with name and text only. Privacy is applied here, before
        anything leaves the process: the author and the revision never reach the agent."""
        if self.container.record is None:
            raise RuntimeError("note projection requires record")
        self.container.view = {
            "name": self.container.record.name,
            "text": self.container.record.body,
        }
        return self

    def prepare_submission(self, *, work: AgentWork, tenant: str) -> Self:
        """Require view; set submission of that work for the tenant. No I/O."""
        if self.container.view is None:
            raise RuntimeError("submission preparation requires the projected view")
        self.container.submission = Submission(
            work=work, tenant=tenant, payload=self.container.view
        )
        return self

    async def submit(self, *, agents: AgentRuns, work: AgentWork) -> Self:
        """Require a submission of that work; set run_id. One hand-over, never repeated here.

        Propagate AgentsUnavailableError and SubmissionTooLargeError; nothing is recorded.
        """
        submission = self.container.submission
        if submission is None or submission.work != work:
            raise RuntimeError(f"submitting requires a prepared {work} submission")
        if self.container.run_id is not None:
            raise RuntimeError("the submission was already handed over")
        self.container.run_id = await agents.submit(submission)
        return self

    def materialize(self) -> DispatchedSummary:
        """Require name and run_id; return them."""
        if self.container.name is None or self.container.run_id is None:
            raise RuntimeError("summary dispatch requires name and run_id")
        return DispatchedSummary(name=self.container.name, run_id=self.container.run_id)
