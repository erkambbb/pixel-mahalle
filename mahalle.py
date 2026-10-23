#!/usr/bin/env python3
"""Masaüstünde duran, tıklanamayan küçük bir piksel mahalle."""
import datetime
import math
import random
import subprocess

import cairo
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

W, H = 220, 90       # mantıksal piksel
S = 3                # her mantıksal piksel ekranda S x S
FPS = 12
GROUND = 66          # evlerin oturduğu çizgi (çimen satırı)
FEET = 72            # kaldırımda yürüyenlerin ayak hizası
PICKUP_X = 140       # taşıyıcıların kamyondan kutu aldığı yer
TRUCK_X = 146        # kamyonun park ettiği yer


def hx(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))


SKIN = [hx(c) for c in ('#f1c27d', '#e0ac69', '#c68642', '#8d5524', '#ffdbac')]
HAIR = [hx(c) for c in ('#2c1b10', '#6a4e2e', '#b5651d', '#e6c35c', '#1a1a1a', '#9e9e9e')]
SHIRT = [hx(c) for c in ('#d9534f', '#3e7cb1', '#5cb85c', '#f0ad4e', '#8e44ad', '#16a085', '#ecf0f1', '#e67e22')]
PANTS = [hx(c) for c in ('#2c3e50', '#34495e', '#5d4037', '#3b3b98', '#555555')]
CARS = [hx(c) for c in ('#e74c3c', '#3498db', '#f1c40f', '#ecf0f1', '#2ecc71', '#9b59b6')]

HOUSES = [
    dict(x=6, w=34, h=24, wall='#e8c39e', roof='#b5523b', kind='gable', door=14),
    dict(x=48, w=30, h=34, wall='#9fb8c9', roof='#5a6a78', kind='flat', door=12),
    dict(x=88, w=38, h=22, wall='#f2e6c9', roof='#3f7f5f', kind='shop', door=24),
    dict(x=136, w=32, h=26, wall='#c9a0b8', roof='#6b3f5a', kind='gable', door=6),
    dict(x=178, w=36, h=20, wall='#d7d98f', roof='#8a5a2b', kind='gable', door=22),
]
TREES = [43, 83, 131, 172]
LAMPS = [30, 108, 200]
TEMP_MIN, TEMP_MAX = 40, 110   # bu aralıkta pencereler 0'dan hepsine kadar yanar
MAX_WALKERS = 14               # %100 CPU'da yoldaki yaya sayısı
MAX_CARS = 8                   # %100 GPU'da yoldaki araba sayısı


class Metrics:
    """CPU %, GPU % ve CPU sıcaklığı."""

    def __init__(self):
        self.cpu = self.gpu = 0.0
        self.temp = TEMP_MIN
        self._prev = self._cpu_times()
        self._temp_file = None
        import glob
        for d in glob.glob('/sys/class/hwmon/hwmon*'):
            try:
                if open(d + '/name').read().strip() in ('coretemp', 'k10temp', 'zenpower'):
                    self._temp_file = d + '/temp1_input'
            except OSError:
                pass

    @staticmethod
    def _cpu_times():
        v = [int(x) for x in open('/proc/stat').readline().split()[1:]]
        idle = v[3] + v[4]
        return idle, sum(v)

    def update(self):
        idle, total = self._cpu_times()
        di, dt = idle - self._prev[0], total - self._prev[1]
        self._prev = (idle, total)
        if dt:
            self.cpu = 100 * (1 - di / dt)
        try:
            out = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                                 capture_output=True, text=True, timeout=1).stdout
            self.gpu = float(out.split()[0])
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            self.gpu = 0.0
        if self._temp_file:
            try:
                self.temp = int(open(self._temp_file).read()) / 1000
            except (OSError, ValueError):
                pass


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


class World:
    def __init__(self):
        self.t = 0
        self.light = 1.0
        self.houses = [House(d) for d in HOUSES]
        self.shop = self.houses[2]
        self.people = []
        self.cars = []
        self.birds = []
        self.smoke = []
        self.clouds = [[random.uniform(0, W), random.uniform(3, 18), random.randint(12, 22),
                        random.uniform(0.03, 0.07)] for _ in range(3)]
        self.truck = Truck()
        self.metrics = Metrics()
        self.shop_lit = [False]
        # Sıcaklık arttıkça bu sırayla yanarlar (dükkan vitrini dahil 22 pencere)
        self.light_order = [w for h in self.houses for w in h.windows] + [self.shop_lit]
        random.Random(7).shuffle(self.light_order)
        self.truck_script = self.run_truck()
        for i in range(2):
            m = Person(self.houses[3].door_x + i * 8)
            m.shirt = hx('#2f6db5')
            m.script = self.run_mover(m, self.houses[3])
            self.people.append(m)
        g = Person()
        g.visible = False
        g.script = self.run_gardener(g, self.houses[0])
        self.people.append(g)

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
        if r < 0.4 and p.dog is None:
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

    # ---- güncelleme ----

    def update_light(self):
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
            self.metrics.update()
            frac = (self.metrics.temp - TEMP_MIN) / (TEMP_MAX - TEMP_MIN)
            lit = round(max(0.0, min(1.0, frac)) * len(self.light_order))
            for i, w in enumerate(self.light_order):
                w[-1] = i < lit
        busy = 0.3 + 0.7 * self.light

        next(self.truck_script)
        for p in self.people:
            try:
                next(p.script)
            except StopIteration:
                p.done = True
            if p.walking and self.t % 2 == 0:
                p.frame ^= 1
            if p.dog:
                target = p.x - p.dir * 7
                p.dog.x += max(-0.9, min(0.9, target - p.dog.x))
        self.people = [p for p in self.people if not p.done]

        walkers = sum(1 for p in self.people if p.script.__name__ == 'run_pedestrian')
        target = round(self.metrics.cpu / 100 * MAX_WALKERS)
        if walkers < target and random.random() < 0.05:
            p = Person()
            if random.random() < 0.15:
                p.dog = Dog(-20)
            p.script = self.run_pedestrian(p)
            self.people.append(p)
            if p.dog:
                next(p.script)
                p.dog.x = p.x

        for h in self.houses:
            h.open = max(0, h.open - 1)

        car_target = round(self.metrics.gpu / 100 * MAX_CARS)
        if len(self.cars) < car_target and random.random() < 0.08 and all(c[0] < W - 22 for c in self.cars):
            self.cars.append([W + 2.0, random.uniform(1.0, 1.6), random.choice(CARS)])
        for c in self.cars:
            c[0] -= c[1]
        self.cars = [c for c in self.cars if c[0] > -20]

        for c in self.clouds:
            c[0] += c[3]
            if c[0] > W + 5:
                c[0], c[1] = -c[2] - 5.0, random.uniform(3, 18)

        if not self.birds and random.random() < 0.002 * busy:
            y = random.uniform(8, 26)
            self.birds = [[-5.0 - i * 6, y + (i % 2) * 3, i * 3] for i in range(random.randint(2, 4))]
        for b in self.birds:
            b[0] += 0.9
        self.birds = [b for b in self.birds if b[0] < W + 5]

        chimney = self.houses[0]
        if self.t % 9 == 0:
            self.smoke.append([chimney.x + chimney.w - 8.0, chimney.top - 9.0, 0])
        for s in self.smoke:
            s[0] += 0.06
            s[1] -= 0.18
            s[2] += 1
        self.smoke = [s for s in self.smoke if s[2] < 70]

    # ---- çizim ----

    def tint(self, c):
        k = self.light
        return (c[0] * (0.35 + 0.65 * k), c[1] * (0.4 + 0.6 * k), c[2] * (0.6 + 0.4 * k))

    def px(self, x, y, w, h, c, glow=False, alpha=1.0):
        c = c if glow else self.tint(c)
        self.ctx.set_source_rgba(c[0], c[1], c[2], alpha)
        self.ctx.rectangle(int(round(x)), int(round(y)), w, h)
        self.ctx.fill()

    def draw(self, ctx):
        self.ctx = ctx
        night = self.light < 0.5
        for cx, cy, cw, _ in self.clouds:
            white = hx('#ffffff')
            self.px(cx, cy + 2, cw, 3, white, alpha=0.85)
            self.px(cx + 3, cy, cw // 2, 2, white, alpha=0.85)
            self.px(cx + cw // 2, cy + 1, cw // 3, 1, white, alpha=0.85)
        for bx, by, ph in self.birds:
            up = (self.t // 3 + ph) % 2
            dark = hx('#333333')
            self.px(bx, by, 1, 1, dark)
            self.px(bx - 1, by - up, 1, 1, dark)
            self.px(bx + 1, by - up, 1, 1, dark)

        for h in self.houses:
            self.draw_house(h, night)
        for sx, sy, age in self.smoke:
            size = 1 + age // 25
            self.px(sx, sy, size, size, hx('#d0d0d0'), alpha=max(0.0, 0.8 - age / 90))
        for i, tx in enumerate(TREES):
            sway = round(math.sin(self.t * 0.08 + i * 1.7) * 0.6)
            self.px(tx + 2, GROUND - 6, 2, 6, hx('#6b4423'))
            leaf, dark = hx('#4f9a3c'), hx('#3d7a2e')
            self.px(tx + sway, GROUND - 14, 6, 8, leaf)
            self.px(tx - 1 + sway, GROUND - 12, 8, 4, leaf)
            self.px(tx + 1 + sway, GROUND - 16, 4, 2, leaf)
            self.px(tx + 3 + sway, GROUND - 10, 3, 3, dark)

        self.px(0, GROUND, W, 1, hx('#7fb069'))
        for i, fx in enumerate(range(8, 19, 2)):
            self.px(fx, GROUND - 1, 1, 1, hx(('#e74c3c', '#f1c40f', '#e84393')[i % 3]))
            self.px(fx, GROUND, 1, 1, hx('#2e7d32'))
        self.px(0, GROUND + 1, W, FEET - GROUND + 1, hx('#bdb6a8'))
        for sx in range(0, W, 8):
            self.px(sx, GROUND + 1, 1, FEET - GROUND + 1, hx('#a9a293'))

        for p in self.people:
            if p.visible:
                self.draw_person(p)
            if p.dog and p.visible:
                self.draw_dog(p.dog, p)

        self.px(0, FEET + 2, W, 1, hx('#d8d4cc'))
        self.px(0, FEET + 3, W, H - FEET - 3, hx('#4a4a52'))
        for dx in range(0, W, 10):
            self.px(dx, 82, 6, 1, hx('#e8e1a0'))
        self.draw_truck(night)
        for cx, _, color in self.cars:
            self.draw_car(cx, color, night)
        for lx in LAMPS:
            self.px(lx, 55, 1, FEET + 2 - 55, hx('#3a3a3a'))
            self.px(lx - 1, 54, 3, 1, hx('#3a3a3a'))
            if night:
                self.px(lx - 1, 55, 3, 1, hx('#ffe08a'), glow=True)
                self.px(lx - 4, 55, 9, 10, hx('#ffe08a'), glow=True, alpha=0.08)
                self.px(lx - 2, 55, 5, 5, hx('#ffe08a'), glow=True, alpha=0.12)

    def draw_house(self, h, night):
        wall, roof = hx(h.wall), hx(h.roof)
        self.px(h.x, h.top, h.w, h.h, wall)
        self.px(h.x, GROUND - 1, h.w, 1, tuple(v * 0.8 for v in wall))
        if h.kind == 'gable':
            rows = min(10, (h.w + 4) // 2 - 1)
            for i in range(rows):
                self.px(h.x - 2 + i, h.top - 1 - i, h.w + 4 - 2 * i, 1, roof)
            if h is self.houses[0]:
                self.px(h.x + h.w - 9, h.top - 9, 3, 6, hx('#8d4a3a'))
        else:
            self.px(h.x - 1, h.top - 2, h.w + 2, 2, roof)

        for wx, wy, lit in h.windows:
            if lit:
                self.px(wx, wy, 5, 5, hx('#ffd36b'), glow=True)
            else:
                self.px(wx, wy, 5, 5, hx('#2b3a55') if night else hx('#bfe3f2'))
            frame = hx('#f5f5f5')
            self.px(wx + 2, wy, 1, 5, frame)
            self.px(wx, wy + 2, 5, 1, frame)
            self.px(wx - 1, wy + 5, 7, 1, frame)

        if h.kind == 'shop':
            self.px(h.x + 4, h.top + 3, h.w - 8, 6, hx('#3f7f5f'))
            for i in range(6):
                self.px(h.x + 7 + i * 4, h.top + 5, 2, 2, hx('#f5f5dc'))
            for i in range(0, h.w, 3):
                stripe = hx('#d9534f') if (i // 3) % 2 == 0 else hx('#f5f5f5')
                self.px(h.x + i, GROUND - 16, 3, 3, stripe)
            lit = self.shop_lit[0]
            glass = hx('#ffe9a8') if lit else hx('#bfe3f2')
            self.px(h.x + 3, GROUND - 12, h.door - 6, 9, glass, glow=lit)
            for i in range(3):
                self.px(h.x + 5 + i * 5, GROUND - 6, 3, 3, hx(('#e67e22', '#c0392b', '#27ae60')[i]))

        door = hx('#1e1410') if h.open else hx('#6b4226')
        self.px(h.door_x, GROUND - 9, 5, 9, door)
        if not h.open:
            self.px(h.door_x + 3, GROUND - 5, 1, 1, hx('#e6c35c'))

    def draw_person(self, p):
        x, top = p.x, FEET - 8
        self.px(x, top, 4, 1, p.hair)
        self.px(x, top + 1, 4, 2, p.skin)
        self.px(x + (3 if p.dir > 0 else 0), top + 1, 1, 1, p.hair)
        self.px(x + (2 if p.dir > 0 else 1), top + 2, 1, 1, hx('#222222'))
        self.px(x, top + 3, 4, 3, p.shirt)
        if p.walking and p.frame:
            self.px(x + 1, top + 6, 2, 2, p.pants)
        else:
            self.px(x, top + 6, 1, 2, p.pants)
            self.px(x + 3, top + 6, 1, 2, p.pants)
        front = x + 4 if p.dir > 0 else x - 1
        if p.carry == 'box':
            bx = x + 2 if p.dir > 0 else x - 3
            self.px(bx, top + 2, 5, 4, hx('#b07a43'))
            self.px(bx, top + 3, 5, 1, hx('#d9b380'))
            self.px(bx + (0 if p.dir > 0 else 4), top + 4, 1, 1, p.skin)
        elif p.carry == 'bag':
            self.px(front, top + 4, 2, 3, hx('#f5f5f5'))
        elif p.carry == 'can':
            cx = x + 4 if p.dir > 0 else x - 2
            self.px(cx, top + 4, 2, 2, hx('#7f8c8d'))
            spout = cx + 2 if p.dir > 0 else cx - 1
            self.px(spout, top + 4, 1, 1, hx('#7f8c8d'))
            if p.watering:
                for i in range(3):
                    self.px(spout, top + 5 + (self.t + i * 2) % 4, 1, 1, hx('#5dade2'))

    def draw_dog(self, d, owner):
        x, y = d.x, FEET - 3
        self.px(x, y, 5, 2, d.color)
        head = x + 5 if owner.dir > 0 else x - 2
        self.px(head, y - 1, 2, 2, d.color)
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
        self.px(x, 68, 21, 12, hx('#e9e4d8'))
        if t.state == 'parked':
            self.px(x + 1, 69, 19, 10, hx('#3b3226'))
            for i in range(t.boxes):
                self.px(x + 2 + (i % 3) * 6, 75 - (i // 3) * 4, 5, 4, hx('#b07a43'))
                self.px(x + 2 + (i % 3) * 6, 76 - (i // 3) * 4, 5, 1, hx('#d9b380'))
        else:
            self.px(x, 73, 21, 2, hx('#2f6db5'))
        self.px(x + 21, 71, 9, 9, hx('#c8423a'))
        self.px(x + 24, 72, 5, 3, hx('#bfe3f2'))
        if night:
            self.px(x + 30, 77, 1, 1, hx('#fff3b0'), glow=True)
        for wx in (x + 3, x + 23):
            self.px(wx, 80, 3, 3, hx('#1c1c1c'))
            spin = (self.t // 2) % 2 if t.moving else 1
            self.px(wx + 2 * spin, 81, 1, 1, hx('#9e9e9e'))

    def draw_car(self, x, color, night):
        self.px(x + 4, 80, 8, 3, color)
        self.px(x + 5, 81, 6, 2, hx('#bfe3f2'))
        self.px(x, 83, 16, 4, color)
        for wx in (x + 2, x + 11):
            self.px(wx, 87, 3, 3, hx('#1c1c1c'))
            self.px(wx + 2 * ((self.t // 2) % 2), 88, 1, 1, hx('#9e9e9e'))
        if night:
            self.px(x, 84, 1, 1, hx('#fff3b0'), glow=True)
            self.px(x - 6, 83, 6, 3, hx('#fff3b0'), glow=True, alpha=0.15)


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title='Piksel Mahalle')
        self.world = World()
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
        self.set_default_size(W * S, H * S)

        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        area = monitor.get_workarea()
        self.move(area.x + area.width - W * S - 20, area.y + area.height - H * S)

        self.connect('draw', self.on_draw)
        self.connect('destroy', Gtk.main_quit)
        GLib.timeout_add(1000 // FPS, self.tick)

    def tick(self):
        self.world.step()
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
    win = Window()
    win.show_all()
    win.input_shape_combine_region(cairo.Region())  # tıklamalar içinden geçsin
    Gtk.main()


if __name__ == '__main__':
    main()
