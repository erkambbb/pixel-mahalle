# Pixel Mahalle

Masaüstünde duran, tıklanamayan küçük bir piksel mahalle. Evler, yürüyen insanlar, köpekler, arabalar ve taşınma kamyonu; mahallenin hareketi bilgisayarın CPU/GPU yüküne ve sıcaklığına göre değişir.

## Mahalle neyi gösteriyor?

Mahalle, bilgisayarın o anki durumunu canlı olarak yansıtır. Değerler 2 saniyede bir güncellenir.

| Mahallede gördüğün | Temsil ettiği | Nasıl okunur |
|---|---|---|
| 🚶 Kaldırımda yürüyen insanlar | **İşlemci (CPU) kullanımı** | %0'da sokak boş, %100'de 14 yaya |
| 🚗 Yoldaki arabalar | **Ekran kartı (GPU) kullanımı** | %0'da yol boş, %100'de 8 araba (`nvidia-smi` gerekir) |
| 💡 Sarı yanan pencereler | **İşlemci sıcaklığı** | 40 °C'de hepsi sönük, 110 °C'de hepsi yanık |
| 🧪 Soldaki yeşil tüp (↓) | **İndirme hızı** | Logaritmik: boş = 1 KB/s, dolu = 100 MB/s |
| 🧪 Soldaki turuncu tüp (↑) | **Yükleme hızı** | Tüp üzerindeki her çizgi 10 kat artış demek |
| 🌙 Gece ışığı | Sabit | Mahalle hep gece; `ALWAYS_NIGHT = False` yapılırsa saate göre değişir |

Tüplerdeki çizgiler sırasıyla 10 KB/s, 100 KB/s, 1 MB/s ve 10 MB/s'yi gösterir. Trafik arttıkça kabarcıklar da hızlanır.

Taşınma kamyonu, bahçıvan ve kuşlar yalnızca süs; bir ölçümü temsil etmez.

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
