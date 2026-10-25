import time
import random
from display_utils import FramePacer

# --- LOGICAL DIMENSIONS ---
WIDTH = 64
HEIGHT = 16 
BALL_SPEED = 1.2
PARTICLE_GRAVITY = 0.10
PARTICLE_SPEED_RANGE = (0.2, 0.5)

# --- STATES ---
STATE_PLAYING = 1
STATE_EXPLODING = 2
STATE_WAITING = 3

class PongPhysics:
    def __init__(self):
        self.state = STATE_PLAYING
        
        # Paddles
        self.left_y = 6.0 
        self.right_y = 6.0
        
        # Ball
        self.ball_x = 32.0
        self.ball_y = 8.0
        self.vel_x = 0
        self.vel_y = 0
        
        # Particles
        self.particles = []
        self.exploded_paddle = None
        self.wait_start_time = 0
        
        self.reset_ball()

    def reset_ball(self):
        self.state = STATE_PLAYING
        self.ball_x = 32.0
        self.ball_y = random.randint(4, 12)
        self.exploded_paddle = None
        
        direction = random.choice([-1, 1])
        self.vel_x = direction * BALL_SPEED
        self.vel_y = random.uniform(-0.6, 0.6)

    def trigger_explosion(self, side):
        self.state = STATE_EXPLODING
        self.exploded_paddle = side
        self.particles = []
        
        # Determine spawn point
        start_x = 0 if side == 'LEFT' else 63
        start_y = self.left_y if side == 'LEFT' else self.right_y
        
        # Create debris
        for _ in range(10):
            self.particles.append({
                'x': float(start_x + random.randint(-1, 1)),
                'y': float(start_y + random.randint(0, 4)), 
                # Keep the debris near the paddle during the longer, softer arc.
                'vx': random.uniform(*PARTICLE_SPEED_RANGE) * (1 if side == 'LEFT' else -1),
                'vy': random.uniform(-0.8, 0.5) # Up/Down spread
            })

    def update_particles(self):
        bounce = 0.5        # Retains half the vertical velocity after impact.
        friction = 0.8      # Floor friction (0.8 = slows down sideways)
        
        all_stopped = True
        
        for p in self.particles:
            # Apply Physics
            p['vy'] += PARTICLE_GRAVITY
            p['x'] += p['vx']
            p['y'] += p['vy']
            
            # --- FLOOR COLLISION ---
            if p['y'] >= HEIGHT - 1:
                p['y'] = HEIGHT - 1 # Clamp to floor
                
                # Bounce if moving fast enough
                if abs(p['vy']) > 0.4:
                    p['vy'] = -p['vy'] * bounce
                    p['vx'] *= friction # Apply friction on impact
                else:
                    # Stop bouncing, just roll/slide
                    p['vy'] = 0
                    p['vx'] *= friction # Apply heavy friction rolling
            
            # Check if this particle is still moving significantly
            if abs(p['vx']) > 0.05 or abs(p['vy']) > 0.05:
                all_stopped = False

        # If all particles have settled, start the existing two-second pause.
        if all_stopped:
            self.state = STATE_WAITING
            self.wait_start_time = time.time()

    def get_ai_move(self, current_y, ball_y, ball_x, ball_vel_x, is_left_paddle):
        target_y = 6.0
        should_engage = False
        
        if is_left_paddle:
            if ball_vel_x < 0 and ball_x < 20: should_engage = True
        else:
            if ball_vel_x > 0 and ball_x > 44: should_engage = True

        if should_engage:
            target_y = ball_y - 2.0

        if abs(current_y - target_y) < 0.8: return current_y

        if current_y < target_y: current_y += 1.0
        elif current_y > target_y: current_y -= 1.0
            
        return max(0.0, min(12.0, current_y))

    def update(self):
        # 1. PLAYING STATE
        if self.state == STATE_PLAYING:
            self.ball_x += self.vel_x
            self.ball_y += self.vel_y

            # Wall Bounces
            if self.ball_y <= 0:
                self.ball_y = 0
                self.vel_y = abs(self.vel_y)
            elif self.ball_y >= HEIGHT - 1:
                self.ball_y = HEIGHT - 1
                self.vel_y = -abs(self.vel_y)

            # Paddle Collisions
            if self.ball_x <= 1:
                if self.left_y - 1 <= self.ball_y <= self.left_y + 4:
                    self.ball_x = 1 
                    self.vel_x = abs(self.vel_x) 
                    self.vel_y += (self.ball_y - (self.left_y + 2)) * 0.5
                else:
                    self.trigger_explosion('LEFT')

            elif self.ball_x >= WIDTH - 2:
                if self.right_y - 1 <= self.ball_y <= self.right_y + 4:
                    self.ball_x = WIDTH - 2
                    self.vel_x = -abs(self.vel_x) 
                    self.vel_y += (self.ball_y - (self.right_y + 2)) * 0.5
                else:
                    self.trigger_explosion('RIGHT')

            # AI
            self.left_y = self.get_ai_move(self.left_y, self.ball_y, self.ball_x, self.vel_x, True)
            self.right_y = self.get_ai_move(self.right_y, self.ball_y, self.ball_x, self.vel_x, False)

        # 2. EXPLODING STATE (Physics active)
        elif self.state == STATE_EXPLODING:
            self.update_particles()
            
        # 3. WAITING STATE (Static Rubble)
        elif self.state == STATE_WAITING:
            if time.time() - self.wait_start_time > 2.0:
                self.reset_ball()

    def render_serpentine(self, device_draw):
        # Draw Paddles (Unless exploded)
        if not (self.exploded_paddle == 'LEFT'):
            ly = int(round(self.left_y))
            for i in range(4): self.draw_pixel(device_draw, 0, ly + i)

        if not (self.exploded_paddle == 'RIGHT'):
            ry = int(round(self.right_y))
            for i in range(4): self.draw_pixel(device_draw, 63, ry + i)

        # Draw Ball (Only if playing)
        if self.state == STATE_PLAYING:
            self.draw_pixel(device_draw, int(self.ball_x), int(self.ball_y))

        # --- MODIFIED PART STARTS HERE ---

        # 1. If Exploding: Draw particles normally (solid)
        if self.state == STATE_EXPLODING:
            for p in self.particles:
                if 0 <= p['x'] < WIDTH and 0 <= p['y'] < HEIGHT:
                    self.draw_pixel(device_draw, int(p['x']), int(p['y']))

        # 2. If Waiting: Blink the particles
        elif self.state == STATE_WAITING:
            # The '* 5' controls the blink speed. Higher = Faster.
            # This checks if the current split-second is even or odd.
            if int(time.time() * 3) % 2 == 0:
                for p in self.particles:
                    if 0 <= p['x'] < WIDTH and 0 <= p['y'] < HEIGHT:
                        self.draw_pixel(device_draw, int(p['x']), int(p['y']))

    def draw_pixel(self, draw, x, y):
        phys_x = x
        phys_y = y
        if y < 8:
            phys_x = x
            phys_y = y
        elif y >= 8:
            phys_x = 64 + (63 - x)
            phys_y = 7 - (y - 8)
        if phys_x < 128:
            draw.point((phys_x, phys_y), fill="white")

def main():
    # Keep importing PongPhysics safe for desktop previews and tests.
    from luma.core.interface.serial import spi, noop
    from luma.led_matrix.device import max7219
    from luma.core.render import canvas

    serial = spi(port=0, device=0, gpio=noop())
    device = max7219(serial, cascaded=16, block_orientation=-90, rotate=0)
    device.contrast(16)
    game = PongPhysics()
    print("Starting Physics Pong...")
    pacer = FramePacer(25)
    try:
        while True:
            game.update()
            with canvas(device) as draw:
                game.render_serpentine(draw)
            pacer.wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
