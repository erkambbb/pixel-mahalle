import unittest

import cairo

import datetime

import hava
import mahalle as m
import piksel_font as pf
import saat


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
        self.assertEqual(set(w.layers), {'shelf', 'houses', 'ground', 'road', 'lamps', 'moon'})


class WeatherTest(unittest.TestCase):
    def test_every_forced_weather_steps_and_draws(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (m.PANEL + m.W) * m.S, m.H * m.S)
        for name in hava.FORCE:
            w = m.World(hava.Weather(force=name, fetch=False))
            w.metrics.cpu = 60
            for _ in range(300):
                w.step()
                w.draw(cairo.Context(surf))
            if w.weather.rain:
                self.assertTrue(w.drops, name)
            if w.weather.snow:
                self.assertTrue(w.flakes, name)

    def test_unknown_code_falls_back_to_nearest(self):
        wx = hava.Weather(fetch=False)
        wx.code = 64
        self.assertIn(wx.label, ('YAĞMURLU', 'ŞİDDETLİ YAĞMUR'))


class MoonTest(unittest.TestCase):
    def test_known_full_moon(self):
        full = datetime.datetime(2024, 1, 25, 17, 54, tzinfo=datetime.timezone.utc).timestamp()
        self.assertAlmostEqual(m.moon_phase(full), 0.5, delta=0.02)


class FontTest(unittest.TestCase):
    def test_glyphs_are_rectangular(self):
        for ch, rows in pf._G.items():
            rows = rows.split()
            self.assertEqual(len(rows), pf.BASE, ch)
            self.assertEqual(len(set(map(len, rows))), 1, ch)

    def test_turkish_text_has_marks(self):
        cells, width = pf.layout('Çarşamba ağustos İ')
        self.assertTrue(any(r < 0 for _, r in cells))
        self.assertTrue(any(r >= pf.BASE for _, r in cells))
        self.assertGreater(width, 0)

    def test_clock_draws(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, saat.WIDTH, saat.HEIGHT)
        saat.draw_clock(cairo.Context(surf), datetime.datetime(2026, 8, 19, 23, 59, 59), None)


if __name__ == '__main__':
    unittest.main()
