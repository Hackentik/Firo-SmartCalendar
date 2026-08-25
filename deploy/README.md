# Деплой и автообновление на VPS

Инструкция ниже разворачивает Firo SmartCalendar на чистом Linux-сервере (Ubuntu/Debian)
как systemd-сервис, который **сам подтягивает обновления с GitHub** каждые 5 минут —
без ручного захода по SSH и перезапуска.

Репозиторий проекта: https://github.com/Hackentik/Firo-SmartCalendar

## 1. Первоначальная установка

```bash
# Клонируем проект в /opt
sudo git clone https://github.com/Hackentik/Firo-SmartCalendar.git /opt/firo-smartcalendar
cd /opt/firo-smartcalendar

# Создаём виртуальное окружение и ставим зависимости
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt

# Готовим файл с переменными окружения
sudo cp deploy/.env.example deploy/.env
sudo nano deploy/.env   # впишите свой FIRO_SECRET_KEY и остальные значения
```

## 2. Настройка systemd-сервиса

```bash
# Копируем юнит-файл в systemd
sudo cp deploy/firo-smartcalendar.service /etc/systemd/system/

# Проверьте и при необходимости поправьте пути внутри firo-smartcalendar.service
# (User, WorkingDirectory) под вашего пользователя/директорию
sudo nano /etc/systemd/system/firo-smartcalendar.service

sudo systemctl daemon-reload
sudo systemctl enable firo-smartcalendar
sudo systemctl start firo-smartcalendar

# Проверяем, что всё запустилось
sudo systemctl status firo-smartcalendar
```

Приложение теперь доступно на `http://IP_СЕРВЕРА:5000`, а если сервер перезагрузится —
systemd поднимет его снова автоматически (см. `Restart=always` в юните).

## 3. Настройка автообновления

```bash
# Делаем скрипт исполняемым
sudo chmod +x /opt/firo-smartcalendar/deploy/autoupdate.sh

# Добавляем задачу в cron ОТ ИМЕНИ ROOT (важно - иначе не будет прав на restart сервиса)
sudo crontab -e
```

В открывшемся редакторе добавьте строку (проверка каждые 5 минут):

```
*/5 * * * * /opt/firo-smartcalendar/deploy/autoupdate.sh >> /var/log/firo-autoupdate.log 2>&1
```

Готово. Теперь при каждом `git push` в ветку `main` на GitHub, в течение 5 минут сервер
сам подтянет изменения, при необходимости обновит зависимости (если менялся
`requirements.txt`) и перезапустит сервис.

### Проверить, что автообновление работает

```bash
# Посмотреть лог последних проверок
tail -f /var/log/firo-autoupdate.log

# Запустить проверку вручную (не дожидаясь cron)
sudo /opt/firo-smartcalendar/deploy/autoupdate.sh
```

## Как это работает

`autoupdate.sh` не использует вебхуки — не нужно ничего настраивать на стороне GitHub
и не нужен публично открытый порт для приёма уведомлений. Скрипт просто:

1. Сравнивает локальный `git rev-parse HEAD` с `origin/main` на GitHub
2. Если есть новые коммиты — делает `git reset --hard origin/main`
3. Если менялся `requirements.txt` — обновляет зависимости
4. Перезапускает `systemctl restart firo-smartcalendar`

Минус такого подхода — обновление приходит не мгновенно, а с задержкой до 5 минут
(зависит от частоты в cron). Для мгновенного обновления по пушу нужен вебхук
GitHub → небольшой HTTP-эндпоинт на сервере, который дёргает тот же скрипт — это можно
добавить отдельным шагом, если задержка в 5 минут окажется критичной.

## Ручное обновление (без ожидания cron)

Если нужно обновить сервер прямо сейчас, не дожидаясь автообновления:

```bash
sudo /opt/firo-smartcalendar/deploy/autoupdate.sh
```

Или вручную, шаг за шагом:

```bash
cd /opt/firo-smartcalendar
sudo git pull origin main
sudo ./venv/bin/pip install -r requirements.txt   # если менялись зависимости
sudo systemctl restart firo-smartcalendar
```

## Если раньше приложение запускали вручную (python app.py)

Если у вас уже был запущен процесс через `python3 app.py` в screen/tmux — остановите
его (`Ctrl+C` в той сессии) перед тем, как включать systemd-сервис, чтобы два процесса
не пытались одновременно занять один и тот же порт.
