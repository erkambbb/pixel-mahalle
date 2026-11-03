# Pixel Mahalle

Masaüstünde duran, tıklanamayan küçük bir piksel mahalle. Evler, yürüyen insanlar, köpekler, arabalar ve taşınma kamyonu; mahallenin hareketi bilgisayarın CPU/GPU yüküne ve sıcaklığına göre değişir.

Soldaki iki cam tüp internet trafiğini gösterir: yeşil tüp indirme, turuncu tüp yükleme. Doluluk logaritmiktir; her çizgi 10 kat demektir (1 KB/s boş, 100 MB/s dolu).

| Ölçüm | Mahallede |
|---|---|
| CPU kullanımı | Kaldırımdaki yaya sayısı |
| GPU kullanımı | Yoldaki araba sayısı |
| CPU sıcaklığı | Yanan pencere sayısı |
| İndirme / yükleme | Soldaki tüplerin doluluğu |
| Saat | Gündüz / gece ışığı |

## Gereksinimler

- Linux (X11/Wayland, GTK 3)
- Python 3, `python3-gi`, `python3-gi-cairo`
- İsteğe bağlı: `nvidia-smi` (GPU kullanımı için)

```bash
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0
```

## Çalıştırma

```bash
./mahalle.py
```
