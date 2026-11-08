"""Ekranın ortasında duran büyük piksel saat: tarih, özel gün, Yalova havası, çalan şarkı ve sistem göstergeleri."""
import datetime
import math
import time

import cairo
import gi

gi.require_version('GdkX11', '3.0')
from gi.repository import Gdk, GdkX11, GLib, Gtk  # noqa: E402,F401  (GdkX11: pencerelere get_xid gelsin)

import piksel_font as pf
import takvim

MONTHS = ('OCAK', 'ŞUBAT', 'MART', 'NİSAN', 'MAYIS', 'HAZİRAN', 'TEMMUZ', 'AĞUSTOS',
          'EYLÜL', 'EKİM', 'KASIM', 'ARALIK')
DAYS = ('PAZARTESİ', 'SALI', 'ÇARŞAMBA', 'PERŞEMBE', 'CUMA', 'CUMARTESİ', 'PAZAR')

TIME_U, DATE_U, INFO_U, SMALL_U = 14, 4, 3, 2     # her yazı pikselinin ekran boyutu
WIDTH, HEIGHT = 760, 420
TIME_Y = 48
SEGS, SEG_W, SEG_H, SEG_GAP = 14, 12, 5, 2        # dikey LED göstergeler
GAUGE_GAP = 54                                    # göstergeler arası (merkezden merkeze)
# sıcaklık yazısının yeşilden kırmızıya döndüğü aralıklar (°C)
HOT = {'CPU': (45, 95), 'GPU': (45, 85), 'RAM': (40, 80), 'DİSK': (35, 70)}


def rgb(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


AMBER, CREAM, MIST, MUSIC = rgb('#ffc857'), rgb('#e9dfcf'), rgb('#9fb3c8'), rgb('#c9a7ff')
GREEN, RED = rgb('#3ddc97'), rgb('#ff5a4f')
SUN, MOON, CLOUD, DARK, DROP, SNOW = (rgb(c) for c in (
    '#ffd34d', '#f4f1de', '#c9d2dd', '#7d8796', '#5dade2', '#ffffff'))

# müzik düğmeleri (7 satır): önceki, oynat, duraklat, sonraki
BUTTONS = {
    'Previous': ('#....#', '#...##', '#..###', '#.####', '#..###', '#...##', '#....#'),
    'play': ('#...', '##..', '###.', '####', '###.', '##..', '#...'),
    'pause': ('##.##',) * 7,
    'Next': ('#....#', '##...#', '###..#', '####.#', '###..#', '##...#', '#....#'),
}
BTN_W, BTN_GAP = 32, 8       # düğme hücresi genişliği, yazıyla arası
MARQUEE_W = 426 - 3 * BTN_W - BTN_GAP

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


def _temp_color(t, lo, hi):
    k = max(0.0, min(1.0, (t - lo) / (hi - lo)))
    return mix(GREEN, AMBER, k / 0.5) if k < 0.5 else mix(AMBER, RED, (k - 0.5) / 0.5)


def _gauge(ctx, cx, frac, label, value, now_s, battery=None, temp=None):
    """Dikey LED gösterge; üstte sıcaklık ve değer, altta etiket. battery: (takılı, doluyor)."""
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
    if temp is not None and label in HOT:
        _text(ctx, f'{round(temp)}°', cx, TIME_Y - 40, SMALL_U, _temp_color(temp, *HOT[label]), 0.9)
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


def keep_above_desktop(win):
    """Masaüstü yöneticisinin (nemo vb.) tam ekran penceresi üstümüze çıkıp tıklamaları yutmasın:
    ona bağlı (transient) pencere olunca pencere yöneticisi bizi hep onun üstünde tutar. Yalnızca X11."""
    gw = win.get_window()
    if not gw or not hasattr(gw, 'get_xid'):
        return
    screen = Gdk.Screen.get_default()
    desk = None
    for w in screen.get_window_stack() or []:
        if (w.get_xid() != gw.get_xid() and w.get_type_hint() == Gdk.WindowTypeHint.DESKTOP
                and w.get_width() * 2 >= screen.get_width() and w.get_height() * 2 >= screen.get_height()):
            desk = w
    if desk and desk.get_xid() != getattr(win, '_desk', None):
        win._desk = desk.get_xid()
        gw.set_transient_for(desk)


def _button(ctx, kind, x, y, hover, flash):
    """Piksel müzik düğmesi; üstüne gelince parlar, basınca bir an beyazlar."""
    rows = BUTTONS[kind]
    w = len(rows[0]) * INFO_U
    x0 = x + (BTN_W - w) / 2
    col = mix(MUSIC, CREAM, flash) if flash else MUSIC
    if hover:
        ctx.set_source_rgba(*MUSIC, 0.12 + 0.2 * flash)
        ctx.rectangle(x, y - 3, BTN_W - 2, pf.BASE * INFO_U + 6)
        ctx.fill()
    cells = [(c, r) for r, row in enumerate(rows) for c, v in enumerate(row) if v == '#']
    _cells(ctx, cells, x0, y, INFO_U, col, 1.0 if hover else 0.8)


def draw_clock(ctx, now, world=None, width=WIDTH, ui=None):
    """ui (isteğe bağlı): {'hover': düğme, 'flash': (düğme, an)}; düğme kareleri ui['rects']'e yazılır."""
    now_s = time.time()
    ui = ui if ui is not None else {}
    ui['rects'] = {}
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

    # ---- iki yanda sistem göstergeleri: solda işlemciler, sağda bellek, disk ve pil
    if system:
        m = world.metrics
        left = [('CPU', cpu, m.temp if m.temp_ok else None)]
        if m.gpu_ok:
            left.append(('GPU', m.gpu / 100, m.gpu_temp))
        right = [('RAM', system.ram, system.ram_temp), ('DİSK', system.disk, system.disk_temp)]
        for i, (label, frac, temp) in enumerate(reversed(left)):
            _gauge(ctx, x0 - 38 - i * GAUGE_GAP, frac, label, f'%{round(frac * 100)}', now_s, temp=temp)
        for i, (label, frac, temp) in enumerate(right):
            _gauge(ctx, x1 + 38 + i * GAUGE_GAP, frac, label, f'%{round(frac * 100)}', now_s, temp=temp)
        bat = system.battery
        if bat.level is not None:
            _gauge(ctx, x1 + 38 + len(right) * GAUGE_GAP, bat.level / 100, 'ŞARJ' if bat.plugged else 'PİL',
                   f'%{bat.level}', now_s, battery=(bat.plugged, bat.charging))

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
    if music and music.visible:
        eq_x = (width - 460) / 2
        for i in range(5):
            h = (math.sin(now_s * 7 + i * 1.3) + math.sin(now_s * 11.3 + i * 2.1) + 2) / 4
            n = 1 + round(h * 6) if music.playing else 1      # duraklatınca ekolayzer yatar
            for r in range(n):
                ctx.set_source_rgba(*MUSIC, 0.5 + 0.5 * r / 7)
                ctx.rectangle(eq_x + i * 5, y + (pf.BASE - 1 - r) * INFO_U, 4, INFO_U - 1)
                ctx.fill()
        name = f'{music.artist} - {music.title}' if music.artist else music.title
        tr = any(c in name for c in 'çğıöşüÇĞİÖŞÜ')
        _marquee(ctx, name, eq_x + 34, y, INFO_U, MARQUEE_W, MUSIC, now_s, tr)
        bx = eq_x + 34 + MARQUEE_W + BTN_GAP
        flash_kind, flash_at = ui.get('flash') or (None, 0.0)
        for i, (cmd, kind) in enumerate((('Previous', 'Previous'),
                                         ('PlayPause', 'pause' if music.playing else 'play'), ('Next', 'Next'))):
            x = bx + i * BTN_W
            flash = max(0.0, 1 - (now_s - flash_at) / 0.3) if flash_kind == cmd else 0.0
            _button(ctx, kind, x, y, ui.get('hover') == cmd, flash)
            ui['rects'][cmd] = (round(x), round(y - 4), BTN_W - 2, pf.BASE * INFO_U + 8)
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
        # yalnızca müzik düğmeleri tıklanır; gerisinde tıklamalar masaüstüne geçer
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect('button-press-event', self.on_press)
        self.connect('motion-notify-event', lambda _w, ev: self.set_hover(self.button_at(ev.x, ev.y)))
        self.connect('leave-notify-event', lambda *_: self.set_hover(None))
        self.ui = {'hover': None, 'flash': None, 'rects': {}}
        self._shape = None
        self._key = None
        self._n = 0
        GLib.timeout_add(100, self.tick)

    def button_at(self, x, y):
        for cmd, (bx, by, bw, bh) in self.ui['rects'].items():
            if bx <= x < bx + bw and by <= y < by + bh:
                return cmd
        return None

    def set_hover(self, cmd):
        if cmd != self.ui['hover']:
            self.ui['hover'] = cmd
            gw = self.get_window()
            if gw:
                gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), 'pointer') if cmd else None)
            self.queue_draw()

    def on_press(self, _widget, ev):
        cmd = self.button_at(ev.x, ev.y)
        if ev.button == 1 and cmd:
            self.world.system.music.command(cmd)
            self.ui['flash'] = (cmd, time.time())
            self.queue_draw()
        return True

    def update_input(self):
        rects = tuple(self.ui['rects'].values())
        if rects != self._shape:
            self._shape = rects
            self.input_shape_combine_region(cairo.Region([cairo.RectangleInt(*r) for r in rects]))
            if not rects:
                self.set_hover(None)

    def tick(self):
        w = self.world
        now = datetime.datetime.now()
        self._n += 1
        if self._n % 30 == 1:
            keep_above_desktop(self)
        music = w.system.music
        flash = self.ui['flash'] and time.time() - self.ui['flash'][1] < 0.4
        animating = (music.playing or flash or w.system.battery.charging or 0.02 < w.sleep < 0.98)
        m = w.metrics
        key = (now.second, now.microsecond < 500_000, w.weather.ok, w.weather.label,
               w.event and w.event.text, round(m.cpu), round(m.gpu), round(m.temp), m.gpu_temp,
               round(w.system.ram, 2), w.system.disk_temp, music.visible, music.paused, music.title)
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
        draw_clock(ctx, datetime.datetime.now(), self.world, ui=self.ui)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(1 - 0.6 * self.world.sleep)   # mahalle uyurken saat de kısılır
        self.update_input()
