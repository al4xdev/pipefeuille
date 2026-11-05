"""Hold every `def run` docstring to the closed vocabulary, and the graph to the code.

The enums live in tests/support/architecture.py; this file pins their values, so a project
that adds or renames one fails here (template-decisions E1). A value that a real package
needs is a proposal to the cookiebook's owner, never an edit of either file.
"""

from pathlib import Path

from architecture import (
    ROOT,
    Concurrency,
    Effect,
    Loops,
    Repeat,
    build_graph,
    parse_docstring,
    render_html,
    render_text,
    step_lines,
)


def write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_the_closed_vocabulary_is_the_template_one() -> None:
    assert [member.value for member in Effect] == [
        "pure",
        "reads",
        "writes",
        "network",
        "model",
        "time",
    ]
    assert [member.value for member in Repeat] == ["safe", "overwrites", "fails", "accumulates"]
    assert [member.value for member in Loops] == ["none", "over-items", "capped"]
    assert [member.value for member in Concurrency] == ["free", "locks-inside", "caller-locks"]


def test_every_run_docstring_uses_only_the_closed_vocabulary() -> None:
    _, problems = build_graph(ROOT)
    assert not problems, "\n".join(problems)


def test_every_package_is_reached_from_the_root() -> None:
    # A package nobody calls is dead code or a call the graph cannot see (an alias that does
    # not end in `.run(...)`); either way the diagram would lie by omission.
    graph, _ = build_graph(ROOT)
    called = {edge.target for edge in graph.edges if edge.kind in ("calls", "enters")}
    orphans = [
        node.path
        for node in graph.nodes.values()
        if node.kind in ("family", "process") and node.id not in called
    ]
    assert not orphans


def test_every_call_is_made_by_a_step_of_run() -> None:
    # The steps are how a reader follows a run; a call they cannot place (an imported run used
    # by no method that run reaches) would be missing from the story.
    graph, _ = build_graph(ROOT)
    assert not graph.hidden, "\n".join(graph.hidden)


def test_the_page_shows_every_node_and_edge() -> None:
    graph, _ = build_graph(ROOT)
    page = render_html(graph)
    for node in graph.nodes.values():
        assert f'data-id="{node.id}"' in page, node.id
        assert f'data-for="{node.id}"' in page, node.id
    for edge in graph.edges:
        assert f'data-source="{edge.source}" data-target="{edge.target}"' in page, edge
    assert "http://" not in page and "https://" not in page  # self-contained, no network
    assert "$" not in page.split("<script>")[0]  # every template slot was filled
    assert render_text(graph)


def test_docstring_parser_keeps_notes_and_continuations() -> None:
    doc, problems = parse_docstring(
        "Summary.\n\nMore text.\n\nRepeat:\n    fails: first line\n        second line\n"
    )
    assert problems == []
    assert (doc.summary, doc.description) == ("Summary.", "More text.")
    assert [(item.value, item.note) for item in doc.sections["Repeat"]] == [
        ("fails", "first line second line")
    ]


SYNTHETIC = {
    "backend_logic/contracts.py": "type BackendRequest = A | B\n",
    "backend_logic/run.py": (
        "lazy from .a import run as doing\n"
        "lazy from .b import run as asking\n\n\n"
        "async def run(initial, *, model):\n"
        '    """Root.\n\n    Effects:\n        pure\n    """\n'
        "    match initial:\n"
        "        case A():\n"
        "            doing.run(initial)\n"
        "        case B():\n"
        "            for item in initial:\n"
        "                await asking.run(item, model=model)\n"
    ),
    "backend_logic/a/contracts.py": "class A: ...\n\n\nclass AError(ValueError): ...\n",
    "backend_logic/a/run.py": (
        "def run(initial, *, clock):\n"
        '    """Do a.\n\n'
        "    Effects:\n        pure\n"
        "    Repeat:\n        maybe\n"
        "    Loops:\n        none\n"
        "    Concurrency:\n        free\n"
        "    Notes:\n        anything\n"
        "    Raises:\n        MadeUpError: invented.\n"
        '    """\n'
        "    while True:\n        break\n"
    ),
    "backend_logic/b/contracts.py": "class B: ...\n",
    "backend_logic/b/run.py": (
        "async def run(initial, *, model):\n"
        '    """Do b.\n\n'
        "    Effects:\n        model\n"
        "    Repeat:\n        accumulates\n"
        "    Loops:\n        none\n"
        "    Concurrency:\n        free\n"
        '    """\n'
    ),
    "backend_logic/c/contracts.py": "class C: ...\n",
    "backend_logic/c/run.py": (
        "lazy from backend_logic.b import run as locking\n\n\n"
        "async def run(initial):\n"
        '    """Do c.\n\n'
        "    Effects:\n        reads\n        reads\n"
        "    Repeat:\n        safe\n"
        "    Concurrency:\n        caller-locks\n"
        "    Loops:\n        capped\n"
        '    """\n'
        "    async with locking.run(initial):\n        pass\n"
    ),
}


def test_graph_scanner_reports_every_violation(tmp_path: Path) -> None:
    write_tree(tmp_path, SYNTHETIC)
    graph, problems = build_graph(tmp_path)
    assert problems == [
        "backend_logic/run.py: a family declares only its summary; remove ['Effects'] "
        "(its effects come from its cases)",
        "backend_logic/a/run.py: unknown section 'Notes'; sections are "
        "['Effects', 'Repeat', 'Loops', 'Concurrency', 'Raises']",
        "backend_logic/a/run.py: Repeat: 'maybe' is not one of "
        "['safe', 'overwrites', 'fails', 'accumulates']",
        "backend_logic/a/run.py: Effects: 'pure' but run takes ports ['clock']",
        "backend_logic/a/run.py: Repeat: a 'pure' package is 'safe'",
        "backend_logic/a/run.py: Loops: 'none' but run has ['while']",
        "backend_logic/c/run.py: section 'Loops' out of order; the order is "
        "['Effects', 'Repeat', 'Loops', 'Concurrency', 'Raises']",
        # The out-of-order section is not read, so it also counts as missing.
        "backend_logic/c/run.py: missing section 'Loops'",
        "backend_logic/c/run.py: Effects: repeated value",
        "backend_logic/c/run.py: Concurrency: 'caller-locks' needs a note",
        "backend_logic/c/run.py: Concurrency: run takes a lock (async with <lock>.run); "
        "'locks-inside'",
        "backend_logic/a/run.py: Raises: 'MadeUpError' is neither a builtin exception nor "
        "defined in a contracts.py",
        "backend_logic/a/run.py: Raises: 'AError' is defined in its contracts.py and missing",
        "backend_logic/c/run.py: Effects: calls backend_logic.b (model) but does not declare it",
    ]
    edges = {(edge.source, edge.target): edge for edge in graph.edges}
    assert edges[("backend_logic", "backend_logic.a")].cases == ("A",)
    assert edges[("backend_logic", "backend_logic.b")].marks == ("per-item",)
    assert edges[("backend_logic.c", "backend_logic.b")].marks == ("lock",)
    # The family's effects are its cases' effects; its declared 'pure' is ignored.
    assert graph.nodes["backend_logic"].effects == ("model",)
    assert graph.alerts == [
        "backend_logic calls backend_logic.b once per item, and backend_logic.b repeats as "
        "'accumulates'"
    ]


STEPS = {
    "backend_logic/run.py": "def run(initial):\n    pass\n",
    **{f"backend_logic/{name}/run.py": "def run(initial):\n    pass\n" for name in "qrst"},
    "backend_logic/p/run.py": (
        "lazy import asyncio\n"
        "lazy from backend_logic.q import run as locking\n"
        "lazy from backend_logic.r import run as asking\n"
        "lazy from .pipeline import Pipe\n\n\n"
        "async def run(initial, *, store):\n"
        "    pipe = Pipe.get(initial).fetch(store=store)\n"
        "    if initial is None:\n"
        "        raise ValueError('a guard that only raises is not a step')\n"
        "    async with locking.run(initial):\n"
        "        if initial.flag:\n"
        "            pipe.keep()\n"
        "        else:\n"
        "            pipe.drop()\n"
        "        async with asyncio.TaskGroup() as group:\n"
        "            for item in initial.items:\n"
        "                group.create_task(asking.run(item))\n"
        "    return pipe.materialize()\n"
    ),
    "backend_logic/p/pipeline.py": (
        "lazy from backend_logic.s import run as reading\n"
        "lazy from backend_logic.t import run as writing\n\n\n"
        "def helper(value):\n"
        "    return reading.run(value)\n\n\n"
        "class Pipe:\n"
        "    @classmethod\n"
        "    def get(cls, initial):\n"
        "        return cls()\n\n"
        "    def fetch(self, *, store):\n"
        "        self.values = [helper(item) for item in store]\n"
        "        return self\n\n"
        "    def keep(self):\n"
        "        return self\n\n"
        "    def drop(self):\n"
        "        return self\n\n"
        "    def unused(self):\n"
        "        writing.run(1)\n\n"
        "    def materialize(self):\n"
        "        return self.values\n"
    ),
}


def test_step_reader_follows_run_in_order_inside_its_frames(tmp_path: Path) -> None:
    write_tree(tmp_path, STEPS)
    graph, _ = build_graph(tmp_path)
    assert step_lines(graph.nodes["backend_logic.p"].steps) == [
        "get",
        # A call inside a method's comprehension, through a local helper, is per item.
        "fetch(store) → s (per item)",
        "lock → q:",
        "  if initial.flag:",
        "    keep",
        "  else:",
        "    drop",
        "  in parallel (TaskGroup), then wait for all:",
        "    for item in initial.items:",
        "      asking.run → r",
        "materialize",
    ]
    calls = graph.calls_from("backend_logic.p")
    assert [(edge.target, edge.marks) for edge in calls] == [
        ("backend_logic.s", ("per-item",)),
        ("backend_logic.q", ("lock",)),
        ("backend_logic.r", ("parallel", "per-item")),
        ("backend_logic.t", ()),
    ]
    assert graph.hidden == [
        "backend_logic/p: imports the run of backend_logic.t, but no step of its run calls it"
    ]
