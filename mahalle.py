#!/usr/bin/env python3
"""Masaüstünde duran, tıklanamayan küçük bir piksel mahalle."""
import argparse
import colorsys
import datetime
import functools
import glob
import math
import os
import random
import shutil
import subprocess
import threading
import time
import traceback

import cairo
import gi

# Wayland'de pencere konumu ve masaüstü ipucu yok sayılır; XWayland varsa onu kullan.
if os.environ.get('WAYLAND_DISPLAY') and os.environ.get('DISPLAY'):
    os.environ.setdefault('GDK_BACKEND', 'x11')

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

import hava  # noqa: E402
import piksel_font as pf  # noqa: E402
import saat  # noqa: E402
import sistem  # noqa: E402
import takvim  # noqa: E402

W, H = 220, 90       # mahallenin mantıksal piksel boyutu (W açılışta ekran genişliğine uzatılır)
PANEL = 28           # sağdaki internet tüplerinin genişliği
S = 4                # her mantıksal piksel ekranda S x S (yarım piksel detay = 2x2); HiDPI'de küçülür
ALWAYS_NIGHT = True  # mahalle hep gece
FPS = 12
GROUND = 66          # evlerin oturduğu çizgi (çimen satırı)
FEET = 72            # kaldırımda yürüyenlerin ayak hizası
PICKUP_X = 140       # taşıyıcıların kamyondan kutu aldığı yer
TRUCK_X = 146        # kamyonun park ettiği yer


@functools.lru_cache(maxsize=None)
def hx(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


def color(c):
    return hx(c) if isinstance(c, str) else c


def shade(c, k):
    return tuple(min(1.0, v * k) for v in color(c))


def read(path):
    with open(path) as f:
        return f.read()


SKIN = [hx(c) for c in ('#f1c27d', '#e0ac69', '#c68642', '#8d5524', '#ffdbac')]
HAIR = [hx(c) for c in ('#2c1b10', '#6a4e2e', '#b5651d', '#e6c35c', '#1a1a1a', '#9e9e9e')]
SHIRT = [hx(c) for c in ('#d9534f', '#3e7cb1', '#5cb85c', '#f0ad4e', '#8e44ad', '#16a085', '#ecf0f1', '#e67e22')]
PANTS = [hx(c) for c in ('#2c3e50', '#34495e', '#5d4037', '#3b3b98', '#555555')]
CARS = [hx(c) for c in ('#e74c3c', '#3498db', '#f1c40f', '#ecf0f1', '#2ecc71', '#9b59b6')]

# chimney: bacanın evin solundan uzaklığı (None = bacasız)
HOUSES = [
    dict(x=6, w=34, h=24, wall='#e8c39e', roof='#b5523b', kind='gable', door=14, chimney=25),
    dict(x=48, w=30, h=34, wall='#9fb8c9', roof='#5a6a78', kind='flat', door=12, chimney=5),
    dict(x=88, w=38, h=26, wall='#f2e6c9', roof='#3f7f5f', kind='shop', door=24, chimney=None),
    dict(x=136, w=32, h=26, wall='#c9a0b8', roof='#6b3f5a', kind='gable', door=6, chimney=6),
    dict(x=178, w=36, h=20, wall='#d7d98f', roof='#8a5a2b', kind='gable', door=22, chimney=27),
]
TREES = [43, 83, 131, 172]
LAMPS = [30, 108, 200]
PUDDLES = (20, 60, 116, 158, 194)             # kaldırımdaki su birikintilerinin x'i
# ilk beş evden sonra mahalle ekran genişliğince bu kalıplarla uzar
EXTRA = [dict(w=32, h=24, kind='gable'), dict(w=28, h=32, kind='flat'), dict(w=36, h=22, kind='gable'),
         dict(w=30, h=28, kind='gable'), dict(w=34, h=30, kind='flat'), dict(w=30, h=20, kind='gable')]
WALLS = ['#e8c39e', '#9fb8c9', '#c9a0b8', '#d7d98f', '#b8d4c0', '#e3b5a4', '#c4b7e0', '#f0d9a8']
ROOFS = ['#b5523b', '#5a6a78', '#6b3f5a', '#8a5a2b', '#3f6b7f', '#7a3b3b', '#4a5a3a']
TEMP_MIN, TEMP_MAX = 40, 110   # bu aralıkta pencereler 0'dan hepsine kadar yanar
GPU_COOL, GPU_HOT = 45, 85     # GPU bu sıcaklıklar arasında bacalar sakinden kıpkırmızıya
MAX_WALKERS = 14               # %100 CPU'da 220 px'lik sokaktaki yaya sayısı (genişlikle ölçeklenir)
MAX_CARS = 8                   # %100 GPU'da 220 px'lik yoldaki araba sayısı
TOWER_W, TOWER_TOP = 16, 24    # saat kulesi gövdesi: genişlik ve gövdenin üst satırı


def layout(width):
    """Evler, ağaçlar, lambalar ve su birikintileri: ilk beşi sabit, gerisi genişliği doldurur."""
    rng = random.Random(21)
    houses, trees = [dict(d) for d in HOUSES], list(TREES)
    # saat kulesi: geniş ekranda ortaya, ilk beş evin hemen sağından önce değil
    tower = max(218, width // 2 - TOWER_W // 2) if width >= 300 else None
    x, i = (tower + TOWER_W + 10) if tower else 224, 0
    while True:
        t = EXTRA[i % len(EXTRA)]
        i += 1
        w = t['w'] + rng.choice((-2, 0, 2))
        if x + w > width - 4:
            break
        if tower and x < tower + TOWER_W + 4 and x + w > tower - 4:   # kulenin yerine taşma
            x = tower + TOWER_W + 10
            continue
        if t['kind'] == 'gable':
            chimney = rng.choice((6, w - 9))
        else:
            chimney = 5 if rng.random() < 0.8 else None
        houses.append(dict(x=x, w=w, h=t['h'] + rng.choice((-2, 0, 2)), wall=rng.choice(WALLS),
                           roof=rng.choice(ROOFS), kind=t['kind'], door=rng.choice((5, w // 2 - 2, w - 11)),
                           chimney=chimney))
        x += w
        gap = rng.choice((8, 10, 12))
        if rng.random() < 0.8:
            trees.append(x + 3)
        x += gap
    lamps = LAMPS + list(range(285, width - 10, 85))
    puddles = PUDDLES + tuple(range(234, width - 10, 40))
    return houses, trees, lamps, puddles, tower

# İnternet tüpleri: doluluk logaritmik, NET_MIN'de boş, NET_MAX'ta dolu (bayt/sn)
NET_MIN, NET_MAX = 1e3, 1e8    # 1 KB/s .. 100 MB/s
NET_SKIP = ('lo', 'veth', 'docker', 'br-', 'virbr', 'vmnet', 'tun', 'wg')
TUBE_TOP, TUBE_BOT = 12, 85    # cam tüpün ağız ve dip satırı
# Hava durumu süsleri
UMBRELLAS = [hx(c) for c in ('#e74c3c', '#2980b9', '#f1c40f', '#27ae60', '#8e44ad', '#ecf0f1', '#e67e22', '#2d3436')]
SCARVES = [hx(c) for c in ('#c0392b', '#f39c12', '#16a085', '#ecf0f1', '#8e44ad')]
SNOW_WHITE = '#f4f7fb'
MOON_Y, MOON_R = 12, 5
SYNODIC, NEW_MOON = 29.530588853, 947182440   # ay döngüsü (gün), 6 Oca 2000 18:14 UTC yeniay
COLD = 8                                      # bu sıcaklığın altında atkı/bere
SLEEP_AFTER = 5 * 60                          # bu kadar sn klavye/fare boşta kalınca mahalle uyur
STALL_X = 67                                  # Cuma pazarı tezgâhı
FW_COLORS = ['#ff5a4f', '#ffd34d', '#3ddc97', '#5dade2', '#c9a7ff', '#ffffff', '#ff9ff3']
DECOR_COLORS = ['#ff5a4f', '#ffd34d', '#3ddc97', '#5dade2', '#ff9ff3']

# kedi çizimleri (sağa bakan, yarım piksel hücreler): # gövde, e göz
CAT_SIT = (('....#.#', '....###', '....#e#', '#..###.', '#####..'),
           ('....#.#', '....###', '#...#e#', '#..###.', '.####..'))
CAT_WALK = (('......##', '#.....#e', '.######.', '.#.#..#.'),
            ('......##', '#.....#e', '.######.', '..#..#..'))
CAT_SLEEP = ('.####.', '######', '######')


def _flag_white():
    """Türk bayrağındaki ay-yıldızın yarım piksel hücreleri (bayrak 7x4.5 px)."""
    out = []
    for cy in range(9):
        for cx in range(14):
            x, y = cx * 0.5 + 0.25, cy * 0.5 + 0.25
            outer = (x - 2.5) ** 2 + (y - 2.25) ** 2 <= 1.3 ** 2
            inner = (x - 2.85) ** 2 + (y - 2.25) ** 2 <= 1.05 ** 2
            star = abs(x - 4.15) + abs(y - 2.25) <= 0.5
            if (outer and not inner) or star:
                out.append((cx, cy))
    return out


FLAG_WHITE = _flag_white()


@functools.lru_cache(maxsize=256)
def text_cells(s):
    return pf.layout(s)

ARROWS = {
    'down': ('..#..', '..#..', '#.#.#', '.###.', '..#..'),
    'up': ('..#..', '.###.', '#.#.#', '..#..', '..#..'),
}


class Metrics:
    """CPU %, GPU %, CPU sıcaklığı ve ağ trafiği (bayt/sn)."""

    def __init__(self):
        self.cpu = self.gpu = 0.0
        self.gpu_temp = None   # °C; bilinmiyorsa None
        self.temp = TEMP_MIN
        self.down = self.up = 0.0
        self._prev = self._cpu_times()
        self._net_prev = (time.monotonic(), *self._net_bytes())
        self._temp_file = self._find_temp_file()
        self._gpu_temp_file = None
        for d in sorted(glob.glob('/sys/class/hwmon/hwmon*')):   # NVIDIA yoksa AMD/Intel/nouveau
            try:
                if read(d + '/name').strip() in ('amdgpu', 'radeon', 'nouveau', 'i915', 'xe'):
                    self._gpu_temp_file = d + '/temp1_input'
                    break
            except OSError:
                pass
        if shutil.which('nvidia-smi'):
            # nvidia-smi yavaş olabilir; GTK döngüsünü bloklamasın diye ayrı iş parçacığı
            threading.Thread(target=self._poll_gpu, daemon=True).start()

    @staticmethod
    def _find_temp_file():
        for d in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
            try:
                if read(d + '/name').strip() in ('coretemp', 'k10temp', 'zenpower'):
                    return d + '/temp1_input'
            except OSError:
                pass
        # yedek: ısıl bölgeler (dizüstü, ARM vb.); CPU'ya benzeyen ilk bölge, yoksa ilki
        zones = sorted(glob.glob('/sys/class/thermal/thermal_zone*'))
        for z in zones:
            try:
                if any(k in read(z + '/type') for k in ('x86_pkg_temp', 'cpu', 'soc')):
                    return z + '/temp'
            except OSError:
                pass
        return zones[0] + '/temp' if zones else None

    def _poll_gpu(self):
        while True:
            try:
                out = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu',
                                      '--format=csv,noheader,nounits'],
                                     capture_output=True, text=True, timeout=5).stdout
                util, temp = out.splitlines()[0].split(',')[:2]
                self.gpu, self.gpu_temp = float(util), float(temp)
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                self.gpu = 0.0
            time.sleep(2)

    @staticmethod
    def _cpu_times():
        with open('/proc/stat') as f:
            v = [int(x) for x in f.readline().split()[1:]]
        return v[3] + v[4], sum(v)

    @staticmethod
    def _net_bytes():
        """Fiziksel arayüzlerin toplam alınan/gönderilen baytı."""
        rx = tx = 0
        try:
            lines = read('/proc/net/dev').splitlines()[2:]
        except OSError:
            return 0, 0
        for line in lines:
            name, _, data = line.partition(':')
            if name.strip().startswith(NET_SKIP):
                continue
            v = data.split()
            if len(v) >= 9:
                rx += int(v[0])
                tx += int(v[8])
        return rx, tx

    def update(self):
        idle, total = self._cpu_times()
        di, dt = idle - self._prev[0], total - self._prev[1]
        self._prev = (idle, total)
        if dt:
            self.cpu = 100 * (1 - di / dt)

        now = time.monotonic()
        rx, tx = self._net_bytes()
        t0, rx0, tx0 = self._net_prev
        self._net_prev = (now, rx, tx)
        if now > t0:
            self.down = max(0, rx - rx0) / (now - t0)
            self.up = max(0, tx - tx0) / (now - t0)

        if self._temp_file:
            try:
                self.temp = int(read(self._temp_file)) / 1000
            except (OSError, ValueError):
                pass
        if self._gpu_temp_file:
            try:
                self.gpu_temp = int(read(self._gpu_temp_file)) / 1000
            except (OSError, ValueError):
                pass


def moon_phase(t=None):
    """0 yeniay, 0.25 ilk dördün, 0.5 dolunay, 0.75 son dördün."""
    return (((time.time() if t is None else t) - NEW_MOON) / 86400 / SYNODIC) % 1


def mix(a, b, k):
    a, b = color(a), color(b)
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def wait(n):
    for _ in range(int(n)):
        yield


def walk(p, tx, speed=None):
    sp = speed or p.speed
    while abs(tx - p.x) > sp:
        p.dir = 1 if tx > p.x else -1
        p.x += p.dir * sp
        p.walking = True
        yield
    p.x = tx
    p.walking = False


class House:
    def __init__(self, d):
        self.__dict__.update(d)
        self.top = GROUND - self.h
        self.door_x = self.x + self.door
        c = d.get('chimney')
        # baca: (sol x, şapka y); dumanı şapkanın üstünden çıkar
        self.chimney = None if c is None else (self.x + c, self.top - (13 if self.kind == 'gable' else 8))
        self.open = 0
        self.windows = []
        if self.kind != 'shop':
            for wy in range(self.top + 4, GROUND - 8, 10):
                for wx in range(self.x + 4, self.x + self.w - 6, 9):
                    near_door = self.door_x - 6 < wx < self.door_x + 6 and wy + 5 > GROUND - 11
                    if not near_door:
                        self.windows.append([wx, wy, False])


class Person:
    def __init__(self, x=0.0):
        self.x = float(x)
        self.dir = 1
        self.speed = random.uniform(0.35, 0.6)
        self.walking = False
        self.frame = 0
        self.skin = random.choice(SKIN)
        self.hair = random.choice(HAIR)
        self.shirt = random.choice(SHIRT)
        self.pants = random.choice(PANTS)
        self.carry = None      # None | 'box' | 'bag' | 'can'
        self.watering = False
        self.visible = True
        self.done = False
        self.dog = None
        self.script = None
        self.kind = 'pedestrian'   # 'pedestrian' | 'mover' | 'gardener'
        self.umbrella = random.choice(UMBRELLAS) if random.random() < 0.85 else None
        self.scarf = random.choice(SCARVES)
        self.shout = 0         # bozacının 'BOZAAA' balonu
        self.keys = False      # gece dönen anahtar arıyor


class Cat:
    def __init__(self, x, y, color, lo=None, hi=None):
        self.x, self.y = float(x), y
        self.dir = 1
        self.color = hx(color)
        self.lo, self.hi = lo, hi
        self.state = 'sit'     # sit | walk | sleep
        self.phase = random.randint(0, 90)
        self.done = False
        self.script = None


class Dog:
    def __init__(self, x):
        self.x = float(x)
        self.color = hx(random.choice(('#8b5a2b', '#f5f5f5', '#222222', '#d2a35a')))


class Truck:
    def __init__(self):
        self.x = -40.0
        self.state = 'away'
        self.boxes = 0
        self.moving = False


class Tube:
    """Ağ trafiğini gösteren, kabarcıklı sıvı dolu cam tüp."""
    INNER = TUBE_BOT - TUBE_TOP - 1    # sıvının dolabileceği satır sayısı
    IW = 7                             # camın iç genişliği

    def __init__(self, x, liquid, arrow):
        self.x = x
        self.liquid = hx(liquid)
        self.arrow = ARROWS[arrow]
        self.level = self.target = 0.0
        self.bubbles = []

    def set_rate(self, bps):
        if bps <= NET_MIN:
            self.target = 0.0
        else:
            self.target = min(1.0, math.log10(bps / NET_MIN) / math.log10(NET_MAX / NET_MIN))

    def step(self):
        self.level += (self.target - self.level) * 0.12
        height = self.level * self.INNER
        if height > 3 and random.random() < 0.08 + self.level * 0.4:
            self.bubbles.append([random.randint(0, self.IW - 2), 0.0, random.uniform(0.3, 0.6 + self.level)])
        for b in self.bubbles:
            b[1] += b[2]
        self.bubbles = [b for b in self.bubbles if b[1] < height - 2]


class World:
    def __init__(self, weather=None, system=None, birthday=None, sleep_after=SLEEP_AFTER, clock=None):
        self.t = 0
        self.system = system or sistem.System(music=False)
        self.birthday = birthday
        self.sleep_after = sleep_after
        self.clock = clock or datetime.datetime.now
        self.sleep, self.asleep = 0.0, False
        self.temp_frac = 0.0
        self.event, self.market_on, self.twi = None, False, (None, 0.0)
        self.forced_lit = []          # [pencere, kalan kare]: gece dönenin yaktığı ışık
        self.notes, self.zs, self.rockets, self.sparks = [], [], [], []
        self.cats = []
        self.light = 1.0
        self.layers = {}   # ad -> (anahtar, yüzey): değişmeyen katmanlar önbellekte
        houses, self.trees, self.lamps, self.puddles, self.tower = layout(W)
        self.ring_hour = None              # son çan çalınan saat
        self.houses = [House(d) for d in houses]
        self.scale = W / 220               # nüfus, bulut, yağış genişlikle ölçeklenir
        self.moon_x = round(W * (0.68 if self.tower else 0.53))
        self.heat = 0.0                    # GPU sıcaklığı 0..1 (yumuşatılmış)
        self.shop = self.houses[2]
        self.people = []
        self.cars = []
        self.birds = []
        self.smoke = []
        self.clouds = [[random.uniform(0, W), random.uniform(3, 18), random.randint(12, 22),
                        random.uniform(0.03, 0.07)] for _ in range(round(9 * W / 220))]
        # hava: hedef değerlere yavaşça yaklaşan yumuşatılmış durum
        self.weather = weather or hava.Weather(fetch=False)
        w = self.weather
        self.rain, self.snow, self.cloud, self.fog, self.wind = w.rain, w.snow, w.cloud, w.fog, w.windy
        self.cover = 1.0 if w.snow else 0.0      # yerdeki kar (0..1)
        self.wet = 1.0 if w.rain else 0.0        # ıslaklık / su birikintileri (0..1)
        self.drops, self.splashes, self.ripples, self.flakes = [], [], [], []
        self.flash, self.bolt, self.meteor = 0, [], None
        rng = random.Random(11)
        self.stars = [(rng.uniform(0, W), rng.uniform(1, 44), rng.uniform(0, 6.3), rng.uniform(0.03, 0.12),
                       rng.random() < 0.15, rng.choice(('#ffffff', '#cfe3ff', '#fff1c9')))
                      for _ in range(round(55 * W / 220))]
        self.fog_blobs = [[rng.uniform(0, W + 60), rng.uniform(25, 84), rng.uniform(25, 55),
                           rng.uniform(2, 6), rng.uniform(0.03, 0.15)] for _ in range(round(16 * W / 220))]
        self.truck = Truck()
        self.metrics = Metrics()
        self.tubes = [Tube(3, '#3ddc97', 'down'), Tube(3 + Tube.IW + 5, '#ff9f43', 'up')]
        self.shop_lit = [False]
        # Sıcaklık arttıkça bu sırayla yanarlar (dükkan vitrini dahil 22 pencere)
        self.light_order = [w for h in self.houses for w in h.windows] + [self.shop_lit]
        random.Random(7).shuffle(self.light_order)
        # Evlerin önünde kalmayan çimen tutamları
        rng = random.Random(3)
        self.tufts = [x for x in range(0, W, 3)
                      if rng.random() < 0.6 and not any(h.x - 1 <= x <= h.x + h.w for h in self.houses)
                      and not (self.tower and self.tower - 1 <= x <= self.tower + TOWER_W)]
        self.truck_script = self.run_truck()
        for i in range(2):
            m = Person(self.houses[3].door_x + i * 8)
            m.kind = 'mover'
            m.shirt = hx('#2f6db5')
            m.script = self.run_mover(m, self.houses[3])
            self.people.append(m)
        g = Person()
        g.kind = 'gardener'
        g.visible = False
        g.script = self.run_gardener(g, self.houses[0])
        self.people.append(g)
        # müzik çalınca apartmanın en üst sağ penceresinde parti
        self.music_win = max(self.houses[1].windows, key=lambda w: (-w[1], w[0]))
        # çatıdaki kedi: son evin mahyasında
        h = self.houses[4]
        rows = min(10, (h.w + 4) // 2 - 1)
        lo = h.x - 3 + rows
        roof_cat = Cat(lo + 6, h.top - rows, '#e08a3c', lo, lo + h.w + 6 - 2 * rows - 4)
        roof_cat.script = self.run_roof_cat(roof_cat)
        self.cats.append(roof_cat)
        self.vendor = Person()
        self.vendor.x, self.vendor.dir = STALL_X + 4, 1
        self.vendor.shirt = hx('#2e86de')
        self.garland = self.garland_points()
        self.update_life()

    # ---- senaryolar ----

    def enter(self, p, house):
        house.open = 8
        yield from wait(3)
        p.visible = False
        yield from wait(3)

    def leave(self, p, house):
        house.open = 8
        p.x = house.door_x
        yield from wait(3)
        p.visible = True
        yield from wait(2)

    def run_truck(self):
        t = self.truck
        while True:
            t.boxes, t.state, t.x = 6, 'arriving', -40.0
            while t.x < TRUCK_X:
                t.x += max(0.3, min(2.0, (TRUCK_X - t.x) * 0.05))
                t.moving = True
                yield
            t.x, t.state, t.moving = TRUCK_X, 'parked', False
            while t.boxes > 0:
                yield
            yield from wait(random.randint(60, 120))
            t.state, sp = 'leaving', 0.2
            while t.x < W + 10:
                sp = min(2.0, sp + 0.04)
                t.x += sp
                t.moving = True
                yield
            t.state, t.moving = 'away', False
            yield from wait(random.randint(400, 900))

    def run_mover(self, p, home):
        while True:
            t = self.truck
            if self.sleep > 0.5:   # mahalle uyuyor: eve gir, uyan(ıl)masını bekle
                if p.visible:
                    yield from walk(p, home.door_x)
                    yield from self.enter(p, home)
                yield from wait(40)
                continue
            if t.state == 'parked' and t.boxes > 0:
                if not p.visible:
                    yield from self.leave(p, home)
                yield from walk(p, PICKUP_X + random.uniform(-1, 1))
                p.dir = 1
                yield from wait(8)
                if t.state != 'parked' or t.boxes == 0:
                    continue
                t.boxes -= 1
                p.carry = 'box'
                yield from walk(p, home.door_x, p.speed * 0.7)
                yield from self.enter(p, home)
                p.carry = None
                yield from wait(random.randint(15, 35))
                yield from self.leave(p, home)
            elif p.visible and random.random() < 0.4:
                yield from walk(p, home.door_x)
                yield from self.enter(p, home)
                yield from wait(random.randint(80, 250))
            elif p.visible:
                yield from walk(p, home.door_x + random.uniform(-12, 12))
                yield from wait(random.randint(30, 90))
            else:
                yield from wait(20)

    def run_gardener(self, p, home):
        while True:
            yield from wait(random.randint(200, 600))
            if self.rain > 0.1 or self.snow > 0.1 or self.cover > 0.3 or self.sleep > 0.3:
                continue   # yağmurda sulamaya gerek yok, karda bahçe uyuyor
            p.carry = 'can'
            yield from self.leave(p, home)
            yield from walk(p, home.x + 5)
            p.dir = -1
            p.watering = True
            yield from wait(70)
            p.watering = False
            yield from walk(p, home.door_x)
            yield from self.enter(p, home)
            p.carry = None

    def run_pedestrian(self, p):
        left = random.random() < 0.5
        exit_x = W + 6 if left else -10
        homes = [h for h in self.houses if h is not self.shop]
        if random.random() < 0.25:
            p.visible = False
            yield from self.leave(p, random.choice(homes))
        else:
            p.x = -6 if left else W + 2
        r = random.random()
        if r < 0.4 and p.dog is None and self.market_on and random.random() < 0.5:
            yield from walk(p, STALL_X + random.uniform(1, 10))   # Cuma pazarından alışveriş
            p.dir = 1
            yield from wait(random.randint(40, 90))
            p.carry = 'bag'
            yield from walk(p, exit_x)
        elif r < 0.4 and p.dog is None:
            yield from walk(p, self.shop.door_x)
            yield from self.enter(p, self.shop)
            yield from wait(random.randint(50, 150))
            if random.random() < 0.7:
                p.carry = 'bag'
            yield from self.leave(p, self.shop)
            yield from walk(p, exit_x)
        elif r < 0.55 and p.dog is None:
            house = random.choice(homes)
            yield from walk(p, house.door_x)
            yield from self.enter(p, house)
            return
        else:
            if random.random() < 0.3:
                yield from walk(p, random.uniform(20, W - 20))
                yield from wait(random.randint(15, 50))
            yield from walk(p, exit_x)
        p.done = True

    def _edge(self, p):
        left = random.random() < 0.5
        p.x = -6.0 if left else W + 2.0
        return W + 6 if left else -10

    def run_simitci(self, p):
        exit_x = self._edge(p)
        p.speed, p.carry = 0.3, 'simit'
        yield from walk(p, random.uniform(50, 170))
        yield from wait(random.randint(50, 100))    # satış
        yield from walk(p, exit_x)
        p.done = True

    def run_bozaci(self, p):
        exit_x = self._edge(p)
        p.speed, p.carry = 0.28, 'boza'
        stops = sorted(random.sample(range(30, W - 30, 12), 3), reverse=exit_x < 0)
        for sx in stops:
            yield from walk(p, sx)
            p.shout = 40
            yield from wait(55)
        yield from walk(p, exit_x)
        p.done = True

    def run_late(self, p):
        house = random.choice([h for h in self.houses if h is not self.shop and h is not self.houses[1]])
        self._edge(p)
        p.speed = 0.22
        yield from walk(p, house.door_x)
        p.dir, p.keys = 1, True
        yield from wait(random.randint(35, 70))      # anahtar arıyor
        p.keys = False
        yield from self.enter(p, house)
        if house.windows:
            self.forced_lit.append([random.choice(house.windows), FPS * random.randint(40, 90)])
        p.done = True

    def run_roof_cat(self, c):
        while True:
            if self.sleep > 0.5:
                c.state = 'sleep'
                yield from wait(20)
                continue
            r = random.random()
            if r < 0.65:
                c.state = 'sit'
                yield from wait(random.randint(80, 300))
            else:
                tx = random.uniform(c.lo, c.hi)
                c.state = 'walk'
                while abs(tx - c.x) > 0.3:
                    c.dir = 1 if tx > c.x else -1
                    c.x += c.dir * 0.25
                    yield
                c.x = tx

    def run_street_cat(self, c):
        exit_x = W + 6 if c.x < 0 else -10
        c.dir = 1 if exit_x > 0 else -1
        pause = random.uniform(40, W - 40) if random.random() < 0.5 else None
        while (exit_x - c.x) * c.dir > 0:
            dog_near = any(p.dog and p.visible and abs(p.dog.x - c.x) < 18 for p in self.people)
            c.state = 'walk'
            c.x += c.dir * (1.8 if dog_near else 0.35)   # köpek yaklaşırsa kaçar
            if pause is not None and abs(c.x - pause) < 0.4 and not dog_near:
                pause = None
                c.state = 'sit'
                yield from wait(random.randint(60, 160))
            yield
        c.done = True

    def update_life(self):
        """2 sn'de bir: sistem, uyku, takvim, alacakaranlık ve sokak hayatı."""
        now = self.clock()
        self.system.update()
        self.asleep = self.system.idle_s > self.sleep_after
        self.event = takvim.event(now, self.birthday)
        self.market_on = takvim.market(now)
        self.twi = takvim.twilight(now)
        h = now.hour + now.minute / 60
        kinds = {p.kind for p in self.people}
        specials = (('simitci', 7 <= h < 11.5, 300, self.run_simitci),
                    ('bozaci', now.month in (11, 12, 1, 2, 3) and 19 <= h < 24, 420, self.run_bozaci),
                    ('late', h < 4, 600, self.run_late))
        for kind, active, every, run in specials:
            if active and kind not in kinds and random.random() < 2 / every:
                p = Person()
                p.kind = kind
                p.script = run(p)
                self.people.append(p)
        if len(self.cats) < 2 and random.random() < 2 / 200:
            c = Cat(-6 if random.random() < 0.5 else W + 2, FEET, random.choice(('#7f8c8d', '#2b2b2b', '#f5f5f5')))
            c.script = self.run_street_cat(c)
            self.cats.append(c)

    def garland_points(self):
        """Evlerin saçak hizasında sarkan ip: (x, y) noktaları, 1 px aralıklı."""
        anchors = []
        for h in self.houses:
            anchors += [(h.x - 1, h.top + 1.0), (h.x + h.w, h.top + 1.0)]
        pts = []
        for (x1, y1), (x2, y2) in zip(anchors, anchors[1:]):
            n = max(1, int(x2 - x1))
            sag = min(3.0, n * 0.12)
            for i in range(n):
                u = i / n
                pts.append((x1 + (x2 - x1) * u, y1 + (y2 - y1) * u + sag * 4 * u * (1 - u)))
        return pts

    # ---- güncelleme ----

    def update_light(self):
        if ALWAYS_NIGHT:
            self.light = 0.0
            return
        now = datetime.datetime.now()
        h = now.hour + now.minute / 60
        if 7 <= h < 18:
            self.light = 1.0
        elif h >= 20.5 or h < 5.5:
            self.light = 0.0
        elif h < 7:
            self.light = (h - 5.5) / 1.5
        else:
            self.light = 1 - (h - 18) / 2.5

    def step(self):
        self.t += 1
        if self.t % (FPS * 30) == 1:
            self.update_light()
        if self.t % (FPS * 2) == 1:
            m = self.metrics
            m.update()
            self.temp_frac = max(0.0, min(1.0, (m.temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN)))
            self.tubes[0].set_rate(m.down)
            self.tubes[1].set_rate(m.up)
            self.update_life()
        # uyku: dalarken ışıklar tek tek söner (~1 dk), uyanınca hemen yanar
        self.sleep += ((1.0 if self.asleep else 0.0) - self.sleep) * (0.004 if self.asleep else 0.08)
        lit = round(self.temp_frac * len(self.light_order) * (1 - self.sleep))
        for i, w in enumerate(self.light_order):
            w[-1] = i < lit
        for f in self.forced_lit:
            f[0][-1] = True
            f[1] -= 1
        self.forced_lit = [f for f in self.forced_lit if f[1] > 0]
        for tube in self.tubes:
            tube.step()
        busy = 0.3 + 0.7 * self.light

        next(self.truck_script)
        for p in self.people:
            try:
                next(p.script)
            except StopIteration:
                p.done = True
            if p.walking and self.t % 2 == 0:
                p.frame ^= 1
            if p.shout:
                p.shout -= 1
            if p.dog:
                target = p.x - p.dir * 7
                p.dog.x += max(-0.9, min(0.9, target - p.dog.x))
        self.people = [p for p in self.people if not p.done]

        walkers = sum(1 for p in self.people if p.kind == 'pedestrian')
        target = round(self.metrics.cpu / 100 * MAX_WALKERS * self.scale * (1 - self.sleep))
        if walkers < target and random.random() < 0.05 * self.scale:
            p = Person()
            if self.rain > 0.3 and not p.umbrella:
                p.speed *= 1.8   # şemsiyesi olmayan koşar
            if random.random() < 0.15:
                p.dog = Dog(-20)
            p.script = self.run_pedestrian(p)
            self.people.append(p)
            if p.dog:
                next(p.script)
                p.dog.x = p.x

        for h in self.houses:
            h.open = max(0, h.open - 1)

        car_target = round(self.metrics.gpu / 100 * MAX_CARS * self.scale * (1 - self.sleep))
        if len(self.cars) < car_target and random.random() < 0.08 and all(c[0] < W - 22 for c in self.cars):
            self.cars.append([W + 2.0, random.uniform(1.0, 1.6), random.choice(CARS)])
        for c in self.cars:
            c[0] -= c[1]
        self.cars = [c for c in self.cars if c[0] > -20]

        for c in self.clouds:
            c[0] += c[3] * (1 + self.wind * 4)
            if c[0] > W + 5:
                c[0], c[1] = -c[2] - 5.0, random.uniform(3, 18)

        if not self.birds and self.rain < 0.05 and self.snow < 0.05 and random.random() < 0.002 * busy:
            y = random.uniform(8, 26)
            self.birds = [[-5.0 - i * 6, y + (i % 2) * 3, i * 3] for i in range(random.randint(2, 4))]
        for b in self.birds:
            b[0] += 0.9
        self.birds = [b for b in self.birds if b[0] < W + 5]

        # bacalar GPU sıcaklığıyla tüter: serinken arada bir, ısındıkça yoğun ve kızıl, çok sıcakta kıvılcım
        gt = self.metrics.gpu_temp
        target = 0.0 if gt is None else max(0.0, min(1.0, (gt - GPU_COOL) / (GPU_HOT - GPU_COOL)))
        self.heat += (target - self.heat) * 0.02
        for h in self.houses:
            if h.chimney:
                cx, ct = h.chimney
                if random.random() < 0.012 + self.heat * 0.2:
                    self.smoke.append([cx + 1 + random.uniform(-0.5, 0.5), ct - 1.0, 0, self.heat, False])
                if self.heat > 0.8 and random.random() < (self.heat - 0.8) * 0.5:
                    self.smoke.append([cx + 1 + random.uniform(-1, 1), ct - 0.5, 0, self.heat, True])
        for s in self.smoke:
            s[0] += 0.06 + self.wind * 0.35 + (random.uniform(-0.15, 0.15) if s[4] else 0)
            s[1] -= (0.35 if s[4] else 0.18) - self.wind * 0.08
            s[2] += 1
        self.smoke = [s for s in self.smoke if s[2] < (25 if s[4] else 70 + 40 * s[3])]
        self.step_weather()
        self.step_life()
        if self.tower:
            now = self.clock()
            if now.minute == 0 and now.hour != self.ring_hour:   # saat başı: güvercinler havalanır
                self.ring_hour = now.hour
                cx = self.tower + TOWER_W / 2
                self.birds = [[cx + i * 3.0, 14.0 - (i % 2) * 2, i * 3] for i in range(random.randint(3, 5))]

    def step_life(self):
        for c in self.cats:
            try:
                next(c.script)
            except StopIteration:
                c.done = True
        self.cats = [c for c in self.cats if not c.done]

        # müzik notaları
        if self.system.music.playing and self.t % 14 == 0:
            wx, wy, _ = self.music_win
            self.notes.append([wx + 1.5, wy - 1, random.uniform(-0.12, 0.12), 0, random.random()])
        for n in self.notes:
            n[0] += n[2] + math.sin((self.t + n[4] * 50) * 0.15) * 0.08
            n[1] -= 0.18
            n[3] += 1
        self.notes = [n for n in self.notes if n[3] < 70]

        # uyku: evlerden Zzz yükselir
        if self.sleep > 0.6 and self.t % 45 == 0:
            h = random.choice([h for h in self.houses if h is not self.shop])
            self.zs.append([h.x + h.w * random.uniform(0.3, 0.7), h.top - 6, 0])
        for z in self.zs:
            z[0] += 0.08
            z[1] -= 0.12
            z[2] += 1
        self.zs = [z for z in self.zs if z[2] < 100]

        # havai fişek
        if self.event and self.event.fireworks and random.random() < 0.04 * self.scale:
            self.rockets.append([random.uniform(20, W - 20), float(GROUND), random.uniform(-1.6, -1.2),
                                 random.choice(FW_COLORS), random.uniform(6, 26)])
        for r in self.rockets:
            r[1] += r[2]
            if r[1] <= r[4]:
                n = random.randint(18, 28)
                for i in range(n):
                    a, sp = 2 * math.pi * i / n, random.uniform(0.45, 0.8)
                    self.sparks.append([r[0], r[1], math.cos(a) * sp, math.sin(a) * sp, 0, r[3]])
        self.rockets = [r for r in self.rockets if r[1] > r[4]]
        for sp in self.sparks:
            sp[0] += sp[2]
            sp[1] += sp[3]
            sp[2] *= 0.97
            sp[3] = sp[3] * 0.97 + 0.025
            sp[4] += 1
        self.sparks = [sp for sp in self.sparks if sp[4] < 45]

    def step_weather(self):
        w, k = self.weather, 0.01
        self.rain += (w.rain - self.rain) * k
        self.snow += (w.snow - self.snow) * k
        self.cloud += (w.cloud - self.cloud) * k
        self.fog += (w.fog - self.fog) * k
        self.wind += (w.windy - self.wind) * k
        if self.snow > 0.15:
            self.cover = min(1.0, self.cover + 0.0004 * self.snow)
        else:
            self.cover = max(0.0, self.cover - 0.00015)
        if self.rain > 0.1:
            self.wet = min(1.0, self.wet + 0.001 * self.rain)
        else:
            self.wet = max(0.0, self.wet - 0.0002)

        # yağmur damlaları: yere (kaldırım ya da yol) inince sıçrar
        slant = 0.15 + self.wind * 0.6
        n = self.rain * 6 * self.scale
        while n > 0:
            if random.random() < n:
                self.drops.append([random.uniform(-10, W + 50), random.uniform(-8, 0),
                                   random.uniform(2.2, 3.0), random.uniform(GROUND + 1, H - 1)])
            n -= 1
        for d in self.drops:
            d[1] += d[2]
            d[0] -= d[2] * slant
            if d[1] >= d[3] and random.random() < 0.5:
                self.splashes.append([d[0], d[3], 0])
        self.drops = [d for d in self.drops if d[1] < d[3]]
        for sp in self.splashes:
            sp[2] += 1
        self.splashes = [sp for sp in self.splashes if sp[2] < 3]
        if self.rain > 0.1 and self.wet > 0.3 and random.random() < self.rain * 0.6:
            self.ripples.append([random.choice(self.puddles) + random.uniform(1, 7), 0.0])
        for r in self.ripples:
            r[1] += 0.25
        self.ripples = [r for r in self.ripples if r[1] < 3]

        # kar taneleri: salınarak düşer
        n = self.snow * 1.5 * self.scale
        while n > 0:
            if random.random() < n:
                self.flakes.append([random.uniform(-10, W + 40), random.uniform(-4, 0), random.uniform(0.25, 0.5),
                                    random.uniform(0, 6.3), random.uniform(GROUND - 2, H - 1), random.random() < 0.3])
            n -= 1
        for f in self.flakes:
            f[1] += f[2]
            f[0] += math.sin(self.t * 0.06 + f[3]) * 0.2 - self.wind * 0.5
        self.flakes = [f for f in self.flakes if f[1] < f[4]]

        # şimşek: çift parlama ve zikzak yıldırım
        if self.flash:
            self.flash -= 1
        elif w.storm and self.rain > 0.5 and random.random() < 1 / (FPS * 7):
            self.flash, self.bolt = 5, self.make_bolt()

        # kayan yıldız: açık gecelerde ara sıra
        if self.meteor:
            m = self.meteor
            m[0] += m[2]
            m[1] += m[3]
            m[4] -= 1
            if m[4] <= 0:
                self.meteor = None
        elif self.cloud < 0.4 and self.fog < 0.3 and random.random() < 1 / (FPS * 120):
            self.meteor = [random.uniform(40, W), random.uniform(2, 12), -random.uniform(1.5, 2.5),
                           random.uniform(0.5, 1.0), random.randint(10, 16)]

    @staticmethod
    def make_bolt():
        x, y, pts = random.uniform(20, W - 20), 4.0, []
        end = random.choice((GROUND - 20, GROUND, FEET))
        branch = None
        while y < end:
            pts.append((x, y))
            x += random.choice((-1, -1, 0, 1, 1)) * (2 if random.random() < 0.15 else 1)
            y += 1
            if branch is None and y > 14 and random.random() < 0.1:
                branch = (x, y)
        if branch:
            bx, by = branch
            for _ in range(random.randint(5, 10)):
                bx += random.choice((-1, 1, 1))
                by += 1
                pts.append((bx, by))
        return pts

    # ---- çizim ----

    def tint(self, c):
        k = self.light
        return (c[0] * (0.35 + 0.65 * k), c[1] * (0.4 + 0.6 * k), c[2] * (0.6 + 0.4 * k))

    def px(self, x, y, w, h, c, glow=False, alpha=1.0):
        c = color(c)
        c = c if glow else self.tint(c)
        self.ctx.set_source_rgba(c[0], c[1], c[2], alpha)
        # yarım piksel ızgarası: çözünürlük 2 kat
        self.ctx.rectangle(round(x * 2) / 2, round(y * 2) / 2, round(w * 2) / 2, round(h * 2) / 2)
        self.ctx.fill()

    def glow(self, cx, cy, r, c, alpha):
        """Yarım piksel adımlı, kenara doğru sönen yuvarlak ışık."""
        for k in (1.0, 0.7, 0.45):
            rr = r * k
            y = -rr
            while y <= rr:
                half = round(math.sqrt(max(0.0, rr * rr - y * y)) * 2) / 2
                if half:
                    self.px(cx - half, cy + y, half * 2, 0.5, c, glow=True, alpha=alpha)
                y += 0.5

    def draw(self, ctx):
        self.ctx = ctx
        ctx.save()
        ctx.rectangle(0, 0, W, H)
        ctx.clip()
        self.draw_scene()
        ctx.restore()
        ctx.save()
        ctx.translate(W, 0)   # tüpler sağda
        self.draw_tubes()
        ctx.restore()

    def draw_scene(self):
        night = self.light < 0.5
        cover = round(self.cover, 1)
        self.draw_sky()
        for x, y, vy, c, _ in self.rockets:
            self.px(x, y, 0.5, 1.5, '#ffe9a8', glow=True)
            self.px(x, y + 1.5, 0.5, 2, c, glow=True, alpha=0.4)
        for x, y, _, _, age, c in self.sparks:
            self.px(x, y, 0.5, 0.5, c, glow=True, alpha=1 - age / 45)
        for bx, by, ph in self.birds:
            up = (self.t // 3 + ph) % 2
            self.px(bx, by, 1, 1, '#333333')
            self.px(bx - 1, by - up, 1, 1, '#333333')
            self.px(bx + 1, by - up, 1, 1, '#333333')

        lit = tuple(w[2] for h in self.houses for w in h.windows)
        self.layer('houses', (self.light, cover, lit, self.shop_lit[0], tuple(bool(h.open) for h in self.houses)),
                   lambda: [(self.draw_house(h, night), self.draw_roof_snow(h, cover)) for h in self.houses])
        if self.tower:
            self.layer('tower', (self.light, cover), lambda: self.draw_tower(night, cover))
            self.draw_tower_clock(night)
        self.draw_decor(night)
        self.draw_battery_sign(self.shop)
        self.draw_music_window()
        for c in self.cats:
            if c.y < GROUND:
                self.draw_cat(c, night)
        for x, y, age in self.zs:
            self.text('Z', x, y, 0.5 if age < 40 else 0.75, '#cfd8ff',
                      alpha=(1 - age / 100) * self.sleep)
        self.draw_chimney_heat()
        for sx, sy, age, f, ember in self.smoke:
            if ember:
                self.px(sx, sy, 0.5, 0.5, '#ffb347', glow=True, alpha=1 - age / 25)
                continue
            life = 70 + 40 * f
            size = min(4, 1 + age // 25)
            c = mix('#c9b3b0', '#ff4a3d', f * 0.75)   # hep hafif kızıl; GPU ısındıkça kıpkırmızı
            self.px(sx - size / 2 + 0.5, sy, size, size, c, glow=f > 0.5,
                    alpha=max(0.0, 0.8 - age / life) * (0.75 if f > 0.5 else 1))
        for i, tx in enumerate(self.trees):
            self.draw_tree(tx, i)
        if self.sleep > 0.5:
            self.draw_owl((self.sleep - 0.5) * 2)
        for x, y, _, age, hue in self.notes:
            c = colorsys.hsv_to_rgb((hue + self.t * 0.005) % 1, 0.45, 1)
            self.text('♪', x, y, 0.5, c, alpha=min(1.0, (70 - age) / 25))
        if self.market_on:
            self.draw_stall(night)

        self.layer('ground', (self.light, cover), lambda: self.draw_ground(night, cover))
        self.draw_puddles()

        for c in self.cats:
            if c.y >= GROUND:
                self.draw_cat(c, night)
        for p in self.people:
            if p.visible:
                self.px(p.x, FEET, 4, 1, '#000000', alpha=0.18)
                self.draw_person(p)
            if p.dog and p.visible:
                self.draw_dog(p.dog, p)

        self.layer('road', (self.light, round(self.wet, 1), cover), self.draw_road)
        self.draw_truck(night)
        for cx, _, c in self.cars:
            self.draw_car(cx, c, night)
        self.layer('lamps', (self.light, cover, round(self.fog, 1)),
                   lambda: [self.draw_lamp(lx, night) for lx in self.lamps])
        self.draw_weather()

    def draw_sky(self):
        dark = max(0.0, 1 - self.light * 2)          # yıldız ve ay yalnızca gece
        kind, k = self.twi
        if k > 0:
            k = round(k * (1 - 0.6 * self.cloud), 2)
            self.layer('twilight', (kind, k), lambda: self.draw_twilight(kind, k))
        vis = dark * (1 - self.cloud) * (1 - self.fog) * (1 - 0.8 * k)
        if vis > 0.02:
            for x, y, ph, sp, big, c in self.stars:
                a = vis * (0.3 + 0.35 * (1 + math.sin(self.t * sp + ph)))
                if big:
                    self.px(x, y, 1, 1, c, glow=True, alpha=a)
                    self.px(x - 0.5, y + 0.25, 2, 0.5, c, glow=True, alpha=a * 0.4)
                    self.px(x + 0.25, y - 0.5, 0.5, 2, c, glow=True, alpha=a * 0.4)
                else:
                    self.px(x, y, 0.5, 0.5, c, glow=True, alpha=a)
            if self.meteor:
                mx, my, vx, vy, life = self.meteor
                for i in range(8):
                    self.px(mx - vx * i * 0.5, my - vy * i * 0.5, 0.5, 0.5, '#ffffff', glow=True,
                            alpha=vis * (1 - i / 8) * min(1.0, life / 4))
        moon = dark * (1 - self.cloud * 0.85) * (1 - self.fog * 0.6)
        if moon > 0.02:
            phase = round(moon_phase(), 2)
            self.layer('moon', phase, lambda: self.draw_moon(phase), alpha=moon)

        # bulutlar: sayısı bulutluluğa göre, yağmurda koyulaşır, şimşekte aydınlanır
        dark_k = min(1.0, self.rain * 1.3 + self.snow * 0.3)
        base = mix('#ffffff', '#4a5160', dark_k)
        lit = self.flash in (5, 3)
        for i, (cx, cy, cw, _) in enumerate(self.clouds):
            a = max(0.0, min(1.0, self.cloud * len(self.clouds) - i)) * 0.85
            if a <= 0:
                continue
            top, bottom = (mix(base, '#dfe8ff', 0.6), base) if lit else (base, shade(base, 0.82))
            self.px(cx, cy + 2, cw, 3, top, glow=lit, alpha=a)
            self.px(cx + 3, cy, cw // 2, 2, top, glow=lit, alpha=a)
            self.px(cx + cw // 2, cy + 1, cw // 3, 1, top, glow=lit, alpha=a)
            self.px(cx + 1, cy + 4, cw - 2, 1, bottom, glow=lit, alpha=a)

    def draw_moon(self, phase):
        """Gerçek ay evresi: aydınlık kısım, sönük kısım ve birkaç krater."""
        cx, cy, r = self.moon_x, MOON_Y, MOON_R
        self.glow(cx, cy, r + 5, '#f4f1de', 0.03)
        c = math.cos(2 * math.pi * phase)

        def lit_span(yc):
            half = math.sqrt(max(0.0, r * r - yc * yc))
            a, b = (half * c, half) if phase < 0.5 else (-half, -half * c)
            return half, round(a * 2) / 2, round(b * 2) / 2

        y = -r
        while y < r:
            half, a, b = lit_span(y + 0.25)
            hw = round(half * 2) / 2
            if hw:
                self.px(cx - hw, cy + y, 2 * hw, 0.5, '#1c2130', glow=True, alpha=0.95)
            if b > a:
                self.px(cx + a, cy + y, b - a, 0.5, '#f4f1de', glow=True)
            y += 0.5
        for dx, dy, size in ((-2, -1.5, 1), (1, 1, 1.5), (-1, 2, 0.5), (2, -2.5, 0.5)):
            _, a, b = lit_span(dy + 0.25)
            if a <= dx and dx + size <= b:
                self.px(cx + dx, cy + dy, size, size, '#cfc9ae', glow=True)

    def draw_puddles(self):
        if self.wet < 0.05:
            return
        a = self.wet
        for x in self.puddles:
            self.px(x + 1, FEET + 0.5, 6, 0.5, '#1d2738', glow=True, alpha=0.8 * a)
            self.px(x, FEET + 1, 8, 0.5, '#1d2738', glow=True, alpha=0.8 * a)
            if self.light < 0.5 and any(abs(x + 4 - lx) < 12 for lx in self.lamps):
                self.px(x + 3, FEET + 0.5, 2, 1, '#ffe08a', glow=True, alpha=0.45 * a)
        for rx, age in self.ripples:
            ra = 0.6 * (1 - age / 3) * a
            self.px(rx - age * 0.5, FEET + 0.5, 0.5, 0.5, '#9fc4e8', glow=True, alpha=ra)
            self.px(rx + age * 0.5, FEET + 0.5, 0.5, 0.5, '#9fc4e8', glow=True, alpha=ra)

    def draw_weather(self):
        for x, y, _, _ in self.drops:
            a, c = 0.32, '#9cc3e6'
            for lx in self.lamps:   # lamba ışığına giren damla parlar
                if 52 < y < FEET and abs(x - lx) < 2 + (y - 52) * 0.45:
                    a, c = 0.75, '#ffe9a8'
                    break
            self.px(x, y, 0.5, 1.5, c, glow=True, alpha=a)
        for x, y, age in self.splashes:
            self.px(x - 0.5 - age * 0.5, y - 0.5 - (age == 1) * 0.5, 0.5, 0.5, '#bcd7ef', glow=True, alpha=0.5)
            self.px(x + 0.5 + age * 0.5, y - 0.5 - (age == 1) * 0.5, 0.5, 0.5, '#bcd7ef', glow=True, alpha=0.5)
        for x, y, _, _, _, big in self.flakes:
            size = 1 if big else 0.5
            self.px(x, y, size, size, '#ffffff', glow=True, alpha=0.85)
        if self.fog > 0.02:
            self.px(0, 0, W, H, '#8090a0', glow=True, alpha=0.05 * self.fog)
            for x0, y, w, h, sp in self.fog_blobs:
                x = (x0 + self.t * sp) % (W + 60) - 30
                for k in range(3):   # uçları yuvarlanmış, ortası yoğun bulut şerit
                    inset = k * w * 0.18
                    self.px(x + inset, y + k * h / 6, w - 2 * inset, h - k * h / 3, '#aab4c3',
                            glow=True, alpha=0.03 * self.fog)
        if self.flash:
            self.px(0, 0, W, H, '#dfe8ff', glow=True, alpha=(0.22, 0.05, 0.3, 0.1, 0.04)[5 - self.flash])
            if self.flash in (5, 3):
                for bx, by in self.bolt:
                    self.px(bx - 1, by, 3, 1, '#bcd0ff', glow=True, alpha=0.3)
                    self.px(bx, by, 1, 1, '#ffffff', glow=True)

    def draw_roof_snow(self, h, cover):
        if not cover:
            return
        if h.kind == 'gable':
            rows = min(10, (h.w + 4) // 2 - 1)
            for i in range(rows):   # her basamağın açıkta kalan iki köşesi
                self.px(h.x - 2 + i, h.top - 1.5 - i, 1, 0.5, SNOW_WHITE, alpha=cover)
                self.px(h.x + h.w + 1 - i, h.top - 1.5 - i, 1, 0.5, SNOW_WHITE, alpha=cover)
            self.px(h.x - 3 + rows, h.top - rows - 0.5, h.w + 6 - 2 * rows, 1, SNOW_WHITE, alpha=cover)
        else:
            self.px(h.x - 1, h.top - 3, h.w + 2, 1, SNOW_WHITE, alpha=cover)
        if h.chimney:
            self.px(h.chimney[0] - 1, h.chimney[1] - 0.5, 5, 0.5, SNOW_WHITE, alpha=cover)
        if h.kind == 'shop':
            self.px(h.x, GROUND - 16.5, h.w, 0.5, SNOW_WHITE, alpha=cover)

    def draw_snowman(self, x):
        g = GROUND
        self.px(x + 1, g - 4, 3, 1, SNOW_WHITE)
        self.px(x, g - 3, 5, 3, SNOW_WHITE)
        self.px(x + 1, g - 7, 3, 3, SNOW_WHITE)
        self.px(x + 1, g - 9, 3, 1.5, '#222222')
        self.px(x + 0.5, g - 7.5, 4, 0.5, '#222222')
        self.px(x + 1.5, g - 6, 0.5, 0.5, '#222222')
        self.px(x + 3, g - 6, 0.5, 0.5, '#222222')
        self.px(x + 3.5, g - 5.5, 1, 0.5, '#e67e22')
        self.px(x + 1, g - 4, 3, 0.5, '#c0392b')
        self.px(x + 2.25, g - 2.5, 0.5, 0.5, '#222222')
        self.px(x + 2.25, g - 1.5, 0.5, 0.5, '#222222')

    def text(self, s, x, y, u, c, glow=True, alpha=1.0):
        cells, _ = text_cells(s)
        x, y = math.floor(x * 2 + 0.5) / 2, math.floor(y * 2 + 0.5) / 2   # yarım piksel ızgarasına oturt
        for cx, cy in cells:
            self.px(x + cx * u, y + cy * u, u, u, c, glow=glow, alpha=alpha)

    def text_bubble(self, s, cx, bottom):
        w = text_cells(s)[1] * 0.5
        x = cx - w / 2
        self.px(x - 1, bottom - 5, w + 2, 4.5, '#f5f5f5', glow=True, alpha=0.9)
        self.px(cx - 0.5, bottom - 0.5, 1, 0.5, '#f5f5f5', glow=True, alpha=0.9)
        self.text(s, x, bottom - 4.25, 0.5, '#2d3436')

    def draw_twilight(self, kind, k):
        top, mid, low = (('#1a2350', '#7a3b6e', '#ff9e5e') if kind == 'dusk'
                         else ('#1c2a5c', '#8a4a7a', '#ffc178'))
        for y in range(GROUND):
            f = y / GROUND
            c = mix(top, mid, f / 0.6) if f < 0.6 else mix(mid, low, (f - 0.6) / 0.4)
            self.px(0, y, W, 1, c, glow=True, alpha=k * (0.12 + 0.6 * f ** 1.6))

    def draw_cat(self, c, night):
        if c.state == 'sleep':
            rows = CAT_SLEEP
        elif c.state == 'walk':
            rows = CAT_WALK[(self.t // 3) % 2]
        else:
            rows = CAT_SIT[(self.t // 12 + c.phase) % 2]
        w = len(rows[0])
        blink = (self.t + c.phase) % 90 < 3
        for r, row in enumerate(rows):
            y = c.y - (len(rows) - r) * 0.5
            for i, v in enumerate(row):
                if v == '.':
                    continue
                x = c.x + (i if c.dir > 0 else w - 1 - i) * 0.5
                if v == 'e' and not blink:
                    self.px(x, y, 0.5, 0.5, '#d4ff5a' if night else '#222222', glow=night)
                else:
                    self.px(x, y, 0.5, 0.5, c.color)
        if c.state == 'sleep' and self.t % 60 < 40:
            self.text('Z', c.x + 3, c.y - 4 - (self.t % 60) * 0.03, 0.5, '#cfd8ff', alpha=0.8)

    def draw_owl(self, a):
        x, y = self.trees[2] + self.tree_sway(2) + 1.5, GROUND - 16
        self.px(x, y - 4, 3, 4, '#6d4c33', alpha=a)
        self.px(x + 0.5, y - 2, 2, 1.5, '#a1887f', alpha=a)
        self.px(x, y - 4.5, 0.5, 0.5, '#6d4c33', alpha=a)
        self.px(x + 2.5, y - 4.5, 0.5, 0.5, '#6d4c33', alpha=a)
        if (self.t % 70) >= 3:
            self.px(x + 0.5, y - 3.5, 0.5, 0.5, '#ffd34d', glow=True, alpha=a)
            self.px(x + 2, y - 3.5, 0.5, 0.5, '#ffd34d', glow=True, alpha=a)

    def draw_music_window(self):
        if not self.system.music.playing:
            return
        wx, wy, _ = self.music_win
        beat = 0.75 + 0.25 * abs(math.sin(self.t * 0.35))
        c = colorsys.hsv_to_rgb((self.t * 0.01) % 1, 0.55, 1)
        self.glow(wx + 2.5, wy + 2.5, 6, c, 0.05 * beat)
        self.px(wx, wy, 5, 5, tuple(v * beat for v in c), glow=True)
        self.px(wx + 2.25, wy, 0.5, 5, '#f5f5f5')
        self.px(wx, wy + 2.25, 5, 0.5, '#f5f5f5')

    def draw_tower(self, night, cover):
        """Saat kulesinin değişmeyen kısmı: taş gövde, çan odası, bakır çatı, kadran."""
        x, top = self.tower, TOWER_TOP
        stone, dark, light = '#b9a58a', '#8f7d64', '#d8c7a8'
        self.px(x, top, TOWER_W, GROUND - top, stone)
        self.px(x + TOWER_W - 2, top, 2, GROUND - top, dark)
        for y in range(top + 4, GROUND, 5):                            # taş sıraları
            self.px(x, y, TOWER_W, 0.5, dark)
            off = 3 if (y // 5) % 2 else 6
            for sx in range(int(x) + off, int(x) + TOWER_W - 2, 6):
                self.px(sx, y - 4.5, 0.5, 4.5, dark)
        self.px(x - 1, top - 1, TOWER_W + 2, 1.5, light)                # korniş
        self.px(x - 1, 40, TOWER_W + 2, 1, light)
        self.px(x - 1, GROUND - 2, TOWER_W + 2, 2, dark)                # kaide
        # kemerli kapı ve dar pencere
        self.px(x + 5, GROUND - 9, 6, 9, '#4a2e1e')
        self.px(x + 6, GROUND - 10, 4, 1, '#4a2e1e')
        self.px(x + 4, GROUND - 10, 8, 0.5, light)
        self.px(x + 7.75, GROUND - 9, 0.5, 9, '#2e1c12')
        self.px(x + 7, 44, 2, 5, '#ffcf6b' if night else '#2a2230', glow=night, alpha=0.9)
        self.px(x + 7, 43, 2, 1, light)
        # çan odası: iki sütun arasında kemer
        bt = top - 10
        self.px(x, bt, TOWER_W, 9, stone)
        self.px(x + 3, bt + 1, TOWER_W - 6, 8, '#1d1824')
        self.px(x + 4, bt + 0.5, TOWER_W - 8, 0.5, '#1d1824')
        if night:
            self.px(x + 3, bt + 1, TOWER_W - 6, 8, '#ffcf6b', glow=True, alpha=0.12)
        self.px(x - 1, bt - 1, TOWER_W + 2, 1, light)
        # bakır (yeşil pas) basamaklı çatı ve tepelik
        roof, roof_hi = '#4f8a76', '#6fb39a'
        rt = bt - 2
        for i in range(8):
            w = TOWER_W + 2 - 2 * i
            self.px(x - 1 + i, rt - i, w, 1, roof if i % 2 else shade(roof, 0.88))
            self.px(x - 1 + i, rt - i, 1, 1, roof_hi)
            if cover:
                self.px(x - 1 + i, rt - i - 0.5, 1, 0.5, SNOW_WHITE, alpha=cover)
                self.px(x + TOWER_W - i, rt - i - 0.5, 1, 0.5, SNOW_WHITE, alpha=cover)
        cx = x + TOWER_W / 2
        self.px(cx - 0.25, rt - 12, 0.5, 5, '#c9a227', glow=night)
        self.px(cx - 0.75, rt - 12.5, 1.5, 1, '#e0b83a', glow=night)
        # kadran: krem disk, koyu çerçeve, saat çizgileri
        fx, fy, r = cx, top + 7.5, 5.5
        if night:
            self.glow(fx, fy, r + 4, '#ffe9b0', 0.05)
        y = -r
        while y < r:
            half = round(math.sqrt(max(0.0, r * r - (y + 0.25) ** 2)) * 2) / 2
            if half:
                self.px(fx - half - 0.5, fy + y, 2 * half + 1, 0.5, '#3a2f25')
                self.px(fx - half + 0.5, fy + y, max(0.0, 2 * half - 1), 0.5, '#f4ecd8', glow=night)
            y += 0.5
        for k in range(12):
            a = k / 12 * 2 * math.pi
            size = 1 if k % 3 == 0 else 0.5
            self.px(fx + math.sin(a) * 4 - size / 2, fy - math.cos(a) * 4 - size / 2, size, size, '#3a2f25')

    def draw_tower_clock(self, night):
        """Akrep, yelkovan, saniye ibresi ve saat başı sallanan çan."""
        now = self.clock()
        cx = self.tower + TOWER_W / 2
        fx, fy = cx, TOWER_TOP + 7.5
        hours = now.hour % 12 + now.minute / 60
        mins = now.minute + now.second / 60
        for angle, length, c in ((hours / 12, 2.8, '#1e1a16'), (mins / 60, 4.2, '#1e1a16'),
                                 (now.second / 60, 4.2, '#d63031')):
            a = angle * 2 * math.pi
            r = 0.0
            while r <= length:
                self.px(fx + math.sin(a) * r - 0.25, fy - math.cos(a) * r - 0.25, 0.5, 0.5, c)
                r += 0.5
        self.px(fx - 0.5, fy - 0.5, 1, 1, '#c9a227')
        # çan: saat başında saat sayısı kadar sallanır, ses halkaları yayılır
        dongs = now.hour % 12 or 12
        ringing = now.minute == 0 and now.second < dongs * 1.5
        swing = math.sin(self.t * 0.55) * 0.7 if ringing else 0.0
        bt = TOWER_TOP - 10
        for i, (w, y) in enumerate(((1, bt + 2), (2, bt + 2.5), (3, bt + 3), (3, bt + 4), (4, bt + 5), (5, bt + 6))):
            off = swing * i * 0.6
            self.px(cx - w / 2 + off, y, w, 0.5 if i < 3 else 1, '#d4a72c', glow=night)
        self.px(cx - 0.25 + swing * 4.5, bt + 7, 0.5, 0.5, '#8a6a1c', glow=night)
        if ringing:
            k = (self.t % 18) / 18
            for side in (-1, 1):
                rx = cx + side * (TOWER_W / 2 + 1 + k * 6)
                for dy in (-1, 0, 1):
                    self.px(rx - side * abs(dy) * 0.5, bt + 4 + dy * 1.5, 0.5, 1, '#ffe9b0', glow=True,
                            alpha=0.7 * (1 - k))

    def draw_chimney_heat(self):
        """GPU çok ısınınca baca ağızları kor gibi parlar."""
        if self.heat <= 0.6:
            return
        a = (self.heat - 0.6) * 1.5 * (0.7 + 0.3 * math.sin(self.t * 0.5))
        for h in self.houses:
            if h.chimney:
                cx, ct = h.chimney
                self.px(cx - 0.5, ct - 0.5, 4, 1, '#ff6a3d', glow=True, alpha=a)

    def draw_battery_sign(self, h):
        """Dükkân tabelası pil göstergesi: doluluk, yüzde, fişe takılıysa kablo ve şimşek."""
        b = self.system.battery
        if b.level is None:
            return
        x0, y0, sw = h.x + 4, h.top + 2, h.w - 8
        self.px(x0, y0, sw, 7, '#3f7f5f')
        self.px(x0 + 1, y0 + 0.5, sw - 2, 6, '#14261d')
        bw, edge = 17, '#e9f5ee'
        bx = x0 + 2 if b.plugged else x0 + (sw - bw - 1) / 2
        by = y0 + 1
        # gövde ve uç
        self.px(bx, by, bw, 0.5, edge, glow=True)
        self.px(bx, by + 4.5, bw, 0.5, edge, glow=True)
        self.px(bx, by, 0.5, 5, edge, glow=True)
        self.px(bx + bw - 0.5, by, 0.5, 5, edge, glow=True)
        self.px(bx + bw, by + 1.5, 1, 2, edge, glow=True)
        # doluluk (koyu tonlar: üstündeki yazı okunsun)
        col = '#b83227' if b.level < 20 else '#b7791f' if b.level < 50 else '#1f8a55'
        inner = bw - 1
        fill = inner * b.level / 100
        self.px(bx + 0.5, by + 0.5, fill, 4, col, glow=True)
        if b.charging and fill < inner:
            extra = ((self.t // 3) % 8) / 7 * (inner - fill)
            self.px(bx + 0.5 + fill, by + 0.5, extra, 4, col, glow=True, alpha=0.45)
        # yüzde ve şimşek ortada
        label = str(b.level)
        tw = text_cells(label)[1] * 0.5
        total = tw + (2.5 if b.plugged else 0)
        tx = math.floor((bx + (bw - total) / 2) * 2) / 2   # yarım piksel ızgarası
        self.text(label, tx, by + 1, 0.5, '#f5fff9')
        if b.plugged and (not b.charging or (self.t // 6) % 2):
            bolt = ('..##', '.##.', '##..', '####', '..##', '.##.', '##..', '#...')
            for cy, row in enumerate(bolt):
                for cx, v in enumerate(row):
                    if v == '#':
                        self.px(tx + tw + 0.5 + cx * 0.5, by + 0.5 + cy * 0.5, 0.5, 0.5, '#ffe14d', glow=True)
        if b.plugged:   # kablo ve fiş
            self.px(bx + bw + 1, by + 2.25, 2.5, 0.5, '#9aa5ad', glow=True)
            self.px(bx + bw + 3.5, by + 1, 2, 3, '#cfd6db', glow=True)
            self.px(bx + bw + 5.5, by + 1.5, 1.5, 0.5, '#e0c068', glow=True)
            self.px(bx + bw + 5.5, by + 3, 1.5, 0.5, '#e0c068', glow=True)

    def draw_decor(self, night):
        ev = self.event
        if not ev:
            return
        if ev.kind in ('flags', 'halfmast'):
            for h in self.houses:
                if h.kind == 'gable':
                    rows = min(10, (h.w + 4) // 2 - 1)
                    self.draw_flag(h.x + h.w / 2 - 0.25, h.top - rows, ev.kind == 'halfmast')
                else:
                    self.draw_flag(h.x + 2, h.top - 2, ev.kind == 'halfmast')
        elif ev.kind in ('bayram', 'newyear'):
            pts = self.garland
            for x, y in pts[::2]:
                self.px(x, y, 0.5, 0.5, '#5a5a5a', alpha=0.8)
            step = 5 if ev.kind == 'bayram' else 2
            for i, (x, y) in enumerate(pts[::step]):
                c = DECOR_COLORS[i % len(DECOR_COLORS)]
                if ev.kind == 'bayram':      # kâğıt fenerler
                    self.px(x - 0.25, y, 1, 0.5, '#444444')
                    self.px(x - 0.5, y + 0.5, 1.5, 2, c, glow=night)
                    if night:
                        self.px(x - 1.5, y - 0.5, 3.5, 4, c, glow=True, alpha=0.12)
                elif (i + self.t // 5) % 3:  # yılbaşı ışıkları, kayan yanıp sönme
                    self.px(x, y + 0.5, 0.5, 1, c, glow=True)
                    self.px(x - 0.5, y, 1.5, 2, c, glow=True, alpha=0.2)
        elif ev.kind == 'birthday':
            for j, h in enumerate(self.houses):
                base_x, base_y = h.door_x + 2.5, GROUND - 10
                for k, dx in enumerate((-2.5, 0, 2.5)):
                    c = DECOR_COLORS[(j + k) % len(DECOR_COLORS)]
                    bob = math.sin(self.t * 0.08 + j + k) * 0.5
                    bx, by = base_x + dx, base_y - 7 - (k == 1) * 2 + bob
                    for i in range(5):
                        u = i / 5
                        self.px(bx + (base_x - bx) * u, by + 1.5 + (base_y - by - 1.5) * u, 0.5, 0.5, '#dddddd')
                    self.px(bx - 1, by - 1.5, 2, 2.5, c, glow=night)
                    self.px(bx - 0.5, by - 1, 0.5, 0.5, '#ffffff', glow=night)

    def draw_flag(self, x, top, half):
        pole = 10
        self.px(x, top - pole, 0.5, pole, '#cfcfcf', glow=True, alpha=0.8)
        self.px(x - 0.25, top - pole - 0.5, 1, 0.5, '#ffd34d', glow=True)
        fy = top - pole + (4.5 if half else 0.5)
        dys = [round(math.sin(self.t * 0.25 - cx * 0.6) * (0.4 + self.wind) * cx / 13 * 2) / 2 for cx in range(14)]
        for cx, dy in enumerate(dys):
            self.px(x + 0.5 + cx * 0.5, fy + dy, 0.5, 4.5, '#d40a1c', glow=True)
        for cx, cy in FLAG_WHITE:
            self.px(x + 0.5 + cx * 0.5, fy + dys[cx] + cy * 0.5, 0.5, 0.5, '#f2f2f2', glow=True)

    def draw_stall(self, night):
        x, g = STALL_X, FEET
        self.draw_person(self.vendor)
        self.px(x, g - 4, 12, 1, '#a1887f')
        self.px(x, g - 3, 12, 3, '#6d4c41')
        self.px(x + 1, g - 2, 10, 0.5, '#5d4037')
        for i in range(11):
            self.px(x + 0.5 + i, g - 5, 1, 1, ('#f39c12', '#e74c3c', '#27ae60', '#f1c40f')[i % 4])
        self.px(x, g - 11, 0.5, 7, '#555555')
        self.px(x + 11.5, g - 11, 0.5, 7, '#555555')
        for i in range(7):
            c = '#2e86de' if i % 2 else '#f5f5f5'
            self.px(x - 1 + i * 2, g - 12.5, 2, 1.5, c)
            self.px(x - 0.5 + i * 2, g - 11, 1, 0.5, c)
        self.px(x + 5.75, g - 10.5, 0.5, 0.5, '#fff3b0', glow=True)
        if night:
            self.glow(x + 6, g - 9, 5, '#ffe08a', 0.06)

    def layer(self, name, key, draw, dx=0, alpha=1.0):
        """Değişmeyen katmanı bir kez yüzeye çizer, anahtar değişene kadar yüzeyi basar."""
        ent = self.layers.get(name)
        if ent is None or ent[0] != key:
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (PANEL + W) * S, H * S)
            c = cairo.Context(surf)
            c.set_antialias(cairo.ANTIALIAS_NONE)
            c.scale(S, S)
            c.translate(dx, 0)
            outer, self.ctx = self.ctx, c
            try:
                draw()
            finally:
                self.ctx = outer
            ent = self.layers[name] = (key, surf)
        ctx = self.ctx
        ctx.save()
        ctx.identity_matrix()
        ctx.set_source_surface(ent[1], 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_NEAREST)
        ctx.paint_with_alpha(alpha)
        ctx.restore()

    def draw_ground(self, night, cover=0.0):
        # çimen, çiçekler, kaldırım
        self.px(0, GROUND, W, 1, '#7fb069')
        for x in self.tufts:
            self.px(x, GROUND - 1, 1, 1, '#5e9a4a')
        for i, fx in enumerate(range(8, 19, 2)):
            self.px(fx, GROUND - 1, 1, 1, ('#e74c3c', '#f1c40f', '#e84393')[i % 3])
            self.px(fx, GROUND, 1, 1, '#2e7d32')
        self.px(0, GROUND + 1, W, FEET - GROUND + 1, '#bdb6a8')
        self.px(0, GROUND + 1, W, 1, '#cfc9bc')
        for sx in range(0, W, 8):
            self.px(sx, GROUND + 1, 1, FEET - GROUND + 1, '#a9a293')

        for lx in self.lamps:
            if night:
                for i in range(2 * (FEET + 2 - 56)):
                    half = 1 + i / 6
                    self.px(lx + 0.5 - half, 56 + i / 2, 2 * half, 0.5, '#ffe08a', glow=True,
                            alpha=0.11 - i * 0.002)
                self.px(lx - 7, FEET, 15, 1.5, '#ffe08a', glow=True, alpha=0.12)

        if cover:
            self.px(0, GROUND - 0.5, W, 1.5, SNOW_WHITE, alpha=cover)
            rng = random.Random(5)
            for _ in range(int(160 * cover)):
                self.px(rng.uniform(0, W), rng.uniform(GROUND + 1, FEET + 1), 1, 0.5, SNOW_WHITE, alpha=0.8)
            if cover >= 0.7:
                self.draw_snowman(0)

    def draw_road(self):
        # bordür ve yol
        self.px(0, FEET + 2, W, 1, '#e2ded6')
        self.px(0, FEET + 3, W, 1, '#8c8679')
        self.px(0, FEET + 4, W, H - FEET - 4, '#4a4a52')
        for dx in range(0, W, 10):
            self.px(dx, 82, 6, 1, '#e8e1a0')
        wet, cover = round(self.wet, 1), round(self.cover, 1)
        if wet:   # ıslak asfalt: koyu parlaklık ve lamba yansımaları
            self.px(0, FEET + 4, W, H - FEET - 4, '#2a3550', alpha=wet * 0.35)
            if self.light < 0.5:
                for lx in self.lamps:
                    for i in range(10):
                        self.px(lx - 1 + (i % 2) * 0.5, FEET + 4 + i, 2.5, 1, '#ffe08a', glow=True,
                                alpha=wet * 0.22 * (1 - i / 10))
        if cover:
            self.px(0, FEET + 4, W, 1, SNOW_WHITE, alpha=cover * 0.8)
            rng = random.Random(6)
            for _ in range(int(40 * cover)):
                self.px(rng.uniform(0, W), FEET + 5 + rng.random() * 2, 1, 0.5, SNOW_WHITE, alpha=0.6)

    def draw_tubes(self):
        night = self.light < 0.5
        self.layer('shelf', self.light, self.draw_shelf, dx=W)

        edge, glass = '#c9dce8', '#e6f6ff'
        iw = Tube.IW
        for tube in self.tubes:
            x, liq = tube.x, tube.liquid
            # ok simgesi
            for r, row in enumerate(tube.arrow):
                for c, ch in enumerate(row):
                    if ch == '#':
                        self.px(x + 1 + (iw - 5) / 2 + c, 2 + r, 1, 1, liq, glow=True)
            # mantar tıpa ve ağız
            self.px(x + 1, TUBE_TOP - 3, iw, 3, '#a9773f')
            self.px(x + 1, TUBE_TOP - 3, iw, 1, '#c8955a')
            self.px(x - 1, TUBE_TOP, iw + 4, 1, edge, alpha=0.9)
            # cam gövde
            body = TUBE_BOT - TUBE_TOP - 2
            self.px(x + 1, TUBE_TOP + 1, iw, body, glass, alpha=0.18)
            self.px(x + 2, TUBE_BOT - 1, iw - 2, 1, glass, alpha=0.18)
            # sıvı
            n = round(tube.level * Tube.INNER)
            if n > 0:
                glow = night
                self.px(x + 2, TUBE_BOT - 1, iw - 2, 1, liq, glow=glow)
                if n > 1:
                    self.px(x + 1, TUBE_BOT - n, iw, n - 1, liq, glow=glow)
                    self.px(x + iw - 1, TUBE_BOT - n, 2, n - 1, shade(liq, 0.8), glow=glow)
                    self.px(x + 1, TUBE_BOT - n, iw, 1, shade(liq, 1.3), glow=glow)
                for bx, by, _ in tube.bubbles:
                    self.px(x + 1 + bx, TUBE_BOT - 2 - by, 1, 1, shade(liq, 1.5), glow=True, alpha=0.8)
                if night:
                    self.px(x - 1, TUBE_BOT - n - 1, iw + 4, n + 2, liq, glow=True, alpha=0.08)
            # ölçek çizgileri (her biri 10 kat)
            for i in range(1, 5):
                y = TUBE_BOT - 1 - round(i / 5 * Tube.INNER)
                self.px(x + 1, y, 2, 1, edge, alpha=0.7)
            # cam kenarları ve parlama
            self.px(x, TUBE_TOP + 1, 1, body, edge)
            self.px(x + iw + 1, TUBE_TOP + 1, 1, body, edge)
            self.px(x + 1, TUBE_BOT - 1, 1, 1, edge)
            self.px(x + iw, TUBE_BOT - 1, 1, 1, edge)
            self.px(x + 2, TUBE_BOT, iw - 2, 1, edge)
            self.px(x + 2, TUBE_TOP + 3, 1, body - 8, '#ffffff', alpha=0.4)

    def draw_shelf(self):
        wood, wood_dark = '#8a6440', '#5e4329'
        # raf: arkadaki tahta, ayaklar ve taban
        self.px(1, 56, PANEL - 2, 3, wood)
        self.px(1, 58, PANEL - 2, 1, wood_dark)
        self.px(1, 59, 1, TUBE_BOT - 58, wood_dark)
        self.px(PANEL - 2, 59, 1, TUBE_BOT - 58, wood_dark)
        self.px(0, TUBE_BOT + 1, PANEL, 3, wood)
        self.px(0, TUBE_BOT + 1, PANEL, 1, '#b08a5f')
        self.px(0, TUBE_BOT + 3, PANEL, 1, wood_dark)

    def draw_house(self, h, night):
        wall, roof = hx(h.wall), hx(h.roof)
        self.px(h.x, h.top, h.w, h.h, wall)
        self.px(h.x + h.w - 2, h.top, 2, h.h, shade(wall, 0.86))
        self.px(h.x, GROUND - 2, h.w, 2, shade(wall, 0.72))
        if h.kind == 'gable':
            rows = min(10, (h.w + 4) // 2 - 1)
            for i in range(rows):
                c = roof if i % 2 else shade(roof, 0.9)
                self.px(h.x - 2 + i, h.top - 1 - i, h.w + 4 - 2 * i, 1, c)
                self.px(h.x - 2 + i, h.top - 1 - i, 1, 1, shade(roof, 1.25))
            self.px(h.x - 2 + rows - 1, h.top - rows, h.w + 6 - 2 * rows, 1, shade(roof, 1.2))
            self.px(h.x - 2, h.top, h.w + 4, 1, shade(roof, 0.65))
        else:
            self.px(h.x - 1, h.top - 2, h.w + 2, 2, roof)
            self.px(h.x - 1, h.top - 2, h.w + 2, 1, shade(roof, 1.25))
            self.px(h.x, h.top, h.w, 1, shade(wall, 0.75))
            if h.kind == 'flat':
                ax = h.x + h.w - 7
                self.px(ax, h.top - 9, 1, 7, '#555555')
                self.px(ax - 2, h.top - 7, 5, 1, '#555555')
                self.px(ax, h.top - 10, 1, 1, '#e74c3c', glow=night)
        if h.chimney:
            cx, ct = h.chimney
            bottom = h.top - (4 if h.kind == 'gable' else 2)
            self.px(cx, ct + 1, 3, bottom - ct - 1, '#8d4a3a')
            self.px(cx + 2, ct + 1, 1, bottom - ct - 1, '#6e392d')
            self.px(cx, ct + 2.5, 3, 0.5, '#6e392d')
            self.px(cx - 1, ct, 5, 1, '#5a2e24')

        for wx, wy, lit in h.windows:
            if lit:
                self.glow(wx + 2.5, wy + 2.5, 5, '#ffb52e', 0.07)
                self.px(wx - 0.5, wy - 0.5, 6, 6, '#ffb52e', glow=True, alpha=0.3)
                self.px(wx, wy, 5, 5, '#ffcf3f', glow=True)
                self.px(wx, wy + 3, 5, 2, '#ff9f1a', glow=True)
            else:
                self.px(wx, wy, 5, 5, '#1f2a40' if night else '#5f7f99')
                if not night:
                    self.px(wx, wy, 2, 2, '#9dbbd0')
            if lit:
                self.px(wx, wy, 1, 4.5, '#c0392b', glow=True, alpha=0.8)
                self.px(wx + 4, wy, 1, 4.5, '#c0392b', glow=True, alpha=0.8)
            self.px(wx + 2.25, wy, 0.5, 5, '#f5f5f5')
            self.px(wx, wy + 2.25, 5, 0.5, '#f5f5f5')
            self.px(wx - 1, wy + 5, 7, 1, '#f5f5f5')
            self.px(wx - 1, wy + 6, 7, 1, shade(wall, 0.8))

        if h.kind == 'shop':
            self.px(h.x + 4, h.top + 3, h.w - 8, 6, '#3f7f5f')
            self.px(h.x + 4, h.top + 8, h.w - 8, 1, '#2d5e45')
            for i in range(6):
                self.px(h.x + 7 + i * 4, h.top + 5, 2, 2, '#f5f5dc')
            for i in range(0, h.w, 3):
                stripe = '#d9534f' if (i // 3) % 2 == 0 else '#f5f5f5'
                self.px(h.x + i, GROUND - 16, 3, 3, stripe)
                self.px(h.x + i + 1, GROUND - 13, 1, 1, stripe)
            lit = self.shop_lit[0]
            self.px(h.x + 3, GROUND - 12, h.door - 6, 9, '#ffd85a' if lit else '#6f8fa8', glow=lit)
            if lit and night:
                self.px(h.x + 2, GROUND - 13, h.door - 4, 11, '#ffe9a8', glow=True, alpha=0.15)
            for i in range(3):
                self.px(h.x + 5 + i * 5, GROUND - 6, 3, 3, ('#e67e22', '#c0392b', '#27ae60')[i])

        self.px(h.door_x - 1, GROUND - 10, 7, 1, shade(wall, 0.65))
        self.px(h.door_x, GROUND - 9, 5, 9, '#1e1410' if h.open else '#6b4226')
        if not h.open:
            self.px(h.door_x + 1, GROUND - 8, 3, 3, '#5a3720')
            self.px(h.door_x + 3, GROUND - 5, 1, 1, '#e6c35c')
        self.px(h.door_x - 1, GROUND, 7, 1, '#9e978a')

    def tree_sway(self, i):
        return round(math.sin(self.t * (0.08 + self.wind * 0.12) + i * 1.7) * (0.6 + self.wind * 1.6))

    def draw_tree(self, tx, i):
        sway = self.tree_sway(i)
        self.px(tx - 1, GROUND - 1, 8, 1, '#000000', alpha=0.15)
        self.px(tx + 2, GROUND - 6, 2, 6, '#6b4423')
        self.px(tx + 3, GROUND - 6, 1, 6, '#523319')
        leaf, dark, light = '#4f9a3c', '#3d7a2e', '#6dbb4f'
        x = tx + sway
        self.px(x, GROUND - 14, 6, 8, leaf)
        self.px(x - 1, GROUND - 12, 8, 4, leaf)
        self.px(x + 1, GROUND - 16, 4, 2, leaf)
        self.px(x + 3, GROUND - 10, 3, 3, dark)
        self.px(x, GROUND - 8, 6, 1, dark)
        self.px(x + 1, GROUND - 15, 2, 1, light)
        self.px(x, GROUND - 13, 2, 2, light)
        self.px(x + 4, GROUND - 12, 1, 1, '#c0392b')
        if self.cover > 0.05:
            for sx, sy, sw in ((x + 1, GROUND - 16, 4), (x, GROUND - 14, 1), (x + 5, GROUND - 14, 1),
                               (x - 1, GROUND - 12, 1), (x + 6, GROUND - 12, 1)):
                self.px(sx, sy - 0.5, sw, 1, SNOW_WHITE, alpha=self.cover)

    def draw_lamp(self, lx, night):
        self.px(lx - 1, FEET + 1, 3, 1, '#2a2a2a')
        self.px(lx, 55, 1, FEET + 1 - 55, '#3a3a3a')
        self.px(lx - 2, 53, 5, 1, '#2a2a2a')
        self.px(lx - 1, 52, 3, 1, '#2a2a2a')
        if self.cover > 0.05:
            self.px(lx - 1, 51.5, 3, 0.5, SNOW_WHITE, alpha=round(self.cover, 1))
        if night:
            self.px(lx - 1, 54, 3, 1, '#fff6c8', glow=True)
            self.glow(lx + 0.5, 54.5, 6, '#ffe08a', 0.07)
            fog = round(self.fog, 1)
            if fog:
                self.glow(lx + 0.5, 54.5, 12, '#ffe08a', 0.035 * fog)
            self.px(lx - 0.5, 54, 2, 0.5, '#ffffff', glow=True)
        else:
            self.px(lx - 1, 54, 3, 1, '#d8d2b0')

    def draw_person(self, p):
        x, top = p.x, FEET - 8
        self.px(x, top, 4, 1, p.hair)
        self.px(x, top + 1, 4, 2, p.skin)
        self.px(x + (3 if p.dir > 0 else 0), top + 1, 1, 1, p.hair)
        self.px(x + (0 if p.dir > 0 else 3), top + 1, 1, 1, p.hair)
        self.px(x + (2 if p.dir > 0 else 1), top + 2, 1, 1, '#222222')
        self.px(x, top + 3, 4, 3, p.shirt)
        self.px(x, top + 5, 4, 1, shade(p.shirt, 0.8))
        if p.walking and p.frame:
            self.px(x + 1, top + 6, 2, 2, p.pants)
        else:
            self.px(x, top + 6, 1, 2, p.pants)
            self.px(x + 3, top + 6, 1, 2, p.pants)
        front = x + 4 if p.dir > 0 else x - 1
        if p.carry == 'box':
            bx = x + 2 if p.dir > 0 else x - 3
            self.px(bx, top + 2, 5, 4, '#b07a43')
            self.px(bx, top + 3, 5, 1, '#d9b380')
            self.px(bx + (0 if p.dir > 0 else 4), top + 4, 1, 1, p.skin)
        elif p.carry == 'bag':
            self.px(front, top + 4, 2, 3, '#f5f5f5')
            self.px(front, top + 4, 2, 1, '#d9534f')
        elif p.carry == 'simit':   # başında simit tablası
            self.px(x - 2, top - 1, 8, 0.5, '#8d6e63')
            for i in range(3):
                self.px(x - 1.5 + i * 2.5, top - 2, 2, 1, '#c68642')
                self.px(x - 1 + i * 2.5, top - 1.5, 1, 0.5, '#8d6e63')
            self.px(x + (3.5 if p.dir > 0 else 0), top - 0.5, 0.5, 3.5, p.skin)
        elif p.carry == 'boza':    # bakır güğüm
            self.px(front, top + 3.5, 2, 3, '#b87333')
            self.px(front + 0.5, top + 2.5, 1, 1, '#d4915a')
            self.px(front, top + 4, 2, 0.5, '#e0a96d')
        elif p.carry == 'can':
            cx = x + 4 if p.dir > 0 else x - 2
            self.px(cx, top + 4, 2, 2, '#7f8c8d')
            spout = cx + 2 if p.dir > 0 else cx - 1
            self.px(spout, top + 4, 1, 1, '#7f8c8d')
            if p.watering:
                for i in range(3):
                    self.px(spout, top + 5 + (self.t + i * 2) % 4, 1, 1, '#5dade2')
        if p.keys and (self.t // 4) % 2:
            self.px(front, top + 4.5, 0.5, 0.5, '#ffe08a', glow=True)
        if p.shout:
            self.text_bubble('BOZAAA', x + 2, top - 3)
        temp = self.weather.temp
        if self.snow > 0.2 or self.cover > 0.3 or (temp is not None and temp < COLD):
            self.px(x, top - 0.5, 4, 1, p.scarf)                       # bere
            self.px(x + 1.5, top - 1, 1, 0.5, '#ffffff')               # ponpon
            self.px(x, top + 3, 4, 1, shade(p.scarf, 0.9))             # atkı
            self.px(x - 0.5 if p.dir > 0 else x + 4, top + 3.5, 0.5, 1.5, p.scarf)
        if self.rain > 0.2 and p.carry != 'box':
            if p.umbrella:
                self.draw_umbrella(p, x, top)
            else:   # ceketi başına çekmiş
                self.px(x - 0.5, top - 1, 5, 1, p.shirt)
                self.px(x - 0.5, top, 0.5, 2.5, p.shirt)
                self.px(x + 4, top, 0.5, 2.5, p.shirt)

    def draw_umbrella(self, p, x, top):
        c, ux = p.umbrella, x + 2
        self.px(ux + (0.5 if p.dir > 0 else -1), top - 3, 0.5, 6, '#3a3a3a')   # sap
        self.px(ux - 4, top - 3, 8, 1, c)
        self.px(ux - 3, top - 4, 6, 1, c)
        self.px(ux - 1.5, top - 5, 3, 1, c)
        self.px(ux - 3, top - 4, 2, 0.5, shade(c, 1.35))                       # parlama
        for ex in (ux - 4, ux - 0.5, ux + 3):                                  # tel uçları
            self.px(ex, top - 2, 1, 0.5, shade(c, 0.7))
        self.px(ux - 0.25, top - 6, 0.5, 1, '#d0d0d0')

    def draw_dog(self, d, owner):
        x, y = d.x, FEET - 3
        self.px(x, FEET, 6, 1, '#000000', alpha=0.15)
        self.px(x, y, 5, 2, d.color)
        head = x + 5 if owner.dir > 0 else x - 2
        self.px(head, y - 1, 2, 2, d.color)
        self.px(head + (1 if owner.dir > 0 else 0), y - 1, 1, 1, '#111111')
        tail = x - 1 if owner.dir > 0 else x + 5
        self.px(tail, y - (self.t // 2) % 2, 1, 1, d.color)
        legs = (0, 3) if (self.t // 2) % 2 else (1, 2)
        for lx in legs:
            self.px(x + lx + (1 if lx > 1 else 0), y + 2, 1, 1, d.color)

    def draw_truck(self, night):
        t = self.truck
        if t.state == 'away':
            return
        x = t.x
        self.px(x, 68, 21, 12, '#e9e4d8')
        self.px(x, 68, 21, 1, '#f7f4ec')
        self.px(x, 79, 21, 1, '#bdb6a6')
        if t.state == 'parked':
            self.px(x + 1, 69, 19, 10, '#3b3226')
            for i in range(t.boxes):
                self.px(x + 2 + (i % 3) * 6, 75 - (i // 3) * 4, 5, 4, '#b07a43')
                self.px(x + 2 + (i % 3) * 6, 76 - (i // 3) * 4, 5, 1, '#d9b380')
        else:
            self.px(x, 73, 21, 2, '#2f6db5')
        self.px(x + 21, 71, 9, 9, '#c8423a')
        self.px(x + 21, 71, 9, 1, '#e0675e')
        self.px(x + 24, 72, 5, 3, '#bfe3f2')
        self.px(x + 22, 79, 9, 1, '#555555')
        if night:
            self.px(x + 30, 77, 1, 1, '#fff3b0', glow=True)
            self.px(x + 31, 76, 6, 3, '#fff3b0', glow=True, alpha=0.15)
        for wx in (x + 3, x + 23):
            self.px(wx, 80, 3, 3, '#1c1c1c')
            spin = (self.t // 2) % 2 if t.moving else 1
            self.px(wx + 2 * spin, 81, 1, 1, '#9e9e9e')

    def draw_car(self, x, c, night):
        self.px(x + 4, 80, 8, 3, c)
        self.px(x + 4, 80, 8, 1, shade(c, 1.2))
        self.px(x + 5, 81, 6, 2, '#bfe3f2')
        self.px(x + 8, 81, 1, 2, c)
        self.px(x, 83, 16, 4, c)
        self.px(x, 83, 16, 1, shade(c, 1.15))
        self.px(x, 86, 16, 1, shade(c, 0.7))
        self.px(x + 15, 84, 1, 1, '#c0392b', glow=night)
        for wx in (x + 2, x + 11):
            self.px(wx, 87, 3, 3, '#1c1c1c')
            self.px(wx + 2 * ((self.t // 2) % 2), 88, 1, 1, '#9e9e9e')
        if night:
            self.px(x, 84, 1, 1, '#fff3b0', glow=True)
            for i in range(24):
                self.px(x - 0.5 - i / 2, 84 - i / 12, 0.5, 1 + i / 6, '#fff3b0', glow=True,
                        alpha=0.22 - i * 0.008)
            self.px(x + 15, 83.5, 2, 2, '#ff3b30', glow=True, alpha=0.25)
        else:
            self.px(x, 84, 1, 1, '#f5e6a0')


class Window(Gtk.Window):
    def __init__(self, world):
        super().__init__(title='Piksel Mahalle')
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        self.world = world
        self.world.update_light()
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)  # "masaüstünü göster" gizlemesin
        self.stick()
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        width = (PANEL + W) * S
        self.set_default_size(width, H * S)

        area = monitor.get_workarea()
        self.move(area.x + (area.width - width) // 2, area.y + area.height - H * S)

        self.connect('draw', self.on_draw)
        self.connect('destroy', Gtk.main_quit)
        GLib.timeout_add(1000 // FPS, self.tick)

    def tick(self):
        try:
            self.world.step()
        except Exception:   # tek hata animasyonu sessizce durdurmasın
            traceback.print_exc()
        self.queue_draw()
        return True

    def on_draw(self, _widget, ctx):
        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source_rgba(0, 0, 0, 0)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.set_antialias(cairo.ANTIALIAS_NONE)
        ctx.scale(S, S)
        self.world.draw(ctx)


def main():
    global S, W, ALWAYS_NIGHT
    ap = argparse.ArgumentParser(description='Masaüstünde duran küçük bir piksel mahalle.')
    ap.add_argument('--scale', type=int, default=S, help='her mantıksal pikselin ekran boyutu (varsayılan %(default)s)')
    ap.add_argument('--day', action='store_true', help='mahalle saate göre gündüz/gece olsun (varsayılan: hep gece)')
    ap.add_argument('--hava', choices=sorted(hava.FORCE), help='Yalova yerine bu havayı göster (deneme için)')
    ap.add_argument('--saat-yok', action='store_true', help='ortadaki saati gösterme')
    ap.add_argument('--dogum-gunu', metavar='GG.AA', help='o gün mahallede balonlar, saatte kutlama')
    ap.add_argument('--uyku', type=float, default=SLEEP_AFTER / 60, metavar='DK',
                    help='bu kadar dakika boşta kalınca mahalle uyur (varsayılan %(default)g)')
    args = ap.parse_args()
    birthday = None
    if args.dogum_gunu:
        d, m = args.dogum_gunu.split('.')
        birthday = (int(d), int(m))
    S = max(1, args.scale)
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    S = max(1, round(S / monitor.get_scale_factor()))   # HiDPI'de pencere şişmesin
    W = monitor.get_workarea().width // S - PANEL       # mahalle ekranın tüm genişliğini kaplar
    if args.day:
        ALWAYS_NIGHT = False
    world = World(hava.Weather(force=args.hava), sistem.System(), birthday, args.uyku * 60)
    wins = [Window(world)]
    if not args.saat_yok:
        wins.append(saat.ClockWindow(world))
    for win in wins:
        win.show_all()
        win.input_shape_combine_region(cairo.Region())  # tıklamalar içinden geçsin
    Gtk.main()


if __name__ == '__main__':
    main()
