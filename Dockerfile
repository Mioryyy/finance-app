# slim — Debian с Python без компиляторов: asyncpg и psycopg2-binary ставятся готовыми сборками
FROM python:3.14-slim

# PYTHONUNBUFFERED — логи сразу видны в `docker compose logs`, без буфера
# PYTHONDONTWRITEBYTECODE — не создавать .pyc внутри контейнера
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /code

# сначала только зависимости: этот слой кэшируется и не пересобирается,
# пока не изменится requirements.txt
COPY requirements.txt .
RUN pip install -r requirements.txt

# код копируем после зависимостей; что не попадает в образ — в .dockerignore
COPY . .

# бот работает не от root; код принадлежит root, поэтому бот может его только читать
RUN useradd --create-home --uid 1000 bot
USER bot

# миграции перед каждым стартом: если применять нечего, alembic ничего не делает.
# exec заменяет shell на python, чтобы бот получил сигнал остановки от Docker
CMD ["sh", "-c", "alembic upgrade head && exec python -m app.bot.main"]
