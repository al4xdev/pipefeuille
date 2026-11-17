"""One sql tool call: load the named workspace files, lock DuckDB down, run the agent's SQL.

Started by sql.js as `python -I worker.py` on the harness server's venv (its duckdb), with
the workspace as cwd, an empty environment, and the request as JSON on stdin. Paths arrive
already resolved by the fence (workspace or template); the model never hands DuckDB a path.
Prints one JSON object on stdout.

The lock-down is the "instance" approach, verified on the pinned duckdb (see the tests):
tables are loaded first, then external access is switched off with no allowed path, so the
agent's SQL reaches no file, not even the loaded ones, and no network. The one exception is
DuckDB's own: temp_directory stays readable (it spills there), so it is a random folder
holding only this call's spill files. DuckDB calls these settings defense in depth, not a
sandbox: sql.js adds a separate process, an empty env, a timeout, and output caps.

Not a pipefeuille package: a script of the runtime layer, typed with the harness server's
mypy and linted with the template's ruff (backend_harness/tests/test.sh).
"""

import csv
import io
import json
import sys
from typing import TypedDict

import duckdb

ALLOWED = {
    duckdb.StatementType.SELECT,
    duckdb.StatementType.EXPLAIN,
    duckdb.StatementType.MULTI,  # PIVOT
    # Scratch tables, in this process's memory only.
    duckdb.StatementType.CREATE,
    duckdb.StatementType.INSERT,
    duckdb.StatementType.UPDATE,
    duckdb.StatementType.DELETE,
    duckdb.StatementType.DROP,
}
MAX_OUTPUT_BYTES = 50 * 1024

type Scalar = str | int | bool


class Table(TypedDict):
    name: str
    path: str
    shown: str
    options: dict[str, Scalar]


class Request(TypedDict):
    query: str
    tables: list[Table]
    memory_mb: int
    max_rows: int
    temp_dir: str


class RefusedError(Exception):
    """A request the worker will not run; its text goes back to the model as the error."""


# sql.js's reader option names -> read_csv's. Values are always bound (?).
CSV_OPTIONS = {
    "delimiter": "delim",
    "quote": "quote",
    "escape": "escape",
    "header": "header",
    "skip": "skip",
    "decimal_separator": "decimal_separator",
    "thousands": "thousands",
    "encoding": "encoding",
    "dateformat": "dateformat",
    "timestampformat": "timestampformat",
    "nullstr": "nullstr",
    "all_varchar": "all_varchar",
}


def detect(path: str) -> str:
    """A file's format from its content, not its name: Parquet by its magic bytes, JSON
    (array or one object per line; read_json tells which) by a leading { or [, and anything
    else is text for read_csv's sniffer, which finds the delimiter (comma, tab, ;, |)."""
    with open(path, "rb") as file:
        head = file.read(4096)
    if head.startswith(b"PAR1"):
        return "parquet"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if text[:1] in (b"{", b"["):
        return "json"
    return "csv"


def reader(table: Table) -> tuple[str, list[Scalar]]:
    """The FROM clause and its parameters for one table."""
    options = dict(table["options"])
    chosen = options.pop("format", None)
    fmt = chosen if isinstance(chosen, str) else detect(table["path"])
    if fmt != "csv":
        if options:
            raise RefusedError(
                f"{table['shown']} reads as {fmt}: {', '.join(options)} apply only to "
                "delimited text (or set format csv)"
            )
        return f"read_{fmt}(?)", [table["path"]]
    names = [CSV_OPTIONS[key] for key in options]
    source = "read_csv(?" + "".join(f", {name} = ?" for name in names) + ")"
    return source, [table["path"], *options.values()]


def connect(request: Request) -> duckdb.DuckDBPyConnection:
    memory = request["memory_mb"]
    return duckdb.connect(
        ":memory:",
        config={
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
            "allow_community_extensions": False,
            "allow_persistent_secrets": False,
            "memory_limit": f"{memory}MB",
            "threads": 1 if memory < 256 else 2,
            # A random folder outside the workspace (sql.js SPILL): DuckDB shows it in
            # allowed_directories, and the agent's SQL may read it.
            "temp_directory": request["temp_dir"],
            "max_temp_directory_size": f"{2 * memory}MB",
        },
    )


def load(con: duckdb.DuckDBPyConnection, tables: list[Table]) -> None:
    for table in tables:
        name = table["name"]
        if not name.isidentifier() or not name.isascii():
            raise RefusedError(f"bad table name: {name}")
        try:
            source, params = reader(table)
            con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM {source}', params)
        except (duckdb.Error, OSError) as error:
            raise RefusedError(
                f"cannot load table {name} from {table['shown']}: {first_line(error)} "
                "(set reader options such as encoding, delimiter or format, or all_varchar "
                "and cast in SQL)"
            ) from error


def lock(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")


def statements(query: str) -> list[duckdb.Statement]:
    try:
        parsed = duckdb.extract_statements(query)
    except duckdb.Error as error:
        raise RefusedError(first_line(error)) from error
    if not parsed:
        raise RefusedError("query is empty")
    for statement in parsed:
        if statement.type not in ALLOWED:
            raise RefusedError(
                f"{statement.type.name} statements are not allowed; use SELECT "
                "(scratch CREATE/INSERT stay in memory)"
            )
    return parsed


def run(
    con: duckdb.DuckDBPyConnection, parsed: list[duckdb.Statement], max_rows: int
) -> tuple[list[str], list[tuple[object, ...]], int]:
    for statement in parsed[:-1]:
        con.execute(statement.query)
    result = con.execute(parsed[-1].query)
    columns = [str(d[0]) for d in result.description] if result.description else []
    rows: list[tuple[object, ...]] = list(result.fetchmany(max_rows)) if columns else []
    total = len(rows)
    while columns:
        more = len(result.fetchmany(10000))
        if not more:
            break
        total += more
    return columns, rows, total


def as_csv(columns: list[str], rows: list[tuple[object, ...]]) -> tuple[str, int]:
    # Each row is rendered on its own and kept whole or not at all: a quoted cell may hold a
    # newline, so the text can't be cut by lines afterwards.
    def line(values: list[object]) -> str:
        out = io.StringIO()
        csv.writer(out, lineterminator="\n").writerow(values)
        return out.getvalue()

    parts = [line(list(columns))]
    size = len(parts[0].encode())
    for row in rows:
        text = line(["NULL" if v is None else v for v in row])
        size += len(text.encode())
        if size > MAX_OUTPUT_BYTES:
            break
        parts.append(text)
    return "".join(parts), len(parts) - 1


def first_line(error: BaseException) -> str:
    return str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__


def main() -> None:
    # sql.js built the request; it is trusted for shape, the values were checked there.
    request: Request = json.load(sys.stdin)
    out: dict[str, object]
    try:
        con = connect(request)
        load(con, request["tables"])
        lock(con)
        parsed = statements(request["query"])
        columns, rows, total = run(con, parsed, request["max_rows"])
        text, shown = as_csv(columns, rows)
        out = {"ok": True, "columns": columns, "csv": text, "shown": shown, "total": total}
    except RefusedError as error:
        out = {"ok": False, "error": str(error)}
    except duckdb.Error as error:
        out = {"ok": False, "error": first_line(error)}
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
