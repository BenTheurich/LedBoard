import sys
import unittest
from pathlib import Path

from luma.core.legacy.font import CP437_FONT, proportional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from matrix_text import render_lines
from message import MessageDisplay, MessageFont, validate_message


class MessageTests(unittest.TestCase):
    def test_text_is_normalized_without_silently_dropping_unsupported_glyphs(self):
        self.assertEqual(validate_message(" Gr\u00fc\u00dfe!\r\nCaf\u00e9 \u201c12\u00b0\u201d "), 'Grüße!\nCafé "12°"')
        for value in ("\u0301", "\U0001f600", "\x7f", "one\ntwo\nthree", "a" * 281):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_message(value)

    def test_decomposed_accents_and_unsupported_latin_accents_are_simplified(self):
        self.assertEqual(validate_message("Cafe\u0301 A\u0304 ❤️"), "Café A ♥")
        self.assertEqual(validate_message("left\t—right…"), "left -right...")
        with self.assertRaises(ValueError):
            validate_message("…" * 100)

    def test_unicode_characters_use_their_cp437_bitmap_slots(self):
        font = MessageFont()
        original = proportional(CP437_FONT)
        for character, slot in (("♥", 3), ("↑", 24), ("°", 248), ("ü", 129), ("é", 130)):
            with self.subTest(character=character):
                self.assertEqual(font[ord(character)], original[slot])

    def test_typed_keyboard_punctuation_and_extended_symbols_render(self):
        for symbol in "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~°±÷√πµ£¥¢€♥↑":
            with self.subTest(symbol=symbol):
                image = MessageDisplay(symbol).render(0, 0)
                self.assertIsNotNone(image.getbbox())

    def test_short_message_is_static_and_rows_do_not_overlap(self):
        display = MessageDisplay("Hello\nBen")
        first = display.render(0, 0)
        self.assertEqual(first.size, (64, 16))
        self.assertEqual(first.mode, "1")
        self.assertIsNotNone(first.crop((0, 0, 64, 8)).getbbox())
        self.assertIsNotNone(first.crop((0, 8, 64, 16)).getbbox())
        self.assertEqual(first.tobytes(), display.render(20, 1).tobytes())

    def test_long_row_scrolls_after_reading_pause_and_keeps_other_row_still(self):
        display = MessageDisplay("This is a long message for the whole board\nBen")
        start = display.render(0, 0)
        paused = display.render(1, 0)
        moved = display.render(5, 0)
        self.assertEqual(start.tobytes(), paused.tobytes())
        self.assertNotEqual(start.crop((0, 0, 64, 8)).tobytes(), moved.crop((0, 0, 64, 8)).tobytes())
        self.assertEqual(start.crop((0, 8, 64, 16)).tobytes(), moved.crop((0, 8, 64, 16)).tobytes())

    def test_single_line_keeps_second_row_blank(self):
        image = render_lines(["Hello"], font=proportional(CP437_FONT))
        self.assertIsNone(image.crop((0, 8, 64, 16)).getbbox())


if __name__ == "__main__":
    unittest.main()
