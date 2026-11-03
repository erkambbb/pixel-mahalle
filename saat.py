"""Ekranın ortasında duran büyük piksel saat: tarih, özel gün, Yalova havası, çalan şarkı ve sistem göstergeleri."""
import datetime
import math
import time

import cairo
from gi.repository import Gdk, GLib, Gtk

import piksel_font as pf
import takvim

MONTHS = ('OCAK', 'ŞUBAT', 'MART', 'NİSAN', 'MAYIS', 'HAZİRAN', 'TEMMUZ', 'AĞUSTOS',
          'EYLÜL', 'EKİM', 'KASIM', 'ARALIK')
DAYS = ('PAZARTESİ', 'SALI', 'ÇARŞAMBA', 'PERŞEMBE', 'CUMA', 'CUMARTESİ', 'PAZAR')

TIME_U, DATE_U, INFO_U, SMALL_U = 14, 4, 3, 2     # her yazı pikselinin ekran boyutu
WIDTH, HEIGHT = 720, 400
TIME_Y = 28
SEGS, SEG_W, SEG_H, SEG_GAP = 14, 12, 5, 2        # dikey LED göstergeler


def rgb(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


AMBER, CREAM, MIST, MUSIC = rgb('#ffc857'), rgb('#e9dfcf'), rgb('#9fb3c8'), rgb('#c9a7ff')
GREEN, RED = rgb('#3ddc97'), rgb('#ff5a4f')
SUN, MOON, CLOUD, DARK, DROP, SNOW = (rgb(c) for c in (
    '#ffd34d', '#f4f1de', '#c9d2dd', '#7d8796', '#5dade2', '#ffffff'))

_CLOUD = ('....##.....', '..######...', '.#########.', '###########', '.#########.')
_BOLT = ('..##', '.##.', '####', '.##.', '##..', '#...')


def mix(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def _cloud(dy, color):
    return [(x, y + dy, color) for y, row in enumerate(_CLOUD) for x, v in enumerate(row)
            if v == '#' and 0 <= y + dy < 9]


def icon(kind, is_day):
    """11x9 hava simgesi: [(x, y, renk), ...]."""
    if is_day:
        sky = [(x, y, SUN) for y in range(9) for x in range(11)
               if (x - 5) ** 2 + (y - 4) ** 2 <= 6.5]
        sky += [(x, y, SUN) for x, y in ((5, 0), (5, 8), (1, 4), (9, 4), (2, 1), (8, 1), (2, 7), (8, 7))]
    else:
        sky = [(x, y, MOON) for y in range(9) for x in range(11)
               if (x - 5) ** 2 + (y - 4) ** 2 <= 16.5 and (x - 7) ** 2 + (y - 3) ** 2 > 10]
    if kind == 'clear':
        return sky
    if kind == 'partly':
        return sky + _cloud(4, CLOUD)
    if kind == 'fog':
        return [(x, y, DARK) for y, a, b in ((1, 1, 8), (3, 2, 10), (5, 0, 7), (7, 3, 9))
                for x in range(a, b + 1)]
    if kind == 'cloudy':
        return _cloud(1, DARK) + [(x + 2, y + 1, c) for x, y, c in _cloud(2, CLOUD) if x < 9]
    base = _cloud(0, DARK)
    if kind == 'rain':
        return base + [(x, y, DROP) for x, y in ((2, 6), (5, 6), (8, 6), (1, 8), (4, 8), (7, 8))]
    if kind == 'snow':
        return base + [(x, y, SNOW) for x, y in ((2, 6), (6, 6), (9, 7), (4, 8), (0, 8))]
    return base + [(x, y, SUN) for x, y in ((6, 5), (5, 6), (6, 6), (5, 7), (4, 8))]   # fırtına


def _cells(ctx, cells, ox, oy, u, color, alpha=1.0, glow=0.0):
    gap = max(1, u // 7) if u >= 6 else 0
    for c, r in cells:
        x, y = ox + c * u, oy + r * u
        if glow:
            ctx.set_source_rgba(*color, glow)
            ctx.rectangle(x - u * 0.4, y - u * 0.4, u * 1.8 - gap, u * 1.8 - gap)
            ctx.fill()
        ctx.set_source_rgba(*color, alpha)
        ctx.rectangle(x, y, u - gap, u - gap)
        ctx.fill()


def _text(ctx, text, cx, y, u, color, alpha=0.9, turkish=True, left=None):
    """Ortalanmış (ya da left verilirse sola dayalı) yazı; genişliği piksel olarak döner."""
    cells, w = pf.layout(text, turkish=turkish)
    x = left if left is not None else cx - w * u / 2
    _cells(ctx, cells, x, y, u, color, alpha)
    return w * u


def _seg_color(i):
    k = i / (SEGS - 1)
    return mix(GREEN, AMBER, k / 0.6) if k < 0.6 else mix(AMBER, RED, (k - 0.6) / 0.4)


def _gauge(ctx, cx, frac, label, value, now_s, battery=None):
    """Dikey LED gösterge; üstte değer, altta etiket. battery: (takılı, doluyor)."""
    x = cx - SEG_W / 2
    bottom = TIME_Y + pf.BASE * TIME_U - SEG_GAP
    lit = round(max(0.0, min(1.0, frac)) * SEGS)
    plugged, charging = battery or (False, False)
    if battery:   # pil rengi seviyeye göre; dolarken dolum dalgası yukarı akar
        col = RED if frac < 0.2 else AMBER if frac < 0.5 else GREEN
        sweep = lit + int(now_s * 4) % (SEGS - lit + 1) if charging and lit < SEGS else lit
    for i in range(SEGS):
        y = bottom - (i + 1) * (SEG_H + SEG_GAP) + SEG_GAP
        c = col if battery else _seg_color(i)
        a = 1.0 if i < lit else 0.45 if battery and i < sweep else 0.08
        if i < lit:
            ctx.set_source_rgba(*c, 0.06)
            ctx.rectangle(x - 3, y - 2, SEG_W + 6, SEG_H + 4)
            ctx.fill()
        ctx.set_source_rgba(*c, a)
        ctx.rectangle(x, y, SEG_W, SEG_H)
        ctx.fill()
    if plugged and (not charging or int(now_s * 2) % 2):
        mid = TIME_Y + pf.BASE * TIME_U / 2
        for r, row in enumerate(_BOLT):
            for c, v in enumerate(row):
                if v == '#':
                    ctx.set_source_rgba(0, 0, 0, 0.6)
                    ctx.rectangle(cx - 6 + c * 3 - 1, mid - 9 + r * 3 - 1, 5, 5)
                    ctx.fill()
        for r, row in enumerate(_BOLT):
            for c, v in enumerate(row):
                if v == '#':
                    ctx.set_source_rgba(*SUN, 1)
                    ctx.rectangle(cx - 6 + c * 3, mid - 9 + r * 3, 3, 3)
                    ctx.fill()
    _text(ctx, value, cx, TIME_Y - 20, SMALL_U, CREAM, 0.8)
    _text(ctx, label, cx, TIME_Y + pf.BASE * TIME_U + 8, SMALL_U, MIST, 0.8)


def _marquee(ctx, text, x, y, u, max_w, color, now_s, turkish):
    cells, w = pf.layout(text, turkish=turkish)
    if w * u <= max_w:
        _cells(ctx, cells, x + (max_w - w * u) / 2, y, u, color, 0.9)
        return
    gap = 40
    off = (now_s * 30) % (w * u + gap)
    ctx.save()
    ctx.rectangle(x, y - pf.ASCENT * u, max_w, pf.HEIGHT * u)
    ctx.clip()
    for start in (x - off, x - off + w * u + gap):
        _cells(ctx, cells, start, y, u, color, 0.9)
    ctx.restore()


def _fmt_hours(h):
    h = max(0, round(h * 60))
    return f'{h // 60}S {h % 60:02d}DK'


def draw_clock(ctx, now, world=None, width=WIDTH):
    now_s = time.time()
    weather = world.weather if world else None
    system = world.system if world else None
    cpu = world.metrics.cpu / 100 if world else 0.0

    # ---- saat: LED matris, sönük hücreler hep görünür, iki nokta yarım saniyede bir yanar
    colon_on = now.microsecond < 500_000
    parts = [(ch, pf.glyph(ch)) for ch in now.strftime('%H:%M')]
    tw = sum(w for _, (w, _) in parts) + 2 * (len(parts) - 1)
    x0 = round((width - tw * TIME_U) / 2)
    x = x0
    for ch, (w, cells) in parts:
        ghost = cells if ch == ':' else [(c, r) for c in range(w) for r in range(pf.BASE)]
        _cells(ctx, ghost, x, TIME_Y, TIME_U, AMBER, alpha=0.07)
        if ch != ':' or colon_on:
            _cells(ctx, cells, x, TIME_Y, TIME_U, AMBER, glow=0.05)
        x += (w + 2) * TIME_U
    x1 = x - 2 * TIME_U

    # ---- iki yanda sistem göstergeleri
    if system:
        _gauge(ctx, x0 - 92, cpu, 'CPU', f'{round(cpu * 100)}', now_s)
        _gauge(ctx, x0 - 38, system.ram, 'RAM', f'{round(system.ram * 100)}', now_s)
        _gauge(ctx, x1 + 38, system.disk, 'DİSK', f'{round(system.disk * 100)}', now_s)
        bat = system.battery
        if bat.level is not None:
            _gauge(ctx, x1 + 92, bat.level / 100, 'ŞARJ' if bat.plugged else 'PİL', f'{bat.level}',
                   now_s, battery=(bat.plugged, bat.charging))

    # ---- saniye çubuğu: 60 nokta, her 15'te bir uzun
    y = TIME_Y + pf.BASE * TIME_U + 16
    sx = (width - 60 * 6) / 2
    for i in range(60):
        a = 1.0 if i == now.second else 0.5 if i < now.second else 0.08
        tall = 2 if i % 15 == 0 else 0
        ctx.set_source_rgba(*AMBER, a)
        ctx.rectangle(sx + i * 6, y - tall, 4, 4 + tall)
        ctx.fill()

    # ---- tarih
    y += 24 + pf.ASCENT * DATE_U
    _text(ctx, f'{now.day} {MONTHS[now.month - 1]} {now.year} · {DAYS[now.weekday()]}',
          width / 2, y, DATE_U, CREAM)
    y += (pf.BASE + pf.DESCENT) * DATE_U + 10 + pf.ASCENT * INFO_U

    # ---- özel gün
    ev = world.event if world else None
    if ev:
        _text(ctx, ev.text, width / 2, y, INFO_U, rgb(ev.color), 0.95)
        y += (pf.BASE + pf.DESCENT) * INFO_U + 8 + pf.ASCENT * INFO_U

    # ---- hava + gün doğumu/batımı
    if weather is None or not weather.ok:
        text, kind = 'YALOVA · BEKLENİYOR', 'clear'
    else:
        text, kind = f'YALOVA {round(weather.temp)}° · {weather.label}', weather.kind
    rise, set_ = takvim.sun_times(now.date())
    text += f' · ↑{rise:%H:%M} ↓{set_:%H:%M}'
    cells, w = pf.layout(text)
    x = (width - (11 + 4 + w) * INFO_U) / 2
    for ix, iy, c in icon(kind, bool(weather and weather.is_day)):
        ctx.set_source_rgba(*c, 0.95)
        ctx.rectangle(x + ix * INFO_U, y - 2 * INFO_U + iy * INFO_U, INFO_U, INFO_U)
        ctx.fill()
    _cells(ctx, cells, x + 15 * INFO_U, y, INFO_U, MIST, alpha=0.9)
    y += (pf.BASE + pf.DESCENT) * INFO_U + 12 + pf.ASCENT * INFO_U

    # ---- çalan şarkı: ekolayzer + kayan yazı + ilerleme
    music = system.music if system else None
    if music and music.playing:
        eq_x = (width - 460) / 2
        for i in range(5):
            h = (math.sin(now_s * 7 + i * 1.3) + math.sin(now_s * 11.3 + i * 2.1) + 2) / 4
            n = 1 + round(h * 6)
            for r in range(n):
                ctx.set_source_rgba(*MUSIC, 0.5 + 0.5 * r / 7)
                ctx.rectangle(eq_x + i * 5, y + (pf.BASE - 1 - r) * INFO_U, 4, INFO_U - 1)
                ctx.fill()
        name = f'{music.artist} - {music.title}' if music.artist else music.title
        tr = any(c in name for c in 'çğıöşüÇĞİÖŞÜ')
        _marquee(ctx, name, eq_x + 34, y, INFO_U, 426, MUSIC, now_s, tr)
        if music.length:
            py = y + pf.BASE * INFO_U + 8
            ctx.set_source_rgba(*MUSIC, 0.15)
            ctx.rectangle(eq_x + 34, py, 426, 2)
            ctx.fill()
            ctx.set_source_rgba(*MUSIC, 0.8)
            ctx.rectangle(eq_x + 34, py, 426 * music.position / music.length, 2)
            ctx.fill()
        y += (pf.BASE + pf.DESCENT) * INFO_U + 12 + pf.ASCENT * SMALL_U

    # ---- ayrıntı satırı
    if system:
        parts = [f'RAM {system.ram_gb:.1f}/{system.ram_total_gb:.0f} GB',
                 f'DİSK {system.disk_gb:.0f}/{system.disk_total_gb:.0f} GB']
        bat = system.battery
        if bat.level is not None:
            if bat.charging and bat.hours:
                parts.append(f'DOLMASINA {_fmt_hours(bat.hours)}')
            elif bat.plugged:
                parts.append('FİŞE TAKILI')
            elif bat.hours:
                parts.append(f'PİL {_fmt_hours(bat.hours)}')
        _text(ctx, ' · '.join(parts), width / 2, y, SMALL_U, MIST, 0.55)


class ClockWindow(Gtk.Window):
    def __init__(self, world):
        super().__init__(title='Piksel Saat')
        self.world = world
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.stick()
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_default_size(WIDTH, HEIGHT)
        display = Gdk.Display.get_default()
        area = (display.get_primary_monitor() or display.get_monitor(0)).get_workarea()
        self.move(area.x + (area.width - WIDTH) // 2, area.y + (area.height - HEIGHT) // 2 - 60)
        self.connect('draw', self.on_draw)
        self._key = None
        GLib.timeout_add(100, self.tick)

    def tick(self):
        w = self.world
        now = datetime.datetime.now()
        animating = w.system.music.playing or w.system.battery.charging or 0.02 < w.sleep < 0.98
        key = (now.second, now.microsecond < 500_000, w.weather.ok, w.weather.label,
               w.event and w.event.text, round(w.metrics.cpu), round(w.system.ram, 2))
        if animating or key != self._key:
            self._key = key
            self.queue_draw()
        return True

    def on_draw(self, _widget, ctx):
        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.set_antialias(cairo.ANTIALIAS_NONE)
        ctx.push_group()
        draw_clock(ctx, datetime.datetime.now(), self.world)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(1 - 0.6 * self.world.sleep)   # mahalle uyurken saat de kısılır
