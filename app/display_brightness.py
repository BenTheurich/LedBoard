"""The board-wide schedule inherited from the original bus display."""

from datetime import datetime


BRIGHTNESS_DAY = 32
BRIGHTNESS_NIGHT = 10
HOUR_DAY_START = 7
HOUR_NIGHT_START = 20


def brightness_for_time(now=None):
    """Use the Pi's local time; Luma maps 0–255 onto 16 hardware levels."""
    now = datetime.now() if now is None else now
    return BRIGHTNESS_DAY if HOUR_DAY_START <= now.hour < HOUR_NIGHT_START else BRIGHTNESS_NIGHT
