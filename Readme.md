# BackupRestoreS3

CLI-инструмент для создания и восстановления резервных копий директорий с хранением в S3-совместимом бакете.

Поддерживает:

- backup директорий в `tar.gz`
- загрузку в один или несколько S3-аккаунтов
- restore из S3
- Telegram-уведомления
- опциональное GPG-шифрование
- запуск по расписанию через `cron`
- очистку старых backup по retention policy

## Требования

- Python 3.8+
- Linux для `cron`-автоматизации и установки глобальной команды `backups3`
- `gpg`, если используется шифрование

Зависимости Python:

```txt
click==8.1.7
boto3==1.34.0
requests==2.31.0
```

## Установка

### Вариант 1. Обычный запуск из проекта

```bash
git clone https://github.com/LaRsonOFFai/BackupResotoreS3.git
cd BackupResotoreS3
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 backup_tool.py
```

### Вариант 2. Установка глобальной команды `backups3`

В проекте команда `backups3` уже реализована, но глобально она появляется только после запуска `setup.sh`.

Что делает `setup.sh`:

- создаёт `venv`
- ставит Python-зависимости
- копирует `backup_tool.py` в `/opt/backup-tool/`
- создаёт `/usr/local/bin/backups3`

Установка:

```bash
git clone https://github.com/LaRsonOFFai/BackupResotoreS3.git
cd BackupResotoreS3
chmod +x setup.sh
./setup.sh
```

После этого можно запускать инструмент из любой директории:

```bash
backups3
backups3 backup --path /home/user/data
backups3 list
backups3 restore
backups3 --auto
```

### Что лежит в файле `backups3`

В репозитории уже есть локальный wrapper-скрипт [backups3](C:/Users/larri/Documents/Codex/2026-04-19-c-users-larri-pycharmprojects-back-restore/Restore-bedolaga/backups3), который запускает `backup_tool.py` из текущей папки проекта.

Это значит:

- `./backups3` работает прямо из каталога репозитория
- просто `backups3` из любой папки будет работать только после `setup.sh`

## Быстрый старт

1. Запустите инструмент:

```bash
python3 backup_tool.py
```

2. Откройте меню `Setup`
3. Добавьте хотя бы один S3-аккаунт
4. При необходимости настройте Telegram
5. При необходимости включите шифрование
6. Для авто-backup задайте расписание и пути

## Основные возможности

### 1. Backup

Создание архива директории и загрузка в S3:

```bash
python3 backup_tool.py backup --path /home/user/documents
```

Или, если установлен глобальный launcher:

```bash
backups3 backup --path /home/user/documents
```

### 2. Restore

Restore поддерживает два режима:

- `safe` по умолчанию: распаковка в отдельную директорию вида `~/backup_restore_YYYY-MM-DD_HH-MM-SS/`
- `overwrite`: восстановление в текущую директорию с возможной перезаписью файлов

Примеры:

```bash
python3 backup_tool.py restore
python3 backup_tool.py restore --overwrite
```

### 3. Просмотр backup в S3

```bash
python3 backup_tool.py list
```

### 4. Интерактивная настройка

```bash
python3 backup_tool.py setup
```

Через `Setup` можно настроить:

- S3-аккаунты
- Telegram-уведомления
- шифрование
- расписание backup
- список директорий для авто-backup

## Настройка S3

Поддерживаются:

- AWS S3
- MinIO
- Yandex Cloud Object Storage
- DigitalOcean Spaces
- другие S3-совместимые хранилища

При добавлении S3-аккаунта используются:

- `endpoint_url`
- `access_key`
- `secret_key`
- `region`
- `bucket`
- `prefix`

Если `endpoint_url` не указан, используется стандартный AWS S3.

## Telegram-уведомления

Поддерживаются:

- личные сообщения
- группы
- форум-топики через `topic_id`

Для настройки понадобятся:

- `BOT_TOKEN`
- `CHAT_ID`
- опционально `TOPIC_ID`

Во время настройки отправляется тестовое сообщение.

## Шифрование

Если включено шифрование, архив перед загрузкой в S3 шифруется через:

```bash
gpg --symmetric
```

Для работы нужен установленный `gpg`:

```bash
sudo apt install gnupg
```

Важно:

- пароль шифрования сейчас хранится в `~/.backup_tool/config.json`
- для production лучше использовать внешнее хранилище секретов или S3 SSE

## Auto-backup через cron

Инструмент умеет запускаться автоматически через `cron`.

Логика такая:

- `cron` запускает скрипт каждую минуту
- скрипт сверяет текущее время со списком `backup_times`
- если время совпало, создаётся backup всех путей из `backup_paths`

Установка cron-задачи:

```bash
python3 backup_tool.py install-cron-cmd
```

Удаление cron-задачи:

```bash
python3 backup_tool.py remove-cron-cmd
```

Также это можно сделать через интерактивное меню.

## Конфиг

Настройки хранятся в:

```bash
~/.backup_tool/config.json
```

Пример:

```json
{
  "s3_accounts": [
    {
      "name": "My AWS",
      "endpoint_url": "",
      "access_key": "...",
      "secret_key": "...",
      "region": "us-east-1",
      "bucket": "my-backups",
      "prefix": "backups/"
    }
  ],
  "telegram": {
    "bot_token": "123456:ABC-DEF...",
    "chat_id": "123456789",
    "topic_id": ""
  },
  "encryption": {
    "enabled": true,
    "password": "your-password"
  },
  "backup_times": ["03:00", "12:00", "23:00"],
  "backup_paths": ["/home/user/documents"],
  "retention_days": 7
}
```

## Примеры команд

```bash
python3 backup_tool.py
python3 backup_tool.py backup --path /home/user/documents
python3 backup_tool.py list
python3 backup_tool.py restore
python3 backup_tool.py restore --overwrite
python3 backup_tool.py setup
python3 backup_tool.py --auto
```

Если установлен launcher:

```bash
backups3
backups3 backup --path /home/user/documents
backups3 list
backups3 restore
```

## Ограничения и замечания

- проект ориентирован в первую очередь на Linux-среду
- глобальная команда `backups3` ставится через `setup.sh` в `/usr/local/bin`
- секреты пока не вынесены во внешнее безопасное хранилище
- для production стоит отдельно продумать хранение ключей и политику доступа к S3

## Troubleshooting

### `backups3: command not found`

Причины обычно такие:

- не запускался `setup.sh`
- `/usr/local/bin` отсутствует в `PATH`
- установка выполнялась без `sudo`

Проверьте:

```bash
which backups3
echo $PATH
ls -l /usr/local/bin/backups3
```

### Не работает cron

Проверьте:

```bash
crontab -l
sudo systemctl status cron
```

### Ошибка подключения к S3

Проверьте:

- `access_key`
- `secret_key`
- существование bucket
- корректность `endpoint_url`

### Telegram не отправляет сообщения

Проверьте:

- корректность `BOT_TOKEN`
- корректность `CHAT_ID`
- что бот добавлен в чат
- что для форум-группы задан правильный `topic_id`

## License

MIT
