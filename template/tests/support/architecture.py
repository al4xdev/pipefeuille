"""Read the architecture from the code: the closed `run` docstrings and the package graph.

The tree, the dispatch, the calls, the loops, the locks and the parallel calls are derived from
the source. Only what the code cannot show is declared, in the Google-style docstring of each
`def run`, and only with the values of the enums below (template-decisions A1, E1, E2):

    Effects:      one or more of Effect
    Repeat:       exactly one Repeat (the worst case over the requests the package serves)
    Loops:        exactly one Loops
    Concurrency:  exactly one Concurrency
    Raises:       names of exceptions a caller may need to handle (optional)

Each line is `<value>` or `<value>: <note>`; the note is free text shown on hover. A family
`run` declares only its summary: its effects come from the cases it dispatches.

As a tool, from the project root:

    uv run python tests/support/architecture.py             # tree, for agents
    uv run python tests/support/architecture.py --json      # the whole graph
    uv run python tests/support/architecture.py --html .dumps/architecture.html

Never edited in a project, like the gates that use it: a new enum value is a change to the
pipefeuille (RUNBOOK, task C).
"""

import ast
import builtins
import html
import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from string import Template
from typing import Literal

ROOT = Path(__file__).resolve().parents[2]
LOGIC_NAME = "backend_logic"
ADAPTER_NAME = "http_adapter"
SHARED = "_shared"


class Effect(StrEnum):
    """What a call touches beyond its own values. `Effects:` lists one or more."""

    PURE = "pure"  # nothing: same request, same product; only alone
    READS = "reads"  # files, a store, a database: observed, not changed
    WRITES = "writes"  # anything that outlives the call: files, registries, remote state
    NETWORK = "network"  # a remote service that is not a language model
    MODEL = "model"  # a language model call: cost, latency, a different reply each time
    TIME = "time"  # the clock: the product depends on when the call ran


class Repeat(StrEnum):
    """What happens when the same request arrives again: a retry, a loop, an agent's tool use.

    Listed from safest to least safe; a family repeats like the worst of its cases.
    """

    SAFE = "safe"  # no further effect, same product
    OVERWRITES = "overwrites"  # the last call wins; earlier effects are replaced
    FAILS = "fails"  # the second call is rejected (conflict, already exists)
    ACCUMULATES = "accumulates"  # every call adds effects or cost


class Loops(StrEnum):
    """The loops in the body of `def run` (pipeline loops are the method's own business)."""

    NONE = "none"  # no `for`, `while` or comprehension
    OVER_ITEMS = "over-items"  # iterates a finite collection it holds; no `while`
    CAPPED = "capped"  # a `while`; the note names the limit that ends it


class Concurrency(StrEnum):
    """What a concurrent caller must know."""

    FREE = "free"  # may be called concurrently; no lock involved
    LOCKS_INSIDE = "locks-inside"  # `run` takes a lock itself (`async with <lock>.run(...)`)
    CALLER_LOCKS = "caller-locks"  # the caller must hold a lock; the note says which


SECTIONS = ("Effects", "Repeat", "Loops", "Concurrency", "Raises")
REQUIRED = ("Effects", "Repeat", "Loops", "Concurrency")
SINGLE = ("Repeat", "Loops", "Concurrency")
VALUES: dict[str, tuple[str, ...]] = {
    "Effects": tuple(member.value for member in Effect),
    "Repeat": tuple(member.value for member in Repeat),
    "Loops": tuple(member.value for member in Loops),
    "Concurrency": tuple(member.value for member in Concurrency),
}
# A note is mandatory where the value alone would hide the one fact a reader needs.
NOTE_REQUIRED = {("Loops", Loops.CAPPED.value), ("Concurrency", Concurrency.CALLER_LOCKS.value)}
# Effects in the order a node is coloured by: the strongest effect wins.
EFFECT_STRENGTH = ("model", "network", "writes", "reads", "time", "pure")

type NodeKind = Literal["family", "process", "shared", "grouping", "adapter"]
type EdgeKind = Literal["calls", "types", "enters"]
# per-item: the call repeats once per item (a loop in `run` or inside the method that makes it).
type Mark = Literal["per-item", "parallel", "lock"]
# A step is a Pipe method or a direct `<alias>.run(...)`; every other kind frames steps, as the
# code of `run` does: a lock, a branch, a match, a loop, a TaskGroup, a try.
type StepKind = Literal[
    "method",
    "call",
    "lock",
    "parallel",
    "loop",
    "if",
    "else",
    "match",
    "case",
    "try",
    "except",
    "finally",
    "with",
]


@dataclass(frozen=True)
class Item:
    value: str
    note: str


@dataclass
class RunDoc:
    summary: str = ""
    description: str = ""
    sections: dict[str, list[Item]] = field(default_factory=dict)

    def values(self, section: str) -> list[str]:
        return [item.value for item in self.sections.get(section, [])]


@dataclass(frozen=True)
class RunFacts:
    """What the body of `def run` shows, read by AST."""

    ports: tuple[str, ...]
    loops: frozenset[Literal["for", "while"]]
    locks: bool


@dataclass(frozen=True)
class StepCall:
    target: str
    per_item: bool  # inside a loop of the method that makes the call


@dataclass
class Step:
    kind: StepKind
    label: str
    calls: tuple[StepCall, ...] = ()
    ports: tuple[str, ...] = ()  # the ports of `run` this step receives
    steps: list[Step] = field(default_factory=list)


@dataclass
class Node:
    id: str
    kind: NodeKind
    path: str
    doc: RunDoc = field(default_factory=RunDoc)
    ports: tuple[str, ...] = ()
    request: str = ""
    response: str = ""
    skeleton: bool = False
    effects: tuple[str, ...] = ()
    repeat: str = ""
    errors: tuple[str, ...] = ()  # *Error classes its own contracts.py defines
    steps: list[Step] = field(default_factory=list)  # the body of `run`, in order

    @property
    def name(self) -> str:
        return self.id.rsplit(".", 1)[-1]

    @property
    def parent(self) -> str | None:
        return self.id.rsplit(".", 1)[0] if "." in self.id else None


@dataclass
class Edge:
    source: str
    target: str
    kind: EdgeKind
    marks: tuple[Mark, ...] = ()
    cases: tuple[str, ...] = ()
    alert: str = ""
    # The index of the first step of `run` that makes the call: the order they run in.
    order: int = 10**6


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[Edge]
    # Calls imported but made by no step of `run`: the steps would hide them.
    hidden: list[str] = field(default_factory=list)

    def calls_from(self, source: str) -> list[Edge]:
        found = [edge for edge in self.edges if edge.source == source and edge.kind == "calls"]
        return sorted(found, key=edge_order)

    @property
    def alerts(self) -> list[str]:
        return [edge.alert for edge in self.edges if edge.alert]


def edge_order(edge: Edge) -> tuple[int, str]:
    return (edge.order, edge.target)


# --- the closed docstring ---------------------------------------------------------------


def is_header(text: str) -> bool:
    word = text[:-1]
    return text.endswith(":") and word.isalpha() and word[:1].isupper()


def parse_docstring(doc: str) -> tuple[RunDoc, list[str]]:
    """Split a cleaned `run` docstring into summary, description and closed sections."""
    lines = doc.splitlines()
    if not lines or not lines[0].strip():
        return RunDoc(), ["missing summary line"]
    parsed = RunDoc(summary=lines[0].strip())
    problems: list[str] = []
    description: list[str] = []
    current: str | None = None  # "" while inside an unknown section, to report it once
    for number, line in enumerate(lines[1:], start=2):
        text = line.strip()
        if not text:
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and is_header(text):
            name = text[:-1]
            if name not in SECTIONS:
                problems.append(f"unknown section {name!r}; sections are {list(SECTIONS)}")
                current = ""
            elif name in parsed.sections:
                problems.append(f"section {name!r} repeated")
                current = ""
            elif parsed.sections and SECTIONS.index(name) < max(
                SECTIONS.index(seen) for seen in parsed.sections
            ):
                problems.append(f"section {name!r} out of order; the order is {list(SECTIONS)}")
                current = ""
            else:
                parsed.sections[name] = []
                current = name
        elif indent == 0:
            if current is None:
                description.append(text)
            else:
                problems.append(f"line {number}: text after the sections: {text!r}")
        elif current == "":
            continue
        elif current is None:
            problems.append(f"line {number}: indented text outside a section")
        elif indent == 4:
            value, _, note = text.partition(":")
            parsed.sections[current].append(Item(value.strip(), note.strip()))
        elif parsed.sections[current]:
            last = parsed.sections[current][-1]
            parsed.sections[current][-1] = Item(last.value, f"{last.note} {text}".strip())
        else:
            problems.append(f"line {number}: continuation before any value in {current}")
    parsed.description = " ".join(description)
    return parsed, problems


def value_problems(doc: RunDoc, *, family: bool) -> list[str]:
    """Closed values: every section of a process present, every value a member of its enum."""
    if family:
        if doc.sections:
            return [
                f"a family declares only its summary; remove {list(doc.sections)} "
                "(its effects come from its cases)"
            ]
        return []
    problems = [f"missing section {name!r}" for name in REQUIRED if name not in doc.sections]
    for name, items in doc.sections.items():
        allowed = VALUES.get(name)
        if name in SINGLE and len(items) != 1:
            problems.append(f"{name}: exactly one value, found {len(items)}")
        if name == "Effects" and not items:
            problems.append("Effects: at least one value")
        for item in items:
            if allowed is not None and item.value not in allowed:
                problems.append(f"{name}: {item.value!r} is not one of {list(allowed)}")
            if (name, item.value) in NOTE_REQUIRED and not item.note:
                problems.append(f"{name}: {item.value!r} needs a note")
        values = [item.value for item in items]
        if len(set(values)) != len(values):
            problems.append(f"{name}: repeated value")
    effects = doc.values("Effects")
    if "pure" in effects and len(effects) > 1:
        problems.append("Effects: 'pure' stands alone")
    return problems


def is_builtin_exception(name: str) -> bool:
    # dir(builtins), not __builtins__: the latter is a dict when this module is imported.
    return name in dir(builtins) and name.endswith(
        ("Error", "Exception", "ExceptionGroup", "Exit", "Interrupt")
    )


# --- facts from the source --------------------------------------------------------------


def run_function(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The module-level `def run`; with `@overload`, the implementation is the last one."""
    found: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            found = node
    return found


def walk(
    node: ast.AST, ancestors: tuple[ast.AST, ...] = ()
) -> Iterator[tuple[ast.AST, tuple[ast.AST, ...]]]:
    yield node, ancestors
    for child in ast.iter_child_nodes(node):
        yield from walk(child, (*ancestors, node))


LOOP_NODES = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def is_child_run_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
        and isinstance(node.func.value, ast.Name)
    )


def run_facts(function: ast.FunctionDef | ast.AsyncFunctionDef) -> RunFacts:
    loops: set[Literal["for", "while"]] = set()
    locks = False
    for node, _ in walk(function):
        if isinstance(node, ast.While):
            loops.add("while")
        elif isinstance(node, LOOP_NODES):
            loops.add("for")
        if isinstance(node, ast.AsyncWith) and any(
            is_child_run_call(item.context_expr) for item in node.items
        ):
            locks = True
    ports = tuple(argument.arg for argument in function.args.kwonlyargs)
    return RunFacts(ports=ports, loops=frozenset(loops), locks=locks)


def fact_problems(doc: RunDoc, facts: RunFacts) -> list[str]:
    """Declarations the body of `run` can confirm or refute."""
    problems: list[str] = []
    effects = doc.values("Effects")
    if "pure" in effects and facts.ports:
        problems.append(f"Effects: 'pure' but run takes ports {list(facts.ports)}")
    if "pure" in effects and doc.values("Repeat") not in ([], ["safe"]):
        problems.append("Repeat: a 'pure' package is 'safe'")
    loops = doc.values("Loops")
    if loops == ["none"] and facts.loops:
        problems.append(f"Loops: 'none' but run has {sorted(facts.loops)}")
    if loops and loops != ["none"] and not facts.loops:
        problems.append(f"Loops: {loops[0]!r} but run has no loop")
    if loops == ["over-items"] and "while" in facts.loops:
        problems.append("Loops: 'over-items' but run has a while; declare 'capped'")
    if loops == ["capped"] and facts.loops and "while" not in facts.loops:
        problems.append("Loops: 'capped' needs a while; a for over items is 'over-items'")
    concurrency = doc.values("Concurrency")
    if concurrency == ["locks-inside"] and not facts.locks:
        problems.append("Concurrency: 'locks-inside' but run takes no lock")
    if concurrency and concurrency != ["locks-inside"] and facts.locks:
        problems.append("Concurrency: run takes a lock (async with <lock>.run); 'locks-inside'")
    return problems


def is_family(run_tree: ast.Module, contracts_tree: ast.Module | None) -> bool:
    """A family dispatches with `match` and declares `type <Family>Request = A | B`."""
    if not any(isinstance(node, ast.Match) for node in ast.walk(run_tree)):
        return False
    return contracts_tree is not None and any(
        isinstance(node, ast.TypeAlias)
        and node.name.id.endswith("Request")
        and isinstance(node.value, ast.BinOp)
        for node in contracts_tree.body
    )


def case_names(run_tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(run_tree):
        if isinstance(node, ast.MatchClass) and isinstance(node.cls, ast.Name):
            names.add(node.cls.id)
    return names


def resolve(module: str | None, level: int, package: str) -> str:
    """The absolute module of an import written in a file of `package`."""
    if level == 0:
        return module or ""
    parts = package.split(".")
    base = parts[: len(parts) - level + 1]
    return ".".join([*base, *([module] if module else [])])


def parse(path: Path) -> ast.Module | None:
    return ast.parse(path.read_text(encoding="utf-8")) if path.exists() else None


# --- the steps of `run` -------------------------------------------------------------------

COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def text(node: ast.AST, limit: int = 60) -> str:
    source = ast.unparse(node)
    return source if len(source) <= limit else f"{source[: limit - 1]}…"


def run_aliases(tree: ast.Module | None, package: str, nodes: dict[str, Node]) -> dict[str, str]:
    """`from <package> import run as <alias>`: alias -> the package it runs."""
    aliases: dict[str, str] = {}
    if tree is None:
        return aliases
    for statement in ast.walk(tree):
        if not isinstance(statement, ast.ImportFrom):
            continue
        module = resolve(statement.module, statement.level, package)
        if module in nodes and module != package:
            for name in statement.names:
                if name.name == "run":
                    aliases[name.asname or name.name] = module
    return aliases


def merge_calls(calls: list[StepCall]) -> tuple[StepCall, ...]:
    """First appearance order; a call repeated per item anywhere is per item."""
    merged: dict[str, bool] = {}
    for call in calls:
        merged[call.target] = merged.get(call.target, False) or call.per_item
    return tuple(StepCall(target, per_item) for target, per_item in merged.items())


def method_calls(
    tree: ast.Module | None, aliases: dict[str, str]
) -> dict[str, tuple[StepCall, ...]]:
    """Each Pipe method -> the packages it runs, following `self.<method>` and local helpers."""
    if tree is None:
        return {}
    pipe = next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Pipe"),
        None,
    )
    if pipe is None:
        return {}
    methods = {
        node.name: node
        for node in pipe.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    helpers = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def collect(function: ast.AST, seen: frozenset[str], looped: bool) -> list[StepCall]:
        found: list[StepCall] = []
        for node, ancestors in walk(function):
            if not isinstance(node, ast.Call):
                continue
            inside = looped or any(isinstance(ancestor, LOOP_NODES) for ancestor in ancestors)
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                owner = func.value.id
                if func.attr == "run" and owner in aliases:
                    found.append(StepCall(aliases[owner], inside))
                elif owner == "self" and func.attr in methods and func.attr not in seen:
                    found.extend(collect(methods[func.attr], seen | {func.attr}, inside))
            elif isinstance(func, ast.Name) and func.id in helpers and func.id not in seen:
                found.extend(collect(helpers[func.id], seen | {func.id}, inside))
        return found

    return {
        name: merge_calls(collect(method, frozenset({name}), False))
        for name, method in methods.items()
    }


def receiver(node: ast.AST) -> str | None:
    """The name a method chain starts from: `Pipe` in `Pipe.get(x).a().b()`."""
    while isinstance(node, (ast.Call, ast.Attribute)):
        node = node.func if isinstance(node, ast.Call) else node.value
    return node.id if isinstance(node, ast.Name) else None


def is_task_group(node: ast.expr) -> bool:
    return "TaskGroup" in ast.unparse(node)


class StepReader:
    """The body of `def run` as steps, in the order they run, inside the frames the code has.

    A frame with no step inside (a guard that only raises) is left out: it changes no order.
    """

    def __init__(
        self,
        aliases: dict[str, str],
        methods: dict[str, tuple[StepCall, ...]],
        ports: tuple[str, ...],
    ) -> None:
        self.aliases = aliases
        self.methods = methods
        self.ports = ports
        self.pipes = {"Pipe"}  # names bound to the Pipe chain

    def block(self, body: list[ast.stmt]) -> list[Step]:
        steps: list[Step] = []
        for statement in body:
            steps.extend(self.statement(statement))
        return steps

    def statement(self, node: ast.stmt) -> list[Step]:
        if isinstance(node, ast.If):
            steps = self.expression(node.test)
            branch, other = self.block(node.body), self.block(node.orelse)
            if branch or other:
                steps.append(Step("if", f"if {text(node.test)}", steps=branch))
            if other:
                steps.append(Step("else", "else", steps=other))
            return steps
        if isinstance(node, ast.Match):
            cases = [
                Step("case", f"case {text(case.pattern)}", steps=inner)
                for case in node.cases
                if (inner := self.block(case.body))
            ]
            return [Step("match", f"match {text(node.subject)}", steps=cases)] if cases else []
        if isinstance(node, (ast.For, ast.AsyncFor)):
            steps = self.expression(node.iter)
            inner = self.block(node.body)
            if inner:
                label = f"for {text(node.target)} in {text(node.iter)}"
                steps.append(Step("loop", label, steps=inner))
            return steps
        if isinstance(node, ast.While):
            inner = self.block(node.body)
            return [Step("loop", f"while {text(node.test)}", steps=inner)] if inner else []
        if isinstance(node, (ast.With, ast.AsyncWith)):
            return self.with_block(node)
        if isinstance(node, (ast.Try, ast.TryStar)):
            steps = []
            inner = self.block(node.body)
            if inner:
                steps.append(Step("try", "try", steps=inner))
            for handler in node.handlers:
                caught = self.block(handler.body)
                if caught:
                    label = f"except {text(handler.type)}" if handler.type else "except"
                    steps.append(Step("except", label, steps=caught))
            last = self.block(node.finalbody)
            if last:
                steps.append(Step("finally", "finally", steps=last))
            return steps
        if isinstance(node, ast.Assign) and receiver(node.value) in self.pipes:
            self.pipes.update(target.id for target in node.targets if isinstance(target, ast.Name))
        return self.expression(node)

    def with_block(self, node: ast.With | ast.AsyncWith) -> list[Step]:
        steps: list[Step] = []
        frame: Step | None = None
        for item in node.items:
            expression = item.context_expr
            call = self.alias_call(expression)
            if call is not None:
                assert isinstance(expression, ast.Call)
                for argument in [*expression.args, *(kw.value for kw in expression.keywords)]:
                    steps.extend(self.expression(argument))
                frame = Step("lock", "lock", calls=(StepCall(call, False),))
            elif is_task_group(expression):
                frame = Step("parallel", "in parallel (TaskGroup), then wait for all")
            else:
                steps.extend(self.expression(expression))
        inner = self.block(node.body)
        if frame is None and inner:
            frame = Step("with", f"with {text(node.items[0].context_expr)}")
        if frame is not None:
            frame.steps = inner
            steps.append(frame)
        return steps

    def alias_call(self, node: ast.expr) -> str | None:
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
        ):
            return self.aliases.get(node.func.value.id)
        return None

    def expression(self, node: ast.AST) -> list[Step]:
        """Steps in evaluation order: a chain's receiver first, then arguments, then the call."""
        if isinstance(node, COMPREHENSIONS):
            steps: list[Step] = []
            for generator in node.generators:
                steps.extend(self.expression(generator.iter))
            # A DictComp key is None for `{**mapping for ...}` (PEP 798).
            parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
            inner = [step for part in parts if part is not None for step in self.expression(part)]
            if inner:
                label = "for " + "; ".join(
                    f"{text(generator.target)} in {text(generator.iter)}"
                    for generator in node.generators
                )
                steps.append(Step("loop", label, steps=inner))
            return steps
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            steps = self.expression(node.func.value)
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                steps.extend(self.expression(argument))
            target = self.alias_call(node)
            if target is not None:
                assert isinstance(node.func.value, ast.Name)
                label = f"{node.func.value.id}.run"
                steps.append(Step("call", label, calls=(StepCall(target, False),)))
            elif node.func.attr in self.methods and receiver(node) in self.pipes:
                ports = tuple(
                    keyword.value.id
                    for keyword in node.keywords
                    if isinstance(keyword.value, ast.Name) and keyword.value.id in self.ports
                )
                calls = self.methods[node.func.attr]
                steps.append(Step("method", node.func.attr, calls=calls, ports=ports))
            return steps
        steps = []
        for child in ast.iter_child_nodes(node):
            steps.extend(self.expression(child))
        return steps


def step_calls(
    steps: list[Step], per_item: bool = False, parallel: bool = False
) -> Iterator[tuple[StepCall, set[Mark]]]:
    """Every call the steps make, in order, with the marks of the frames around it."""
    for step in steps:
        for call in step.calls:
            marks: set[Mark] = set()
            if per_item or call.per_item:
                marks.add("per-item")
            if parallel:
                marks.add("parallel")
            if step.kind == "lock":
                marks.add("lock")
            yield call, marks
        yield from step_calls(
            step.steps, per_item or step.kind == "loop", parallel or step.kind == "parallel"
        )


def apply_steps(graph: Graph) -> None:
    """Order and mark each call edge by the steps; a call no step makes is hidden."""
    for node in graph.nodes.values():
        first: dict[str, int] = {}
        marks: dict[str, set[Mark]] = {}
        for index, (call, call_marks) in enumerate(step_calls(node.steps)):
            first.setdefault(call.target, index)
            marks.setdefault(call.target, set()).update(call_marks)
        for edge in graph.edges:
            if edge.source != node.id or edge.kind != "calls":
                continue
            if edge.target in first:
                edge.order = first[edge.target]
                edge.marks = tuple(sorted(marks[edge.target]))
            else:
                graph.hidden.append(
                    f"{node.path}: imports the run of {edge.target}, but no step of its run "
                    "calls it"
                )


# --- the graph ----------------------------------------------------------------------------


def folder_kind(
    folder: Path, run_tree: ast.Module | None, contracts: ast.Module | None
) -> NodeKind:
    if folder.name == SHARED:
        return "shared"
    if run_tree is None:
        return "grouping" if folder.parent.name == SHARED else "process"
    return "family" if is_family(run_tree, contracts) else "process"


def build_graph(root: Path = ROOT) -> tuple[Graph, list[str]]:
    """The package graph and the problems of every `run` docstring."""
    logic = root / LOGIC_NAME
    folders = sorted(
        folder
        for folder in [logic, *(path for path in logic.rglob("*") if path.is_dir())]
        if "__pycache__" not in folder.parts
    )
    nodes: dict[str, Node] = {}
    trees: dict[str, list[tuple[Path, ast.Module]]] = {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    problems: list[str] = []
    defined: dict[str, set[str]] = {}  # class or alias name -> packages whose contracts define it
    for folder in folders:
        node_id = ".".join(folder.relative_to(root).parts)
        run_tree = parse(folder / "run.py")
        contracts = parse(folder / "contracts.py")
        kind = folder_kind(folder, run_tree, contracts)
        node = Node(node_id, kind, folder.relative_to(root).as_posix())
        nodes[node_id] = node
        trees[node_id] = [
            (path, tree)
            for path in sorted(folder.glob("*.py"))
            if (tree := parse(path)) is not None
        ]
        if contracts is not None:
            for statement in contracts.body:
                if isinstance(statement, ast.ClassDef):
                    defined.setdefault(statement.name, set()).add(node_id)
                elif isinstance(statement, ast.TypeAlias):
                    defined.setdefault(statement.name.id, set()).add(node_id)
            node.errors = tuple(
                statement.name
                for statement in contracts.body
                if isinstance(statement, ast.ClassDef) and statement.name.endswith("Error")
            )
        pipeline = parse(folder / "pipeline.py")
        node.skeleton = pipeline is not None and any(
            isinstance(statement, ast.Raise)
            and statement.exc is not None
            and "NotImplementedError" in ast.unparse(statement.exc)
            for statement in ast.walk(pipeline)
        )
        if run_tree is None:
            continue
        function = run_function(run_tree)
        if function is None:
            problems.append(f"{node.path}/run.py: no `def run`")
            continue
        functions[node_id] = function
        docstring = ast.get_docstring(function)
        if docstring is None:
            problems.append(f"{node.path}/run.py: `def run` has no docstring")
            continue
        node.doc, parse_problems = parse_docstring(docstring)
        facts = run_facts(function)
        node.ports = tuple(
            f"{argument.arg}: {ast.unparse(argument.annotation)}"
            if argument.annotation is not None
            else argument.arg
            for argument in function.args.kwonlyargs
        )
        if function.args.args and function.args.args[0].annotation is not None:
            node.request = ast.unparse(function.args.args[0].annotation)
        if function.returns is not None:
            node.response = ast.unparse(function.returns)
        family = node.kind == "family"
        own = (
            parse_problems
            + value_problems(node.doc, family=family)
            + ([] if family else fact_problems(node.doc, facts))
        )
        problems.extend(f"{node.path}/run.py: {problem}" for problem in own)
        node.effects = tuple(node.doc.values("Effects"))
        node.repeat = next(iter(node.doc.values("Repeat")), "")

    edges = import_edges(nodes, trees, defined)
    for node_id, function in functions.items():
        files = {path.name: tree for path, tree in trees[node_id]}
        methods = method_calls(
            files.get("pipeline.py"), run_aliases(files.get("pipeline.py"), node_id, nodes)
        )
        ports = tuple(argument.arg for argument in function.args.kwonlyargs)
        reader = StepReader(run_aliases(files.get("run.py"), node_id, nodes), methods, ports)
        nodes[node_id].steps = reader.block(function.body)
    adapter = root / ADAPTER_NAME
    if adapter.is_dir():
        add_adapter(adapter, nodes, edges)
    graph = Graph(nodes, edges)
    apply_steps(graph)
    aggregate(graph)
    problems.extend(raises_problems(graph, defined))
    problems.extend(effect_problems(graph))
    mark_alerts(graph)
    return graph, problems


def owning_node(module: str, nodes: dict[str, Node]) -> str | None:
    while module:
        if module in nodes:
            return module
        module = module.rpartition(".")[0]
    return None


def import_edges(
    nodes: dict[str, Node],
    trees: dict[str, list[tuple[Path, ast.Module]]],
    defined: dict[str, set[str]],
) -> list[Edge]:
    """`from <package> import run as <alias>` is a call; a contracts import of `_shared/`, types."""
    edges: dict[tuple[str, str, EdgeKind], Edge] = {}
    for source, files in trees.items():
        for path, tree in files:
            for statement in ast.walk(tree):
                if not isinstance(statement, ast.ImportFrom):
                    continue
                module = resolve(statement.module, statement.level, source)
                target = owning_node(module, nodes)
                if target is None or target == source:
                    continue
                for name in statement.names:
                    if name.name == "run" and module == target:
                        edges.setdefault((source, target, "calls"), Edge(source, target, "calls"))
                    elif SHARED in target.split(".") and not source.startswith(f"{target}."):
                        edges.setdefault((source, target, "types"), Edge(source, target, "types"))
            if path.name == "run.py" and nodes[source].kind == "family":
                for (edge_source, target, kind), edge in edges.items():
                    if edge_source == source and kind == "calls":
                        edge.cases = tuple(
                            sorted(
                                name
                                for name in case_names(tree)
                                if any(
                                    owner == target or owner.startswith(f"{target}.")
                                    for owner in defined.get(name, set())
                                )
                            )
                        )
    # A call edge already says the source depends on the target's contracts.
    calls = {(edge.source, edge.target) for edge in edges.values() if edge.kind == "calls"}
    return [
        edge
        for edge in edges.values()
        if edge.kind == "calls" or (edge.source, edge.target) not in calls
    ]


def add_adapter(adapter: Path, nodes: dict[str, Node], edges: list[Edge]) -> None:
    summary = ""
    application = parse(adapter / "application.py")
    if application is not None:
        summary = (ast.get_docstring(application) or "").split("\n")[0]
    nodes[ADAPTER_NAME] = Node(ADAPTER_NAME, "adapter", ADAPTER_NAME, RunDoc(summary=summary))
    for path in sorted(adapter.rglob("*.py")):
        tree = parse(path)
        if tree is None:
            continue
        for statement in ast.walk(tree):
            if (
                isinstance(statement, ast.ImportFrom)
                and statement.module == LOGIC_NAME
                and any(name.name == "run" for name in statement.names)
                and not any(edge.kind == "enters" for edge in edges)
            ):
                edges.append(Edge(ADAPTER_NAME, LOGIC_NAME, "enters"))


def aggregate(graph: Graph) -> None:
    """A family's effects and repeat are those of everything it dispatches to."""

    def visit(node_id: str, seen: frozenset[str]) -> tuple[set[str], str]:
        node = graph.nodes[node_id]
        if node.kind != "family":
            return set(node.effects), node.repeat
        effects: set[str] = set()
        worst = ""
        for edge in graph.calls_from(node_id):
            if edge.target in seen:
                continue
            child_effects, child_repeat = visit(edge.target, seen | {node_id})
            effects |= child_effects
            worst = max(worst, child_repeat, key=repeat_rank)
        if len(effects) > 1:
            effects.discard("pure")
        node.effects = tuple(effect for effect in EFFECT_STRENGTH if effect in effects)
        node.repeat = worst
        return effects, worst

    for node_id in graph.nodes:
        visit(node_id, frozenset())


def repeat_rank(value: str) -> int:
    order = [member.value for member in Repeat]
    return order.index(value) if value in order else -1


def raises_problems(graph: Graph, defined: dict[str, set[str]]) -> list[str]:
    """`Raises` names exist; each error a package's own contracts define is declared."""
    problems: list[str] = []
    for node in graph.nodes.values():
        if node.kind != "process" or not node.doc.summary:
            continue
        declared = node.doc.values("Raises")
        for name in declared:
            if name not in defined and not is_builtin_exception(name):
                problems.append(
                    f"{node.path}/run.py: Raises: {name!r} is neither a builtin exception nor "
                    "defined in a contracts.py"
                )
        for error in node.errors:
            if error not in declared:
                problems.append(
                    f"{node.path}/run.py: Raises: {error!r} is defined in its contracts.py "
                    "and missing"
                )
    return problems


def effect_problems(graph: Graph) -> list[str]:
    """A process declares every effect of what it calls: calling a writer is writing."""
    problems: list[str] = []
    for node in graph.nodes.values():
        if node.kind != "process" or not node.effects:
            continue
        for edge in graph.calls_from(node.id):
            missing = [
                effect
                for effect in graph.nodes[edge.target].effects
                if effect != "pure" and effect not in node.effects
            ]
            if missing:
                problems.append(
                    f"{node.path}/run.py: Effects: calls {edge.target} ({', '.join(missing)}) "
                    "but does not declare it"
                )
    return problems


def mark_alerts(graph: Graph) -> None:
    """A call repeated by a loop to a package that is not safe to repeat."""
    for edge in graph.edges:
        target = graph.nodes[edge.target]
        if "per-item" in edge.marks and target.repeat not in ("", Repeat.SAFE.value):
            edge.alert = (
                f"{edge.source} calls {edge.target} once per item, and {edge.target} "
                f"repeats as {target.repeat!r}"
            )


# --- outputs ------------------------------------------------------------------------------


def children(graph: Graph, node_id: str, *, shared: bool = True) -> list[Node]:
    """Children by name, `_shared/` last; `shared=False` leaves the shelves out."""
    found = {node.name: node for node in graph.nodes.values() if node.parent == node_id}
    own = sorted(name for name in found if not name.startswith("_"))
    rest = sorted(name for name in found if name.startswith("_")) if shared else []
    return [found[name] for name in [*own, *rest]]


def display(node_id: str) -> str:
    """A package as its path under backend_logic: `notes/_shared/storage/lock`."""
    if "." not in node_id:
        return node_id
    return node_id.removeprefix(f"{LOGIC_NAME}.").replace(".", "/")


def is_shelved(node_id: str) -> bool:
    return SHARED in node_id.split(".")


def short(node_id: str) -> str:
    """A shelved package by its place on the shelf: `storage/lock`, `note_name`."""
    parts = node_id.split(".")
    if SHARED not in parts:
        return display(node_id)
    return "/".join(parts[parts.index(SHARED) + 1 :]) or display(node_id)


def top_shelves(graph: Graph) -> list[Node]:
    """The `_shared/` folders not inside another shelf; the ones inside are drawn within."""
    return [
        node
        for node in graph.nodes.values()
        if node.kind == "shared" and not is_shelved(node.parent or "")
    ]


def node_tags(node: Node) -> str:
    tags: list[str] = [node.kind]
    if node.effects:
        tags.append(",".join(node.effects))
    if node.repeat:
        tags.append(node.repeat)
    for section in ("Loops", "Concurrency"):
        value = next(iter(node.doc.values(section)), "")
        if value and value not in ("none", "free"):
            tags.append(value)
    if node.skeleton:
        tags.append("skeleton")
    return " · ".join(tags)


def users(graph: Graph) -> dict[str, list[str]]:
    """Who calls a package or imports its types."""
    found: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.kind in ("calls", "types"):
            found.setdefault(edge.target, set()).add(edge.source)
    return {target: sorted(sources) for target, sources in found.items()}


def outside_calls(graph: Graph, node: Node) -> list[Edge]:
    """Calls to packages that are not its children: what the tree does not already show."""
    return [
        edge for edge in graph.calls_from(node.id) if graph.nodes[edge.target].parent != node.id
    ]


MARK_WORDS: dict[Mark, str] = {"per-item": "per item", "lock": "lock", "parallel": "in parallel"}


def call_text(call: StepCall) -> str:
    return display(call.target) + (" (per item)" if call.per_item else "")


def step_lines(steps: list[Step]) -> list[str]:
    """The steps of a run as indented lines: frames end with `:`, like the code."""
    lines: list[str] = []
    for step in steps:
        ports = f"({', '.join(step.ports)})" if step.ports else ""
        calls = f" → {', '.join(call_text(call) for call in step.calls)}" if step.calls else ""
        if step.kind in ("method", "call"):
            lines.append(f"{step.label}{ports}{calls}")
        else:
            lines.append(f"{step.label}{calls}:")
            lines.extend(f"  {line}" for line in step_lines(step.steps))
    return lines


def render_text(graph: Graph) -> str:
    """For agents: the use cases with the steps of each run, then the shared shelves."""
    lines: list[str] = []
    used_by = users(graph)
    if ADAPTER_NAME in graph.nodes:
        lines.append(f"{ADAPTER_NAME}  [adapter]  {graph.nodes[ADAPTER_NAME].doc.summary}")
        lines.append(f"  enters {LOGIC_NAME}")

    def visit(node: Node, depth: int, shared: bool) -> None:
        pad = "  " * depth
        folder = "/" if node.kind in ("shared", "grouping") else ""
        label = display(node.id) if depth == 0 else f"{node.name}{folder}"
        summary = f"  {node.doc.summary}" if node.doc.summary else ""
        lines.append(f"{pad}{label}  [{node_tags(node)}]{summary}")
        if shared and node.kind in ("family", "process") and node.id in used_by:
            names = ", ".join(display(user) for user in used_by[node.id])
            lines.append(f"{pad}  │ used by: {names}")
        lines.extend(f"{pad}  │ {line}" for line in step_lines(node.steps))
        for child in children(graph, node.id, shared=shared):
            visit(child, depth + 1, shared)

    visit(graph.nodes[LOGIC_NAME], 0, False)
    for shelf in top_shelves(graph):
        lines.append("")
        lines.append(
            f"shelf {shelf.path}/  (shared by the children of {display(shelf.parent or '')})"
        )
        for child in children(graph, shelf.id):
            visit(child, 1, True)
    if graph.alerts:
        lines.append("")
        lines.append("alerts:")
        lines.extend(f"  ! {alert}" for alert in graph.alerts)
    return "\n".join(lines)


def step_json(step: Step) -> dict[str, object]:
    return {
        "kind": step.kind,
        "label": step.label,
        "calls": [{"target": call.target, "per_item": call.per_item} for call in step.calls],
        "ports": list(step.ports),
        "steps": [step_json(inner) for inner in step.steps],
    }


def node_json(node: Node) -> dict[str, object]:
    return {
        "id": node.id,
        "kind": node.kind,
        "path": node.path,
        "summary": node.doc.summary,
        "description": node.doc.description,
        "sections": {
            name: [{"value": item.value, "note": item.note} for item in items]
            for name, items in node.doc.sections.items()
        },
        "effects": list(node.effects),
        "repeat": node.repeat,
        "ports": list(node.ports),
        "request": node.request,
        "response": node.response,
        "skeleton": node.skeleton,
        "steps": [step_json(step) for step in node.steps],
    }


def render_json(graph: Graph) -> str:
    document: dict[str, object] = {
        "nodes": [node_json(node) for node in graph.nodes.values()],
        "edges": [
            {
                "source": edge.source,
                "target": edge.target,
                "kind": edge.kind,
                "marks": list(edge.marks),
                "cases": list(edge.cases),
                "alert": edge.alert,
            }
            for edge in graph.edges
        ],
        "alerts": graph.alerts,
        "hidden": graph.hidden,
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


EFFECT_COLOURS = {
    # Bright enough to read as a signal on the page's dark background.
    "model": "#b48cff",
    "network": "#3fd8d8",
    "writes": "#ffa94d",
    "reads": "#5ea8ff",
    "time": "#d4d95a",
    "pure": "#6fdc8c",
    "": "#8e99ae",
}
KIND_WORDS: dict[NodeKind, str] = {
    "family": "family: sends each request to one case, by match",
    "process": "process: a chain of steps, in the order of its run",
    "shared": "shelf: packages used by two or more children of the parent",
    "grouping": "grouping: the contracts its operations exchange; no run",
    "adapter": "HTTP adapter: enters only through backend_logic/run.py",
}


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def marks_html(marks: tuple[Mark, ...] | list[Mark]) -> str:
    return "".join(f'<span class="mark {mark}">{MARK_WORDS[mark]}</span>' for mark in marks)


def go(node_id: str, label: str) -> str:
    return f'<button type="button" class="go" data-go="{esc(node_id)}">{esc(label)}</button>'


def card(graph: Graph, node: Node, used_by: dict[str, list[str]], cases: tuple[str, ...]) -> str:
    """A package in the tree or on a shelf; calls outside its children become chips."""
    strongest = next((effect for effect in EFFECT_STRENGTH if effect in node.effects), "")
    classes = " ".join(["node", node.kind, *(["skeleton"] if node.skeleton else [])])
    related = {edge.target for edge in graph.edges if edge.source == node.id}
    related |= set(used_by.get(node.id, []))
    folder = "/" if node.kind in ("shared", "grouping") else ""
    # A shelf is named by its full path: whose children share it is the point.
    label = node.path if node.parent is None or node.kind == "shared" else node.name
    parts = [f'<div class="h"><b>{esc(label + folder)}</b>']
    if node.kind != "shared":
        parts.append(f'<span class="t">{esc(node_tags(node))}</span>')
    parts.append("</div>")
    if cases:
        parts.append(f'<div class="case">case {esc(", ".join(cases))}</div>')
    summary = node.doc.summary
    if node.kind == "shared":
        summary = f"used by two or more children of {display(node.parent or '')}"
    if summary:
        parts.append(f'<div class="sum">{esc(summary)}</div>')
    chips = "".join(
        f'<span class="chip" data-go="{esc(edge.target)}">{esc(short(edge.target))}'
        f"{marks_html(edge.marks)}</span>"
        for edge in outside_calls(graph, node)
    )
    if chips:
        parts.append(f'<div class="uses">uses {chips}</div>')
    if is_shelved(node.id) and node.kind == "process" and node.id in used_by:
        names = ", ".join(display(user) for user in used_by[node.id])
        parts.append(f'<div class="by">used by {esc(names)}</div>')
    rel = " ".join(sorted(related))
    return (
        f'<div class="{classes}" data-id="{esc(node.id)}" data-rel="{esc(rel)}" '
        f'data-fx="{esc(" ".join(node.effects))}" tabindex="0" role="button" '
        f'aria-label="{esc(node.id)}: {esc(summary)}" '
        f'style="--c:{EFFECT_COLOURS[strongest]}">{"".join(parts)}</div>'
    )


def steps_html(steps: list[Step]) -> str:
    items: list[str] = []
    for step in steps:
        ports = f'<span class="ports">({esc(", ".join(step.ports))})</span>' if step.ports else ""
        calls = "".join(
            go(call.target, f"→ {short(call.target)}")
            + (marks_html(["per-item"]) if call.per_item else "")
            for call in step.calls
        )
        if step.kind in ("method", "call"):
            items.append(
                f'<li class="step {step.kind}"><code>{esc(step.label)}</code>{ports}{calls}</li>'
            )
        else:
            items.append(
                f'<li class="frame {step.kind}"><div class="fl">{esc(step.label)}{calls}</div>'
                f"<ol>{steps_html(step.steps)}</ol></li>"
            )
    return "".join(items)


def panel(graph: Graph, node: Node, used_by: dict[str, list[str]]) -> str:
    """Everything about one package, shown when it is selected."""
    parts = [
        f"<h2>{esc(display(node.id))}{'/' if node.kind in ('shared', 'grouping') else ''}</h2>",
        f'<p class="kind">{esc(KIND_WORDS[node.kind])}</p>',
    ]
    if node.doc.summary:
        parts.append(f"<p>{esc(node.doc.summary)}</p>")
    if node.doc.description:
        parts.append(f'<p class="d">{esc(node.doc.description)}</p>')
    if node.request or node.response:
        parts.append(f"<p><code>{esc(node.request)} → {esc(node.response)}</code></p>")
    if node.ports:
        parts.append(f"<p>ports: <code>{esc(', '.join(node.ports))}</code></p>")
    if node.steps:
        parts.append("<h3>Steps of run, in order</h3>")
        parts.append(f'<ol class="steps">{steps_html(node.steps)}</ol>')
    if node.kind == "family" and node.effects:
        parts.append("<h3>From its cases</h3>")
        parts.append(f"<p>{esc(', '.join(node.effects))} · repeat {esc(node.repeat)}</p>")
    if node.doc.sections:
        parts.append("<h3>Declared in the docstring</h3><dl>")
        for name, items in node.doc.sections.items():
            values = "".join(
                f"<dd><b>{esc(item.value)}</b>{': ' + esc(item.note) if item.note else ''}</dd>"
                for item in items
            )
            parts.append(f"<dt>{name}</dt>{values}")
        parts.append("</dl>")
    outgoing = sorted((edge for edge in graph.edges if edge.source == node.id), key=edge_order)
    if outgoing:
        verbs = {"calls": "calls", "types": "uses the types of", "enters": "enters"}
        rows = "".join(
            f'<li class="edge {edge.kind}" data-source="{esc(edge.source)}" '
            f'data-target="{esc(edge.target)}">{verbs[edge.kind]} '
            f"{go(edge.target, display(edge.target))}{marks_html(edge.marks)}"
            + (
                f' <span class="ports">case {esc(", ".join(edge.cases))}</span>'
                if edge.cases
                else ""
            )
            + (f'<div class="alert">{esc(edge.alert)}</div>' if edge.alert else "")
            + "</li>"
            for edge in outgoing
        )
        parts.append(f"<h3>Depends on</h3><ul>{rows}</ul>")
    if node.id in used_by:
        rows = "".join(f"<li>{go(user, display(user))}</li>" for user in used_by[node.id])
        parts.append(f"<h3>Used by</h3><ul>{rows}</ul>")
    if node.skeleton:
        parts.append('<p class="alert">skeleton: some bodies still raise NotImplementedError</p>')
    return f'<section class="panel" data-for="{esc(node.id)}" hidden>{"".join(parts)}</section>'


def graph_layout(
    graph: Graph,
) -> tuple[dict[str, tuple[int, float]], list[tuple[str, float, float, int]]]:
    """Columns by depth, rows by leaf order; each `_shared/` shelf in a band below the cases."""
    positions: dict[str, tuple[int, float]] = {}
    row = [0.0]

    def place(node: Node, depth: int, shared: bool) -> float:
        kids = children(graph, node.id, shared=shared)
        if kids:
            ys = [place(kid, depth + 1, shared) for kid in kids]
            y = (ys[0] + ys[-1]) / 2
        else:
            y = row[0]
            row[0] += 1
        positions[node.id] = (depth, y)
        return y

    place(graph.nodes[LOGIC_NAME], 1, False)
    if ADAPTER_NAME in graph.nodes:
        positions[ADAPTER_NAME] = (0, positions[LOGIC_NAME][1])
    bands: list[tuple[str, float, float, int]] = []
    for shelf in top_shelves(graph):
        row[0] += 0.7  # room for the band's label
        first = row[0]
        # A folder's depth is its number of parts: backend_logic is 1, backend_logic/x is 2.
        place(shelf, len(shelf.id.split(".")), True)
        bands.append((shelf.path, first, row[0] - 1, positions[shelf.id][0]))
    return positions, bands


def graph_data(graph: Graph) -> str:
    """The graph view's data, as JSON safe inside a <script> and inside the page template."""
    positions, bands = graph_layout(graph)
    nodes: list[dict[str, object]] = []
    for node in graph.nodes.values():
        if node.id not in positions:
            continue
        column, row = positions[node.id]
        strongest = next((effect for effect in EFFECT_STRENGTH if effect in node.effects), "")
        folder = "/" if node.kind in ("shared", "grouping") else ""
        # In the graph a shelf sits inside a band that already names its full path.
        label = node.path if node.parent is None else node.name
        nodes.append(
            {
                "id": node.id,
                "parent": node.parent or "",
                "label": label + folder,
                "kind": node.kind,
                "shelved": is_shelved(node.id),
                "colour": EFFECT_COLOURS[strongest],
                "effects": list(node.effects),
                "tags": node_tags(node),
                "summary": node.doc.summary,
                "x": column,
                "y": row,
            }
        )
    edges: list[dict[str, object]] = [
        {
            "source": edge.source,
            "target": edge.target,
            "kind": edge.kind,
            "marks": [MARK_WORDS[mark] for mark in edge.marks],
            "alert": edge.alert,
        }
        for edge in graph.edges
        if edge.source in positions and edge.target in positions
    ]
    shelves: list[dict[str, object]] = [
        {"label": label, "y0": first, "y1": last, "x": column}
        for label, first, last, column in bands
    ]
    document: dict[str, object] = {"nodes": nodes, "edges": edges, "bands": shelves}
    text = json.dumps(document, ensure_ascii=False)
    # `<` would close the script early; `$` would read as a slot of the page template.
    return text.replace("<", "\\u003c").replace("$", "\\u0024")


def render_html(graph: Graph) -> str:
    """A self-contained page: the use-case tree with shelves apart, a graph view, a step panel."""
    used_by = users(graph)
    cases = {edge.target: edge.cases for edge in graph.edges if edge.kind == "calls" and edge.cases}

    def branch(node: Node, shared: bool) -> str:
        inner = "".join(branch(child, shared) for child in children(graph, node.id, shared=shared))
        nested = f"<ul>{inner}</ul>" if inner else ""
        return f"<li>{card(graph, node, used_by, cases.get(node.id, ()))}{nested}</li>"

    root = branch(graph.nodes[LOGIC_NAME], False)
    if ADAPTER_NAME in graph.nodes:
        adapter = card(graph, graph.nodes[ADAPTER_NAME], used_by, ())
        root = f"<li>{adapter}<ul>{root}</ul></li>"
    shelves = "".join(
        f'<div class="shelf">{card(graph, shelf, used_by, ())}<ul class="tree">'
        + "".join(branch(child, True) for child in children(graph, shelf.id))
        + "</ul></div>"
        for shelf in top_shelves(graph)
    )
    legend = "".join(
        f'<button type="button" class="fx" data-fx="{effect}" aria-pressed="false" '
        f'style="--c:{colour}"><i></i>{effect}</button>'
        for effect, colour in EFFECT_COLOURS.items()
        if effect
    )
    kinds = [node.kind for node in graph.nodes.values()]
    counts = [
        ("families", kinds.count("family")),
        ("processes", sum(1 for node in graph.nodes.values() if node.kind == "process")),
        ("shelves", len(top_shelves(graph))),
        ("calls", sum(1 for edge in graph.edges if edge.kind == "calls")),
        ("alerts", len(graph.alerts)),
    ]
    stats = "".join(
        f'<span class="stat{" warn" if name == "alerts" and count else ""}">'
        f'<b data-n="{count}">{count}</b>{name}</span>'
        for name, count in counts
    )
    alerts = "".join(f"<li>{esc(alert)}</li>" for alert in graph.alerts)
    return PAGE.substitute(
        tree=f'<ul class="tree">{root}</ul>',
        shelves=shelves,
        panels="".join(panel(graph, node, used_by) for node in graph.nodes.values()),
        legend=legend,
        stats=stats,
        data=graph_data(graph),
        alerts=f'<ul class="alerts">{alerts}</ul>' if alerts else "",
    )


# The page is a string.Template: `$name` is a slot, so the CSS and JS never use a dollar sign.
PAGE = Template("""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Architecture</title>
<style>
:root{--bg:#090c12;--s1:#0f1520;--s2:#151d2c;--line:#222d42;--tx:#e7ecf6;--mu:#8e99ae;
 --a1:#8b5cf6;--a2:#22d3ee;--bad:#ff6b6b;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;font:13px/1.5 ui-sans-serif,system-ui,sans-serif;color:var(--tx);min-height:100vh;
 background:radial-gradient(1100px 600px at 8% -10%,#1e1645 0,transparent 60%),
 radial-gradient(900px 520px at 100% 0,#0d2c38 0,transparent 55%),var(--bg)}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;
 background-image:linear-gradient(#ffffff07 1px,transparent 1px),
 linear-gradient(90deg,#ffffff07 1px,transparent 1px);background-size:28px 28px;
 mask-image:linear-gradient(#000,transparent 85%)}
code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
header{padding:18px 24px 12px;display:grid;gap:10px;border-bottom:1px solid var(--line)}
.top{display:flex;flex-wrap:wrap;align-items:center;gap:18px}
h1{margin:0;font-size:24px;letter-spacing:-.02em;font-weight:750;
 background:linear-gradient(90deg,var(--a1),var(--a2),var(--a1));background-size:200% 100%;
 -webkit-background-clip:text;background-clip:text;color:transparent;
 animation:sheen 8s linear infinite}
@keyframes sheen{to{background-position:200% 0}}
.sub{color:var(--mu);font-size:12px}
.stats{display:flex;gap:16px;margin-left:auto}
.stat{color:var(--mu);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.stat b{display:block;font-size:20px;color:var(--tx);letter-spacing:0;
 font-variant-numeric:tabular-nums}
.stat.warn b{color:var(--bad)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:12px}
.seg{position:relative;display:inline-flex;background:var(--s1);border:1px solid var(--line);
 border-radius:999px;padding:3px}
.seg button{position:relative;z-index:1;width:78px;font:inherit;font-weight:600;color:var(--mu);
 background:none;border:0;padding:5px 0;border-radius:999px;cursor:pointer;transition:color .3s}
.seg button[aria-selected=true]{color:#fff}
.seg .pill{position:absolute;top:3px;bottom:3px;left:3px;width:78px;border-radius:999px;
 background:linear-gradient(90deg,var(--a1),var(--a2));box-shadow:0 4px 20px -4px var(--a1);
 transition:transform .4s cubic-bezier(.2,.9,.2,1)}
.seg[data-view=graph] .pill{transform:translateX(78px)}
#search{font:inherit;color:var(--tx);background:var(--s1);border:1px solid var(--line);
 border-radius:999px;padding:6px 14px;width:240px;outline:none;transition:border-color .2s,
 box-shadow .2s}
#search:focus{border-color:var(--a2);box-shadow:0 0 0 3px #22d3ee22}
.fx{font:inherit;font-size:12px;color:var(--tx);background:var(--s1);border:1px solid var(--line);
 border-radius:999px;padding:3px 10px;cursor:pointer;transition:all .2s}
.fx i{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);
 margin-right:6px;box-shadow:0 0 8px var(--c)}
.fx:hover{border-color:var(--c)}
.fx[aria-pressed=true]{border-color:var(--c);background:color-mix(in srgb,var(--c) 22%,var(--s1))}
.key{color:var(--mu);font-size:12px}
.alerts{color:var(--bad);margin:0;padding-left:18px}
main{display:grid;grid-template-columns:minmax(0,1fr) 440px;gap:20px;padding:18px 24px;
 align-items:start}
h2.part{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--a2);
 margin:4px 0 2px}
p.how{color:var(--mu);margin:0 0 12px;max-width:80ch}
.tree,.tree ul{list-style:none;margin:0;padding:0}
.tree ul{margin-left:16px}
.tree li{position:relative;padding:4px 0 4px 22px;border-left:1.5px solid var(--line)}
.tree>li{border-left:0;padding-left:0}
.tree li:last-child{border-left-color:transparent}
.tree ul>li::before{content:"";position:absolute;left:-1.5px;top:0;width:18px;height:24px;
 border-left:1.5px solid var(--line);border-bottom:1.5px solid var(--line);
 border-bottom-left-radius:8px}
.node{display:inline-block;min-width:300px;max-width:640px;border:1px solid var(--line);
 border-left:3px solid var(--c);border-radius:11px;padding:6px 12px;cursor:pointer;
 background:radial-gradient(260px circle at var(--mx,-300px) var(--my,-300px),
 color-mix(in srgb,var(--c) 20%,transparent),transparent 70%),
 linear-gradient(180deg,var(--s2),var(--s1));
 transition:opacity .2s,transform .2s,box-shadow .2s;animation:rise .5s both;
 animation-delay:calc(var(--i,0) * 22ms)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}}
.node:hover{transform:translateY(-1px);
 box-shadow:0 0 0 1px color-mix(in srgb,var(--c) 55%,transparent),0 12px 32px -14px var(--c)}
.node:focus-visible{outline:2px solid var(--a2);outline-offset:2px}
.node.family{box-shadow:inset 0 0 0 1px #ffffff1a}
.node.adapter{background:linear-gradient(90deg,#2b1c5c,#0e3542);border-left-color:var(--a2)}
.node.skeleton{border-style:dashed}
.node.shared,.node.grouping{background:#ffffff05;border-style:dashed;border-left-color:#ffffff30}
.node .h b{font-size:13.5px} .node .t{color:var(--mu);font-size:11px;margin-left:8px}
.node .sum{color:#c6cddc}
.node .case{display:inline-block;font-size:11px;color:#d8ccff;background:#8b5cf626;
 border-radius:5px;padding:0 6px}
.node .by{font-size:11px;color:var(--mu)}
.chip{display:inline-block;font-size:11px;border:1px dashed #ffffff2e;border-radius:10px;
 padding:0 8px;margin:3px 4px 0 0;background:#ffffff08;transition:border-color .2s}
.chip:hover{border-color:var(--a2)}
.node.sel{outline:2px solid var(--a2);outline-offset:2px}
.node.rel{box-shadow:0 0 0 1px var(--a2),0 0 26px -6px var(--a2)}
body.relating .node:not(.rel):not(.me){opacity:.32}
.faded{opacity:.12 !important}
.shelves{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}
.shelf{border:1px dashed #ffffff26;border-radius:16px;padding:10px 14px 12px;background:#ffffff04}
.shelf>.tree{margin-top:6px}
#stage{position:relative;height:calc(100vh - 60px);min-height:480px;border:1px solid var(--line);
 border-radius:16px;overflow:hidden;background:#0a0f18d9}
#graph{width:100%;height:100%;display:block;cursor:grab;touch-action:none;user-select:none}
#graph.drag{cursor:grabbing}
.tools{position:absolute;right:12px;top:12px;display:flex;gap:6px}
.tools button{font:inherit;color:var(--tx);background:var(--s2);border:1px solid var(--line);
 border-radius:8px;min-width:32px;height:30px;cursor:pointer}
.tools button:hover{border-color:var(--a2)}
.hint{position:absolute;left:14px;bottom:10px;color:var(--mu);font-size:11.5px}
.band{fill:#ffffff04;stroke:#ffffff22;stroke-dasharray:5 5}
.bl{fill:var(--mu);font-size:11px;letter-spacing:.06em}
path.tree{fill:none;stroke:#ffffff14;stroke-width:1.2}
path.e{fill:none;stroke-width:1.4;opacity:.55;transition:opacity .25s,stroke-width .25s;
 animation:fade .8s both;animation-delay:calc(300ms + var(--i,0) * 12ms)}
path.e.calls{stroke:#7c8cff} path.e.enters{stroke:#e7ecf6}
path.e.types{stroke:#5d6b85;stroke-dasharray:3 4} path.e.alert{stroke:var(--bad)}
.elabel{fill:#ffc078;font-size:10px;paint-order:stroke;stroke:#0a0f18;stroke-width:3px;
 transition:opacity .25s}
.gnode{cursor:pointer;transition:opacity .25s;animation:fade .5s both;
 animation-delay:calc(var(--i,0) * 14ms)}
@keyframes fade{from{opacity:0}}
.gnode rect.b{fill:#131b2a;stroke:#2a3853;transition:stroke .2s}
.gnode.family rect.b{stroke:#56658a;stroke-width:1.5}
.gnode.adapter rect.b{fill:#1f1946;stroke:var(--a2)}
.gnode.shared rect.b,.gnode.grouping rect.b{fill:#0d131d;stroke-dasharray:4 3}
.gnode text{fill:var(--tx);font-size:12.5px;font-weight:600}
.gnode text.t{fill:var(--mu);font-size:10px;font-weight:400}
.gnode:hover rect.b,.gnode.rel rect.b,.gnode:focus rect.b{stroke:var(--a2)}
.gnode:focus{outline:none} .gnode.sel rect.b{stroke:#fff;stroke-width:2}
#graph.hot path.e,#graph.hot .elabel{opacity:.07}
#graph.hot path.e.hot{opacity:1;stroke-width:2.4;stroke-dasharray:7 6;
 animation:flow .5s linear infinite}
#graph.hot .elabel.hot{opacity:1}
#graph.hot .gnode:not(.rel){opacity:.22}
@keyframes flow{to{stroke-dashoffset:-13}}
aside{position:sticky;top:14px;max-height:calc(100vh - 28px);overflow:auto;
 background:#0f1520cc;backdrop-filter:blur(14px);border:1px solid var(--line);
 border-radius:16px;padding:14px 16px;box-shadow:0 20px 60px -30px #000}
.panel h2{margin:0;font-size:16px;word-break:break-all;
 background:linear-gradient(90deg,#fff,#b9c6ff);-webkit-background-clip:text;
 background-clip:text;color:transparent}
.panel .kind{color:var(--mu);margin:2px 0 8px}
.panel h3{font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;color:var(--a2);
 margin:16px 0 6px}
.panel .d{color:var(--mu)} .panel ul{padding-left:18px;margin:2px 0}
.panel dt{font-weight:600;margin-top:4px} .panel dd{margin:0 0 0 14px;color:#c6cddc}
.panel li.in{animation:slide .35s both;animation-delay:calc(var(--i,0) * 32ms)}
@keyframes slide{from{opacity:0;transform:translateX(10px)}}
.steps,.steps ol{list-style:none;margin:0;padding:0} .steps{counter-reset:step}
.steps li{margin:4px 0}
.step{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px}
.step::before{counter-increment:step;content:counter(step);display:inline-grid;
 place-items:center;width:20px;height:20px;margin-right:6px;border-radius:50%;
 background:var(--s2);border:1px solid var(--line);color:var(--mu);font-size:10.5px}
.step code{background:#ffffff0a;border-radius:5px;padding:1px 6px}
.frame{border-left:2px solid #ffffff30;padding:4px 6px 4px 10px;margin:6px 0;
 border-radius:0 10px 10px 0;background:#ffffff05}
.frame>.fl{font-size:11.5px;color:#c6cddc;font-weight:600}
.frame.lock{border-color:#b48cff;background:#b48cff12}
.frame.parallel{border-color:var(--a2);background:#22d3ee10}
.frame.loop{border-color:#ffa94d;background:#ffa94d10}
.go{font:inherit;font-size:12px;color:#8fb4ff;background:none;border:0;padding:0;
 margin-left:6px;cursor:pointer}
.go:hover{color:var(--a2);text-decoration:underline}
.mark{font-size:10.5px;border-radius:4px;padding:0 5px;margin-left:4px}
.mark.per-item{background:#ffa94d24;color:#ffc078}
.mark.lock{background:#b48cff26;color:#d6c4ff}
.mark.parallel{background:#22d3ee22;color:#99e9f2}
.ports{color:var(--mu);font-size:11.5px} .alert{color:var(--bad)}
kbd{font:11px ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;
 border-radius:4px;padding:0 4px;color:var(--tx)}
body.graphing main{grid-template-columns:minmax(0,1fr) 340px}
@media (max-width:980px){main{grid-template-columns:1fr} aside{position:static;max-height:none}
 .stats{margin-left:0}}
@media (prefers-reduced-motion:reduce){*,*::before{animation:none !important;
 transition:none !important}}
</style></head><body>
<header>
<div class="top"><div><h1>Architecture</h1>
<div class="sub">generated from the code by tests/support/architecture.py</div></div>
<div class="stats">$stats</div></div>
<div class="bar">
<div class="seg" data-view="tree" role="tablist" aria-label="View"><span class="pill"></span>
<button type="button" role="tab" data-v="tree" aria-selected="true"
 aria-controls="view-tree">Tree</button>
<button type="button" role="tab" data-v="graph" aria-selected="false"
 aria-controls="view-graph">Graph</button></div>
<input id="search" type="search" placeholder="Filter packages" aria-label="Filter packages">
<div class="legend" role="group" aria-label="Highlight by effect">$legend</div>
</div>
<div class="key">left border: strongest effect · thick frame: family · dashed: _shared/ or
grouping · chip: a package it uses outside its own children ·
<span class="mark per-item">per item</span> <span class="mark lock">lock</span>
<span class="mark parallel">in parallel</span> · keys <kbd>t</kbd> tree <kbd>g</kbd> graph
<kbd>/</kbd> filter <kbd>Esc</kbd> clear</div>
$alerts</header>
<main><div>
<section id="view-tree" role="tabpanel" aria-label="Tree">
<h2 class="part">Use cases: the climb from the door</h2>
<p class="how">Each request enters at the top and descends one level per family, by match, to
the process that serves it; the children of a process are its steps. Hover a package to light
up what it uses and who uses it; select it to read the steps of its run.</p>
$tree
<h2 class="part" style="margin-top:22px">Shared shelves</h2>
<p class="how">What two or more neighbours share lives on the shelf of their nearest common
parent, apart from the use cases: the chips above say who takes what.</p>
<div class="shelves">$shelves</div>
</section>
<section id="view-graph" role="tabpanel" aria-label="Graph" hidden>
<div id="stage"><svg id="graph" aria-label="Package graph">
<defs>
<marker id="m-calls" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
 orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#7c8cff"/></marker>
<marker id="m-enters" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
 orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#e7ecf6"/></marker>
<marker id="m-types" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6"
 orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#5d6b85"/></marker>
</defs><g id="world"></g></svg>
<div class="tools"><button type="button" data-zoom="1.25" aria-label="Zoom in">+</button>
<button type="button" data-zoom="0.8" aria-label="Zoom out">−</button>
<button type="button" id="fit" aria-label="Fit to width">fit</button></div>
<div class="hint">drag to pan · wheel to scroll · Ctrl + wheel to zoom · hover to trace ·
click to open</div></div>
</section>
</div>
<aside id="aside"><section class="panel" data-for=""><h2>How to read</h2>
<p>Select a package (click, or Tab and Enter) to see its run as numbered steps, inside the
frames the code has: a lock, a branch, a loop, a TaskGroup. An arrow names the package a step
calls.</p><p class="d">The tree is the reading path; the graph shows every call at once, which
is busier but shows the whole system.</p></section>
$panels</aside></main>
<script type="application/json" id="data">$data</script>
<script>
const D=JSON.parse(document.getElementById("data").textContent);
const q=s=>document.querySelector(s), qa=s=>[...document.querySelectorAll(s)];
const calm=matchMedia("(prefers-reduced-motion: reduce)").matches;
const cards=qa(".node"), panels=qa(".panel"), svg=q("#graph"), world=q("#world");
const W=210,H=42,COL=270,ROW=56,PAD=40;
const byNode=new Map(D.nodes.map(n=>[n.id,n]));
let drawn=false, cam={x:0,y:0,k:1}, fxOn=new Set();
const X=n=>PAD+n.x*COL, Y=n=>PAD+n.y*ROW;
const ent={"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"};
const e=s=>String(s).replace(/[&<>"]/g,c=>ent[c]);
const cut=(s,k)=>s.length>k?s.slice(0,k-1)+"…":s;
const at=(x,y)=>x+","+y;
function draw(){
 let out="";
 const right=Math.max(...D.nodes.map(X))+W+PAD;
 D.bands.forEach(b=>{
  const x=PAD+b.x*COL-18, y=PAD+b.y0*ROW-28, h=(b.y1-b.y0)*ROW+H+44;
  out+='<rect class="band" x="'+x+'" y="'+y+'" width="'+(right-x)+'" height="'+h+'" rx="16"/>';
  out+='<text class="bl" x="'+(x+14)+'" y="'+(y+17)+'">SHELF '+e(b.label)+'/</text>';
 });
 D.nodes.forEach(n=>{
  const p=byNode.get(n.parent);
  // A top shelf is not tied to its parent by a line: it is drawn apart, in its band.
  if(!p||(n.kind==="shared"&&!p.shelved))return;
  const sx=X(p)+W, sy=Y(p)+H/2, tx=X(n), ty=Y(n)+H/2, m=sx+(tx-sx)/2;
  out+='<path class="tree" d="M'+at(sx,sy)+" H"+m+" V"+ty+" H"+tx+'"/>';
 });
 D.edges.forEach((g,i)=>{
  const s=byNode.get(g.source), t=byNode.get(g.target);
  const sx=X(s)+W, sy=Y(s)+H/2, tx=X(t), ty=Y(t)+H/2, k=Math.max(70,Math.abs(tx-sx)/2);
  const c1=sx+k, c2=tx-k, ref=' data-s="'+e(g.source)+'" data-t="'+e(g.target)+'"';
  const title=g.alert||(g.source+" "+g.kind+" "+g.target);
  out+='<path class="e '+g.kind+(g.alert?" alert":"")+'"'+ref+' style="--i:'+i+'" d="M'
   +at(sx,sy)+" C"+at(c1,sy)+" "+at(c2,ty)+" "+at(tx,ty)+'" marker-end="url(#m-'+g.kind
   +')"><title>'+e(title)+"</title></path>";
  if(g.marks.length){
   out+='<text class="elabel"'+ref+' x="'+(sx+3*c1+3*c2+tx)/8+'" y="'+((sy+ty)/2-5)
    +'" text-anchor="middle">'+e(g.marks.join(" · "))+"</text>";
  }
 });
 D.nodes.forEach((n,i)=>{
  out+='<g class="gnode '+n.kind+'" data-id="'+e(n.id)+'" data-fx="'+e(n.effects.join(" "))
   +'" tabindex="0" role="button" aria-label="'+e(n.id+": "+n.summary)+'" style="--i:'+i
   +'" transform="translate('+at(X(n),Y(n))+')"><rect class="b" width="'+W+'" height="'+H
   +'" rx="10"/><rect width="4" height="'+(H-14)+'" x="0" y="7" rx="2" fill="'+n.colour
   +'"/><text x="14" y="18">'+e(cut(n.label,25))+'</text><text class="t" x="14" y="32">'
   +e(cut(n.tags,36))+"</text><title>"+e(n.summary||n.id)+"</title></g>";
 });
 world.innerHTML=out;
 drawn=true;
 filter();
}
function apply(){world.setAttribute("transform","translate("+at(cam.x,cam.y)+") scale("+cam.k+")");}
// fit shows the whole graph; home starts readable from the door, at the top left.
function fit(){
 const b=world.getBBox(), r=svg.getBoundingClientRect();
 if(!b.width||!r.width)return;
 const k=Math.min((r.width-40)/b.width,(r.height-40)/b.height,1.1);
 cam={k,x:(r.width-b.width*k)/2-b.x*k,y:(r.height-b.height*k)/2-b.y*k};
 apply();
}
function home(){
 const b=world.getBBox();
 cam={k:.85,x:24-b.x*.85,y:60-b.y*.85}; apply();
}
function zoom(f,mx,my){
 const k=Math.min(3,Math.max(.15,cam.k*f));
 cam.x=mx-(mx-cam.x)*k/cam.k; cam.y=my-(my-cam.y)*k/cam.k; cam.k=k; apply();
}
svg.addEventListener("wheel",ev=>{
 ev.preventDefault();
 const r=svg.getBoundingClientRect();
 if(ev.ctrlKey||ev.metaKey){zoom(Math.exp(-ev.deltaY*.002),ev.clientX-r.left,ev.clientY-r.top);}
 else{cam.x-=ev.deltaX;cam.y-=ev.deltaY;apply();}
},{passive:false});
let drag=null;
svg.addEventListener("pointerdown",ev=>{
 if(ev.target.closest(".gnode"))return;
 drag={x:ev.clientX-cam.x,y:ev.clientY-cam.y}; svg.setPointerCapture(ev.pointerId);
 svg.classList.add("drag");
});
svg.addEventListener("pointermove",ev=>{
 if(drag){cam.x=ev.clientX-drag.x;cam.y=ev.clientY-drag.y;apply();}
});
svg.addEventListener("pointerup",()=>{drag=null;svg.classList.remove("drag");});
qa("[data-zoom]").forEach(b=>b.addEventListener("click",()=>{
 const r=svg.getBoundingClientRect(); zoom(+b.dataset.zoom,r.width/2,r.height/2);
}));
q("#fit").addEventListener("click",fit);
function trace(id){
 svg.classList.toggle("hot",!!id);
 const near=new Set([id]);
 qa("#world [data-s]").forEach(p=>{
  const on=!!id&&(p.dataset.s===id||p.dataset.t===id);
  p.classList.toggle("hot",on);
  if(on){near.add(p.dataset.s);near.add(p.dataset.t);}
 });
 qa(".gnode").forEach(g=>g.classList.toggle("rel",!!id&&near.has(g.dataset.id)));
}
const hit=ev=>ev.target.closest(".gnode");
world.addEventListener("mouseover",ev=>{const g=hit(ev);trace(g?g.dataset.id:"");});
world.addEventListener("mouseleave",()=>trace(""));
world.addEventListener("focusin",ev=>{const g=hit(ev);if(g)trace(g.dataset.id);});
world.addEventListener("focusout",()=>trace(""));
world.addEventListener("click",ev=>{const g=hit(ev);if(g)select(g.dataset.id);});
world.addEventListener("keydown",ev=>{
 const g=ev.target.closest(".gnode");
 if(g&&(ev.key==="Enter"||ev.key===" ")){ev.preventDefault();select(g.dataset.id);}
});
function select(id){
 qa(".node,.gnode").forEach(n=>n.classList.toggle("sel",n.dataset.id===id));
 panels.forEach(p=>{p.hidden=p.dataset.for!==id;});
 const p=panels.find(p=>p.dataset.for===id);
 if(p&&!calm){p.querySelectorAll("li").forEach((li,i)=>{
  li.style.setProperty("--i",Math.min(i,30)); li.classList.remove("in");
  void li.offsetWidth; li.classList.add("in");
 });}
 const c=cards.find(n=>n.dataset.id===id);
 if(c&&!q("#view-tree").hidden){c.scrollIntoView({block:"nearest",behavior:"smooth"});}
 q("#aside").scrollTop=0;
}
function relate(id){
 const n=cards.find(c=>c.dataset.id===id), rel=new Set(n?n.dataset.rel.split(" "):[]);
 cards.forEach(m=>{
  m.classList.toggle("rel",rel.has(m.dataset.id));
  m.classList.toggle("me",m.dataset.id===id);
 });
 document.body.classList.toggle("relating",!!n);
}
cards.forEach((n,i)=>{
 n.style.setProperty("--i",Math.min(i,40));
 n.addEventListener("click",ev=>{if(!ev.target.closest("[data-go]")){select(n.dataset.id);}});
 n.addEventListener("keydown",ev=>{
  if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();select(n.dataset.id);}
 });
 n.addEventListener("mouseenter",()=>relate(n.dataset.id));
 n.addEventListener("mouseleave",()=>relate(""));
 n.addEventListener("focus",()=>relate(n.dataset.id));
 n.addEventListener("blur",()=>relate(""));
 n.addEventListener("pointermove",ev=>{
  const r=n.getBoundingClientRect();
  n.style.setProperty("--mx",(ev.clientX-r.left)+"px");
  n.style.setProperty("--my",(ev.clientY-r.top)+"px");
 });
});
document.addEventListener("click",ev=>{
 const g=ev.target.closest("[data-go]"); if(g){select(g.dataset.go);}
});
function filter(){
 const s=q("#search").value.trim().toLowerCase();
 qa(".node,.gnode").forEach(n=>{
  const hay=(n.dataset.id+" "+(n.getAttribute("aria-label")||"")).toLowerCase();
  const fx=(n.dataset.fx||"").split(" ");
  const out=(s&&!hay.includes(s))||(fxOn.size>0&&!fx.some(f=>fxOn.has(f)));
  n.classList.toggle("faded",!!out);
 });
}
q("#search").addEventListener("input",filter);
qa(".fx").forEach(b=>b.addEventListener("click",()=>{
 const f=b.dataset.fx, on=!fxOn.has(f);
 if(on){fxOn.add(f);}else{fxOn.delete(f);}
 b.setAttribute("aria-pressed",String(on)); filter();
}));
function show(name){
 const graph=name==="graph";
 q("#view-tree").hidden=graph; q("#view-graph").hidden=!graph;
 q(".seg").dataset.view=name; document.body.classList.toggle("graphing",graph);
 qa(".seg button").forEach(b=>b.setAttribute("aria-selected",String(b.dataset.v===name)));
 history.replaceState(null,"","#"+name);
 if(graph&&!drawn){draw();requestAnimationFrame(home);}
}
qa(".seg button").forEach(b=>b.addEventListener("click",()=>show(b.dataset.v)));
document.addEventListener("keydown",ev=>{
 const typing=ev.target.matches("input");
 if(ev.key==="Escape"){if(typing){ev.target.blur();}else{select("");}return;}
 if(typing||ev.ctrlKey||ev.metaKey||ev.altKey)return;
 if(ev.key==="/"){ev.preventDefault();q("#search").focus();}
 else if(ev.key==="g"){show("graph");}
 else if(ev.key==="t"){show("tree");}
});
if(!calm){qa("[data-n]").forEach(el=>{
 const n=+el.dataset.n, t0=performance.now();
 const step=t=>{const p=Math.min(1,(t-t0)/900);
  el.textContent=String(Math.round(n*(1-Math.pow(1-p,3))));
  if(p<1)requestAnimationFrame(step);};
 requestAnimationFrame(step);
});}
show(location.hash==="#graph"?"graph":"tree");
</script></body></html>
""")


def main(arguments: list[str]) -> int:
    root = ROOT
    if "--root" in arguments:
        root = Path(arguments[arguments.index("--root") + 1]).resolve()
    graph, problems = build_graph(root)
    if "--html" in arguments:
        target = Path(arguments[arguments.index("--html") + 1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_html(graph), encoding="utf-8")
        print(f"wrote {target}")
    elif "--json" in arguments:
        print(render_json(graph))
    else:
        print(render_text(graph))
    for problem in problems:
        print(f"docstring: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
