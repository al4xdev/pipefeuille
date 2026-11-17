"""Gate: every agent declares itself in agent.yml, strictly, with E1's vocabulary.

agent.yml sits beside an agent's workspace/, so the model never sees it. Three readers read it:

- the image build, app-agent and the context capture, through dsh-plugin-app-tools/agent.js
  (js-yaml's core schema): the shape, and which shared tools exist;
- the architecture graph, through harness_agents.py's stdlib reader: the shape, the shared
  tools, and the E1 values of tools.own;
- this gate, with PyYAML (a repeated key refused, scalars read as the core schema reads them):
  the same, independently.

    description: <one or two sentences>
    limits:                          time and tokens: dsh-plugin-app-limits; attempts: the queue
      max_run_seconds: <int> | null  null = no limit
      max_tokens: <int> | null
      max_attempts: <int>
    tools:                           optional
      shared: [read, sql, ...]       opt-in tools of agents/_shared/plugins (their harness.tools)
      own:                           every tool the agent's own plugins register, no other
        <tool>:
          effects: {<Effect>: <note>, ...}   `pure` only alone
          repeat: {<Repeat>: <note>}         exactly one, the worst case; pure implies safe
    model:                           optional; absent = the profile's agent-default-model
      name: <model id>
      reasoning: off | low | high | max

Every real agent.yml passes all three, to the same values. backend_harness/tests/
agent_yml_cases.json pins each reader's verdict on every good and bad case, and says why where
one differs by design; the Python readers are held to it here, agent.js in the image
(backend_harness/tests/test.sh). The E1 values come from architecture.py, never copied.
Template-decisions E3.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import override

import pytest
import yaml
from architecture import ROOT, VALUES
from harness_agents import (
    AGENT_FILE,
    AGENT_KEYS,
    AGENTS_FOLDER,
    BASELINES,
    HARNESS_NAME,
    LIMIT_KEYS,
    MANIFEST_KEY,
    MODEL_NAME,
    NEEDS_READ,
    REASONING,
    SENTENCE_END,
    SHARED_PLUGINS,
    TOOL_NAME,
    declared_shared,
    manifest_list,
    parse_agent_yml,
    parse_capture,
    profile_of,
    registered_tools,
)

HARNESS = ROOT / HARNESS_NAME
AGENTS = HARNESS / AGENTS_FOLDER
CASES = HARNESS / "tests" / "agent_yml_cases.json"
KNOWN, KNOWN_PROBLEMS = declared_shared(HARNESS)
# YAML 1.1 (PyYAML's) reads `off`, `yes`, `010` and `1_000` as booleans and numbers; the core
# schema of YAML 1.2 (js-yaml's, the image's) reads them as text. These scalars stay text here.
BOOL = "tag:yaml.org,2002:bool"
INT = "tag:yaml.org,2002:int"
CORE_BOOLS = ("true", "True", "TRUE", "false", "False", "FALSE")
DECIMAL = re.compile(r"0|[1-9][0-9]*")


class DuplicateKeyError(yaml.YAMLError):
    """A key repeated in one mapping: plain PyYAML would keep the last one silently."""


class CoreLoader(yaml.SafeLoader):
    """SafeLoader that refuses a repeated key at any depth and reads the values of a mapping
    with the core schema's booleans and plain decimal integers."""

    @override
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
        found: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in found:
                raise DuplicateKeyError(f"duplicate key {key!r}")
            found[key] = self.core(value_node)
        return found

    def core(self, node: yaml.Node) -> object:
        if isinstance(node, yaml.ScalarNode) and node.style is None:
            if node.tag == BOOL and node.value not in CORE_BOOLS:
                return node.value
            if node.tag == INT and not DECIMAL.fullmatch(node.value):
                return node.value
        return self.construct_object(node, deep=True)


def load(text: str) -> object:
    """One agent.yml; a repeated key raises DuplicateKeyError."""
    loader = CoreLoader(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def text_keys(value: object) -> dict[str, object] | None:
    """A mapping with text keys, or None."""
    if not isinstance(value, dict):
        return None
    found: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        found[key] = item
    return found


def unknown(mapping: dict[str, object], allowed: tuple[str, ...], where: str) -> list[str]:
    return [f"{where}: unknown key {key!r}" for key in mapping if key not in allowed]


def notes(where: str, value: object, allowed: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """`{<value>: <note>}`: the values, and the problems."""
    mapping = text_keys(value)
    if not mapping:
        return [], [f"{where}: a mapping of value to note, not {value!r}"]
    found: list[str] = []
    for key, note in mapping.items():
        if key not in allowed:
            found.append(f"{where}: {key!r} is not one of {list(allowed)}")
        if not isinstance(note, str) or not note.strip():
            found.append(f"{where}.{key}: the note is a non-empty text")
    return list(mapping), found


def own_problems(value: object) -> list[str]:
    own = text_keys(value)
    if not own:
        return ["tools.own: a mapping of tool name to its effects and repeat"]
    found: list[str] = []
    for tool, raw in own.items():
        where = f"tools.own.{tool}"
        if not TOOL_NAME.fullmatch(tool):
            found.append(f"{where}: a tool name is {TOOL_NAME.pattern}")
        entry = text_keys(raw)
        if entry is None:
            found.append(f"{where}: a mapping with effects and repeat")
            continue
        found += unknown(entry, ("effects", "repeat"), where)
        effects, problems = notes(f"{where}.effects", entry.get("effects"), VALUES["Effects"])
        found += problems
        repeat, problems = notes(f"{where}.repeat", entry.get("repeat"), VALUES["Repeat"])
        found += problems
        if "pure" in effects and len(effects) > 1:
            found.append(f"{where}.effects: pure only alone")
        if len(repeat) > 1:
            found.append(f"{where}.repeat: exactly one value")
        if effects == ["pure"] and repeat != ["safe"]:
            found.append(f"{where}: pure implies repeat: safe")
    return found


def shared_problems(value: object) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
        return ["tools.shared: a non-empty list of tool names"]
    names = [name for name in value if isinstance(name, str)]
    if len(set(names)) != len(names):
        return ["tools.shared: a tool listed twice"]
    found = [f"tools.shared: unknown tool {name!r}" for name in names if name not in KNOWN]
    found += [
        f"tools.shared: {name} needs read"
        for name in NEEDS_READ
        if name in names and "read" not in names
    ]
    return found


def limit_problems(value: object) -> list[str]:
    limits = text_keys(value)
    if limits is None:
        return ["limits: required"]
    found = unknown(limits, tuple(LIMIT_KEYS), "limits")
    for key, nullable in LIMIT_KEYS.items():
        limit = limits.get(key, "missing")
        if limit is None and nullable:
            continue
        # bool is an int to Python: `max_attempts: true` must not pass as 1.
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            found.append(f"limits.{key}: a positive integer{', or null' if nullable else ''}")
    return found


def model_problems(value: object) -> list[str]:
    model = text_keys(value)
    if model is None:
        return ["model: a mapping with name and reasoning"]
    found = unknown(model, ("name", "reasoning"), "model")
    name = model.get("name")
    if not isinstance(name, str) or not MODEL_NAME.fullmatch(name):
        found.append(f"model.name: a model id, {MODEL_NAME.pattern}")
    if model.get("reasoning") not in REASONING:
        found.append(f"model.reasoning: one of {', '.join(REASONING)}")
    return found


def problems(value: object) -> list[str]:
    """What is wrong with one parsed agent.yml (empty when it passes)."""
    doc = text_keys(value)
    if doc is None:
        return ["not a mapping"]
    found = unknown(doc, AGENT_KEYS, AGENT_FILE)
    description = doc.get("description")
    text = description.strip() if isinstance(description, str) else ""
    sentences = sum(1 for _ in SENTENCE_END.finditer(text))
    if not text or not 1 <= sentences <= 2 or not SENTENCE_END.search(text[-1]):
        found.append("description: one or two sentences, required")
    found += limit_problems(doc.get("limits"))
    if "model" in doc:
        found += model_problems(doc["model"])
    if "tools" not in doc:
        return found
    tools = text_keys(doc["tools"])
    if not tools:
        return [*found, "tools: a mapping with shared and/or own"]
    found += unknown(tools, ("shared", "own"), "tools")
    if "shared" in tools:
        found += shared_problems(tools["shared"])
    if "own" in tools:
        found += own_problems(tools["own"])
    return found


def verdict(text: str) -> list[str]:
    """This gate's problems with a text: a repeated key is one problem, like any other."""
    try:
        return problems(load(text))
    except DuplicateKeyError as error:
        return [str(error)]


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    problems: tuple[str, ...]
    subset: str  # "accepts" or "refuses": the stdlib reader's verdict
    agent_js: str  # the image's reader's, checked by tools.test.mjs
    why: str


def read_cases() -> list[Case]:
    if not HARNESS.is_dir():
        return []  # a project without the runtime layer has no agent.yml to read
    document: object = json.loads(CASES.read_text(encoding="utf-8"))
    root = text_keys(document)
    raw = root.get("cases") if root is not None else None
    assert isinstance(raw, list), f"{CASES}: no list of cases"
    cases: list[Case] = []
    for item in raw:
        entry = text_keys(item)
        assert entry is not None, item
        ident, text, fragments = entry.get("id"), entry.get("text"), entry.get("problems")
        why = entry.get("why", "")
        assert isinstance(ident, str) and isinstance(text, str) and isinstance(why, str), entry
        assert isinstance(fragments, list) and all(isinstance(f, str) for f in fragments), entry
        default = "refuses" if fragments else "accepts"
        subset, agent_js = entry.get("subset", default), entry.get("agent_js", default)
        if not (isinstance(subset, str) and isinstance(agent_js, str)):
            raise AssertionError(entry)
        assert {subset, agent_js} <= {"accepts", "refuses"}, entry
        assert set(entry) <= {"id", "text", "problems", "subset", "agent_js", "why"}, entry
        # An exception to "every reader agrees" says why; an agreement needs no reason.
        assert bool(why) == (subset != default or agent_js != default), entry
        cases.append(
            Case(
                ident,
                text,
                tuple(f for f in fragments if isinstance(f, str)),
                subset,
                agent_js,
                why,
            )
        )
    return cases


CASE_LIST = read_cases()


def agents() -> list[Path]:
    if not AGENTS.is_dir():
        return []
    return sorted(path for path in AGENTS.iterdir() if (path / "workspace").is_dir())


AGENT_DIRS = agents()


def captured(agent: Path) -> set[str]:
    profile, profile_problems = profile_of(HARNESS)
    assert profile is not None, profile_problems
    capture_file = HARNESS / Path(*BASELINES) / f"{profile}.{agent.name}.txt"
    capture, capture_problems = parse_capture(capture_file.read_text(encoding="utf-8"))
    assert capture_problems == [], capture_problems
    return {tool.name for tool in capture.tools}


def test_there_is_something_to_check() -> None:
    assert KNOWN_PROBLEMS == []
    if HARNESS.is_dir():
        # The runtime layer ships with at least one agent, and every reader's cases.
        assert AGENT_DIRS and CASE_LIST and KNOWN


@pytest.mark.parametrize("agent", AGENT_DIRS, ids=[path.name for path in AGENT_DIRS])
def test_agent_yml(agent: Path) -> None:
    declared = agent / AGENT_FILE
    assert declared.is_file(), f"{agent} has no {AGENT_FILE}"
    text = declared.read_text(encoding="utf-8")
    doc = text_keys(load(text))
    assert doc is not None and problems(doc) == []
    # The graph's own reader (stdlib only) reads the same file to the same values.
    parsed, reader_problems = parse_agent_yml(text, VALUES, KNOWN)
    assert reader_problems == [] and parsed is not None
    limits, tools = text_keys(doc["limits"]), text_keys(doc.get("tools", {}))
    assert limits is not None and tools is not None
    assert parsed.description == str(doc["description"]).strip()
    assert (
        parsed.limits.max_run_seconds,
        parsed.limits.max_tokens,
        parsed.limits.max_attempts,
    ) == (limits["max_run_seconds"], limits["max_tokens"], limits["max_attempts"])
    model = text_keys(doc["model"]) if "model" in doc else None
    assert parsed.model == (None if model is None else (model["name"], model["reasoning"]))
    assert list(parsed.shared) == tools.get("shared", [])
    own = text_keys(tools.get("own", {}))
    assert own is not None
    expected: dict[str, tuple[list[tuple[str, str]], tuple[str, str]]] = {}
    for tool, raw in own.items():
        entry = text_keys(raw)
        effects = text_keys(entry["effects"]) if entry is not None else None
        repeat = text_keys(entry["repeat"]) if entry is not None else None
        assert effects is not None and repeat is not None
        expected[tool] = (
            [(value, str(note).strip()) for value, note in effects.items()],
            next((value, str(note).strip()) for value, note in repeat.items()),
        )
    assert {
        tool: ([(n.value, n.note) for n in effects], (repeat.value, repeat.note))
        for tool, (effects, repeat) in parsed.own.items()
    } == expected
    # tools.own names exactly the captured tools no picked shared plugin registers.
    shelf = AGENTS / Path(*SHARED_PLUGINS)
    picked = {KNOWN[name] for name in parsed.shared}
    shared_tools = set().union(*(registered_tools(shelf / plugin) for plugin in picked))
    assert set(own) == captured(agent) - shared_tools
    # An own plugin is inserted whole (no harness.tools); it may say which tools end the run.
    ends_run: set[str] = set()
    for plugin in sorted(path for path in (agent / "plugins").glob("*") if path.is_dir()):
        declared_tools, tool_problems = manifest_list(plugin, "tools")
        ends, end_problems = manifest_list(plugin, "ends_run")
        assert (declared_tools, tool_problems, end_problems) == (None, [], []), plugin
        ends_run |= set(ends or [])
    assert ends_run <= set(own), f"{MANIFEST_KEY}.ends_run: {ends_run}"


def test_no_agent_yml_reaches_the_model() -> None:
    assert sorted(AGENTS.glob(f"*/workspace/**/{AGENT_FILE}")) == []


def test_the_cases_cover_every_verdict_and_their_ids_are_unique() -> None:
    ids = [case.id for case in CASE_LIST]
    assert len(ids) == len(set(ids))
    assert any(not case.problems for case in CASE_LIST)
    assert any(case.problems for case in CASE_LIST)
    assert any(case.subset != ("refuses" if case.problems else "accepts") for case in CASE_LIST)
    assert any("duplicate key" in case.problems for case in CASE_LIST)


@pytest.mark.parametrize("case", CASE_LIST, ids=[case.id for case in CASE_LIST])
def test_each_python_reader_gives_the_verdict_the_case_pins(case: Case) -> None:
    found = verdict(case.text)
    assert len(found) == len(case.problems), found
    for fragment in case.problems:
        assert any(fragment in problem for problem in found), (fragment, found)
    parsed, reader_problems = parse_agent_yml(case.text, VALUES, KNOWN)
    assert (parsed is not None) == (case.subset == "accepts"), reader_problems
    if "duplicate key" in case.problems:
        assert any("duplicate key" in problem for problem in reader_problems), reader_problems
