#!/usr/bin/env bash
# autoupdate.sh - проверяет, есть ли новые коммиты в GitHub-репозитории проекта,
# и если да - подтягивает их, обновляет зависимости и перезапускает systemd-сервис.
#
# Не требует вебхука от GitHub: просто запускается по расписанию (через cron)
# и сам сравнивает локальный HEAD с тем, что лежит на GitHub.
#
# Настройка (один раз):
#   1. Склонируйте репозиторий на сервер:
#        sudo git clone https://github.com/Hackentik/Firo-SmartCalendar.git /opt/firo-smartcalendar
#   2. Поправьте переменные ниже под свой сервер, если пути отличаются.
#   3. Сделайте скрипт исполняемым:
#        chmod +x /opt/firo-smartcalendar/deploy/autoupdate.sh
#   4. Добавьте в cron (проверка раз в 5 минут) - ВАЖНО: скрипт делает systemctl restart,
#      поэтому cron-задачу нужно ставить от имени root (sudo crontab -e), иначе перезапуск
#      сервиса не сработает из-за прав доступа:
#        sudo crontab -e
#        */5 * * * * /opt/firo-smartcalendar/deploy/autoupdate.sh >> /var/log/firo-autoupdate.log 2>&1

set -euo pipefail

REPO_DIR="/opt/firo-smartcalendar"
BRANCH="main"
SERVICE_NAME="firo-smartcalendar"
VENV_PIP="$REPO_DIR/venv/bin/pip"

cd "$REPO_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Проверяем обновления..."

git fetch origin "$BRANCH" --quiet

LOCAL_HASH=$(git rev-parse HEAD)
REMOTE_HASH=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL_HASH" = "$REMOTE_HASH" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Новых коммитов нет, всё актуально."
    exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Найдены новые коммиты, обновляем: $LOCAL_HASH -> $REMOTE_HASH"

# Смотрим, менялся ли requirements.txt между старым и новым коммитом -
# если да, после pull нужно будет обновить зависимости
REQS_CHANGED=$(git diff --name-only "$LOCAL_HASH" "$REMOTE_HASH" | grep -c "requirements.txt" || true)

git reset --hard "origin/$BRANCH"

if [ "$REQS_CHANGED" != "0" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] requirements.txt изменился, обновляем зависимости..."
    "$VENV_PIP" install -r requirements.txt --quiet
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Перезапускаем сервис $SERVICE_NAME..."
systemctl restart "$SERVICE_NAME"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Готово. Приложение обновлено до $REMOTE_HASH"
