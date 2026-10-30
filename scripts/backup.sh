#!/bin/bash
# Ежедневный дамп базы finance из контейнера db.
# Дампы старше RETENTION_DAYS удаляются. Это число должно совпадать с
# BACKUP_RETENTION_DAYS в app/constants.py: бот обещает его пользователям
# при /delete_my_data.
#
# Запуск: bash scripts/backup.sh (из любой папки).
# cron, каждый день в 3:00:
#   0 3 * * * /bin/bash /root/finance-app/scripts/backup.sh >> /root/backup.log 2>&1
#
# pipefail: без него ошибка pg_dump терялась бы в конвейере, gzip всё равно
# создал бы маленький «успешный» файл
set -euo pipefail

RETENTION_DAYS=14
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"

# docker compose ищет docker-compose.yml в текущей папке: переходим в корень проекта
cd "$(dirname "$0")/.."
mkdir -p "$BACKUP_DIR"

file="$BACKUP_DIR/finance_$(date +%F_%H%M).sql.gz"
if ! docker compose exec -T db pg_dump -U postgres finance | gzip > "$file"; then
    # не оставляем битый файл, который выглядит как настоящий бэкап
    rm -f "$file"
    echo "Backup failed" >&2
    exit 1
fi

find "$BACKUP_DIR" -name 'finance_*.sql.gz' -mtime +"$RETENTION_DAYS" -delete
echo "Backup saved: $file"
