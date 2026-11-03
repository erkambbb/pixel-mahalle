"""Ekranın ortasında duran büyük piksel saat, tarih ve Yalova hava durumu."""
import datetime

import cairo
from gi.repository import Gdk, GLib, Gtk

import piksel_font as pf

MONTHS = ('OCAK', 'ŞUBAT', 'MART', 'NİSAN', 'MAYIS', 'HAZİRAN', 'TEMMUZ', 'AĞUSTOS',
          'EYLÜL', 'EKİM', 'KASIM', 'ARALIK')
DAYS = ('PAZARTESİ', 'SALI', 'ÇARŞAMBA', 'PERŞEMBE', 'CUMA', 'CUMARTESİ', 'PAZAR')

TIME_U, DATE_U, INFO_U = 14, 4, 3     # her yazı pikselinin ekran boyutu
WIDTH, HEIGHT = 640, 290


def rgb(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


AMBER, CREAM, MIST = rgb('#ffc857'), rgb('#e9dfcf'), rgb('#9fb3c8')
SUN, MOON, CLOUD, DARK, DROP, SNOW = (rgb(c) for c in (
    '#ffd34d', '#f4f1de', '#c9d2dd', '#7d8796', '#5dade2', '#ffffff'))

_CLOUD = ('....##.....', '..######...', '.#########.', '###########', '.#########.')


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


def draw_clock(ctx, now, weather, width=WIDTH):
    # ---- saat: LED matris, sönük hücreler hep görünür, iki nokta yarım saniyede bir yanar
    colon_on = now.microsecond < 500_000
    parts = [(ch, pf.glyph(ch)) for ch in now.strftime('%H:%M')]
    tw = sum(w for _, (w, _) in parts) + 2 * (len(parts) - 1)
    x, y = (width - tw * TIME_U) / 2, 20
    for ch, (w, cells) in parts:
        ghost = cells if ch == ':' else [(c, r) for c in range(w) for r in range(pf.BASE)]
        _cells(ctx, ghost, x, y, TIME_U, AMBER, alpha=0.07)
        if ch != ':' or colon_on:
            _cells(ctx, cells, x, y, TIME_U, AMBER, glow=0.05)
        x += (w + 2) * TIME_U

    # ---- saniye çubuğu: 60 nokta, her 15'te bir uzun
    y += pf.BASE * TIME_U + 16
    x0 = (width - 60 * 6) / 2
    for i in range(60):
        a = 1.0 if i == now.second else 0.5 if i < now.second else 0.08
        tall = 2 if i % 15 == 0 else 0
        ctx.set_source_rgba(*AMBER, a)
        ctx.rectangle(x0 + i * 6, y - tall, 4, 4 + tall)
        ctx.fill()

    # ---- tarih
    y += 22 + pf.ASCENT * DATE_U
    text = f'{now.day} {MONTHS[now.month - 1]} {now.year} · {DAYS[now.weekday()]}'
    cells, w = pf.layout(text)
    _cells(ctx, cells, (width - w * DATE_U) / 2, y, DATE_U, CREAM, alpha=0.9)

    # ---- hava: simge + YALOVA 18° · YAĞMURLU
    y += (pf.BASE + pf.DESCENT) * DATE_U + 12 + pf.ASCENT * INFO_U
    if weather is None or not weather.ok:
        text, kind = 'YALOVA · BEKLENİYOR', 'clear'
    else:
        text, kind = f'YALOVA {round(weather.temp)}° · {weather.label}', weather.kind
    cells, w = pf.layout(text)
    total = (11 + 4 + w) * INFO_U
    x = (width - total) / 2
    for ix, iy, c in icon(kind, bool(weather and weather.is_day)):
        ctx.set_source_rgba(*c, 0.95)
        ctx.rectangle(x + ix * INFO_U, y - 2 * INFO_U + iy * INFO_U, INFO_U, INFO_U)
        ctx.fill()
    _cells(ctx, cells, x + 15 * INFO_U, y, INFO_U, MIST, alpha=0.9)


class ClockWindow(Gtk.Window):
    def __init__(self, weather):
        super().__init__(title='Piksel Saat')
        self.weather = weather
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
        self.move(area.x + (area.width - WIDTH) // 2, area.y + (area.height - HEIGHT) // 2 - 40)
        self.connect('draw', self.on_draw)
        self._key = None
        GLib.timeout_add(100, self.tick)

    def tick(self):
        now = datetime.datetime.now()
        key = (now.second, now.microsecond < 500_000, self.weather.ok, self.weather.label)
        if key != self._key:
            self._key = key
            self.queue_draw()
        return True

    def on_draw(self, _widget, ctx):
        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.set_antialias(cairo.ANTIALIAS_NONE)
        draw_clock(ctx, datetime.datetime.now(), self.weather)
