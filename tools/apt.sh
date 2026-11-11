#!/usr/bin/env bash
# Установка пакетов на раннере GitHub без зависаний: зеркало Ubuntu иногда не отвечает
# (11.11.2026 apt-get висел по 20 минут из-за DNS). Порядок: уже стоит → apt с тайм-аутом →
# для ffmpeg — готовая сборка с GitHub (BtbN/FFmpeg-Builds, есть и ffprobe).
# Запуск: bash tools/apt.sh ffmpeg imagemagick
missing=()
for p in "$@"; do
  bin=$p; [ "$p" = imagemagick ] && bin=convert
  command -v "$bin" >/dev/null || missing+=("$p")
done
[ ${#missing[@]} -eq 0 ] && exit 0
opts="-o Acquire::Retries=1 -o Acquire::http::Timeout=15 -o Acquire::https::Timeout=15"
timeout 120 sudo apt-get update -qq $opts >/dev/null 2>&1 || echo "::warning::apt-get update не прошёл"
if timeout 240 sudo apt-get install -y -qq $opts "${missing[@]}" >/dev/null 2>&1; then
  exit 0
fi
echo "::warning::apt-get не смог установить ${missing[*]} — пробую запасной путь"
ok=1
for p in "${missing[@]}"; do
  if [ "$p" = ffmpeg ]; then
    url=https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz
    if curl -fsSL --retry 3 --max-time 300 "$url" -o /tmp/ffmpeg.tar.xz && tar -xJf /tmp/ffmpeg.tar.xz -C /tmp; then
      sudo install -m 755 /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffmpeg /tmp/ffmpeg-master-latest-linux64-gpl/bin/ffprobe /usr/local/bin/
      ffmpeg -version | head -1
    else
      ok=0
    fi
  else
    ok=0
  fi
done
[ $ok = 1 ] && exit 0
echo "::error::не удалось установить ${missing[*]}"
exit 1
