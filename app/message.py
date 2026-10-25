"""Display a controller message without interpreting it as a command."""

import argparse
import unicodedata

from luma.core.legacy.font import CP437_FONT, proportional

from matrix_text import render_lines

MAX_MESSAGE_LENGTH = 280
_PUNCTUATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00df": "ss",
    "\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue",
    "\u00c4": "Ae", "\u00d6": "Oe", "\u00dc": "Ue", "\u00b0": "deg",
})


def validate_message(value):
    """Normalize Latin text to the matrix font; reject unsupported input."""
    if not isinstance(value, str):
        raise ValueError("Enter a message to display.")
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if any(ord(character) < 32 and character != "\n" for character in value):
        raise ValueError("The message contains an unsupported control character.")
    value = "\n".join(line.strip() for line in value.strip().split("\n"))
    if not value:
        raise ValueError("Enter a message to display.")
    if len(value.split("\n")) > 2:
        raise ValueError("Use at most two lines.")
    if len(value) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Use at most {MAX_MESSAGE_LENGTH} characters.")
    decomposed = unicodedata.normalize("NFKD", value.translate(_PUNCTUATION))
    normalized = "".join(c for c in decomposed if not unicodedata.combining(c))
    if not normalized.strip():
        raise ValueError("Enter a message to display.")
    if any(c != "\n" and not 32 <= ord(c) <= 126 for c in normalized):
        raise ValueError("Use letters, numbers, and punctuation. Emoji are not supported.")
    if len(normalized) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Use at most {MAX_MESSAGE_LENGTH} characters after accents are simplified.")
    return normalized


class MessageDisplay:
    def __init__(self, message):
        self.lines = validate_message(message).split("\n")
        self.font = proportional(CP437_FONT)

    def render(self, elapsed, delta):
        return render_lines(self.lines, elapsed, font=self.font)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    try:
        display = MessageDisplay(args.message)
    except ValueError as error:
        parser.error(str(error))
    from effect_runner import run
    run(display)


if __name__ == "__main__":
    main()
