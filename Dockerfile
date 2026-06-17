# Home Assistant с предустановленной зависимостью tele2api.
# HA при загрузке кастомной интеграции читает manifest.json и пытается
# pip-установить требования (tele2api тянется из git). Ставим её заранее,
# чтобы старт был быстрым и не зависел от наличия git в рантайме.
FROM ghcr.io/home-assistant/home-assistant:stable

# git нужен для установки tele2api из git+https
RUN apk add --no-cache git \
    && pip install --no-cache-dir "tele2api @ git+https://github.com/Muxee4ka/tele2api@v3.0.0"
