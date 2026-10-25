import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from pong_explode2 import (
    BALL_SPEED, HEIGHT, PARTICLE_GRAVITY, PongPhysics,
    STATE_EXPLODING, STATE_WAITING,
)


class PongTuningTests(unittest.TestCase):
    def test_ball_keeps_its_direction_at_the_slower_horizontal_speed(self):
        for direction in (-1, 1):
            with self.subTest(direction=direction), patch("pong_explode2.random.choice", return_value=direction):
                game = PongPhysics()
                self.assertEqual(BALL_SPEED, 1.2)
                self.assertEqual(game.vel_x, direction * BALL_SPEED)
                game.ball_y = 8.0
                game.vel_y = 0.0
                game.update()
                self.assertAlmostEqual(game.ball_x, 32 + direction * 1.2)

    def test_fragment_uses_gentler_gravity_before_moving(self):
        game = PongPhysics()
        game.state = STATE_EXPLODING
        particle = {"x": 20.0, "y": 5.0, "vx": 0.8, "vy": -0.4}
        game.particles = [particle]
        game.update_particles()
        self.assertEqual(PARTICLE_GRAVITY, 0.10)
        self.assertAlmostEqual(particle["vy"], -0.3)
        self.assertAlmostEqual(particle["x"], 20.8)
        self.assertAlmostEqual(particle["y"], 4.7)
        self.assertEqual(game.state, STATE_EXPLODING)

    def test_floor_bounce_still_halves_vertical_velocity_and_applies_friction(self):
        game = PongPhysics()
        game.state = STATE_EXPLODING
        particle = {"x": 20.0, "y": 14.7, "vx": 0.8, "vy": 0.9}
        game.particles = [particle]
        game.update_particles()
        self.assertEqual(particle["y"], HEIGHT - 1)
        self.assertAlmostEqual(particle["vy"], -0.5)
        self.assertAlmostEqual(particle["vx"], 0.64)
        self.assertEqual(game.state, STATE_EXPLODING)

    def test_fragments_still_settle_and_begin_the_existing_pause(self):
        game = PongPhysics()
        game.state = STATE_EXPLODING
        particle = {"x": 20.0, "y": 10.0, "vx": 0.8, "vy": -0.4}
        game.particles = [particle]
        with patch("pong_explode2.time.time", return_value=123.0):
            for _ in range(200):
                game.update_particles()
                if game.state == STATE_WAITING:
                    break
        self.assertEqual(game.state, STATE_WAITING)
        self.assertEqual(game.wait_start_time, 123.0)
        self.assertEqual(particle["y"], HEIGHT - 1)
        self.assertEqual(particle["vy"], 0)
        self.assertLessEqual(abs(particle["vx"]), 0.05)


if __name__ == "__main__":
    unittest.main()
