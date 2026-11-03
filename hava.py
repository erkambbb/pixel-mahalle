"""Yalova'nın anlık hava durumu (Open-Meteo; anahtar gerekmez)."""
import json
import os
import threading
import time
import urllib.request

LAT, LON = 40.655, 29.275            # Yalova
URL = ('https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}'
       '&current=temperature_2m,weather_code,wind_speed_10m,is_day'
       '&timezone=Europe%2FIstanbul').format(LAT, LON)
EVERY, RETRY = 15 * 60, 2 * 60        # başarılıysa 15 dk, değilse 2 dk sonra tekrar
CACHE = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'),
                     'pixel-mahalle', 'hava.json')

# WMO kodu -> (etiket, yağmur, kar, bulut, sis, fırtına)
CODES = {
    0: ('AÇIK', 0, 0, 0.05, 0, False),
    1: ('AZ BULUTLU', 0, 0, 0.25, 0, False),
    2: ('PARÇALI BULUTLU', 0, 0, 0.5, 0, False),
    3: ('KAPALI', 0, 0, 0.95, 0, False),
    45: ('SİSLİ', 0, 0, 0.6, 1, False),
    48: ('KIRAĞILI SİS', 0, 0, 0.6, 1, False),
    51: ('ÇİSELEME', 0.15, 0, 0.9, 0.2, False),
    53: ('ÇİSELEME', 0.25, 0, 0.9, 0.2, False),
    55: ('YOĞUN ÇİSELEME', 0.35, 0, 0.95, 0.2, False),
    56: ('DONDURUCU ÇİSE', 0.25, 0, 0.95, 0.2, False),
    57: ('DONDURUCU ÇİSE', 0.35, 0, 0.95, 0.2, False),
    61: ('HAFİF YAĞMUR', 0.4, 0, 1, 0, False),
    63: ('YAĞMURLU', 0.7, 0, 1, 0, False),
    65: ('ŞİDDETLİ YAĞMUR', 1, 0, 1, 0, False),
    66: ('DONDURUCU YAĞMUR', 0.5, 0, 1, 0, False),
    67: ('DONDURUCU YAĞMUR', 0.8, 0, 1, 0, False),
    71: ('HAFİF KAR', 0, 0.4, 1, 0, False),
    73: ('KARLI', 0, 0.7, 1, 0, False),
    75: ('YOĞUN KAR', 0, 1, 1, 0, False),
    77: ('KAR TANELİ', 0, 0.3, 1, 0, False),
    80: ('SAĞANAK', 0.5, 0, 0.9, 0, False),
    81: ('SAĞANAK', 0.8, 0, 1, 0, False),
    82: ('ŞİDDETLİ SAĞANAK', 1, 0, 1, 0, False),
    85: ('KAR SAĞANAĞI', 0, 0.6, 1, 0, False),
    86: ('YOĞUN KAR SAĞANAĞI', 0, 1, 1, 0, False),
    95: ('GÖK GÜRÜLTÜLÜ', 0.9, 0, 1, 0, True),
    96: ('DOLULU FIRTINA', 1, 0, 1, 0, True),
    99: ('DOLULU FIRTINA', 1, 0, 1, 0, True),
}
# --hava seçenekleri: denemek için havayı zorla
FORCE = {'acik': 0, 'parcali': 2, 'bulutlu': 3, 'sis': 45, 'cisenti': 53, 'yagmur': 63,
         'saganak': 82, 'kar': 73, 'firtina': 95}


class Weather:
    def __init__(self, force=None, fetch=True):
        self.code = 0
        self.temp = None          # °C; None = henüz bilinmiyor
        self.wind = 0.0           # km/sa
        self.is_day = False
        self.ok = False           # en az bir kez veri geldi mi
        self.force = FORCE.get(force) if force else None
        self._load_cache()
        if fetch:
            threading.Thread(target=self._loop, daemon=True).start()

    # ---- türetilen değerler ----
    def _row(self):
        code = self.force if self.force is not None else self.code
        return CODES.get(code, CODES[min(CODES, key=lambda c: abs(c - code))])

    label = property(lambda self: self._row()[0])
    rain = property(lambda self: self._row()[1])
    snow = property(lambda self: self._row()[2])
    cloud = property(lambda self: self._row()[3])
    fog = property(lambda self: self._row()[4])
    storm = property(lambda self: self._row()[5])
    windy = property(lambda self: max(0.6 if self.storm else 0.0, min(1.0, self.wind / 40)))

    @property
    def kind(self):
        """Simge seçimi için kaba tür."""
        if self.storm:
            return 'storm'
        if self.snow:
            return 'snow'
        if self.rain:
            return 'rain'
        if self.fog:
            return 'fog'
        return 'clear' if self.cloud < 0.3 else 'partly' if self.cloud < 0.7 else 'cloudy'

    # ---- veri çekme ----
    def _apply(self, cur):
        self.code = int(cur['weather_code'])
        self.temp = float(cur['temperature_2m'])
        self.wind = float(cur.get('wind_speed_10m') or 0)
        self.is_day = bool(cur.get('is_day'))
        self.ok = True

    def _load_cache(self):
        try:
            with open(CACHE) as f:
                data = json.load(f)
            if time.time() - data['saved'] < 6 * 3600:
                self._apply(data['current'])
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def fetch(self):
        req = urllib.request.Request(URL, headers={'User-Agent': 'pixel-mahalle'})
        with urllib.request.urlopen(req, timeout=15) as r:
            cur = json.load(r)['current']
        self._apply(cur)
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE, 'w') as f:
                json.dump({'saved': time.time(), 'current': cur}, f)
        except OSError:
            pass

    def _loop(self):
        while True:
            try:
                self.fetch()
                time.sleep(EVERY)
            except Exception:   # ağ yok, API değişti vb.: son bilinen hava kalsın
                time.sleep(RETRY)
