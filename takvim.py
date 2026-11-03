"""Özel günler (bayramlar, yılbaşı, doğum günü, Cuma pazarı) ve Yalova'da gün doğumu/batımı."""
import datetime
import math

LAT, LON = 40.655, 29.275    # Yalova

# Dini bayramların ilk günü. Hicri takvime bağlı olduğu için tahmini (±1 gün); gerekirse düzelt.
RAMAZAN = ['2025-03-30', '2026-03-20', '2027-03-09', '2028-02-26', '2029-02-14', '2030-02-04']
KURBAN = ['2025-06-06', '2026-05-27', '2027-05-16', '2028-05-05', '2029-04-24', '2030-04-13']

FLAG_DAYS = {   # (ay, gün): mesaj
    (4, 23): 'ULUSAL EGEMENLİK VE ÇOCUK BAYRAMI',
    (5, 19): 'GENÇLİK VE SPOR BAYRAMI',
    (7, 15): 'DEMOKRASİ VE MİLLİ BİRLİK GÜNÜ',
    (8, 30): 'ZAFER BAYRAMI KUTLU OLSUN',
    (10, 29): 'CUMHURİYET BAYRAMI KUTLU OLSUN',
}


class Event:
    def __init__(self, kind, text, color='#e9dfcf', fireworks=False):
        self.kind = kind          # flags | halfmast | bayram | newyear | birthday
        self.text = text
        self.color = color
        self.fireworks = fireworks


def _in_bayram(day, table, length):
    for s in table:
        start = datetime.date.fromisoformat(s)
        if start - datetime.timedelta(days=1) <= day < start + datetime.timedelta(days=length):
            return day < start   # arife mi
    return None


def event(now, birthday=None):
    """Bugünün özel günü (yoksa None). birthday: (gün, ay)."""
    day, md = now.date(), (now.month, now.day)
    if birthday and md == (birthday[1], birthday[0]):
        return Event('birthday', 'İYİ Kİ DOĞDUN!', '#ff9ff3')
    if md == (12, 31) or md == (1, 1):
        return Event('newyear', 'MUTLU YILLAR!', '#ffd34d',
                     fireworks=(md == (12, 31) and now.hour == 23 and now.minute >= 50)
                     or (md == (1, 1) and now.hour == 0 and now.minute < 40))
    if (now.month == 12 and now.day >= 20) or md == (1, 2):
        left = (datetime.date(day.year + (now.month == 1), 12, 31) - day).days + 1
        return Event('newyear', f'YENİ YILA {left} GÜN', '#9fe2bf')
    if md == (11, 10):
        return Event('halfmast', "ATATÜRK'Ü SAYGIYLA ANIYORUZ", '#d0d0d0')
    if md in FLAG_DAYS or (md == (10, 28) and now.hour >= 13):
        return Event('flags', FLAG_DAYS.get(md, FLAG_DAYS[(10, 29)]), '#ff5a4f',
                     fireworks=md == (10, 29) and 20 <= now.hour < 23)
    for table, length, name in ((RAMAZAN, 3, 'RAMAZAN'), (KURBAN, 4, 'KURBAN')):
        arife = _in_bayram(day, table, length)
        if arife is not None:
            return Event('bayram', f'{name} BAYRAMI ARİFESİ' if arife else f'{name} BAYRAMINIZ MÜBAREK OLSUN',
                         '#ffcf6b')
    return None


def market(now):
    """Cuma akşamı pazar tezgâhı."""
    return now.weekday() == 4 and 17 <= now.hour < 23


def sun_times(day, lat=LAT, lon=LON):
    """(gün doğumu, gün batımı) yerel saat olarak datetime (NOAA yaklaşık formülü, ~1 dk)."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_ha = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    ha = math.degrees(math.acos(max(-1.0, min(1.0, cos_ha))))
    midnight = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    out = []
    for sign in (1, -1):
        minutes = 720 - 4 * (lon + sign * ha) - eqtime
        out.append((midnight + datetime.timedelta(minutes=minutes)).astimezone().replace(tzinfo=None))
    return tuple(out)


def twilight(now, window=45):
    """('dawn'|'dusk', 0..1): gün doğumu/batımına yakınlık; uzaksa (None, 0)."""
    rise, set_ = sun_times(now.date())
    for kind, t in (('dawn', rise), ('dusk', set_)):
        k = 1 - abs((now - t).total_seconds()) / 60 / window
        if k > 0:
            return kind, k
    return None, 0.0
