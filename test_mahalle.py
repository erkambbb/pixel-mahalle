import unittest

import cairo

import mahalle as m


class TubeTest(unittest.TestCase):
    def test_rate_is_logarithmic(self):
        t = m.Tube(0, '#ffffff', 'down')
        t.set_rate(m.NET_MIN)
        self.assertEqual(t.target, 0.0)
        t.set_rate(m.NET_MAX * 10)
        self.assertEqual(t.target, 1.0)
        t.set_rate(1e5)
        self.assertAlmostEqual(t.target, 0.4)


class WorldTest(unittest.TestCase):
    def test_steps_and_draws_headless(self):
        w = m.World()
        w.metrics.cpu = 100
        w.metrics.gpu = 100
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (m.PANEL + m.W) * m.S, m.H * m.S)
        ctx = cairo.Context(surf)
        ctx.scale(m.S, m.S)
        for _ in range(600):
            w.step()
            w.draw(ctx)
        self.assertTrue(any(p.kind == 'pedestrian' for p in w.people))
        self.assertEqual(set(w.layers), {'shelf', 'houses', 'ground', 'road', 'lamps'})


if __name__ == '__main__':
    unittest.main()
