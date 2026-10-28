import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from display_utils import map_serpentine
from drawing import DrawingDisplay, validate_pixels


class DrawingTests(unittest.TestCase):
    def test_row_major_pixels_keep_their_orientation_on_both_matrix_rows(self):
        points = {(0, 0), (63, 0), (0, 7), (0, 8), (10, 10), (63, 15)}
        pixels = "".join("1" if (x, y) in points else "0"
                         for y in range(16) for x in range(64))
        display = DrawingDisplay(pixels)
        image = display.render(0, 0)
        self.assertEqual(image.mode, "1")
        self.assertEqual(image.size, (64, 16))
        self.assertEqual({(x, y) for y in range(16) for x in range(64)
                          if image.getpixel((x, y))}, points)
        self.assertEqual(image.tobytes(), display.render(100, 1).tobytes())
        physical = map_serpentine(image)
        expected = {(x, y) if y < 8 else (127 - x, 15 - y) for x, y in points}
        self.assertEqual({(x, y) for y in range(8) for x in range(128)
                          if physical.getpixel((x, y))}, expected)

    def test_blank_and_fully_lit_images_are_valid(self):
        self.assertIsNone(DrawingDisplay("0" * 1024).render(0, 0).getbbox())
        self.assertEqual(DrawingDisplay("1" * 1024).render(0, 0).getbbox(), (0, 0, 64, 16))

    def test_wrong_sizes_and_non_binary_values_are_rejected(self):
        for value in (None, [0] * 1024, "", "0" * 1023, "0" * 1025,
                      "0" * 1023 + "2", "0" * 1023 + "\n", "0" * 1023 + "０"):
            with self.subTest(value=repr(value)[:60]), self.assertRaises(ValueError):
                validate_pixels(value)


if __name__ == "__main__":
    unittest.main()
