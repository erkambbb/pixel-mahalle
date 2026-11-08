#!/bin/sh
# Oturum açılışında çalıştırılır (~/.config/autostart). Çıktıyı günlüğe yazar;
# hemen çökerse (20 sn içinde) birkaç kez yeniden dener.
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$HOME/.cache/pixel-mahalle/log.txt"
mkdir -p "$(dirname "$LOG")"
for deneme in 1 2 3 4 5; do
    basla=$(date +%s)
    echo "$(date '+%F %T') başlatılıyor (deneme $deneme)" >> "$LOG"
    /usr/bin/python3 "$DIR/mahalle.py" >> "$LOG" 2>&1
    kod=$?
    echo "$(date '+%F %T') kapandı, kod $kod" >> "$LOG"
    [ $(( $(date +%s) - basla )) -ge 20 ] && break
    sleep 5
done
