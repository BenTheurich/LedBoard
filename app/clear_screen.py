from luma.core.interface.serial import spi, noop
from luma.led_matrix.device import max7219
from luma.core.render import canvas

# Hard Reset
serial = spi(port=0, device=0, gpio=noop())
device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)

# Flush completely
with canvas(device) as draw:
    draw.rectangle(device.bounding_box, fill="black")
