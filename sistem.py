"""Sistem okumaları: RAM, disk, pil, sıcaklıklar, ekran parlaklığı, klavye/fare boşta süresi ve çalan müzik (MPRIS)."""
import ctypes
import glob
import math
import os
import shutil
import sys
import threading
import time

from gi.repository import Gio, GLib


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _hwmon_temp(names):
    """Adı names içinde geçen ilk hwmon aygıtının sıcaklık dosyası (yoksa None)."""
    for d in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        if _read(d + '/name') in names and os.path.exists(d + '/temp1_input'):
            return d + '/temp1_input'
    return None


def _temp(path):
    try:
        return int(_read(path)) / 1000
    except (TypeError, ValueError):
        return None


class Backlight:
    """Ekran parlaklığı (0..1): /sys/class/backlight'tan okunur, root gerekmeden logind üzerinden yazılır.

    0, donanımın en kısığına değil FLOOR'a denk gelir: ekran tamamen kararıp güneş kaybolmasın.
    """
    FLOOR = 0.05
    HOLD = 1.5     # yazdıktan sonra bu kadar sn sysfs okunmaz, eski değer güneşi geri çekmesin

    def __init__(self, root='/sys/class/backlight'):
        self.path = self.name = None
        self.max = self.min = 1
        self.level = None
        self.writable = True
        rank = {'firmware': 0, 'platform': 1, 'raw': 2}   # systemd ile aynı öncelik
        for d in sorted(glob.glob(root + '/*') if root else [], key=lambda d: rank.get(_read(d + '/type'), 3)):
            try:
                mx = int(_read(d + '/max_brightness'))
            except (TypeError, ValueError):
                continue
            if mx > 0:
                self.path, self.name, self.max = d, os.path.basename(d), mx
                self.min = min(mx, max(1, math.ceil(mx * self.FLOOR)))
                break
        self._bus = None
        self._want = self._sent = None
        self._inflight = False
        self._touched = 0.0
        self.update()

    @property
    def ok(self):
        return self.path is not None and self.writable

    def update(self):
        if not self.path or time.monotonic() - self._touched < self.HOLD:
            return
        try:
            raw = int(_read(self.path + '/brightness'))
        except (TypeError, ValueError):
            return
        span = self.max - self.min
        self.level = max(0.0, min(1.0, (raw - self.min) / span)) if span > 0 else 1.0

    def set(self, frac):
        """Parlaklığı frac'a çek. Çağrılar üst üste binmez: biri yoldayken yalnızca son değer bekler."""
        if not self.ok:
            return
        self.level = frac = max(0.0, min(1.0, frac))
        self._touched = time.monotonic()
        self._want = round(self.min + (self.max - self.min) * frac)
        if not self._inflight and self._want != self._sent:
            self._send()

    def _send(self):
        self._inflight, self._sent = True, self._want
        try:
            self._bus = self._bus or Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self._bus.call('org.freedesktop.login1', '/org/freedesktop/login1/session/auto',
                           'org.freedesktop.login1.Session', 'SetBrightness',
                           GLib.Variant('(ssu)', ('backlight', self.name, self._sent)), None,
                           Gio.DBusCallFlags.NONE, 2000, None, self._done)
        except GLib.Error as e:
            self._fail(e)

    def _done(self, bus, res, *_):
        self._inflight = False
        try:
            bus.call_finish(res)
        except GLib.Error as e:
            self._fail(e)
            return
        self._touched = time.monotonic()
        if self._want != self._sent:
            self._send()

    def _fail(self, e):
        self._inflight = False
        if self.writable:
            print(f'Parlaklık ayarlanamadı, güneş yalnızca mahalleyi aydınlatacak: {e.message}', file=sys.stderr)
        self.writable = False


class Battery:
    """İlk sistem pili (/sys/class/power_supply/BAT*); telefon gibi 'Device' kapsamlılar atlanır."""

    def __init__(self):
        self.path = None
        for d in sorted(glob.glob('/sys/class/power_supply/*')):
            if _read(d + '/type') == 'Battery' and _read(d + '/scope', 'System') != 'Device':
                self.path = d
                break
        self.adapters = [d for d in glob.glob('/sys/class/power_supply/*') if _read(d + '/type') == 'Mains']
        self.level = None        # 0..100
        self.plugged = False     # adaptör takılı mı
        self.charging = False    # şu an doluyor mu
        self.hours = None        # kalan (boşalma) ya da dolmaya kalan süre, saat

    def update(self):
        if not self.path:
            return
        try:
            self.level = int(_read(self.path + '/capacity'))
        except (TypeError, ValueError):
            self.level = None
        status = _read(self.path + '/status', '')
        self.charging = status == 'Charging'
        self.plugged = self.charging or any(_read(a + '/online') == '1' for a in self.adapters)
        self.hours = None
        for now_f, full_f, rate_f in (('energy_now', 'energy_full', 'power_now'),
                                      ('charge_now', 'charge_full', 'current_now')):
            try:
                now = int(_read(self.path + '/' + now_f))
                full = int(_read(self.path + '/' + full_f))
                rate = abs(int(_read(self.path + '/' + rate_f)))
            except (TypeError, ValueError):
                continue
            if rate:
                if self.charging:
                    self.hours = (full - now) / rate
                elif status == 'Discharging':
                    self.hours = now / rate
            break


class Idle:
    """X11 boşta süresi (XScreenSaver eklentisi). Yoksa hep 0 döner."""

    class _Info(ctypes.Structure):
        _fields_ = [('window', ctypes.c_ulong), ('state', ctypes.c_int), ('kind', ctypes.c_int),
                    ('til_or_since', ctypes.c_ulong), ('idle', ctypes.c_ulong), ('eventMask', ctypes.c_ulong)]

    def __init__(self):
        self._ok = False
        try:
            x11 = ctypes.cdll.LoadLibrary('libX11.so.6')
            xss = ctypes.cdll.LoadLibrary('libXss.so.1')
            x11.XOpenDisplay.restype = ctypes.c_void_p
            x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(self._Info)
            xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(self._Info)]
            self._dpy = x11.XOpenDisplay(None)
            if self._dpy:
                self._root = x11.XDefaultRootWindow(self._dpy)
                self._info = xss.XScreenSaverAllocInfo()
                self._xss = xss
                self._ok = True
        except (OSError, AttributeError):
            pass

    def seconds(self):
        if not self._ok or not self._xss.XScreenSaverQueryInfo(self._dpy, self._root, self._info):
            return 0.0
        return self._info.contents.idle / 1000


class Music:
    """Çalan şarkı: MPRIS yayınlayan her oynatıcı (Firefox'ta YouTube Music dahil). Duraklat/sonraki/önceki de buradan."""
    PAUSED_SHOW = 600          # duraklatılan şarkı bu kadar sn daha saatte kalır (devam ettirilebilsin)
    PLAYER = 'org.mpris.MediaPlayer2.Player'

    def __init__(self, start=True):
        self.title = self.artist = ''
        self.playing = self.paused = False
        self.length = 0.0          # sn
        self.player = None         # D-Bus adı
        self._pos = (0.0, 0.0)     # (konum sn, okunduğu an)
        self._bus = None
        self._last_play = 0.0
        self._hold = 0.0           # komuttan sonra kısa süre eski durumu okuma
        if start:
            threading.Thread(target=self._loop, daemon=True).start()

    @property
    def visible(self):
        """Saatte gösterilsin mi: çalıyor ya da az önce duraklatıldı."""
        return self.playing or (self.paused and time.monotonic() - self._last_play < self.PAUSED_SHOW)

    def command(self, method):
        """PlayPause, Next ya da Previous; sonuç beklenmez, durum hemen tahmin edilir."""
        if not self.player:
            return
        try:
            self._bus = self._bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self._bus.call(self.player, '/org/mpris/MediaPlayer2', self.PLAYER, method, None, None,
                           Gio.DBusCallFlags.NONE, 1000, None, None)
        except GLib.Error:
            return
        if method == 'PlayPause':
            if self.playing:
                self._pos = (self.position, time.monotonic())
            self.playing, self.paused = not self.playing, self.playing
            self._last_play = time.monotonic()
            self._hold = time.monotonic() + 1.5

    @property
    def position(self):
        pos, at = self._pos
        if self.playing:
            pos += time.monotonic() - at
        return min(pos, self.length) if self.length else pos

    def _loop(self):
        bus = None
        while True:
            try:
                bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION, None)
                self._poll(bus)
            except GLib.Error:
                self.playing = self.paused = False
            time.sleep(1)

    @staticmethod
    def _call(bus, name, path, iface, method, args, ret):
        return bus.call_sync(name, path, iface, method, args, GLib.VariantType(ret),
                             Gio.DBusCallFlags.NONE, 800, None).unpack()

    def _poll(self, bus):
        names = self._call(bus, 'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                           'ListNames', None, '(as)')[0]
        best = None
        for n in names:
            if not n.startswith('org.mpris.MediaPlayer2.'):
                continue
            try:
                props = self._call(bus, n, '/org/mpris/MediaPlayer2', 'org.freedesktop.DBus.Properties', 'GetAll',
                                   GLib.Variant('(s)', ('org.mpris.MediaPlayer2.Player',)), '(a{sv})')[0]
            except GLib.Error:
                continue
            md = props.get('Metadata') or {}
            if not md.get('xesam:title'):
                continue
            rank = {'Playing': 2, 'Paused': 1}.get(props.get('PlaybackStatus'), 0)
            if best is None or rank > best[0]:
                best = (rank, props, md, n)
        if time.monotonic() < self._hold:
            return
        if not best or best[0] < 1:
            self.playing = self.paused = False
            self.player = None
            return
        rank, props, md, self.player = best
        self.playing, self.paused = rank == 2, rank == 1
        if self.playing:
            self._last_play = time.monotonic()
        artist = md.get('xesam:artist') or ''
        self.artist = ', '.join(artist) if isinstance(artist, list) else str(artist)
        self.title = str(md.get('xesam:title'))
        self.length = (md.get('mpris:length') or 0) / 1e6
        self._pos = ((props.get('Position') or 0) / 1e6, time.monotonic())


class System:
    def __init__(self, music=True, backlight=True):
        self.battery = Battery()
        self.backlight = Backlight('/sys/class/backlight' if backlight else None)
        self.idle = Idle()
        self.music = Music(start=music)
        self.ram = self.disk = 0.0                 # 0..1
        self.ram_gb = self.ram_total_gb = 0.0
        self.disk_gb = self.disk_total_gb = 0.0
        self.ram_temp = self.disk_temp = None      # °C; sensör yoksa None
        self._ram_temp_file = _hwmon_temp(('spd5118', 'jc42'))
        self._disk_temp_file = _hwmon_temp(('nvme', 'drivetemp'))
        self.idle_s = 0.0
        self.update()

    def update(self):
        info = {}
        for line in (_read('/proc/meminfo', '') or '').splitlines():
            k, _, v = line.partition(':')
            info[k] = int(v.split()[0]) * 1024 if v.split() else 0
        total = info.get('MemTotal', 0)
        if total:
            used = total - info.get('MemAvailable', 0)
            self.ram, self.ram_gb, self.ram_total_gb = used / total, used / 1e9, total / 1e9
        try:
            du = shutil.disk_usage('/')
            self.disk, self.disk_gb, self.disk_total_gb = du.used / du.total, du.used / 1e9, du.total / 1e9
        except OSError:
            pass
        if self._ram_temp_file:
            self.ram_temp = _temp(self._ram_temp_file)
        if self._disk_temp_file:
            self.disk_temp = _temp(self._disk_temp_file)
        self.battery.update()
        self.backlight.update()
        self.idle_s = self.idle.seconds()
