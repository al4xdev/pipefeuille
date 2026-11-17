"""Hold the graph's `agent` nodes to the code, the captures, agent.yml and the profile.

One `agent` node per backend_harness/agents/<name>/ (with a workspace/). What it says comes
from what the model gets, the context capture the owner accepted (route, effort, AGENTS.md,
every tool's text), never from a second copy; agent.yml adds what the capture cannot say (the
description, the limits, the E1 effects and repeat of the agent's own tools). The port's
AGENTS table (backend_logic/<...>/_shared/<port>/harness/contracts.py) turns each work into a
`dispatches` edge from the runs that submit it and an `answers` edge to the runs that observe
it. The self-tests write a synthetic tree and break it one way at a time; each mutation names
the exact problems the graph must report. Template-decisions D10.
"""

from pathlib import Path

from architecture import ROOT, VALUES, build_graph, render_html, render_json, render_text
from harness_agents import (
    AGENTS_FOLDER,
    BASELINES,
    HARNESS_NAME,
    MODEL_ENTRY,
    PATCH_FILE,
    PROFILES,
    JsonObject,
    declared_shared,
    default_model,
    load_json,
    parse_agent_yml,
    parse_capture,
    profile_of,
)

HARNESS = ROOT / HARNESS_NAME


def write_tree(root: Path, files: dict[str, str]) -> None:
    for relative, source in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")


def test_every_agent_folder_is_a_node_held_to_its_capture() -> None:
    graph, problems = build_graph(ROOT)
    assert problems == []
    profile, _ = profile_of(HARNESS)
    assert profile is not None
    patch = (HARNESS / Path(*PROFILES) / profile / PATCH_FILE).read_text(encoding="utf-8")
    route = default_model(patch)
    assert route is not None
    folders = sorted(
        path.name for path in (HARNESS / AGENTS_FOLDER).iterdir() if (path / "workspace").is_dir()
    )
    ids = sorted(node_id for node_id, node in graph.nodes.items() if node.kind == "agent")
    nodes = [graph.nodes[node_id] for node_id in ids]
    assert [node.name for node in nodes] == folders and folders
    for node in nodes:
        facts = node.agent
        assert facts is not None
        capture_file = HARNESS / Path(*BASELINES) / f"{profile}.{node.name}.txt"
        capture, capture_problems = parse_capture(capture_file.read_text(encoding="utf-8"))
        assert capture_problems == []
        # The node's text is the capture's: no second copy to drift.
        assert [(t.name, t.description, t.parameters) for t in facts.tools] == [
            (t.name, t.description, t.parameters) for t in capture.tools
        ]
        assert facts.instructions == capture.instructions
        known, _ = declared_shared(HARNESS)
        declared = HARNESS / AGENTS_FOLDER / node.name / "agent.yml"
        doc, _ = parse_agent_yml(declared.read_text(encoding="utf-8"), VALUES, known)
        assert doc is not None
        expected = route if doc.model is None else (route[0], *doc.model)
        assert (facts.provider, facts.model, facts.effort) == expected
        assert (capture.provider, capture.model, capture.effort) == expected
        assert facts.description == doc.description == node.doc.summary
        assert facts.limits == doc.limits
        assert "model" in node.effects and node.repeat == "accumulates"


def test_every_work_of_the_table_dispatches_and_is_answered() -> None:
    graph, _ = build_graph(ROOT)
    for node in graph.nodes.values():
        if node.kind != "agent" or node.agent is None:
            continue
        dispatches = [e for e in graph.edges if e.kind == "dispatches" and e.target == node.id]
        answers = [e for e in graph.edges if e.kind == "answers" and e.source == node.id]
        assert {work for e in dispatches for work in e.works} == set(node.agent.works)
        assert {work for e in answers for work in e.works} == set(node.agent.works)
        for edge in dispatches:
            # Handing a work over is a call to another process: the run says so.
            assert "network" in graph.nodes[edge.source].effects, edge.source


def test_the_views_show_every_agent_and_its_tools() -> None:
    graph, _ = build_graph(ROOT)
    agents = [node for node in graph.nodes.values() if node.kind == "agent"]
    text, page = render_text(graph), render_html(graph)
    document = load_json(render_json(graph))
    assert isinstance(document, JsonObject)
    nodes = document.get("nodes")
    assert isinstance(nodes, list)
    for agent in agents:
        assert agent.agent is not None
        assert f"  {agent.name}  [agent" in text
        assert f'data-id="{agent.id}"' in page and f'data-for="{agent.id}"' in page
        listed = [n for n in nodes if isinstance(n, JsonObject) and n.get("id") == agent.id]
        assert len(listed) == 1 and isinstance(listed[0].get("agent"), JsonObject)
        for tool in agent.agent.tools:
            assert f"tool {tool.name}  (" in text
            assert f"Tool <code>{tool.name}</code>" in page


# --- self-tests --------------------------------------------------------------------------

INSTRUCTIONS = "You answer.\n"


def capture(tools: list[tuple[str, str]], effort: str = "low") -> str:
    """A capture in context.mjs's toText shape: the profile `zz`, two messages, the tools."""
    reminder = (
        f"<system-reminder>\nInstructions from: AGENTS.md\n\n{INSTRUCTIONS}</system-reminder>"
    )
    messages = [("user/user", "ping"), ("user/agent-instructions", reminder)]
    lines = [
        "profile zz_a  route prov/m-1  preset -",
        f'options {{"reasoningEffort":"{effort}"}}',
        "",
        f"== messages ({len(messages)})",
    ]
    for index, (role, body) in enumerate(messages, start=1):
        lines += [f"-- #{index} {role} ({len(body)} chars)", body, ""]
    lines.append(f"== tools ({len(tools)})")
    for name, description in tools:
        lines += [f"-- {name}", description, '{"type":"object"}', ""]
    return "\n".join(lines)


AGENT_YML = (
    "description: Answers.\n"
    "limits:\n  max_run_seconds: 60\n  max_tokens: null\n  max_attempts: 2\n"
    "tools:\n  shared: [look]\n  own:\n    finish:\n"
    "      effects: {writes: the answer}\n      repeat: {fails: once only}\n"
)
PATCH = "- id: agent-default-model\n  config:\n    provider: prov\n    model: m-1\n"
DOC = (
    '    """{summary}.\n\n'
    "    Effects:\n        {effect}\n"
    "    Repeat:\n        {repeat}\n"
    "    Loops:\n        none\n"
    "    Concurrency:\n        free\n"
    '    """\n'
)
TABLE = "backend_logic/_shared/port/harness/contracts.py"
SYNTHETIC = {
    "backend_logic/contracts.py": "type BackendRequest = Ask | Read\n",
    "backend_logic/run.py": (
        "lazy from .ask import run as asking\n"
        "lazy from .read import run as reading\n\n\n"
        "async def run(initial, *, agents):\n"
        '    """Root."""\n'
        "    match initial:\n"
        "        case Ask():\n"
        "            await asking.run(initial, agents=agents)\n"
        "        case Read():\n"
        "            await reading.run(initial, agents=agents)\n"
    ),
    "backend_logic/ask/contracts.py": "class Ask: ...\n",
    "backend_logic/ask/run.py": (
        "async def run(initial, *, agents):\n"
        + DOC.format(summary="Hand a work over", effect="network", repeat="accumulates")
        + '    await agents.submit(initial, work="w")\n'
    ),
    "backend_logic/read/contracts.py": "class Read: ...\n",
    "backend_logic/read/run.py": (
        "async def run(initial, *, agents):\n"
        + DOC.format(summary="Read its answer", effect="network", repeat="safe")
        + '    await agents.observe(initial, work="w")\n'
    ),
    "backend_logic/_shared/port/contracts.py": "class Port: ...\n",
    TABLE: 'AGENTS = {"w": "a"}\n',
    "backend_harness/runtime/profiles/zz/cordis.patch.yml": PATCH + "    reasoningEffort: low\n",
    "backend_harness/agents/_shared/plugins/dsh-plugin-zz-fs/package.json": (
        '{"name": "dsh-plugin-zz-fs", "harness": {"tools": ["look"]}}\n'
    ),
    "backend_harness/agents/_shared/plugins/dsh-plugin-zz-fs/index.js": "    name: 'look',\n",
    "backend_harness/agents/a/agent.yml": AGENT_YML,
    "backend_harness/agents/a/workspace/AGENTS.md": INSTRUCTIONS,
    "backend_harness/agents/a/plugins/dsh-plugin-zz-a/package.json": (
        '{"name": "dsh-plugin-zz-a", "harness": {"ends_run": ["finish"]}}\n'
    ),
    "backend_harness/agents/a/plugins/dsh-plugin-zz-a/index.js": "    name: 'finish',\n",
    "backend_harness/tests/baseline/zz.a.txt": capture(
        [("finish", "End the run."), ("look", "Look at a file.")]
    ),
}
AGENT = "backend_harness/agents/a"
STALE = "the capture is stale"


def problems_of(tmp_path: Path, changes: dict[str, str | None]) -> list[str]:
    """The graph's problems with the synthetic tree, changed (None deletes a file)."""
    write_tree(tmp_path, {k: v for k, v in (SYNTHETIC | changes).items() if v is not None})
    _, problems = build_graph(tmp_path)
    return problems


def test_the_synthetic_tree_is_clean_and_reads_whole(tmp_path: Path) -> None:
    write_tree(tmp_path, SYNTHETIC)
    graph, problems = build_graph(tmp_path)
    assert problems == []
    node = graph.nodes["backend_harness.agents.a"]
    facts = node.agent
    assert facts is not None
    # The profile is the one folder of runtime/profiles: the prefix is read, never written.
    assert facts.capture == "backend_harness/tests/baseline/zz.a.txt"
    assert (facts.provider, facts.model, facts.effort) == ("prov", "m-1", "low")
    assert [(t.name, t.plugin, t.shared) for t in facts.tools] == [
        ("finish", "dsh-plugin-zz-a", False),
        ("look", "dsh-plugin-zz-fs", True),
    ]
    finish = facts.tools[0].doc
    assert finish is not None and finish.ends_run
    assert [(n.value, n.note) for n in finish.effects] == [("writes", "the answer")]
    assert (finish.repeat.value, finish.repeat.note) == ("fails", "once only")
    assert facts.instructions == INSTRUCTIONS.strip() and facts.works == ("w",)
    assert node.effects == ("model", "writes") and node.repeat == "accumulates"
    agent_edges = [
        (edge.source, edge.target, edge.kind, edge.works)
        for edge in graph.edges
        if edge.kind in ("dispatches", "answers")
    ]
    assert agent_edges == [
        ("backend_logic.ask", "backend_harness.agents.a", "dispatches", ("w",)),
        ("backend_harness.agents.a", "backend_logic.read", "answers", ("w",)),
    ]
    assert facts.input == "the submission of ask (work w), as one JSON message"
    assert facts.output == (
        "what finish accepts (its stdout); a successful call ends the run, read by read"
    )


def test_the_table_must_name_an_agent_that_exists(tmp_path: Path) -> None:
    assert problems_of(tmp_path, {TABLE: 'AGENTS = {"w": "b"}\n'}) == [
        f"{TABLE}: work 'w' goes to agent 'b', but backend_harness/agents/b/workspace does "
        "not exist"
    ]


def test_one_table_and_a_literal_one(tmp_path: Path) -> None:
    assert problems_of(tmp_path, {TABLE: 'AGENTS = dict(w="a")\n'}) == [
        f"{TABLE}: AGENTS is not a dict literal",
        "backend_logic/ask/run.py: names work 'w', which AGENTS sends to no agent",
        "backend_logic/read/run.py: names work 'w', which AGENTS sends to no agent",
    ]
    second = "backend_logic/ask/harness/contracts.py"
    assert problems_of(tmp_path / "two", {second: 'AGENTS = {"w": "a"}\n'}) == [
        "backend_logic: one `harness/contracts.py` (the agent-runs port's adapter) holds the "
        f"AGENTS table; found ['{TABLE}', '{second}']",
        "backend_logic/ask/run.py: names work 'w', which AGENTS sends to no agent",
        "backend_logic/read/run.py: names work 'w', which AGENTS sends to no agent",
    ]


def test_every_work_is_submitted_and_observed(tmp_path: Path) -> None:
    read = SYNTHETIC["backend_logic/read/run.py"].replace('work="w"', 'work="v"')
    assert problems_of(tmp_path, {"backend_logic/read/run.py": read}) == [
        "backend_logic/read/run.py: names work 'v', which AGENTS sends to no agent",
        f"{TABLE}: work 'w' is submitted, but no run observes it: its answer would never be read",
    ]
    ask = SYNTHETIC["backend_logic/ask/run.py"].replace('work="w"', 'work="v"')
    assert problems_of(tmp_path / "ask", {"backend_logic/ask/run.py": ask}) == [
        "backend_logic/ask/run.py: names work 'v', which AGENTS sends to no agent",
        f"{TABLE}: no run submits work 'w'",
    ]


def test_an_agent_needs_its_accepted_capture(tmp_path: Path) -> None:
    assert problems_of(tmp_path, {"backend_harness/tests/baseline/zz.a.txt": None}) == [
        f"{AGENT}: no context capture tests/baseline/zz.a.txt: capture the agent with "
        "tests/context.sh and have the owner accept its baseline"
    ]


def test_a_capture_behind_the_profile_agent_yml_or_agents_md_is_stale(tmp_path: Path) -> None:
    patch = PATCH + "    reasoningEffort: high\n"
    assert problems_of(
        tmp_path, {"backend_harness/runtime/profiles/zz/cordis.patch.yml": patch}
    ) == [
        f"{AGENT}: zz.a.txt: the model gets prov/m-1 at effort 'low', but {MODEL_ENTRY} says "
        f"prov/m-1 at 'high': {STALE}"
    ]
    model = AGENT_YML + "model:\n  name: m-2\n  reasoning: low\n"
    assert problems_of(tmp_path / "model", {f"{AGENT}/agent.yml": model}) == [
        f"{AGENT}: zz.a.txt: the model gets prov/m-1 at effort 'low', but agent.yml's model "
        f"says prov/m-2 at 'low': {STALE}"
    ]
    assert problems_of(tmp_path / "md", {f"{AGENT}/workspace/AGENTS.md": "You ask.\n"}) == [
        f"{AGENT}: workspace/AGENTS.md is not what zz.a.txt says the model gets: {STALE}"
    ]


def test_tools_own_describes_exactly_the_own_tools_the_model_gets(tmp_path: Path) -> None:
    bare = AGENT_YML.split("  own:\n")[0]
    assert problems_of(tmp_path, {f"{AGENT}/agent.yml": bare}) == [
        f"{AGENT}: zz.a.txt: the model gets 'finish', which agent.yml's tools.own does not "
        "describe (its effects and repeat)",
        f"{AGENT}: an own plugin's harness.ends_run names 'finish', which tools.own does not",
    ]
    extra = AGENT_YML + "    extra:\n      effects: {pure: p}\n      repeat: {safe: s}\n"
    assert problems_of(tmp_path / "extra", {f"{AGENT}/agent.yml": extra}) == [
        f"{AGENT}: agent.yml: tools.own describes 'extra', which the model does not get "
        "(zz.a.txt): a typo, or the capture is stale"
    ]
    vocabulary = AGENT_YML.replace("{writes: the answer}", "{mostly: the answer}")
    assert problems_of(tmp_path / "e1", {f"{AGENT}/agent.yml": vocabulary}) == [
        f"{AGENT}: agent.yml: tools.own.finish.effects: 'mostly' is not one of "
        "['pure', 'reads', 'writes', 'network', 'model', 'time']"
    ]


def test_every_captured_tool_has_a_plugin_and_every_pick_is_captured(tmp_path: Path) -> None:
    ghost = capture([("finish", "End the run."), ("look", "Look."), ("ghost", "Boo.")])
    assert problems_of(tmp_path, {"backend_harness/tests/baseline/zz.a.txt": ghost}) == [
        f"{AGENT}: zz.a.txt: the model gets 'ghost', which agent.yml's tools.own does not "
        "describe (its effects and repeat)",
        f"{AGENT}: zz.a.txt: the model gets tool 'ghost', which no plugin of the agent registers",
    ]
    shelf = "backend_harness/agents/_shared/plugins/dsh-plugin-zz-dig"
    assert problems_of(
        tmp_path / "dig",
        {
            f"{shelf}/package.json": '{"name": "dsh-plugin-zz-dig", "harness": {"tools": ["dig"]}}',
            f"{shelf}/index.js": "    name: 'dig',\n",
            f"{AGENT}/agent.yml": AGENT_YML.replace("[look]", "[look, dig]"),
        },
    ) == [
        f"{AGENT}: agent.yml: tools.shared lists 'dig', but the model does not get it "
        f"(zz.a.txt): {STALE}"
    ]


def test_an_own_plugin_is_inserted_whole(tmp_path: Path) -> None:
    manifest = (
        '{"name": "dsh-plugin-zz-a", "harness": {"tools": ["finish"], "ends_run": ["finish"]}}'
    )
    package = f"{AGENT}/plugins/dsh-plugin-zz-a/package.json"
    assert problems_of(tmp_path, {package: manifest}) == [
        f"{AGENT}: plugins/dsh-plugin-zz-a/package.json: harness.tools is for shared plugins; "
        "an own plugin is inserted whole"
    ]


def test_the_profile_is_the_one_folder_of_runtime_profiles(tmp_path: Path) -> None:
    other = "backend_harness/runtime/profiles/yy/cordis.patch.yml"
    assert problems_of(tmp_path, {other: PATCH}) == [
        "backend_harness/runtime/profiles: one profile folder with cordis.patch.yml is expected "
        "(the harness prefix), found ['yy', 'zz']"
    ]
