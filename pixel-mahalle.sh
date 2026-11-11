#!/bin/sh
# Oturum açılışında çalıştırılır (~/.config/autostart). Çıktıyı günlüğe yazar;
# süreç hangi nedenle kapanırsa kapansın (X hatası dahil) yeniden başlatır.
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$HOME/.cache/pixel-mahalle/log.txt"
KILIT="$HOME/.cache/pixel-mahalle/kilit"
mkdir -p "$(dirname "$LOG")"
# Aynı anda iki örnek çalışmasın.
exec 9>"$KILIT"
flock -n 9 || exit 0
while true; do
    basla=$(date +%s)
    echo "$(date '+%F %T') başlatılıyor" >> "$LOG"
    /usr/bin/python3 "$DIR/mahalle.py" >> "$LOG" 2>&1
    kod=$?
    echo "$(date '+%F %T') kapandı, kod $kod" >> "$LOG"
    # Hemen çöküyorsa bekleme uzasın, uzun çalıştıysa hemen dön.
    if [ $(( $(date +%s) - basla )) -ge 20 ]; then
        sleep 3
    else
        sleep 10
    fi
done
