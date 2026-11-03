import unittest

import cairo

import datetime

import hava
import mahalle as m
import piksel_font as pf
import saat
import sistem
import takvim


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
        self.assertLessEqual({'shelf', 'houses', 'ground', 'road', 'lamps'}, set(w.layers))


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


class CalendarTest(unittest.TestCase):
    def test_events(self):
        dt = datetime.datetime
        self.assertEqual(takvim.event(dt(2026, 10, 29, 21)).kind, 'flags')
        self.assertTrue(takvim.event(dt(2026, 10, 29, 21)).fireworks)
        self.assertEqual(takvim.event(dt(2026, 11, 10, 9)).kind, 'halfmast')
        self.assertEqual(takvim.event(dt(2026, 12, 25, 9)).text, 'YENİ YILA 7 GÜN')
        self.assertEqual(takvim.event(dt(2026, 5, 28, 9)).kind, 'bayram')
        self.assertEqual(takvim.event(dt(2026, 5, 14, 9), birthday=(14, 5)).kind, 'birthday')
        self.assertIsNone(takvim.event(dt(2026, 11, 3, 9)))
        self.assertTrue(takvim.market(dt(2026, 11, 6, 18)))

    def test_sun_times_yalova(self):
        rise, set_ = takvim.sun_times(datetime.date(2026, 6, 21))
        self.assertEqual((rise.hour, set_.hour), (5, 20))


class LifeTest(unittest.TestCase):
    def test_sleep_dims_and_specials_walk(self):
        sysm = sistem.System(music=False)
        upd = sysm.update
        sysm.update = lambda: (upd(), setattr(sysm, 'idle_s', 10_000))
        w = m.World(hava.Weather(fetch=False), sysm, clock=lambda: datetime.datetime(2026, 12, 31, 23, 55))
        for kind, run in (('simitci', w.run_simitci), ('bozaci', w.run_bozaci), ('late', w.run_late)):
            p = m.Person()
            p.kind, p.script = kind, run(p)
            w.people.append(p)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (m.PANEL + m.W) * m.S, m.H * m.S)
        for _ in range(900):
            w.step()
            w.draw(cairo.Context(surf))
        self.assertGreater(w.sleep, 0.9)
        self.assertTrue(w.event.fireworks)
        self.assertTrue(w.sparks or w.rockets)


if __name__ == '__main__':
    unittest.main()
