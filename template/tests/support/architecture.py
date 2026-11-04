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
cookiebook (RUNBOOK, task C).
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
type Mark = Literal["loop", "parallel", "lock"]


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
    # Where the first call is written: run.py before pipeline.py, then by line. The order a
    # reader meets the calls, which in a chain is the order they run.
    order: tuple[int, int] = (9, 0)


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: list[Edge]

    def calls_from(self, source: str) -> list[Edge]:
        found = [edge for edge in self.edges if edge.source == source and edge.kind == "calls"]
        return sorted(found, key=edge_order)

    @property
    def alerts(self) -> list[str]:
        return [edge.alert for edge in self.edges if edge.alert]


def edge_order(edge: Edge) -> tuple[int, int, str]:
    return (*edge.order, edge.target)


FILE_ORDER = {"run.py": 0, "pipeline.py": 1}


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
    adapter = root / ADAPTER_NAME
    if adapter.is_dir():
        add_adapter(adapter, nodes, edges)
    graph = Graph(nodes, edges)
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
            aliases: dict[str, str] = {}
            for statement in ast.walk(tree):
                if not isinstance(statement, ast.ImportFrom):
                    continue
                module = resolve(statement.module, statement.level, source)
                target = owning_node(module, nodes)
                if target is None or target == source:
                    continue
                for name in statement.names:
                    if name.name == "run" and module == target:
                        aliases[name.asname or name.name] = target
                        edges.setdefault((source, target, "calls"), Edge(source, target, "calls"))
                    elif SHARED in target.split(".") and not source.startswith(f"{target}."):
                        edges.setdefault((source, target, "types"), Edge(source, target, "types"))
            for node, ancestors in walk(tree):
                if not is_child_run_call(node):
                    continue
                assert isinstance(node, ast.Call)
                assert isinstance(node.func, ast.Attribute)
                assert isinstance(node.func.value, ast.Name)
                target = aliases.get(node.func.value.id)
                if target is None:
                    continue
                edge = edges[(source, target, "calls")]
                edge.marks = tuple(sorted({*edge.marks, *call_marks(node, ancestors)}))
                edge.order = min(edge.order, (FILE_ORDER.get(path.name, 2), node.lineno))
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


def call_marks(node: ast.AST, ancestors: tuple[ast.AST, ...]) -> set[Mark]:
    marks: set[Mark] = set()
    if ancestors and isinstance(ancestors[-1], ast.withitem) and ancestors[-1].context_expr is node:
        marks.add("lock")
    for ancestor in ancestors:
        if isinstance(ancestor, LOOP_NODES):
            marks.add("loop")
        if isinstance(ancestor, ast.AsyncWith) and any(
            "TaskGroup" in ast.unparse(item.context_expr) for item in ancestor.items
        ):
            marks.add("parallel")
        if (
            isinstance(ancestor, ast.Call)
            and isinstance(ancestor.func, ast.Attribute)
            and ancestor.func.attr in ("create_task", "gather")
        ):
            marks.add("parallel")
    return marks


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
        if "loop" in edge.marks and target.repeat not in ("", Repeat.SAFE.value):
            edge.alert = (
                f"{edge.source} calls {edge.target} inside a loop, and {edge.target} "
                f"repeats as {target.repeat!r}"
            )


# --- outputs ------------------------------------------------------------------------------


def children(graph: Graph, node_id: str) -> list[Node]:
    """Children by name, `_shared/` last: the use cases first, what they share after."""
    found = {node.name: node for node in graph.nodes.values() if node.parent == node_id}
    own = sorted(name for name in found if not name.startswith("_"))
    shared = sorted(name for name in found if name.startswith("_"))
    return [found[name] for name in [*own, *shared]]


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


def render_text(graph: Graph) -> str:
    """A compact tree for agents: one line per package, its calls beneath it."""
    lines: list[str] = []
    if ADAPTER_NAME in graph.nodes:
        lines.append(f"{ADAPTER_NAME}  [adapter]  {graph.nodes[ADAPTER_NAME].doc.summary}")
        lines.append(f"  → enters {LOGIC_NAME}")

    def visit(node: Node, depth: int) -> None:
        pad = "  " * depth
        label = node.id if depth == 0 else node.name
        summary = f"  {node.doc.summary}" if node.doc.summary else ""
        lines.append(f"{pad}{label}  [{node_tags(node)}]{summary}")
        for edge in graph.calls_from(node.id):
            marks = f" ({', '.join(edge.marks)})" if edge.marks else ""
            cases = f" for {', '.join(edge.cases)}" if edge.cases else ""
            lines.append(f"{pad}  → {edge.target}{marks}{cases}")
        for child in children(graph, node.id):
            visit(child, depth + 1)

    visit(graph.nodes[LOGIC_NAME], 0)
    if graph.alerts:
        lines.append("")
        lines.append("alerts:")
        lines.extend(f"  ! {alert}" for alert in graph.alerts)
    return "\n".join(lines)


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
    }
    return json.dumps(document, indent=2, ensure_ascii=False)


NODE_W, NODE_H, COLUMN, ROW, MARGIN = 250, 46, 330, 58, 40
EFFECT_COLOURS = {
    "model": "#8e5bd0",
    "network": "#1f9e9e",
    "writes": "#d9822b",
    "reads": "#3b7dd8",
    "time": "#8a8f3c",
    "pure": "#5f9e6e",
    "": "#9aa0a6",
}


def layout(graph: Graph) -> dict[str, tuple[float, float]]:
    """Left to right by depth; leaves one row apart, a parent centred on its children."""
    positions: dict[str, tuple[float, float]] = {}
    next_row = [0]

    def visit(node: Node, column: int) -> float:
        kids = children(graph, node.id)
        if not kids:
            row = float(next_row[0])
            next_row[0] += 1
        else:
            rows = [visit(kid, column + 1) for kid in kids]
            row = (rows[0] + rows[-1]) / 2
        positions[node.id] = (MARGIN + column * COLUMN, MARGIN + row * ROW)
        return row

    offset = 1 if ADAPTER_NAME in graph.nodes else 0
    visit(graph.nodes[LOGIC_NAME], offset)
    if offset:
        positions[ADAPTER_NAME] = (MARGIN, positions[LOGIC_NAME][1])
    return positions


def tooltip(node: Node) -> str:
    """The hover card, as escaped HTML."""
    parts = [f"<b>{html.escape(node.id)}</b> <i>{node.kind}</i>"]
    if node.doc.summary:
        parts.append(f"<p>{html.escape(node.doc.summary)}</p>")
    if node.doc.description:
        parts.append(f"<p class=d>{html.escape(node.doc.description)}</p>")
    if node.request or node.response:
        parts.append(
            f"<p><code>{html.escape(node.request)} → {html.escape(node.response)}</code></p>"
        )
    if node.ports:
        parts.append(f"<p>ports: <code>{html.escape(', '.join(node.ports))}</code></p>")
    if node.kind == "family" and node.effects:
        parts.append(
            f"<p>from its cases: {html.escape(', '.join(node.effects))} · "
            f"repeat {html.escape(node.repeat)}</p>"
        )
    for name, items in node.doc.sections.items():
        rows = "".join(
            f"<li><b>{html.escape(item.value)}</b>"
            + (f": {html.escape(item.note)}" if item.note else "")
            + "</li>"
            for item in items
        )
        parts.append(f"<div class=s>{name}</div><ul>{rows}</ul>")
    if node.skeleton:
        parts.append("<p class=k>skeleton: some bodies still raise NotImplementedError</p>")
    return "".join(parts)


def edge_path(start: tuple[float, float], end: tuple[float, float]) -> str:
    x1, y1 = start[0] + NODE_W, start[1] + NODE_H / 2
    x2, y2 = end[0], end[1] + NODE_H / 2
    if x2 <= x1:  # backwards or same column: arc around the right side
        x2 = end[0] + NODE_W
        bulge = max(x1, x2) + 60 + abs(y2 - y1) / 6
        return f"M{x1},{y1} C{bulge},{y1} {bulge},{y2} {x2},{y2}"
    middle = (x1 + x2) / 2
    return f"M{x1},{y1} C{middle},{y1} {middle},{y2} {x2},{y2}"


def render_html(graph: Graph) -> str:
    """A self-contained page: inline SVG, a little CSS and JS, no network."""
    positions = layout(graph)
    width = max(x for x, _ in positions.values()) + NODE_W + MARGIN + 160
    height = max(y for _, y in positions.values()) + NODE_H + MARGIN
    shapes: list[str] = []
    called = {(edge.source, edge.target) for edge in graph.edges}
    names = [node.name for node in graph.nodes.values()]
    for node in graph.nodes.values():
        parent = node.parent
        # Containment is drawn only where no call already joins parent and child.
        if (
            parent is not None
            and parent in positions
            and node.id in positions
            and (parent, node.id) not in called
        ):
            px, py = positions[parent]
            x, y = positions[node.id]
            shapes.append(
                f'<path class="tree" d="M{px + NODE_W},{py + NODE_H / 2} '
                f'H{px + NODE_W + 20} V{y + NODE_H / 2} H{x}"/>'
            )
    for index, edge in enumerate(graph.edges):
        if edge.source not in positions or edge.target not in positions:
            continue
        classes = ["edge", edge.kind, *edge.marks, *(["alert"] if edge.alert else [])]
        path = edge_path(positions[edge.source], positions[edge.target])
        label = " ".join(edge.marks)
        title = html.escape(
            edge.alert
            or f"{edge.source} {edge.kind} {edge.target}"
            + (f" for {', '.join(edge.cases)}" if edge.cases else "")
        )
        shapes.append(
            f'<g class="{" ".join(classes)}" data-source="{edge.source}" '
            f'data-target="{edge.target}"><title>{title}</title>'
            f'<path id="e{index}" d="{path}" marker-end="url(#arrow)"/>'
            + (
                f'<text><textPath href="#e{index}" startOffset="50%">{label}</textPath></text>'
                if label
                else ""
            )
            + "</g>"
        )
    for node in graph.nodes.values():
        if node.id not in positions:
            continue
        x, y = positions[node.id]
        strongest = next((e for e in EFFECT_STRENGTH if e in node.effects), "")
        colour = EFFECT_COLOURS[strongest]
        node_classes = " ".join(["node", node.kind, *(["skeleton"] if node.skeleton else [])])
        sub = node_tags(node)
        # A repeated name (save/decode, json/decode) is told apart by its parent.
        label = node.name
        if names.count(node.name) > 1 and node.parent is not None:
            label = f"{node.parent.rsplit('.', 1)[-1]}/{node.name}"
        shapes.append(
            f'<g class="{node_classes}" data-id="{node.id}" tabindex="0" role="button" '
            f'aria-label="{html.escape(node.id)}" '
            f'data-tip="{html.escape(tooltip(node))}">'
            f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="8" '
            f'style="--c:{colour}"/>'
            f'<text class="n" x="{x + 10}" y="{y + 19}">{html.escape(label)}</text>'
            f'<text class="t" x="{x + 10}" y="{y + 36}">{html.escape(sub)}</text></g>'
        )
    legend = "".join(
        f'<span><i style="background:{colour}"></i>{effect or "none"}</span>'
        for effect, colour in EFFECT_COLOURS.items()
        if effect
    )
    alerts = "".join(f"<li>{html.escape(alert)}</li>" for alert in graph.alerts)
    return PAGE.format(
        width=width,
        height=height,
        shapes="\n".join(shapes),
        legend=legend,
        alerts=f"<ul class=alerts>{alerts}</ul>" if alerts else "",
    )


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Architecture</title>
<style>
body{{margin:0;font:13px/1.4 system-ui,sans-serif;background:#f7f7f5;color:#222}}
header{{padding:14px 20px;border-bottom:1px solid #ddd;background:#fff;position:sticky;top:0}}
header b{{font-size:15px}} header span{{margin-right:14px;white-space:nowrap}}
header i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px}}
.key{{color:#555;margin-top:6px}} .alerts{{color:#b3261e;margin:6px 0 0;padding-left:18px}}
svg{{display:block}}
.tree{{fill:none;stroke:#d5d5d0;stroke-width:1}}
.edge path{{fill:none;stroke:#5c6670;stroke-width:1.6;opacity:.75}}
.edge.types path{{stroke-dasharray:5 4;stroke:#9aa0a6}} .edge.types:not(.hot){{opacity:0}}
.edge.enters path{{stroke:#222;stroke-width:2.2}}
.edge.loop path{{stroke:#d9822b}} .edge.parallel path{{stroke:#1f9e9e}}
.edge.lock path{{stroke:#8e5bd0}} .edge.alert path{{stroke:#b3261e;stroke-width:2.4}}
.edge text{{font-size:10px;fill:#444;dominant-baseline:text-after-edge}}
.node rect{{fill:#fff;stroke:var(--c);stroke-width:2}}
.node.family rect{{stroke-width:3.5}} .node.adapter rect{{fill:#222}}
.node.adapter text{{fill:#fff}}
.node.shared rect,.node.grouping rect{{fill:#f0f0ec;stroke-dasharray:4 3;stroke:#9aa0a6}}
.node.skeleton rect{{stroke-dasharray:2 3}}
.node text.n{{font-weight:600}} .node text.t{{font-size:10.5px;fill:#666}}
.node{{cursor:default}} .dim{{opacity:.15}} .hot path{{opacity:1;stroke-width:3}}
#tip{{position:fixed;max-width:440px;background:#fff;border:1px solid #ccc;border-radius:8px;
 box-shadow:0 6px 24px #0002;padding:10px 12px;pointer-events:none;display:none}}
#tip p{{margin:4px 0}} #tip .d{{color:#555}} #tip .s{{margin-top:6px;font-weight:600;color:#444}}
#tip ul{{margin:2px 0;padding-left:18px}} #tip .k{{color:#b3261e}}
</style></head><body>
<header><b>Architecture</b> · generated from the code by tests/support/architecture.py
<div class="key">node border: strongest effect {legend}</div>
<div class="key">edges: <span>solid call</span><span>dashed: shared types, shown on hover</span>
<span style="color:#d9822b">loop</span><span style="color:#1f9e9e">parallel</span>
<span style="color:#8e5bd0">lock</span><span style="color:#b3261e">loop into a package not safe
to repeat</span> · thick border: family · dashed box: _shared/ or grouping · hover a node</div>
{alerts}</header>
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7"
orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="#5c6670"/></marker></defs>
{shapes}
</svg><div id="tip"></div>
<script>
const tip=document.getElementById("tip");
const edges=[...document.querySelectorAll(".edge")];
function place(x,y){{tip.style.left=Math.max(8,Math.min(x+16,innerWidth-460))+"px";
 tip.style.top=Math.max(8,Math.min(y+16,innerHeight-tip.offsetHeight-8))+"px";}}
function show(n){{tip.innerHTML=n.dataset.tip;tip.style.display="block";const id=n.dataset.id;
 edges.forEach(e=>{{const on=e.dataset.source===id||e.dataset.target===id;
  e.classList.toggle("hot",on);e.classList.toggle("dim",!on);}});}}
function hide(){{tip.style.display="none";edges.forEach(e=>e.classList.remove("hot","dim"));}}
document.querySelectorAll(".node").forEach(n=>{{
 n.addEventListener("mouseenter",ev=>{{show(n);place(ev.clientX,ev.clientY);}});
 n.addEventListener("mousemove",ev=>place(ev.clientX,ev.clientY));
 n.addEventListener("mouseleave",hide);
 n.addEventListener("focus",()=>{{show(n);const r=n.getBoundingClientRect();
  place(r.left,r.bottom);}});
 n.addEventListener("blur",hide);
}});
</script></body></html>
"""


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
