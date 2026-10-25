from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from acid_rain import AcidRain, GLYPHS, GLYPH_HEIGHT, GLYPH_PITCH, HEIGHT, STREAM_COUNT


class AcidRainTests(unittest.TestCase):
    def test_monochrome_code_is_visible_and_evolves(self):
        effect = AcidRain()
        first = effect.render(0, 0)
        self.assertEqual(first.mode, "1")
        self.assertEqual(first.size, (64, 16))
        self.assertIsNotNone(first.getbbox())
        later = effect.render(0.2, 0.2)
        self.assertIsNotNone(later.getbbox())
        self.assertNotEqual(first.tobytes(), later.tobytes())

    def test_leading_character_is_a_complete_tiny_digit(self):
        effect = AcidRain()
        for stream in effect.streams:
            stream.y = -100
        stream = effect.streams[0]
        stream.y = 0
        stream.glyphs = (GLYPHS[0], GLYPHS[1])
        image = effect.render(0, 0)
        self.assertEqual(image.getbbox(), (0, 0, 3, GLYPH_HEIGHT))
        self.assertEqual([[int(image.getpixel((x, y)) > 0) for x in range(3)] for y in range(5)],
                         [[1, 1, 1], [1, 0, 1], [1, 0, 1], [1, 0, 1], [1, 1, 1]])

    def test_tempo_does_not_depend_on_render_rate(self):
        frames = []
        for fps in (20, 40):
            effect = AcidRain(seed=90)
            for step in range(fps * 2):
                frame = effect.render((step + 1) / fps, 1 / fps)
            frames.append(frame.tobytes())
        self.assertEqual(frames[0], frames[1])

    def test_streams_keep_recycling_with_bounded_glyphs(self):
        effect = AcidRain(seed=7219)
        previous = [stream.y for stream in effect.streams]
        resets = 0
        for step in range(1200):
            image = effect.render((step + 1) / 20, 1 / 20)
            resets += sum(stream.y < old for stream, old in zip(effect.streams, previous))
            previous = [stream.y for stream in effect.streams]
            self.assertEqual(len(effect.streams), STREAM_COUNT)
            self.assertTrue(all(2 <= len(stream.glyphs) <= 4 for stream in effect.streams))
            self.assertLessEqual(sum(len(stream.glyphs) for stream in effect.streams), 64)
        self.assertGreater(resets, STREAM_COUNT * 5)
        self.assertIsNotNone(image.getbbox())

    def test_code_leaves_no_pixels_after_its_trailing_glyph_exits(self):
        effect = AcidRain()
        for stream in effect.streams:
            stream.y = HEIGHT + (len(stream.glyphs) - 1) * GLYPH_PITCH
        self.assertIsNone(effect.render(0, 0).getbbox())
        # Recycling starts entirely above the panel, rather than adding a floor effect.
        self.assertIsNone(effect.render(0.025, 0.025).getbbox())
        self.assertTrue(all(stream.y <= -GLYPH_HEIGHT for stream in effect.streams))

    def test_a_long_pause_does_not_fast_forward_the_streams(self):
        effect = AcidRain()
        before = [stream.y for stream in effect.streams]
        effect.render(1000, 1000)
        self.assertTrue(all(0 <= stream.y - old <= 2.26
                            for stream, old in zip(effect.streams, before)))
        self.assertLess(effect.pending, 0.025)


if __name__ == "__main__":
    unittest.main()
