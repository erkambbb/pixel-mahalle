"""Sistem okumaları: RAM, disk, pil, klavye/fare boşta süresi ve çalan müzik (MPRIS)."""
import ctypes
import glob
import shutil
import threading
import time

from gi.repository import Gio, GLib


def _read(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


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
    """Çalan şarkı: MPRIS yayınlayan her oynatıcı (Firefox'ta YouTube Music dahil)."""

    def __init__(self, start=True):
        self.title = self.artist = ''
        self.playing = False
        self.length = 0.0          # sn
        self._pos = (0.0, 0.0)     # (konum sn, okunduğu an)
        if start:
            threading.Thread(target=self._loop, daemon=True).start()

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
                self.playing = False
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
                best = (rank, props, md)
        if not best or best[0] < 2:
            self.playing = False
            return
        _, props, md = best
        artist = md.get('xesam:artist') or ''
        self.artist = ', '.join(artist) if isinstance(artist, list) else str(artist)
        self.title = str(md.get('xesam:title'))
        self.length = (md.get('mpris:length') or 0) / 1e6
        self._pos = ((props.get('Position') or 0) / 1e6, time.monotonic())
        self.playing = True


class System:
    def __init__(self, music=True):
        self.battery = Battery()
        self.idle = Idle()
        self.music = Music(start=music)
        self.ram = self.disk = 0.0                 # 0..1
        self.ram_gb = self.ram_total_gb = 0.0
        self.disk_gb = self.disk_total_gb = 0.0
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
        self.battery.update()
        self.idle_s = self.idle.seconds()
