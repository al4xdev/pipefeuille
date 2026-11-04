"""The shared note_name authority: one grammar for save input, stored records and listing."""

import pytest

from backend_logic._shared.note_name import run as naming
from backend_logic._shared.note_name.contracts import NoteValidationError


@pytest.mark.parametrize("name", ["groceries", "a", "A-b_9", "x" * 64])
def test_valid_names_are_returned_unchanged(name: str) -> None:
    assert naming.run(name) == name


@pytest.mark.parametrize(
    "name", ["", " groceries", "groceries ", "a/b", "../etc", "a.b", "²½", "Ⅰ", "x" * 65]
)
def test_invalid_names_are_rejected_never_corrected(name: str) -> None:
    with pytest.raises(NoteValidationError) as raised:
        naming.run(name)
    assert raised.value.code == "invalid_name"
