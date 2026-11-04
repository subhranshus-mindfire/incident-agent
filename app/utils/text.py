import re
from typing import Final

_REPEATED_CHARACTERS: Final = re.compile(r"(.)\1+")


def squeeze_repeats(text: str) -> str:
    """Collapses runs of a repeated character, so 'hii' and 'helloo' match 'hi' and 'hello'."""
    return _REPEATED_CHARACTERS.sub(r"\1", text)
