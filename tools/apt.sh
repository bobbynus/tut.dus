#!/usr/bin/env bash
# Установка пакетов на раннере GitHub с повторами и тайм-аутом: зеркало Ubuntu иногда
# не отвечает (11.11.2026 apt-get повис на 18 минут из-за DNS) — не даём задаче зависнуть.
# Запуск: bash tools/apt.sh ffmpeg imagemagick
missing=()
for p in "$@"; do
  bin=$p; [ "$p" = imagemagick ] && bin=convert
  command -v "$bin" >/dev/null || missing+=("$p")
done
[ ${#missing[@]} -eq 0 ] && exit 0
for i in 1 2 3; do
  timeout 180 sudo apt-get update -qq -o Acquire::Retries=2 -o Acquire::http::Timeout=20 >/dev/null 2>&1 || true
  if timeout 300 sudo apt-get install -y -qq -o Acquire::Retries=2 -o Acquire::http::Timeout=20 "${missing[@]}" >/dev/null; then
    exit 0
  fi
  echo "::warning::apt-get: попытка $i не удалась, повторяю"
  sleep 30
done
echo "::error::не удалось установить ${missing[*]}"
exit 1
