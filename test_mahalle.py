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
        fired = False
        for _ in range(900):
            w.step()
            w.draw(cairo.Context(surf))
            fired = fired or bool(w.sparks)
        self.assertGreater(w.sleep, 0.9)
        self.assertTrue(w.event.fireworks)
        self.assertTrue(fired)


class WideTest(unittest.TestCase):
    def test_full_width_layout_with_tower(self):
        houses, trees, lamps, puddles, tower = m.layout(452)
        self.assertIsNotNone(tower)
        for h in houses:   # evler sahneye sığar ve kuleyle çakışmaz
            self.assertLessEqual(h['x'] + h['w'], 452)
            self.assertFalse(h['x'] < tower + m.TOWER_W and h['x'] + h['w'] > tower)
        self.assertIsNone(m.layout(220)[4])

    def test_tower_rings_on_the_hour(self):
        old = m.W
        m.W = 452
        try:
            w = m.World(hava.Weather(fetch=False), sistem.System(music=False),
                        clock=lambda: datetime.datetime(2026, 11, 3, 21, 0, 2))
            w.step()
            self.assertEqual(w.ring_hour, 21)
            self.assertTrue(w.birds)
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (m.PANEL + m.W) * m.S, m.H * m.S)
            w.draw(cairo.Context(surf))
            self.assertIn('tower', w.layers)
        finally:
            m.W = old


class FakeBacklight:
    ok, level = True, 0.0

    def set(self, frac):
        self.level = frac

    def update(self):
        pass


class SunTest(unittest.TestCase):
    def setUp(self):
        self.old_w = m.W
        m.W = 452
        sysm = sistem.System(music=False, backlight=False)
        sysm.backlight = FakeBacklight()
        self.w = m.World(hava.Weather(fetch=False), sysm, clock=lambda: datetime.datetime(2026, 11, 8, 14, 0, 30))
        self.surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (m.PANEL + m.W) * m.S, m.H * m.S)

    def tearDown(self):
        m.W = self.old_w

    def drag_to(self, x):
        w = self.w
        sx, sy = w.sun_xy()
        self.assertTrue(w.sun_hit(sx, sy))
        w.sun_grab(sx)
        w.sun_move(x)
        w.draw(cairo.Context(self.surf))
        w.sun_release()

    def test_drag_sets_brightness_and_daylight(self):
        w = self.w
        self.assertEqual(w.light, 0.0)          # parlaklık 0: gece
        self.drag_to(m.W + 50)                  # en sağ: gündüz, parlaklık %100
        self.assertEqual(w.system.backlight.level, 1.0)
        for _ in range(40):
            w.step()
            w.draw(cairo.Context(self.surf))
        self.assertEqual(w.light, 1.0)
        self.assertLess(w.sun_xy()[1], m.SUN_LOW)
        self.drag_to(-50)                       # en sol: gece, parlaklık %0
        self.assertEqual(w.system.backlight.level, 0.0)
        for _ in range(40):
            w.step()
        self.assertEqual(w.light, 0.0)
        self.assertIn('sunhalo', w.layers)

    def test_sun_follows_brightness_keys(self):
        w = self.w
        w.system.backlight.level = 0.7          # parlaklık tuşla değişti
        w.update_light()
        self.assertEqual(w.sun, 0.7)
        self.assertGreater(w.sun_label, 0)
        for _ in range(40):
            w.step()
        self.assertAlmostEqual(w.light, 0.7)
        self.assertAlmostEqual(w.sun_u, 0.7)

    def test_sun_by_tower_is_drawn(self):
        w = self.w
        self.drag_to(w.tower + m.TOWER_W / 2)
        self.assertTrue(w.sun_by_tower())


class BacklightTest(unittest.TestCase):
    def test_floor_and_mapping(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            d = os.path.join(root, 'panel')
            os.mkdir(d)
            for name, value in (('type', 'raw'), ('max_brightness', '100'), ('brightness', '5')):
                with open(os.path.join(d, name), 'w') as f:
                    f.write(value)
            bl = sistem.Backlight(root)
            self.assertEqual((bl.name, bl.min), ('panel', 5))
            self.assertEqual(bl.level, 0.0)     # en kısık güvenli seviye = %0
            sent = []
            bl._send = lambda: sent.append(bl._want)
            bl.set(1.0)
            self.assertEqual(sent, [100])
            bl.set(0.0)
            self.assertEqual(sent, [100, 5])     # ekran tamamen kararmaz
        self.assertFalse(sistem.Backlight(None).ok)


class ClockGaugeTest(unittest.TestCase):
    def test_clock_with_gpu_and_temps(self):
        w = m.World()
        w.metrics.gpu_ok, w.metrics.gpu, w.metrics.gpu_temp = True, 55, 61.0
        w.system.disk_temp = 38.0
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, saat.WIDTH, saat.HEIGHT)
        saat.draw_clock(cairo.Context(surf), datetime.datetime(2026, 11, 8, 14, 7, 30), w)
        self.assertEqual(saat._temp_color(30, 45, 85), saat.GREEN)

    def test_music_buttons(self):
        w = m.World()
        mu = w.system.music
        mu.title, mu.artist, mu.playing, mu.player = 'Şarkı', 'Sanatçı', True, 'org.mpris.MediaPlayer2.test'
        sent = []
        mu.command = sent.append
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, saat.WIDTH, saat.HEIGHT)
        ui = {'hover': 'Next', 'flash': ('PlayPause', 0.0)}
        saat.draw_clock(cairo.Context(surf), datetime.datetime(2026, 11, 8, 14, 7, 30), w, ui=ui)
        self.assertEqual(set(ui['rects']), {'Previous', 'PlayPause', 'Next'})
        mu.playing = False
        saat.draw_clock(cairo.Context(surf), datetime.datetime(2026, 11, 8, 14, 7, 30), w, ui=ui)
        self.assertEqual(ui['rects'], {})     # çalmıyor ve duraklatılmamış: düğme yok
        self.assertIsInstance(cairo.Region([]), cairo.Region)
        self.assertEqual(saat._temp_color(99, 45, 85), saat.RED)


if __name__ == '__main__':
    unittest.main()
