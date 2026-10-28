"""Display a controller message without interpreting it as a command."""

import argparse
import unicodedata

from luma.core.legacy.font import CP437_FONT, proportional

from matrix_text import render_lines

MAX_MESSAGE_LENGTH = 280
_PUNCTUATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "...",
    "\u2764": "\u2665", "\ufe0f": "",
})
# CP437's first 32 slots contain pictures, but Python's codec maps them to
# control characters. Accept their visible Unicode equivalents instead.
_PICTURES = {character: index for index, character in enumerate(
    "\x00☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"
) if index}
_PICTURES["⌂"] = 127
_GLYPHS = {ord(bytes([index]).decode("cp437")): bitmap
           for index, bitmap in enumerate(CP437_FONT) if index >= 32 and index != 127}
_GLYPHS.update({ord(character): CP437_FONT[index] for character, index in _PICTURES.items()})
# The original DOS font predates the euro; add a five-column, seven-row glyph.
_GLYPHS[ord("€")] = [0x14, 0x3e, 0x55, 0x55, 0x41]


class MessageFont:
    def __init__(self):
        self.font = proportional(_GLYPHS)

    def __getitem__(self, codepoint):
        # luma indexes by Unicode ordinal; the bitmap table uses CP437 slots.
        return self.font[codepoint]


def validate_message(value):
    """Preserve supported Unicode glyphs and simplify other Latin accents."""
    if not isinstance(value, str):
        raise ValueError("Enter a message to display.")
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if any(unicodedata.category(c).startswith("C") and c != "\n" for c in value):
        raise ValueError("The message contains an unsupported control character.")
    value = "\n".join(line.strip() for line in value.strip().split("\n"))
    if not value:
        raise ValueError("Enter a message to display.")
    if len(value.split("\n")) > 2:
        raise ValueError("Use at most two lines.")
    if len(value) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Use at most {MAX_MESSAGE_LENGTH} characters.")
    normalized = ""
    for character in unicodedata.normalize("NFC", value.translate(_PUNCTUATION)):
        if character == "\n":
            normalized += character
            continue
        if ord(character) in _GLYPHS:
            normalized += character
        else:
            simplified = "".join(c for c in unicodedata.normalize("NFKD", character)
                                 if not unicodedata.combining(c))
            if any(ord(c) not in _GLYPHS for c in simplified):
                raise ValueError(f"The matrix font cannot display {character!r}. Try another character or draw it below.") from None
            normalized += simplified
    if not normalized.strip():
        raise ValueError("Enter a message to display.")
    if len(normalized) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Use at most {MAX_MESSAGE_LENGTH} characters after accents are simplified.")
    return normalized


class MessageDisplay:
    def __init__(self, message):
        self.lines = validate_message(message).split("\n")
        self.font = MessageFont()

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
