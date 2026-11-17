"""HTTP entrypoint of the agent runtime, and the only way in: dsh runs in the same
container and is never exposed. The logic's harness adapter dispatches agents here
(backend to backend, trusted: tenant_id comes from it).

Routes: POST /dispatch and POST /status. Each dispatch queues one `app-agent run`
process (one dsh agent, its own workspace); at most CAP run at once, the rest wait in
order. Agents are single-shot: once a process ends, status returns its stdout (the
agent's answer, e.g. the JSON line its finalize_* tool wrote), and chaining agents is
the caller's job (dispatch that output to the next one).

Two queues behind the same routes, picked at startup:
- APP_PG_DSN unset (the default): MemoryQueue, in this process, lost on restart. A
  run that fails is `failed`; nothing is rerun.
- APP_PG_DSN set (a libpq connection string, e.g. the local container of
  `docker.sh --pg`): PgQueue, the table SCHEMA.processes shared by every instance on
  that database. An instance claims a queued row only while the global CAP allows,
  heartbeats what it runs, and requeues what a dead run left behind (the reaper), up
  to the agent's limits.max_attempts. TLS, if the database needs it, goes in the
  connection string (sslmode=...); this server adds nothing of its own.

When a run ends, its token usage (read_usage: summed over the model calls in its dsh
session log) is stored with its output, and /status returns it as `usage`; absent when
unknown.

This is the runtime layer's own code, not a pipefeuille package: one module, its own
pyproject, venv and Python (backend_harness/README.md says which rules apply here).
Run it as `python server.py` (APP_HARNESS_HOST, APP_HARNESS_PORT).
"""

import glob
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import IO, Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Agents running at once, across every instance of a Postgres queue. A tuning knob:
# the queue, not the machine, holds the rest.
CAP = 20

# Every agent's limits, generated at image build from its agents/<name>/agent.yml by
# runtime/bin/app-profiles.mjs (the one agent.yml parser, dsh-plugin-app-tools/agent.js),
# so this server parses no YAML. The Dockerfile writes this exact path.
AGENTS_FILE = "/opt/app/server/agents.json"

# The runner of one agent process (runtime/bin/app-agent.sh, on PATH in the image) and
# the root of its workspaces (the runner's WORK). Module attributes so tests can point
# them at a fake runner and a temporary folder.
RUNNER = "app-agent"
WORK = "/tmp/app-work"

# The exit code of an agent that went over 125% of its time or token limit
# (runtime/plugins/dsh-plugin-app-limits). A FINAL failure: the row fails with reason
# LIMIT_EXCEEDED and is never requeued, since a rerun would hit the same limit.
EXIT_LIMIT_EXCEEDED = 75
LIMIT_EXCEEDED = "LIMIT_EXCEEDED"

# The Postgres schema of the queue (SCHEMA.processes): one per deployment's database.
SCHEMA = "app_harness"

# tenant_id becomes a path segment (WORK/<tenant>/): same rule as app-agent. 64 keeps
# the dsh session folder (which embeds the cwd) under NAME_MAX.
TenantId = Field(pattern=r"^[A-Za-z0-9_-]+$", max_length=64)
# agent_name is the next segment (WORK/<tenant>/<agent>/<id>), same rule as app-agent:
# no '-', so the session folder name still splits into its three ids.
AGENT_NAME = r"^[A-Za-z0-9][A-Za-z0-9_]*$"
AgentName = Field(pattern=AGENT_NAME, max_length=64)
PROCESS_ID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"

# The public statuses; /status never shows another.
STATUSES = ("queued", "running", "completed", "failed")


class DispatchRequest(BaseModel):
    agent_name: str = AgentName
    tenant_id: str = TenantId
    # The model's first message is exactly this object as JSON; the ids never reach it.
    input: dict[str, Any]


class DispatchResponse(BaseModel):
    status: str
    process_id: str


class Usage(BaseModel):
    """A run's tokens, summed over its model calls (read_usage) and over its attempts
    (merge_usage). input excludes the cached part, which is cache_read; reasoning as the
    provider reports it."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    # Every model the run named (its requests and its compactions' summaries), sorted;
    # model is that one when there is exactly one, else None.
    models: list[str] = Field(default_factory=list)
    model: str | None = None


class StatusResponse(DispatchResponse):
    output: str | None = None  # stdout, once the process ended
    # Why a run failed for good, when the server knows: LIMIT_EXCEEDED, START_FAILED,
    # ATTEMPTS_EXHAUSTED, RERUN_REFUSED. None for a plain nonzero exit.
    reason: str | None = None
    # Once the process ended, when its session log could be read. Left unset (absent
    # from the JSON: the route excludes unset fields) when unknown.
    usage: Usage | None = None


class StatusRequest(BaseModel):
    tenant_id: str = TenantId
    process_id: str


# --- logging: one JSON object per line, with severity and message --------------------

logger = logging.getLogger("app.harness")
ACCESS_LOGGER = "uvicorn.access"


def log(severity: str, event: str, **fields: Any) -> None:
    """One event as one JSON line on stdout; `severity` is the field a log reader files it by."""
    print(
        json.dumps(
            {"severity": severity, "message": event, "component": "server", "event": event, **fields}, default=str
        ),
        flush=True,
    )


def severity_of(record: logging.LogRecord) -> str:
    """A record's severity: its level name, except uvicorn's access line, logged at INFO
    whatever its status: a 5xx is an ERROR and a 4xx a WARNING. Its arguments are
    (client, method, path, version, status)."""
    if record.name == ACCESS_LOGGER and isinstance(record.args, tuple) and len(record.args) == 5:
        status = record.args[4]
        if isinstance(status, int) and status >= 500:
            return "ERROR"
        if isinstance(status, int) and status >= 400:
            return "WARNING"
    return record.levelname


class JsonLines(logging.Formatter):
    """A record as one JSON line. A traceback goes inside the message, after its text:
    one entry with the record's severity, not one plain line per traceback line."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"
        return json.dumps(
            {"severity": severity_of(record), "message": message, "component": "server", "logger": record.name},
            default=str,
        )


class StdStreams(logging.Handler):
    """WARNING and above on stderr, the rest on stdout, the stream looked up per line
    (pytest swaps them per test)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            stream = sys.stderr if severity_of(record) in ("WARNING", "ERROR", "CRITICAL") else sys.stdout
            stream.write(line + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


def uncaught_thread(args: threading.ExceptHookArgs) -> None:
    """A thread's uncaught exception (a watcher's, the ticker's) as one ERROR line."""
    if issubclass(args.exc_type, SystemExit):
        return  # as the default hook: a thread ending by SystemExit is no error
    name = args.thread.name if args.thread is not None else "?"
    logger.error("uncaught exception in thread %s", name, exc_info=args.exc_value or True)


def json_logging() -> None:
    """Every log record as JsonLines: uvicorn's (access, startup, "Exception in ASGI
    application") and any library's at WARNING and up. main() calls it before uvicorn
    starts, and uvicorn runs with log_config=None, so nothing replaces it."""
    handler = StdStreams()
    handler.setFormatter(JsonLines())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.WARNING)
    logger.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", ACCESS_LOGGER):
        server = logging.getLogger(name)
        server.handlers = []
        server.propagate = True
    threading.excepthook = uncaught_thread


# --- agents and their processes -----------------------------------------------------


def load_max_attempts(path: str) -> dict[str, int]:
    """agent name -> limits.max_attempts, from the build's agents.json. Strict and fail
    closed: anything but a positive int for every agent stops the server at startup,
    because a run must never be retried by a limit nobody declared."""
    with open(path) as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or not doc:
        raise ValueError(f"{path}: not a non-empty mapping of agent name to its limits")
    attempts = {}
    for name, entry in doc.items():
        limits = entry.get("limits") if isinstance(entry, dict) else None
        value = limits.get("max_attempts") if isinstance(limits, dict) else None
        # type() and not isinstance(): JSON true is a bool, and a bool is an int to Python.
        if not re.fullmatch(AGENT_NAME, name) or type(value) is not int or value < 1:
            raise ValueError(f"{path}: agent {name!r} has no valid limits.max_attempts (a positive integer)")
        attempts[name] = value
    return attempts


def outcome(code: int) -> tuple[str, str | None]:
    """An app-agent exit code as (status, reason)."""
    if code == 0:
        return "completed", None
    if code == EXIT_LIMIT_EXCEEDED:
        return "failed", LIMIT_EXCEEDED
    return "failed", None


def output_path(tenant_id: str, process_id: str) -> str:
    return os.path.join(WORK, tenant_id, f"{process_id}.out")


def send_to_dsh(process_id: str, request: DispatchRequest) -> subprocess.Popen[bytes]:
    """Start the agent; its answer lands in output_path() (the session log in DSH_HOME
    has the full trace). Its stderr goes to the .err file next to it, through
    relay_stderr, which also relays the plugins' structured lines to this log."""
    out_path = output_path(request.tenant_id, process_id)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as out:
        # The ids are for the harness only: the model sees just `input`.
        env = {**os.environ, "APP_TENANT_ID": request.tenant_id}
        proc = subprocess.Popen(
            [RUNNER, "run", request.agent_name, process_id, json.dumps(request.input)],
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.PIPE,
            env=env,
        )
    err_path = out_path.removesuffix(".out") + ".err"
    try:
        threading.Thread(
            target=relay_stderr, args=(process_id, proc.stderr, err_path), name=f"stderr-{process_id}", daemon=True
        ).start()
    except BaseException as error:
        # No reader: a full pipe would block the agent forever. Closed, its next stderr
        # write fails (EPIPE) and the run most likely ends failed, which the queue
        # sees; a hang it would not.
        log("ERROR", "stderr_relay_failed", process_id=process_id, error=str(error))
        if proc.stderr is not None:
            proc.stderr.close()
    return proc


def structured(line: bytes) -> dict[str, Any] | None:
    """A plugin's log line: one JSON object with a severity and a component, as every
    one of ours writes (app-recovery, app-limits, app-fs). Anything else is None."""
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    if isinstance(entry, dict) and isinstance(entry.get("severity"), str) and isinstance(entry.get("component"), str):
        return entry
    return None


def relay_stderr(process_id: str, pipe: IO[bytes] | None, err_path: str) -> None:
    """An agent's stderr, line by line, until it closes: every line to the .err file
    (unbuffered: it holds what the agent wrote even if the container dies); a plugin's
    structured line also to this process's stderr, with the process_id, so the server's
    log has it with its severity. Plain text is never relayed: dsh writes the model's
    reasoning there, which is the tenant's content. A failure stops the copying, never
    the reading: the pipe is drained to the end, so the agent never blocks on it nor
    gets an EPIPE (Node would crash)."""
    if pipe is None:
        return
    broken = False
    with pipe, open(err_path, "wb", buffering=0) as err:
        for line in pipe:
            if broken:
                continue
            try:
                err.write(line)
                if (entry := structured(line)) is not None:
                    entry.setdefault("process_id", process_id)
                    if isinstance(entry.get("event"), str):
                        entry.setdefault("message", entry["event"])  # the line's summary
                    print(json.dumps(entry, default=str), file=sys.stderr, flush=True)
            except Exception as error:
                broken = True
                log("ERROR", "stderr_relay_failed", process_id=process_id, error=str(error))


def read_output(tenant_id: str, process_id: str) -> str | None:
    """The ended process's stdout, as text Postgres accepts (no NUL)."""
    try:
        with open(output_path(tenant_id, process_id), "rb") as f:
            data = f.read()
    except OSError as error:
        log("WARNING", "output_unreadable", process_id=process_id, error=str(error))
        return None
    return data.decode("utf-8", errors="replace").replace("\x00", "\ufffd")


# --- usage, from the dsh session log ------------------------------------------------

# dsh's session log: one per session folder, under $DSH_HOME/sessions, the folder named
# after the run's cwd WORK/<tenant>/<agent>/<id> ('/' becomes '-', app-agent.sh globs it
# the same way). zstd, one frame per batch.
SESSION_LOG = "session.v4.jsonl.zstd"
# Usage field -> dsh-llm TokenUsage's key in data.usage.
USAGE_KEYS = (
    ("input_tokens", "inputTokens"),
    ("output_tokens", "outputTokens"),
    ("reasoning_tokens", "reasoningTokens"),
    ("cache_read_tokens", "cacheReadTokens"),
    ("cache_write_tokens", "cacheWriteTokens"),
)
COUNTS = tuple(field for field, _ in USAGE_KEYS)
# The events that carry a model call's usage: each step's `assistant/message`, and a
# compaction's `compaction/summary` (its own model, in data.model). An
# `assistant/attempt` (a failed, retried or cancelled attempt) carries no usage in dsh's
# schema, so what a failed provider attempt cost cannot be counted.
USAGE_EVENTS = frozenset({"assistant/message", "compaction/summary"})
# Bytes read from a session log at a time.
READ_CHUNK = 1 << 16


def session_folder(tenant_id: str, agent_name: str, process_id: str) -> str | None:
    """The run's session folder, None without DSH_HOME. dsh names it after the cwd with
    every '/' as '-', between '-' and '--': /tmp/app-work/t/a/i is --tmp-app-work-t-a-i--."""
    home = os.environ.get("DSH_HOME")
    if not home:
        return None
    cwd = os.path.join(WORK, tenant_id, agent_name, process_id)
    return os.path.join(home, "sessions", f"-{cwd.replace('/', '-')}--")


def log_lines(path: str) -> Iterator[str]:
    """A session log's lines, decoded frame by frame as the file is read (never the whole
    text at once). A torn last frame (dsh killed mid-write) gives what it decodes; its cut
    line then fails to parse and sum_usage skips it. Bytes that are no zstd raise
    ZstdError: a corrupt log is unknown usage, never a partial sum. compression.zstd is
    Python 3.14+ (this server's .python-version)."""
    from compression import zstd

    decompressor = zstd.ZstdDecompressor()
    pending = b""
    with open(path, "rb") as f:
        while chunk := f.read(READ_CHUNK):
            while chunk:
                if decompressor.eof:
                    decompressor = zstd.ZstdDecompressor()  # the next frame
                pending += decompressor.decompress(chunk)
                chunk = decompressor.unused_data if decompressor.eof else b""
                *lines, pending = pending.split(b"\n")
                for line in lines:
                    yield line.decode("utf-8", errors="replace")
    if pending:
        yield pending.decode("utf-8", errors="replace")


def zero_usage() -> dict[str, Any]:
    return {**dict.fromkeys(COUNTS, 0), "models": [], "model": None}


def with_models(usage: dict[str, Any], models: Iterable[str]) -> dict[str, Any]:
    """usage with models set to these (sorted, distinct) and model to the only one."""
    names = sorted(set(models))
    return {**usage, "models": names, "model": names[0] if len(names) == 1 else None}


def sum_usage(lines: Iterable[str]) -> dict[str, Any]:
    """Usage's fields summed over the USAGE_EVENTS of a session log's lines; models are
    the ones every `request/header` and `compaction/summary` named. A line that is no JSON
    event, an event without usage and a count that is no int >= 0 add nothing."""
    totals = zero_usage()
    models: set[str] = set()
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        data = record.get("data") if isinstance(record, dict) else None
        if not isinstance(data, dict):
            continue
        kind = record.get("type")
        model = None
        if kind == "request/header":
            header = data.get("header")
            config = header.get("config") if isinstance(header, dict) else None
            model = config.get("model") if isinstance(config, dict) else None
        elif kind == "compaction/summary":
            model = data.get("model")
        if isinstance(model, str) and model:
            models.add(model)
        if kind in USAGE_EVENTS and isinstance(usage := data.get("usage"), dict):
            for field, key in USAGE_KEYS:
                value = usage.get(key)
                # type() and not isinstance(): JSON true is a bool, and a bool is an int to Python.
                if type(value) is int and value >= 0:
                    totals[field] += value
    return with_models(totals, models)


def merge_usage(stored: Mapping[str, Any] | None, usage: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A row's usage after one more attempt: the counts summed, the models joined. An
    attempt whose usage is unknown (None) adds nothing, so a row's usage is a floor when
    one of its attempts could not be read (a reaped run, a lost log)."""
    if stored is None or usage is None:
        known = usage if stored is None else stored
        return None if known is None else dict(known)
    counts = {field: int(stored.get(field) or 0) + int(usage.get(field) or 0) for field in COUNTS}
    return with_models(counts, [*(stored.get("models") or []), *(usage.get("models") or [])])


def read_usage(tenant_id: str, agent_name: str, process_id: str) -> dict[str, Any] | None:
    """The ended run's usage (Usage's fields), None when unknown: no session log, or one
    that could not be read. Never raises: usage is a report, it must not fail the run."""
    try:
        folder = session_folder(tenant_id, agent_name, process_id)
        if folder is None:
            log("WARNING", "usage_unknown", process_id=process_id, error="no DSH_HOME")
            return None
        logs = sorted(glob.glob(os.path.join(glob.escape(folder), "session-*", SESSION_LOG)))
        if not logs:
            # A folder with no log where app-agent.sh expects it: dsh's layout changed (a
            # DSH_VERSION bump), not a run that never started; say so apart.
            event = "usage_session_layout" if os.path.isdir(folder) else "usage_unknown"
            log("WARNING", event, process_id=process_id, error=f"no session-*/{SESSION_LOG} in {folder}")
            return None
        return Usage(**sum_usage(line for path in logs for line in log_lines(path))).model_dump()
    except Exception as error:
        log("WARNING", "usage_unknown", process_id=process_id, error=f"{type(error).__name__}: {error}")
        return None


# --- queues ----------------------------------------------------------------------------


class MemoryQueue:
    """The default queue (no APP_PG_DSN): lost on restart and invisible to other
    instances, which is fine for one container."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.processes: dict[str, dict[str, Any]] = {}
        self.waiting: deque[tuple[str, DispatchRequest]] = deque()
        self.running = 0

    def enqueue(self, process_id: str, request: DispatchRequest) -> None:
        with self.lock:
            self.processes[process_id] = {
                "tenant_id": request.tenant_id,
                "status": "queued",
                "output": None,
                "reason": None,
                "usage": None,
            }
            self.waiting.append((process_id, request))

    def claim(self) -> tuple[str, DispatchRequest, int] | None:
        """Take the oldest waiting process if a slot is free, and count it running."""
        with self.lock:
            if not self.waiting or self.running >= CAP:
                return None
            process_id, request = self.waiting.popleft()
            self.running += 1
            self.processes[process_id]["status"] = "running"
            return process_id, request, 1

    def finish(
        self,
        process_id: str,
        attempt: int,
        status: str,
        output: str | None = None,
        reason: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        with self.lock:
            self.running -= 1
            stored = self.processes[process_id]
            stored |= {
                "status": status,
                "output": output,
                "reason": reason,
                "usage": merge_usage(stored["usage"], usage),
            }

    def get(self, process_id: str) -> dict[str, Any] | None:
        with self.lock:
            return self.processes.get(process_id)


# Postgres queue. A heartbeat every HEARTBEAT seconds; a running row silent for STALE
# belongs to a dead run (instance stopped or crashed) and goes back to the queue, its
# agent's limits.max_attempts runs at most. Its session and workspace died with that
# container's /tmp, so it reruns from scratch.
HEARTBEAT = 30
STALE = 150

# Measured per agent in the source project's load test: ~130-150 MiB RSS, plus the
# server. Rounded up: /tmp (workspaces, sessions) may be memory too.
BASE_MIB = 512
PER_AGENT_MIB = 192


def memory_mib() -> int | None:
    """The container's memory: the cgroup limit if there is one, else the machine's."""
    sizes = []
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            value = f.read().strip()
        if value != "max":
            sizes.append(int(value) // 2**20)
    except OSError, ValueError:
        pass
    try:
        with open("/proc/meminfo") as f:
            sizes.append(int(f.readline().split()[1]) // 1024)
    except OSError, ValueError, IndexError:
        pass
    return min(sizes) if sizes else None


def slots() -> int:
    """Agents this instance can hold: at least 1, at most CAP."""
    mib = memory_mib()
    if mib is None:
        return CAP
    return max(1, min(CAP, (mib - BASE_MIB) // PER_AGENT_MIB))


class PgQueue:
    """Queue in SCHEMA.processes. Every write that ends or refreshes a run is fenced by
    (instance, attempts): a run that lost its row to the reaper can no longer touch it.
    Reap and release clear `instance`, so an old run sees its row is gone.

    max_attempts is each agent's limits.max_attempts. A row of an agent this image does
    not know (only a dispatch typo: app-agent refuses it) gets 1. `instance` names who
    runs the rows: this process plus a uuid."""

    # The agent's own limit, read per row: requeue below it, fail for good at it. A
    # requeued row keeps no instance, so its old run's fence matches nothing. In SET
    # every `attempts` is the row's value before the update.
    EXHAUSTED = "attempts >= coalesce((%(limits)s::jsonb ->> agent_name)::int, 1)"
    GIVE_BACK = f"""
        SET status = CASE WHEN {EXHAUSTED} THEN 'failed' ELSE 'queued' END,
            ended_at = CASE WHEN {EXHAUSTED} THEN now() END,
            reason = CASE WHEN {EXHAUSTED} THEN 'ATTEMPTS_EXHAUSTED' END,
            instance = NULL"""

    def __init__(self, dsn: str, max_attempts: Mapping[str, int], open_timeout: float = 30.0) -> None:
        """Opens the pool, waits for its first connection `open_timeout` seconds at most,
        then migrates. Whatever fails leaves no pool."""
        from psycopg.types.json import Jsonb
        from psycopg_pool import ConnectionPool

        self.Jsonb = Jsonb
        self.max_attempts = dict(max_attempts)
        self.table = f"{SCHEMA}.processes"
        self.instance = f"{os.uname().nodename}/{uuid4()}"
        self.slots = slots()
        self.lock = threading.Lock()
        self.mine: dict[str, int] = {}  # process_id -> attempt, runs of this instance
        # Every process this instance ever started. A rerun here is impossible: app-agent
        # run refuses the workspace the first attempt left in /tmp.
        self.tried: set[str] = set()
        self.pool = ConnectionPool(
            conninfo=dsn,
            kwargs={"application_name": "app-harness"},
            min_size=1,
            max_size=4,
            open=False,
            check=ConnectionPool.check_connection,
        )
        try:
            self.pool.open(wait=True, timeout=open_timeout)
            self.migrate()
        except BaseException:
            # Nobody holds this object: its pool would keep reconnecting forever.
            self.pool.close()
            raise
        log(
            "INFO",
            "queue_ready",
            queue="postgres",
            table=self.table,
            instance=self.instance,
            slots=self.slots,
            cap=CAP,
            memory_mib=memory_mib(),
            max_attempts=self.max_attempts,
        )

    def close(self) -> None:
        self.pool.close()

    def migrate(self) -> None:
        statuses = ", ".join(f"'{status}'" for status in STATUSES)
        # Instances start together: concurrent CREATE ... IF NOT EXISTS can still collide
        # in the catalog, so one at a time.
        with self.pool.connection() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.table}.migrate",))
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table} (
                    process_id   uuid PRIMARY KEY,
                    tenant_id    text NOT NULL,
                    agent_name   text NOT NULL,
                    input        jsonb NOT NULL,
                    status       text NOT NULL DEFAULT 'queued'
                                 CONSTRAINT processes_status CHECK (status IN ({statuses})),
                    instance     text,
                    attempts     int NOT NULL DEFAULT 0,
                    created_at   timestamptz NOT NULL DEFAULT now(),
                    started_at   timestamptz,
                    heartbeat_at timestamptz,
                    ended_at     timestamptz,
                    output       text,
                    reason       text,
                    usage        jsonb
                )""")
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS processes_queued ON {self.table} (created_at) WHERE status = 'queued'"
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS processes_running ON {self.table} (heartbeat_at) WHERE status = 'running'"
            )

    def enqueue(self, process_id: str, request: DispatchRequest) -> None:
        with self.pool.connection() as conn:
            conn.execute(
                f"INSERT INTO {self.table} (process_id, tenant_id, agent_name, input) VALUES (%s, %s, %s, %s)",
                (process_id, request.tenant_id, request.agent_name, self.Jsonb(request.input)),
            )

    def claim(self) -> tuple[str, DispatchRequest, int] | None:
        """Take the oldest queued row to run it here."""
        # The local lock keeps this instance under its slots; the advisory lock makes
        # count-then-claim atomic across instances, so CAP holds globally.
        with self.lock:
            while not STOP.is_set() and len(self.mine) < self.slots:
                with self.pool.connection() as conn, conn.transaction():
                    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{self.table}.claim",))
                    busy = conn.execute(f"SELECT count(*) FROM {self.table} WHERE status = 'running'").fetchone()
                    if busy is None or busy[0] >= CAP:
                        return None
                    row = conn.execute(
                        f"""
                        UPDATE {self.table}
                           SET status = 'running', instance = %s, attempts = attempts + 1,
                               started_at = now(), heartbeat_at = now()
                         WHERE process_id = (SELECT process_id FROM {self.table} WHERE status = 'queued'
                                              ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
                     RETURNING process_id, tenant_id, agent_name, input, attempts""",
                        (self.instance,),
                    ).fetchone()
                    if row is None:
                        return None
                    process_id, tenant_id, agent_name, input_, attempt = row
                    process_id = str(process_id)
                    if process_id in self.tried:
                        # Reaped from here after a long outage, and back to us.
                        conn.execute(
                            f"""
                            UPDATE {self.table} SET status = 'failed', ended_at = now(), reason = 'RERUN_REFUSED'
                             WHERE process_id = %s AND attempts = %s""",
                            (process_id, attempt),
                        )
                        log("ERROR", "rerun_here_refused", process_id=process_id, attempt=attempt)
                        continue
                self.tried.add(process_id)
                self.mine[process_id] = attempt
                return process_id, DispatchRequest(agent_name=agent_name, tenant_id=tenant_id, input=input_), attempt
            return None

    def finish(
        self,
        process_id: str,
        attempt: int,
        status: str,
        output: str | None = None,
        reason: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        delay = 1
        try:
            # A failure at shutdown is most likely our own SIGTERM: release() requeues the
            # row, so don't record it as the run's outcome. A limit exceeded is the
            # agent's own final verdict, SIGTERM or not.
            if STOP.is_set() and status != "completed" and reason != LIMIT_EXCEEDED:
                return
            # Until the result is written the run keeps its slot and its heartbeat, so an
            # outage can't make the reaper rerun a finished run. If the row was reaped
            # meanwhile, the fence matches nothing.
            while True:
                try:
                    with self.pool.connection() as conn, conn.transaction():
                        merged = self.merged_usage(conn, process_id, attempt, usage)
                        conn.execute(
                            f"""
                            UPDATE {self.table} SET status = %s, output = %s, reason = %s, usage = %s,
                                   ended_at = now(), heartbeat_at = now()
                             WHERE process_id = %s AND instance = %s AND attempts = %s AND status = 'running'""",
                            (status, output, reason, merged, process_id, self.instance, attempt),
                        )
                    return
                except Exception as error:
                    if STOP.is_set():
                        log("ERROR", "finish_lost", process_id=process_id, error=str(error))
                        return
                    log("WARNING", "finish_retry", process_id=process_id, error=str(error))
                    STOP.wait(delay)
                    delay = min(delay * 2, HEARTBEAT)
        finally:
            with self.lock:
                if self.mine.get(process_id) == attempt:
                    del self.mine[process_id]

    def merged_usage(self, conn: Any, process_id: str, attempt: int, usage: dict[str, Any] | None) -> Any:
        """The row's usage with this attempt's added (merge_usage), as a parameter, read
        under the write's fence and locked until it commits: two writes never race."""
        row = conn.execute(
            f"""
            SELECT usage FROM {self.table}
             WHERE process_id = %s AND instance = %s AND attempts = %s AND status = 'running'
               FOR UPDATE""",
            (process_id, self.instance, attempt),
        ).fetchone()
        merged = merge_usage(None if row is None else row[0], usage)
        return None if merged is None else self.Jsonb(merged)

    def get(self, process_id: str) -> dict[str, Any] | None:
        if not re.fullmatch(PROCESS_ID, process_id):
            return None  # not a uuid: Postgres would raise, and it can't exist anyway
        with self.pool.connection() as conn:
            row = conn.execute(
                f"SELECT tenant_id, status, output, reason, usage FROM {self.table} WHERE process_id = %s",
                (process_id,),
            ).fetchone()
        if row is None:
            return None
        return {"tenant_id": row[0], "status": row[1], "output": row[2], "reason": row[3], "usage": row[4]}

    def heartbeat(self) -> set[str]:
        """Refresh this instance's runs; return the ones whose row is no longer ours
        (reaped after a long outage): they must stop, a rerun owns them now. A row this
        run already ended is still ours, not lost."""
        with self.lock:
            mine = dict(self.mine)
        if not mine:
            return set()
        with self.pool.connection() as conn:
            rows = conn.execute(
                f"""
                WITH m AS (SELECT * FROM unnest(%(ids)s::uuid[], %(attempts)s::int[]) AS m(process_id, attempts)),
                beat AS (
                    UPDATE {self.table} p SET heartbeat_at = now() FROM m
                     WHERE p.process_id = m.process_id AND p.attempts = m.attempts
                       AND p.instance = %(me)s AND p.status = 'running')
                SELECT m.process_id FROM m LEFT JOIN {self.table} p USING (process_id)
                 WHERE p.process_id IS NULL OR p.instance IS DISTINCT FROM %(me)s
                    OR p.attempts <> m.attempts OR p.status = 'queued'""",
                {"ids": list(mine), "attempts": list(mine.values()), "me": self.instance},
            ).fetchall()
        lost = {str(r[0]) for r in rows}
        # Ended between the snapshot and now: not lost, just gone.
        with self.lock:
            return {p for p in lost if self.mine.get(p) == mine[p]}

    def reap(self) -> None:
        """Rows of dead runs (a running heartbeat older than STALE) go back to the queue,
        or fail at their agent's max_attempts."""
        with self.pool.connection() as conn:
            rows = conn.execute(
                f"""
                UPDATE {self.table} {self.GIVE_BACK}
                 WHERE status = 'running' AND heartbeat_at < now() - make_interval(secs => %(stale)s)
             RETURNING process_id, status, instance""",
                {"limits": self.Jsonb(self.max_attempts), "stale": STALE},
            ).fetchall()
        for process_id, now, instance in rows:
            log("WARNING", "reaped", process_id=str(process_id), now=now, instance=instance)

    def release(self) -> None:
        """On shutdown (SIGTERM): hand this instance's runs back now instead of after
        STALE. Their processes are ended first (stop_runs)."""
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    f"""
                    UPDATE {self.table} {self.GIVE_BACK}
                     WHERE instance = %(me)s AND status = 'running'""",
                    {"limits": self.Jsonb(self.max_attempts), "me": self.instance},
                )
        finally:
            self.close()


# --- the server ------------------------------------------------------------------------

QUEUE: MemoryQueue | PgQueue = MemoryQueue()
PROCS: dict[str, subprocess.Popen[bytes]] = {}
STOP = threading.Event()


def start_next() -> None:
    """Start waiting processes while CAP (and, for Postgres, this instance's slots)
    allow. Called on every dispatch, every process exit and, for Postgres, every
    HEARTBEAT (work another instance queued, rows the reaper gave back)."""
    while (claimed := QUEUE.claim()) is not None:
        process_id, request, attempt = claimed
        try:
            proc = send_to_dsh(process_id, request)
        except Exception as error:
            # claim() took the slot: give it back, or it leaks forever.
            log("ERROR", "start_failed", process_id=process_id, error=str(error))
            QUEUE.finish(process_id, attempt, "failed", reason="START_FAILED")
            continue
        PROCS[process_id] = proc
        threading.Thread(
            target=watch,
            args=(process_id, attempt, proc, request.tenant_id, request.agent_name),
            name=f"watch-{process_id}",
            daemon=True,
        ).start()


def watch(process_id: str, attempt: int, proc: subprocess.Popen[bytes], tenant_id: str, agent_name: str) -> None:
    code = proc.wait()
    if PROCS.get(process_id) is proc:
        del PROCS[process_id]
    status, reason = outcome(code)
    if reason == LIMIT_EXCEEDED:
        log("WARNING", "limit_exceeded", process_id=process_id)
    log("INFO", "run_ended", process_id=process_id, agent_name=agent_name, code=code, status=status, reason=reason)
    QUEUE.finish(
        process_id,
        attempt,
        status,
        read_output(tenant_id, process_id),
        reason,
        read_usage(tenant_id, agent_name, process_id),
    )
    try:
        start_next()
    except Exception as error:
        log("ERROR", "start_next_failed", error=str(error))


def tick() -> None:
    """Postgres only: heartbeat, reap and claim, every HEARTBEAT seconds."""
    while not STOP.wait(HEARTBEAT):
        try:
            if isinstance(QUEUE, PgQueue):
                for process_id in QUEUE.heartbeat():
                    log("WARNING", "lost_row", process_id=process_id)
                    if (proc := PROCS.get(process_id)) is not None:
                        proc.terminate()
                QUEUE.reap()
            start_next()
        except Exception as error:
            log("ERROR", "tick_failed", error=str(error))


def stop_runs() -> None:
    """No run may still be going when release() hands its row to another: end them,
    TERM then KILL after 5 s."""
    for proc in list(PROCS.values()):
        proc.terminate()
    deadline = time.monotonic() + 5
    for proc in list(PROCS.values()):
        try:
            proc.wait(max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global QUEUE
    # Fail closed: a server that can't tell an agent's attempts must not start.
    max_attempts = load_max_attempts(AGENTS_FILE)
    dsn = os.environ.get("APP_PG_DSN") or None  # empty = unset
    if dsn is not None:
        QUEUE = PgQueue(dsn, max_attempts)
        threading.Thread(target=tick, name="tick", daemon=True).start()
    else:
        QUEUE = MemoryQueue()
        log("INFO", "queue_ready", queue="memory", cap=CAP, max_attempts=max_attempts)
    yield
    STOP.set()
    if isinstance(QUEUE, PgQueue):
        stop_runs()
        QUEUE.release()


api = FastAPI(title="agent runtime (harness)", lifespan=lifespan)


@api.post("/dispatch", status_code=202, response_model=DispatchResponse)
def dispatch(request: DispatchRequest) -> DispatchResponse:
    process_id = str(uuid4())
    QUEUE.enqueue(process_id, request)
    # Queued is durable from here (Postgres): if starting fails now, tick() retries it.
    try:
        start_next()
    except Exception as error:
        log("ERROR", "start_next_failed", error=str(error))
    return DispatchResponse(status="queued", process_id=process_id)


# exclude_unset: a usage left unset is absent from the JSON, not null.
@api.post("/status", response_model=StatusResponse, response_model_exclude_unset=True)
def status(request: StatusRequest) -> StatusResponse:
    process = QUEUE.get(request.process_id)
    # Another tenant's process answers exactly like a missing one.
    if process is None or process["tenant_id"] != request.tenant_id:
        raise HTTPException(404, "process not found")
    answer = StatusResponse(
        status=process["status"], process_id=request.process_id, output=process["output"], reason=process["reason"]
    )
    if (stored := process.get("usage")) is not None:
        # Only this server writes the column, but a row it cannot read must still answer.
        try:
            answer.usage = Usage.model_validate(stored)
        except ValueError as error:
            log("WARNING", "usage_unreadable", process_id=request.process_id, error=str(error))
    return answer


def main() -> int:
    """`python server.py`: serve on APP_HARNESS_HOST:APP_HARNESS_PORT (default
    127.0.0.1:8081, loopback: only what runs in the same container reaches it)."""
    import uvicorn

    json_logging()
    host = os.environ.get("APP_HARNESS_HOST") or "127.0.0.1"
    port = int(os.environ.get("APP_HARNESS_PORT") or "8081")
    uvicorn.run(api, host=host, port=port, log_config=None, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
