"""Pure, frame-stepped erase/loading/reveal transitions for the folded board."""

from enum import Enum

from PIL import Image, ImageChops, ImageDraw

from display_utils import map_serpentine

SWEEP_STEPS = 68
SWEEP_SECONDS = SWEEP_STEPS / 30
FRAME_SECONDS = SWEEP_SECONDS / SWEEP_STEPS


class Phase(str, Enum):
    ERASE = "erase"
    LOADING = "loading"
    REVEAL = "reveal"
    DONE = "done"


_BLACK = Image.new("1", (128, 8), 0)
_WHITE = Image.new("1", (128, 8), 1)
_EVEN_EDGE = Image.frombytes("1", (1, 16), bytes((0x80, 0)) * 8)
_ODD_EDGE = Image.frombytes("1", (1, 16), bytes((0, 0x80)) * 8)


def _bar(step):
    image = Image.new("1", (64, 16), 0)
    x = step - 3
    ImageDraw.Draw(image).rectangle((x, 0, x + 2, 15), fill=1)
    image.paste(_EVEN_EDGE, (x - 1, 0))
    image.paste(_ODD_EDGE, (x + 3, 0))
    return image


def _left_mask(step):
    boundary = max(0, min(64, step - 3))
    mask = _BLACK.copy()
    if boundary:
        # The lower logical row runs backwards in the right physical half.
        mask.paste(1, (0, 0, boundary, 8))
        mask.paste(1, (128 - boundary, 0, 128, 8))
    return mask


# These small immutable-by-convention frames keep preparation out of the tick.
_BARS = tuple(_bar(step) for step in range(SWEEP_STEPS))
_PHYSICAL_BARS = tuple(map_serpentine(image) for image in _BARS)
_LEFT_MASKS = tuple(_left_mask(step) for step in range(SWEEP_STEPS))
_RIGHT_MASKS = tuple(ImageChops.logical_xor(mask, _WHITE) for mask in _LEFT_MASKS)


def render_bar(step):
    """Return one logical bar position, from x=-3 through x=64 inclusive."""
    if not isinstance(step, int) or not 0 <= step < SWEEP_STEPS:
        raise ValueError("Bar step must be an integer from 0 through 67")
    return _BARS[step].copy()


def _copy_frame(image):
    if not isinstance(image, Image.Image) or image.mode != "1" or image.size != (128, 8):
        raise ValueError("Transition frames must be monochrome 128x8 images")
    return image.copy()


class Transition:
    def __init__(self, outgoing, off=False):
        self._outgoing = _copy_frame(outgoing)
        self._incoming = None
        self._target = None
        self._off = bool(off)
        self._cancelled = False
        self.phase = Phase.ERASE
        self.step = 0

    @property
    def done(self):
        return self.phase is Phase.DONE

    def offer_frame(self, image):
        frame = _copy_frame(image)
        if not self._off and not self._cancelled and self.phase in (Phase.ERASE, Phase.LOADING):
            self._incoming = frame

    def cancel(self):
        """Finish the current pass, then leave the board black."""
        self._cancelled = True
        self._incoming = None

    def image(self):
        if self.done:
            target = None if self._off or self._cancelled else self._target
            return target.copy() if target is not None else _BLACK.copy()
        bar = _PHYSICAL_BARS[self.step]
        if self.phase is Phase.LOADING:
            return bar.copy()
        if self.phase is Phase.ERASE:
            content = ImageChops.logical_and(self._outgoing, _RIGHT_MASKS[self.step])
        else:
            content = ImageChops.logical_and(self._target, _LEFT_MASKS[self.step])
        return ImageChops.logical_or(content, bar)

    def advance(self):
        """Move exactly one column; readiness changes phase only at wraparound."""
        if self.done:
            return
        if self.step < SWEEP_STEPS - 1:
            self.step += 1
            return
        if self._off or self._cancelled:
            self.phase = Phase.DONE
        elif self.phase is Phase.REVEAL:
            self.phase = Phase.DONE
        elif self._incoming is not None:
            # Later producer updates must not change pixels halfway through a wipe.
            self._target = self._incoming.copy()
            self.phase = Phase.REVEAL
        else:
            self.phase = Phase.LOADING
        if not self.done:
            self.step = 0
