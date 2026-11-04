lazy from dataclasses import dataclass


@dataclass(frozen=True)
class DecodeText:
    """Untrusted JSON text from a file, a model reply or an HTTP body.

    Every rejection is a ValueError, so each consumer maps it in one place.
    """

    text: str


@dataclass(frozen=True)
class Parsed:
    """Parsing completed; value is still the library's untrusted object."""

    value: object
