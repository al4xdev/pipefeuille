"""Read the agents of the runtime layer (backend_harness/) as the model gets them.

The architecture graph (architecture.py) draws one `agent` node per agents/<name>/, and the
gates hold it to the code. What an agent is comes from three places, none copied here:

- agents/<name>/agent.yml: its description, limits and tools (read by the stdlib reader
  below; the image reads the same file with js-yaml, dsh-plugin-app-tools/agent.js, and
  tests/gates/test_agent_yml.py with PyYAML: three readers, held to the same verdicts);
- tests/baseline/<profile>.<name>.txt: the context capture the owner accepted (the route, the
  effort, the AGENTS.md text, every tool's description and schema as the model gets them);
- runtime/profiles/<profile>/cordis.patch.yml: the profile's default route.

The profile's name is the harness prefix (a FILL-IN, `app` until a project renames it with
backend_harness/rename-prefix.sh): it is read from the one folder in runtime/profiles/, never
written here, so a rename needs no change of this module.

Never edited in a project, like architecture.py (RUNBOOK, task C).
"""

import ast
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_NAME = "backend_harness"
AGENTS_FOLDER = "agents"
AGENT_FILE = "agent.yml"
SHARED_PLUGINS = ("_shared", "plugins")
PROFILES = ("runtime", "profiles")
PATCH_FILE = "cordis.patch.yml"
BASELINES = ("tests", "baseline")
MODEL_ENTRY = "agent-default-model"
# The key of a plugin's package.json the harness reads: `tools` (a shared plugin's opt-in
# names) and `ends_run` (an own plugin's tools whose successful call ends the run).
MANIFEST_KEY = "harness"
# The adapter of the agent-runs port that names the agents: a `harness` package's contracts.py
# holding `AGENTS = {"<work>": "<agent>"}` (backend_logic/<nearest parent>/_shared/<port>/).
AGENTS_TABLE_NAME = "AGENTS"
ADAPTER_PACKAGE = "harness"
# Use cases name the work in the calls of their run on the port's pipe steps:
# `pipe.submit(..., work="<work>")` hands it over, `pipe.observe(..., work="<work>")` reads
# the answer back.
SUBMIT_METHOD = "submit"
OBSERVE_METHOD = "observe"
WORK_KEYWORD = "work"


@dataclass(frozen=True)
class Note:
    """One `<value>: <note>` of agent.yml's tools.own (the E1 vocabulary of architecture.py)."""

    value: str
    note: str


@dataclass(frozen=True)
class AgentLimits:
    """agent.yml's limits (time and tokens: app-limits, in the run; attempts: the queue).
    None is no limit."""

    max_run_seconds: int | None
    max_tokens: int | None
    max_attempts: int


@dataclass(frozen=True)
class AgentDoc:
    """agents/<agent>/agent.yml, checked: the one declaration of an agent to the harness."""

    description: str
    limits: AgentLimits
    shared: tuple[str, ...]  # tools.shared: opt-in tools of agents/_shared/plugins, by name
    own: dict[str, tuple[tuple[Note, ...], Note]]  # tools.own: tool -> (effects, repeat)
    model: tuple[str, str] | None = None  # (name, reasoning); None = the profile's default


@dataclass(frozen=True)
class OwnToolDoc:
    """An own tool: its effects and repeat (agent.yml), and its plugin's `harness.ends_run`."""

    effects: tuple[Note, ...]
    repeat: Note
    ends_run: bool


@dataclass(frozen=True)
class AgentTool:
    """One tool as the model gets it (the capture), and the plugin that registers it."""

    name: str
    description: str
    parameters: str  # the JSON schema, compact, as captured
    plugin: str
    shared: bool  # picked from agents/_shared/plugins by agent.yml's tools.shared
    doc: OwnToolDoc | None  # an own tool's; a shared tool has none


@dataclass
class AgentFacts:
    provider: str
    model: str
    effort: str
    instructions: str  # workspace/AGENTS.md, as the model gets it
    system: str  # the system prompt the plugins add (their guidance), "" if none
    capture: str  # the baseline the facts come from, relative to the template root
    tools: list[AgentTool] = field(default_factory=list)
    works: tuple[str, ...] = ()  # the works the AGENTS table sends to it
    input: str = ""
    output: str = ""
    description: str = ""  # agent.yml's
    limits: AgentLimits | None = None  # None when agent.yml is unreadable (a problem)


# --- JSON --------------------------------------------------------------------------------


class JsonObject(dict[str, object]):
    """A JSON object as decoded here: string keys, values typed `object`, narrowed on use."""


def json_pairs(pairs: list[tuple[str, object]]) -> JsonObject:
    return JsonObject(pairs)


def load_json(text: str) -> object:
    """JSON with objects as JsonObject; None for a text that is no JSON."""
    try:
        parsed: object = json.loads(text, object_pairs_hook=json_pairs)
    except ValueError:
        return None
    return parsed


def manifest_list(plugin: Path, key: str) -> tuple[list[str] | None, list[str]]:
    """`harness.<key>` of a plugin's package.json: None when absent, or the problems."""
    manifest = plugin / "package.json"
    found = load_json(manifest.read_text(encoding="utf-8")) if manifest.exists() else None
    where = f"{plugin.name}/package.json"
    if not isinstance(found, JsonObject):
        return None, [f"{where}: missing or not a JSON object"]
    if found.get("name") != plugin.name:
        return None, [f"{where}: its name is not its folder's, {plugin.name!r}"]
    section = found.get(MANIFEST_KEY)
    if section is None:
        return None, []
    value = section.get(key) if isinstance(section, JsonObject) else None
    if isinstance(section, JsonObject) and value is None:
        return None, []
    if not isinstance(value, list) or not value or not all(isinstance(t, str) for t in value):
        return None, [f"{where}: {MANIFEST_KEY}.{key} is a non-empty list of tool names"]
    return [tool for tool in value if isinstance(tool, str)], []


def declared_shared(harness: Path) -> tuple[dict[str, str], list[str]]:
    """tool -> shared plugin, from each shared plugin's package.json (`harness.tools`)."""
    found: dict[str, str] = {}
    problems: list[str] = []
    shelf = harness / AGENTS_FOLDER / Path(*SHARED_PLUGINS)
    for plugin in sorted(path for path in shelf.glob("*") if path.is_dir()):
        tools, tool_problems = manifest_list(plugin, "tools")
        problems.extend(tool_problems)
        for tool in tools or []:
            if tool in found:
                problems.append(f"tool {tool!r} declared by both {found[tool]} and {plugin.name}")
            found[tool] = plugin.name
    return found, problems


# --- captures ----------------------------------------------------------------------------


@dataclass(frozen=True)
class CapturedTool:
    name: str
    description: str
    parameters: str


@dataclass
class Capture:
    """What one context.sh capture says the model gets."""

    provider: str = ""
    model: str = ""
    effort: str = ""
    instructions: str | None = None  # the AGENTS.md text inside the agent-instructions message
    system: str = ""
    tools: list[CapturedTool] = field(default_factory=list)


# The capture is context.mjs's toText: `-- <name> (<n> chars)` heads a section or a message, and
# n counts UTF-16 code units (JavaScript's length), so a text is cut by that count, never by a
# search for the next header, which the text itself may contain.
MESSAGES_HEADER = re.compile(r"^== messages \((\d+)\)\n", re.MULTILINE)
MESSAGE_HEADER = re.compile(r"-- #\d+ [^/\n]+/(\S+) \((\d+) chars\)\n")
TOOLS_HEADER = re.compile(r"== tools \((\d+)\)\n")
ROUTE = re.compile(r"profile \S+  route ([^/\s]+)/(\S+)  preset \S+")
# dsh wraps AGENTS.md in a reminder; the file's text is what sits between these two.
INSTRUCTIONS_FROM = "Instructions from: AGENTS.md\n\n"
REMINDER_END = "\n</system-reminder>"


def utf16_prefix(text: str, units: int) -> str:
    """The first `units` UTF-16 code units of text."""
    count = 0
    for index, char in enumerate(text):
        if count >= units:
            return text[:index]
        count += 2 if ord(char) > 0xFFFF else 1
    return text


def is_parameters_line(lines: list[str], at: int) -> bool:
    """A tool's last line: its JSON schema, then the end or a blank line before the next tool."""
    last = at + 1 == len(lines)
    before_next = at + 2 < len(lines) and lines[at + 1] == "" and lines[at + 2].startswith("-- ")
    return (last or before_next) and isinstance(load_json(lines[at]), JsonObject)


def parse_tools(section: str) -> list[CapturedTool]:
    """`-- <name>`, the description (any lines), the parameters (one JSON line), a blank line."""
    lines = section.rstrip("\n").split("\n") if section.strip() else []
    tools: list[CapturedTool] = []
    index = 0
    while index < len(lines) and lines[index].startswith("-- "):
        end = index + 1
        while end < len(lines) and not is_parameters_line(lines, end):
            end += 1
        if end == len(lines):
            break
        name = lines[index].removeprefix("-- ")
        tools.append(CapturedTool(name, "\n".join(lines[index + 1 : end]), lines[end]))
        index = end + 2
    return tools


def parse_capture(text: str) -> tuple[Capture, list[str]]:
    """The route, the effort, the instructions, the system prompt and the tools of a capture."""
    capture = Capture()
    lines = text.split("\n")
    route = ROUTE.fullmatch(lines[0])
    if route is None:
        return capture, [
            "the first line is not `profile <p>  route <provider>/<model>  preset <p>`"
        ]
    capture.provider, capture.model = route.expand(r"\1"), route.expand(r"\2")
    problems: list[str] = []
    options = next((line for line in lines if line.startswith("options ")), "options ")
    parsed = load_json(options.removeprefix("options "))
    effort = parsed.get("reasoningEffort") if isinstance(parsed, JsonObject) else None
    if isinstance(effort, str):
        capture.effort = effort
    else:
        problems.append("the options line has no reasoningEffort")
    heading = MESSAGES_HEADER.search(text)
    if heading is None:
        return capture, [*problems, "no `== messages (<n>)` section"]
    position = heading.end()
    for _ in range(int(heading.expand(r"\1"))):
        header = MESSAGE_HEADER.match(text, position)
        if header is None:
            return capture, [*problems, f"no message header at offset {position}"]
        body = utf16_prefix(text[header.end() :], int(header.expand(r"\2")))
        position = header.end() + len(body)
        if text[position : position + 2] != "\n\n":
            return capture, [*problems, f"a message does not end where its size says ({position})"]
        position += 2
        role = header.expand(r"\1")
        if role == "agent-instructions":
            start, end = body.find(INSTRUCTIONS_FROM), body.rfind(REMINDER_END)
            if 0 <= start < end:
                capture.instructions = body[start + len(INSTRUCTIONS_FROM) : end]
        elif role == "system-prompt":
            capture.system = body
    tools = TOOLS_HEADER.match(text, position)
    if tools is None:
        return capture, [*problems, "no `== tools (<n>)` section after the messages"]
    capture.tools = parse_tools(text[tools.end() :])
    count = int(tools.expand(r"\1"))
    if len(capture.tools) != count:
        problems.append(f"`== tools ({count})` but {len(capture.tools)} tools were read")
    return capture, problems


# --- agent.yml, the stdlib reader ---------------------------------------------------------

# agent.yml as this reader reads it: block mappings by indentation, plain or quoted text, a
# flow list of names (`[read, sql]`) and a flow mapping of `value: note` pairs. Anything else
# (anchors, tags, block scalars, `- ` lists, escapes) is refused rather than guessed. The
# image reads the same files with js-yaml (dsh-plugin-app-tools/agent.js) and
# tests/gates/test_agent_yml.py with PyYAML; this one needs nothing beyond the standard
# library, like the rest of the graph. backend_harness/tests/agent_yml_cases.json holds the
# cases all three are held to.
type YamlValue = str | list[str] | dict[str, YamlValue]
YAML_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*")
YAML_LINE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_-]*):(?:\s+(.*))?")
YAML_FLOW_KEY = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_-]*):\s+")
# Starts a plain scalar YAML gives another meaning (or this reader does not read).
YAML_INDICATORS = tuple("[]{}|>&*!%@`-?,:#")
# YAML's core schema spells null four ways; a nullable limit takes any of them.
YAML_NULLS = ("null", "Null", "NULL", "~")
TOOL_NAME = re.compile(r"[a-z][a-z0-9_]*")
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
AGENT_KEYS = ("description", "limits", "tools", "model")
# Every limit is required; a nullable one says "no limit" with null.
LIMIT_KEYS: dict[str, bool] = {"max_run_seconds": True, "max_tokens": True, "max_attempts": False}
# agent.yml's model: a model id on the profile's route and one of its efforts (as in
# dsh-plugin-app-tools/agent.js, the reader the image build uses).
MODEL_NAME = re.compile(r"[a-z][a-z0-9.-]*[a-z0-9]")
REASONING = ("off", "low", "high", "max")
# Shared tools that only make sense next to `read` (as dsh-plugin-app-tools checks them).
NEEDS_READ = ("edit", "apply_patch")
# The E1 values a tool's notes may use, by section; architecture.py passes its enums.
type Vocabulary = Mapping[str, tuple[str, ...]]


def quoted_end(value: str) -> int | None:
    """Where the quoted scalar at the start of value ends ('' is a quote inside '...')."""
    quote, at = value[0], 1
    while (at := value.find(quote, at)) != -1:
        if quote == "'" and value[at + 1 : at + 2] == "'":
            at += 2
            continue
        return at + 1
    return None


def yaml_text(raw: str) -> str:
    """The text of a scalar as stored (quotes kept, so `'3'` stays apart from `3`)."""
    if raw[:1] == "'":
        return raw[1:-1].replace("''", "'")
    if raw[:1] == '"':
        return raw[1:-1]
    return raw


def yaml_scalar(value: str, stops: str = "") -> tuple[str, int, str | None]:
    """The raw scalar at the start of value, where it ends, or a problem.

    `stops` ends a plain scalar too (`,}` inside a flow mapping, as YAML reads it).
    """
    if value[:1] in ("'", '"'):
        end = quoted_end(value)
        if end is None:
            return "", 0, "an unterminated quote"
        if value[0] == '"' and "\\" in value[:end]:
            return "", 0, "an escape in double quotes (write the text in single quotes)"
        return value[:end], end, None
    end = min([at for at in (value.find(stop) for stop in stops) if at != -1] or [len(value)])
    comment = value.find(" #")
    if comment != -1 and comment < end:
        end = comment
    raw = value[:end].rstrip()
    if not raw or raw.startswith(YAML_INDICATORS) or ": " in raw or raw.endswith(":"):
        return "", 0, f"not text this reader reads: {raw!r}"
    return raw, end, None


def only_comment(rest: str) -> bool:
    return not rest.strip() or rest.strip().startswith("#")


def flow_list(value: str) -> tuple[list[str], str | None]:
    end = value.find("]")
    if end == -1 or not only_comment(value[end + 1 :]):
        return [], "a flow list is `[name, name]` on one line"
    inner = value[1:end].strip()
    names = [name.strip() for name in inner.split(",")] if inner else []
    if not all(YAML_KEY.fullmatch(name) for name in names):
        return [], "a flow list holds plain names only"
    return names, None


def flow_mapping(value: str) -> tuple[dict[str, YamlValue], str | None]:
    """`{value: note, value: 'note'}` on one line; a duplicate key is a problem."""
    found: dict[str, YamlValue] = {}
    at = 1
    while True:
        at += len(value[at:]) - len(value[at:].lstrip())
        if value[at : at + 1] == "}" and not found:
            break
        key = YAML_FLOW_KEY.match(value, at)
        if key is None:
            return {}, "a flow mapping is `{value: note, ...}` on one line"
        name = key.expand(r"\1")
        if name in found:
            return {}, f"duplicate key {name!r}"
        raw, length, problem = yaml_scalar(value[key.end() :], ",}")
        if problem is not None:
            return {}, problem
        found[name] = raw
        at = key.end() + length
        at += len(value[at:]) - len(value[at:].lstrip())
        if value[at : at + 1] == ",":
            at += 1
            continue
        if value[at : at + 1] == "}":
            break
        return {}, "a flow mapping is `{value: note, ...}` on one line"
    if not only_comment(value[at + 1 :]):
        return {}, "text after the flow mapping"
    return found, None


def parse_yaml_subset(text: str) -> tuple[dict[str, YamlValue], list[str]]:
    """The mappings of an agent.yml; a duplicate key is a problem, never a silent overwrite."""
    root: dict[str, YamlValue] = {}
    # (indent of a mapping's keys, the mapping). A block mapping just opened takes the indent
    # of its first key, which must be deeper than the key that opened it.
    stack: list[tuple[int, dict[str, YamlValue]]] = [(0, root)]
    opened: tuple[int, int, str] | None = None  # (indent, line, key) awaiting its first key
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if line[indent : indent + 1] == "\t":
            problems.append(f"line {number}: a tab in the indentation")
            continue
        if opened is not None:
            if indent > opened[0]:
                stack[-1] = (indent, stack[-1][1])
            else:
                problems.append(f"line {opened[1]}: `{opened[2]}:` has nothing under it")
                stack.pop()
            opened = None
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        if indent != stack[-1][0]:
            problems.append(f"line {number}: unexpected indentation")
            continue
        match = YAML_LINE.fullmatch(stripped)
        if match is None:
            problems.append(f"line {number}: not `key: value` nor `key:` over a block")
            continue
        key = match.expand(r"\1")
        value = match.expand(r"\2")
        mapping = stack[-1][1]
        if key in mapping:
            problems.append(f"line {number}: duplicate key {key!r}")
            mapping = {}  # read on, so what is under it is not misread as the next key's
        if not value or value.startswith("#"):
            child: dict[str, YamlValue] = {}
            mapping[key] = child
            stack.append((-1, child))
            opened = (indent, number, key)
            continue
        problem: str | None
        if value.startswith("["):
            mapping[key], problem = flow_list(value)
        elif value.startswith("{"):
            mapping[key], problem = flow_mapping(value)
        else:
            raw, end, problem = yaml_scalar(value)
            if problem is None and not only_comment(value[end:]):
                problem = "text after the value"
            mapping[key] = raw
        if problem is not None:
            problems.append(f"line {number}: {key}: {problem}")
    if opened is not None:
        problems.append(f"line {opened[1]}: `{opened[2]}:` has nothing under it")
    return root, problems


def unknown_keys(mapping: dict[str, YamlValue], allowed: tuple[str, ...], where: str) -> list[str]:
    return [f"{where}: unknown key {key!r}" for key in mapping if key not in allowed]


def notes_of(
    value: YamlValue | None, where: str, allowed: tuple[str, ...]
) -> tuple[tuple[Note, ...], list[str]]:
    """`{<value>: <note>}` with the allowed values, every note a non-empty text."""
    if not isinstance(value, dict) or not value:
        return (), [f"{where}: a mapping of value to note"]
    notes: list[Note] = []
    problems: list[str] = []
    for key, note in value.items():
        text = yaml_text(note).strip() if isinstance(note, str) else ""
        if key not in allowed:
            problems.append(f"{where}: {key!r} is not one of {list(allowed)}")
        if not text:
            problems.append(f"{where}.{key}: the note is a non-empty text")
        notes.append(Note(key, text))
    return tuple(notes), problems


def read_limits(value: YamlValue | None) -> tuple[AgentLimits | None, list[str]]:
    if not isinstance(value, dict):
        return None, [f"limits: required, with {', '.join(LIMIT_KEYS)}"]
    problems = unknown_keys(value, tuple(LIMIT_KEYS), "limits")
    found: dict[str, int | None] = {}
    for key, nullable in LIMIT_KEYS.items():
        raw = value.get(key)
        if raw is None:
            problems.append(f"limits.{key}: required{' (null is no limit)' if nullable else ''}")
        elif nullable and raw in YAML_NULLS:
            found[key] = None
        elif isinstance(raw, str) and re.fullmatch(r"[1-9][0-9]*", raw):
            found[key] = int(raw)
        else:
            problems.append(f"limits.{key}: a positive integer{', or null' if nullable else ''}")
    attempts = found.get("max_attempts")
    if problems or attempts is None:
        return None, problems
    return AgentLimits(found["max_run_seconds"], found["max_tokens"], attempts), []


def read_model(value: YamlValue | None) -> tuple[tuple[str, str] | None, list[str]]:
    """agent.yml's model: None when absent (the profile's default), else name and reasoning."""
    if value is None:
        return None, []
    if not isinstance(value, dict):
        return None, ["model: a mapping with name and reasoning"]
    problems = unknown_keys(value, ("name", "reasoning"), "model")
    name, reasoning = value.get("name"), value.get("reasoning")
    if not isinstance(name, str) or not MODEL_NAME.fullmatch(yaml_text(name)):
        problems.append(f"model.name: a model id, {MODEL_NAME.pattern}")
    if not isinstance(reasoning, str) or yaml_text(reasoning) not in REASONING:
        problems.append(f"model.reasoning: one of {', '.join(REASONING)}")
    if problems or not isinstance(name, str) or not isinstance(reasoning, str):
        return None, problems
    return (yaml_text(name), yaml_text(reasoning)), []


def read_shared(picked: YamlValue, known: Mapping[str, str]) -> list[str]:
    """tools.shared: a non-empty list of known names, none twice, `read` beside those needing it."""
    if not isinstance(picked, list) or not picked:
        return ["tools.shared: a non-empty list of tool names"]
    if len(set(picked)) != len(picked):
        return ["tools.shared: a tool listed twice"]
    problems = [f"tools.shared: unknown tool {name!r}" for name in picked if name not in known]
    problems += [
        f"tools.shared: {name} needs read"
        for name in NEEDS_READ
        if name in picked and "read" not in picked
    ]
    return problems


def read_own(
    value: YamlValue, vocabulary: Vocabulary
) -> tuple[dict[str, tuple[tuple[Note, ...], Note]], list[str]]:
    if not isinstance(value, dict) or not value:
        return {}, ["tools.own: a mapping of tool name to its effects and repeat"]
    own: dict[str, tuple[tuple[Note, ...], Note]] = {}
    problems: list[str] = []
    for tool, entry in value.items():
        where = f"tools.own.{tool}"
        if not TOOL_NAME.fullmatch(tool):
            problems.append(f"{where}: a tool name is {TOOL_NAME.pattern}")
        if not isinstance(entry, dict):
            problems.append(f"{where}: a mapping with effects and repeat")
            continue
        problems.extend(unknown_keys(entry, ("effects", "repeat"), where))
        effects, effect_problems = notes_of(
            entry.get("effects"), f"{where}.effects", vocabulary["Effects"]
        )
        repeat, repeat_problems = notes_of(
            entry.get("repeat"), f"{where}.repeat", vocabulary["Repeat"]
        )
        problems.extend(effect_problems + repeat_problems)
        values = {note.value for note in effects}
        if "pure" in values and len(values) > 1:
            problems.append(f"{where}.effects: pure only alone")
        if len(repeat) > 1:
            problems.append(f"{where}.repeat: exactly one value, the worst case")
        if values == {"pure"} and [note.value for note in repeat] != ["safe"]:
            problems.append(f"{where}: pure implies repeat: safe")
        if effects and len(repeat) == 1:
            own[tool] = (effects, repeat[0])
    return own, problems


def parse_agent_yml(
    text: str, vocabulary: Vocabulary, known: Mapping[str, str]
) -> tuple[AgentDoc | None, list[str]]:
    """agent.yml read and held to its closed schema; None with the problems if it fails.

    vocabulary: the E1 values of tools.own (architecture.py's enums); known: the shared
    tools the shared plugins declare (declared_shared).
    """
    doc, problems = parse_yaml_subset(text)
    if problems:
        return None, problems
    problems = unknown_keys(doc, AGENT_KEYS, "agent.yml")
    raw = doc.get("description")
    description = yaml_text(raw).strip() if isinstance(raw, str) else ""
    sentences = sum(1 for _ in SENTENCE_END.finditer(description))
    if not description or not 1 <= sentences <= 2 or not SENTENCE_END.search(description[-1]):
        problems.append("description: one or two sentences, required")
    limits, limit_problems = read_limits(doc.get("limits"))
    problems.extend(limit_problems)
    model, model_problems = read_model(doc.get("model"))
    problems.extend(model_problems)
    tools = doc.get("tools", {})
    shared: list[str] = []
    own: dict[str, tuple[tuple[Note, ...], Note]] = {}
    if not isinstance(tools, dict) or ("tools" in doc and not tools):
        problems.append("tools: a mapping with shared and/or own")
    else:
        problems.extend(unknown_keys(tools, ("shared", "own"), "tools"))
        if "shared" in tools:
            shared_problems = read_shared(tools["shared"], known)
            problems.extend(shared_problems)
            picked = tools["shared"]
            if not shared_problems and isinstance(picked, list):
                shared = picked
        if "own" in tools:
            own, own_problems = read_own(tools["own"], vocabulary)
            problems.extend(own_problems)
    if problems or limits is None:
        return None, problems
    return AgentDoc(description, limits, tuple(shared), own, model), []


# --- the rest of an agent -----------------------------------------------------------------


def profile_of(harness: Path) -> tuple[str | None, list[str]]:
    """The harness prefix: the one folder of runtime/profiles/ that holds a profile patch."""
    profiles = harness / Path(*PROFILES)
    found = sorted(path.parent.name for path in profiles.glob(f"*/{PATCH_FILE}"))
    if len(found) != 1:
        return None, [
            f"{HARNESS_NAME}/{'/'.join(PROFILES)}: one profile folder with {PATCH_FILE} is "
            f"expected (the harness prefix), found {found}"
        ]
    return found[0], []


def default_model(patch: str) -> tuple[str, str, str] | None:
    """provider, model and reasoningEffort of the profile patch's `agent-default-model` entry."""
    lines = patch.splitlines()
    if f"- id: {MODEL_ENTRY}" not in lines:
        return None
    values: dict[str, str] = {}
    for line in lines[lines.index(f"- id: {MODEL_ENTRY}") + 1 :]:
        if line.startswith("- "):
            break
        key, _, value = line.strip().partition(":")
        if key and not key.startswith("#"):
            raw, _, _ = value.strip().partition(" #")
            values[key] = yaml_text(raw.strip())
    provider, model, effort = (
        values.get("provider"),
        values.get("model"),
        values.get("reasoningEffort"),
    )
    return (provider, model, effort) if provider and model and effort else None


# How a dsh plugin names a tool it registers: `name: 'finalize_summary',` in a tool object.
# Only to tell which plugin a captured tool comes from; what the tool says is the capture's.
REGISTERED = re.compile(r"^\s*name: '([a-z][a-z0-9_]*)',?\s*$", re.MULTILINE)


def registered_tools(plugin: Path) -> set[str]:
    return {
        match.expand(r"\1")
        for path in sorted(plugin.glob("*.js"))
        for match in REGISTERED.finditer(path.read_text(encoding="utf-8"))
    }


def agents_table(path: Path) -> tuple[dict[str, str], list[str]]:
    """The literal `AGENTS = {"<work>": "<agent>"}` of the agent-runs port's harness adapter."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for statement in tree.body:
        target: ast.expr
        value: ast.expr | None
        if isinstance(statement, ast.AnnAssign):
            target, value = statement.target, statement.value
        elif isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        else:
            continue
        if not isinstance(target, ast.Name) or target.id != AGENTS_TABLE_NAME:
            continue
        if not isinstance(value, ast.Dict):
            return {}, [f"{AGENTS_TABLE_NAME} is not a dict literal"]
        table: dict[str, str] = {}
        for key, item in zip(value.keys, value.values, strict=True):
            if not (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(item, ast.Constant)
                and isinstance(item.value, str)
            ):
                return {}, [f"{AGENTS_TABLE_NAME} maps a string work to a string agent name"]
            table[key.value] = item.value
        return table, []
    return {}, [f"no {AGENTS_TABLE_NAME} table"]


def table_modules(logic: Path) -> list[Path]:
    """Every `<...>/harness/contracts.py` of the logic that assigns the AGENTS table."""
    found: list[Path] = []
    for path in sorted(logic.rglob(f"{ADAPTER_PACKAGE}/contracts.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            targets = (
                [statement.target]
                if isinstance(statement, ast.AnnAssign)
                else statement.targets
                if isinstance(statement, ast.Assign)
                else []
            )
            if any(isinstance(t, ast.Name) and t.id == AGENTS_TABLE_NAME for t in targets):
                found.append(path)
                break
    return found


def work_calls(function: ast.FunctionDef | ast.AsyncFunctionDef, method: str) -> list[str]:
    """The literal `work="<work>"` of every `<x>.<method>(...)` call in a `run`."""
    found: list[str] = []
    for node in ast.walk(function):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
        ):
            continue
        for keyword in node.keywords:
            value = keyword.value
            if (
                keyword.arg == WORK_KEYWORD
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                found.append(value.value)
    return found


def first_paragraph(text: str) -> str:
    """The first paragraph that is no heading: an AGENTS.md says there what the agent is."""
    found: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            found.append(stripped)
        elif found:
            break
    return " ".join(found)


def read_tools(
    folder: Path,
    capture: Capture,
    capture_name: str,
    shared: list[Path],
    doc: AgentDoc | None,
) -> tuple[list[AgentTool], list[str]]:
    """Each captured tool with the plugin that registers it, and agent.yml's doc if it is own.

    The capture is the authority on which tools the model gets: tools.own must name exactly
    the captured tools no picked shared plugin registers, in both directions.
    """
    problems: list[str] = []
    # Without a readable agent.yml the picks are unknown: every shared plugin may be one, so
    # an unreadable file is reported once, not again as every shared tool unaccounted for.
    picked = set(doc.shared) if doc is not None else None
    own = sorted(path for path in (folder / "plugins").glob("*") if path.is_dir())
    registers: dict[str, tuple[Path, bool]] = {}
    shared_names: set[str] = set()  # every tool of the shared plugins the agent picks from
    for plugin in shared:
        names = registered_tools(plugin)
        if picked is None or names & picked:
            registers.update(dict.fromkeys(names, (plugin, True)))
            shared_names |= names
    ends_run: set[str] = set()
    for plugin in own:
        registers.update(dict.fromkeys(registered_tools(plugin), (plugin, False)))
        declared, declared_problems = manifest_list(plugin, "tools")
        if declared is not None:
            problems.append(
                f"plugins/{plugin.name}/package.json: {MANIFEST_KEY}.tools is for shared "
                "plugins; an own plugin is inserted whole"
            )
        ends, end_problems = manifest_list(plugin, "ends_run")
        ends_run |= set(ends or [])
        problems.extend(f"plugins/{problem}" for problem in declared_problems + end_problems)
    captured = {tool.name for tool in capture.tools}
    stale = f"the model does not get it ({capture_name}): the capture is stale"
    for name in sorted(picked or ()):
        if name not in registers:
            problems.append(
                f"{AGENT_FILE}: tools.shared lists {name!r}, which no shared plugin registers"
            )
        elif name not in captured:
            problems.append(f"{AGENT_FILE}: tools.shared lists {name!r}, but {stale}")
    for plugin in own:
        for name in sorted(registered_tools(plugin) - captured):
            problems.append(f"plugins/{plugin.name} registers {name!r}, but {stale}")
    docs: dict[str, OwnToolDoc] = {}
    if doc is not None:
        for name in sorted(set(doc.own) - captured):
            problems.append(
                f"{AGENT_FILE}: tools.own describes {name!r}, which the model does not get "
                f"({capture_name}): a typo, or the capture is stale"
            )
        for name in sorted(captured - shared_names - set(doc.own)):
            problems.append(
                f"{capture_name}: the model gets {name!r}, which {AGENT_FILE}'s tools.own does "
                "not describe (its effects and repeat)"
            )
        for name in sorted(ends_run - set(doc.own)):
            problems.append(
                f"an own plugin's {MANIFEST_KEY}.ends_run names {name!r}, which tools.own does not"
            )
        docs = {
            name: OwnToolDoc(effects, repeat, name in ends_run)
            for name, (effects, repeat) in doc.own.items()
        }
    tools: list[AgentTool] = []
    for tool in capture.tools:
        if tool.name not in registers:
            problems.append(
                f"{capture_name}: the model gets tool {tool.name!r}, which no plugin of the agent "
                "registers"
            )
            continue
        plugin, is_shared = registers[tool.name]
        tools.append(
            AgentTool(
                tool.name,
                tool.description,
                tool.parameters,
                plugin.name,
                is_shared,
                None if is_shared else docs.get(tool.name),
            )
        )
    return tools, problems


def read_agent(
    folder: Path,
    harness: Path,
    profile: str,
    route: tuple[str, str, str] | None,
    vocabulary: Vocabulary,
) -> tuple[AgentFacts | None, list[str]]:
    """An agent as the model gets it, held to its folder and to the profile."""
    baselines = harness / Path(*BASELINES)
    capture_name = f"{profile}.{folder.name}.txt"
    capture_path = baselines / capture_name
    if not capture_path.exists():
        return None, [
            f"no context capture {'/'.join(BASELINES)}/{capture_name}: capture the agent with "
            "tests/context.sh and have the owner accept its baseline"
        ]
    capture, parse_problems = parse_capture(capture_path.read_text(encoding="utf-8"))
    problems = [f"{capture_name}: {problem}" for problem in parse_problems]
    known, known_problems = declared_shared(harness)
    problems.extend(known_problems)
    declared = folder / AGENT_FILE
    doc: AgentDoc | None = None
    if not declared.exists():
        problems.append(f"no {AGENT_FILE}: every agent declares itself there, beside workspace/")
    else:
        doc, doc_problems = parse_agent_yml(declared.read_text(encoding="utf-8"), vocabulary, known)
        problems.extend(f"{AGENT_FILE}: {problem}" for problem in doc_problems)
    provider, model, effort = route or (capture.provider, capture.model, capture.effort)
    # An agent.yml model replaces the profile's model and effort in the agent's own profile
    # (app-profiles.mjs); the provider stays the profile's.
    says = f"{MODEL_ENTRY} says"
    if doc is not None and doc.model is not None:
        (model, effort), says = doc.model, f"{AGENT_FILE}'s model says"
    if (provider, model, effort) != (capture.provider, capture.model, capture.effort):
        problems.append(
            f"{capture_name}: the model gets {capture.provider}/{capture.model} at effort "
            f"{capture.effort!r}, but {says} {provider}/{model} at {effort!r}: "
            "the capture is stale"
        )
    agents_md = folder / "workspace" / "AGENTS.md"
    on_disk = agents_md.read_text(encoding="utf-8").strip() if agents_md.exists() else None
    if capture.instructions is None:
        problems.append(f"{capture_name}: the model gets no AGENTS.md")
    elif on_disk != capture.instructions.strip():
        problems.append(
            f"workspace/AGENTS.md is not what {capture_name} says the model gets: the capture "
            "is stale"
        )
    shelf = harness / AGENTS_FOLDER / Path(*SHARED_PLUGINS)
    shared = sorted(path for path in shelf.glob("*") if path.is_dir())
    tools, tool_problems = read_tools(folder, capture, capture_name, shared, doc)
    facts = AgentFacts(
        provider,
        model,
        effort,
        capture.instructions or "",
        capture.system,
        capture=f"{HARNESS_NAME}/{'/'.join(BASELINES)}/{capture_name}",
        tools=tools,
        description=doc.description if doc is not None else "",
        limits=doc.limits if doc is not None else None,
    )
    return facts, problems + tool_problems
