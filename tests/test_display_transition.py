from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from display_transition import FRAME_SECONDS, Phase, SWEEP_SECONDS, SWEEP_STEPS, Transition, render_bar
from display_utils import map_serpentine


def physical(image):
    return map_serpentine(image)


def finish_pass(transition):
    for _ in range(SWEEP_STEPS - transition.step):
        transition.advance()


class BarTests(unittest.TestCase):
    def test_every_column_position_has_a_visible_bar_and_moves_one_column(self):
        self.assertEqual(SWEEP_STEPS, 68)
        self.assertAlmostEqual(FRAME_SECONDS * SWEEP_STEPS, SWEEP_SECONDS)
        previous = None
        for step in range(SWEEP_STEPS):
            bar = render_bar(step)
            self.assertEqual((bar.mode, bar.size), ("1", (64, 16)))
            self.assertIsNotNone(bar.getbbox())
            x = step - 3
            if previous is not None:
                self.assertEqual(x - previous, 1)
            previous = x
            for column in range(max(0, x), min(64, x + 3)):
                self.assertEqual(list(bar.crop((column, 0, column + 1, 16)).getdata()), [1] * 16)
        self.assertEqual(render_bar(0).getbbox(), (0, 1, 1, 16))
        self.assertEqual(render_bar(67).getbbox(), (63, 0, 64, 15))

    def test_bar_returns_copies_and_rejects_invalid_positions(self):
        image = render_bar(30)
        expected = image.tobytes()
        image.paste(0, (0, 0, 64, 16))
        self.assertEqual(render_bar(30).tobytes(), expected)
        for step in (-1, 68, 1.5, "1"):
            with self.subTest(step=step), self.assertRaises(ValueError):
                render_bar(step)


class TransitionTests(unittest.TestCase):
    def test_all_phases_use_identical_bar_frames_without_skipping_columns(self):
        blank = Image.new("1", (128, 8), 0)
        transition = Transition(blank)
        observed = []
        for phase in (Phase.ERASE, Phase.LOADING, Phase.REVEAL):
            if phase is Phase.LOADING:
                transition.offer_frame(blank)
            for step in range(SWEEP_STEPS):
                self.assertEqual((transition.phase, transition.step), (phase, step))
                self.assertEqual(transition.image().tobytes(), physical(render_bar(step)).tobytes())
                observed.append((phase, step))
                transition.advance()
        self.assertTrue(transition.done)
        self.assertEqual(transition.phase, Phase.DONE)
        self.assertIsNone(transition.image().getbbox())
        transition.advance()
        self.assertTrue(transition.done)
        self.assertEqual(len(observed), SWEEP_STEPS * 3)

    def test_offer_during_loading_waits_for_the_next_complete_boundary(self):
        transition = Transition(Image.new("1", (128, 8), 0))
        finish_pass(transition)
        self.assertEqual((transition.phase, transition.step), (Phase.LOADING, 0))
        for _ in range(17):
            transition.advance()
        target = Image.new("1", (128, 8), 1)
        before = transition.image().tobytes()
        transition.offer_frame(target)
        self.assertEqual((transition.phase, transition.step), (Phase.LOADING, 17))
        self.assertEqual(transition.image().tobytes(), before)
        for _ in range(SWEEP_STEPS - 1 - transition.step):
            transition.advance()
        self.assertEqual((transition.phase, transition.step), (Phase.LOADING, 67))
        transition.advance()
        self.assertEqual((transition.phase, transition.step), (Phase.REVEAL, 0))

    def test_content_masks_cover_matching_logical_columns_on_both_rows(self):
        logical = Image.new("1", (64, 16), 1)
        transition = Transition(physical(logical))
        transition.offer_frame(physical(logical))
        for phase in (Phase.ERASE, Phase.REVEAL):
            for step in range(SWEEP_STEPS):
                self.assertEqual((transition.phase, transition.step), (phase, step))
                if step in (0, 3, 4, 32, 66, 67):
                    frame, bar = transition.image(), render_bar(step)
                    boundary = max(0, min(64, step - 3))
                    for y in range(16):
                        for x in range(64):
                            point = (x, y) if y < 8 else (127 - x, 15 - y)
                            visible = x >= boundary if phase is Phase.ERASE else x < boundary
                            self.assertEqual(bool(frame.getpixel(point)), visible or bool(bar.getpixel((x, y))))
                transition.advance()
        self.assertTrue(transition.done)
        self.assertEqual(transition.image().tobytes(), physical(logical).tobytes())

    def test_latest_candidate_is_copied_then_frozen_for_the_entire_reveal(self):
        outgoing = Image.new("1", (128, 8), 1)
        transition = Transition(outgoing)
        original = transition.image().tobytes()
        outgoing.paste(0, (0, 0, 128, 8))
        self.assertEqual(transition.image().tobytes(), original)
        first = Image.new("1", (128, 8), 0)
        first.putpixel((2, 1), 1)
        target = Image.new("1", (128, 8), 0)
        target.putpixel((70, 6), 1)
        expected = target.tobytes()
        transition.offer_frame(first)
        transition.offer_frame(target)
        target.paste(0, (0, 0, 128, 8))
        finish_pass(transition)
        self.assertEqual(transition.phase, Phase.REVEAL)
        for _ in range(10):
            transition.advance()
        unchanged = transition.image().tobytes()
        transition.offer_frame(Image.new("1", (128, 8), 1))
        self.assertEqual(transition.image().tobytes(), unchanged)
        finish_pass(transition)
        self.assertTrue(transition.done)
        self.assertEqual(transition.image().tobytes(), expected)
        transition.image().paste(0, (0, 0, 128, 8))
        self.assertEqual(transition.image().tobytes(), expected)

    def test_off_and_cancellation_finish_the_current_pass_then_leave_black(self):
        full = Image.new("1", (128, 8), 1)
        off = Transition(full, off=True)
        off.offer_frame(full)
        finish_pass(off)
        self.assertTrue(off.done)
        self.assertIsNone(off.image().getbbox())
        for phase in (Phase.ERASE, Phase.LOADING, Phase.REVEAL):
            with self.subTest(phase=phase):
                transition = Transition(full)
                if phase is Phase.LOADING:
                    finish_pass(transition)
                elif phase is Phase.REVEAL:
                    transition.offer_frame(full)
                    finish_pass(transition)
                for _ in range(9):
                    transition.advance()
                transition.cancel()
                self.assertEqual(transition.phase, phase)
                self.assertFalse(transition.done)
                finish_pass(transition)
                self.assertTrue(transition.done)
                self.assertIsNone(transition.image().getbbox())

    def test_frame_format_is_validated_even_for_blank_candidates(self):
        blank = Image.new("1", (128, 8), 0)
        transition = Transition(blank)
        invalid = (None, "pixels", Image.new("1", (64, 16)), Image.new("RGB", (128, 8)))
        for image in invalid:
            with self.subTest(image=type(image).__name__):
                with self.assertRaises(ValueError):
                    Transition(image)
                with self.assertRaises(ValueError):
                    transition.offer_frame(image)
        transition.offer_frame(blank)
        finish_pass(transition)
        self.assertEqual(transition.phase, Phase.REVEAL)


if __name__ == "__main__":
    unittest.main()
