# PyYAML ships no types, and loading YAML is Any: disallow_any_expr rejects every expression
# that touches it. This stub (on mypy_path) declares only what tests/gates/test_agent_yml.py
# uses, the third reader of agent.yml: SafeLoader subclassed to refuse a repeated key and to
# read scalars as YAML 1.2's core schema does (the schema js-yaml uses in the image), with
# every value `object`, narrowed with isinstance before use. Anything else from yaml is an
# error until it is declared here. Checked against the installed library by
# tests/gates/test_boundaries.py::test_every_stub_matches_the_installed_library.

class YAMLError(Exception): ...

class Node:
    tag: str

class ScalarNode(Node):
    value: str
    style: str | None

class MappingNode(Node):
    value: list[tuple[Node, Node]]

class SafeLoader:
    def __init__(self, stream: str) -> None: ...
    def construct_object(self, node: Node, deep: bool = False) -> object: ...
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[object, object]: ...
    def get_single_data(self) -> object: ...
    def dispose(self) -> None: ...
