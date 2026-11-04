lazy import string

lazy from .contracts import NoteName
lazy from .pipeline import Pipe


def run(initial: str) -> NoteName:
    """Admit a note name: the single authority for save input, stored records and listing.

    Effects:
        pure
    Repeat:
        safe
    Loops:
        none
    Concurrency:
        free
    Raises:
        NoteValidationError: empty, longer than 64, or outside ASCII letters, digits, - and _.
    """
    # The grammar is fixed here, once: every consumer gets the same answer.
    # str.isalnum() would also accept "²", "½" and "Ⅰ", so the set is explicit ASCII.
    return (
        Pipe
            .get(initial)
                .validate_grammar(
                    allowed=string.ascii_letters + string.digits + "-_",
                    max_length=64,
                )
                    .materialize()
    )
