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

## Установка в одну команду

Если нужно, чтобы пользователь просто скопировал ссылку, запустил установку и сразу попал в программу, используйте:

```bash
curl -fsSL https://raw.githubusercontent.com/LaRsonOFFai/BackupResotoreS3/main/install.sh | bash
```

Если на сервере нет `curl`, можно так:

```bash
wget -qO- https://raw.githubusercontent.com/LaRsonOFFai/BackupResotoreS3/main/install.sh | bash
```

Что делает этот установщик:

- скачивает нужные файлы проекта
- при необходимости доустанавливает `python3` и поддержку `venv`
- ставит приложение в `/opt/backup-tool`
- создаёт отдельный `venv` в `/opt/backup-tool/venv`
- ставит глобальную команду `backups3` в `/usr/local/bin/backups3`
- сразу запускает программу после завершения установки

После установки команда работает из любой директории:

```bash
backups3
backups3 backup --path /home/user/data
backups3 list
backups3 restore
```

## Обычная установка из репозитория

```bash
git clone https://github.com/LaRsonOFFai/BackupResotoreS3.git
cd BackupResotoreS3
chmod +x setup.sh
./setup.sh
```

`setup.sh` теперь тоже:

- устанавливает приложение глобально
- создаёт launcher `backups3`
- в конце сразу запускает программу

## Требования

- Python 3.8+
- Linux
- `sudo`
- `curl` или `wget` для one-line установки
- `gpg`, если используется шифрование

На Debian/Ubuntu установщик сам пытается поставить недостающие системные пакеты вроде `python3-venv`.

Python-зависимости:

```txt
click==8.1.7
boto3==1.34.0
requests==2.31.0
```

## Как работает `backups3`

В проекте есть два сценария запуска:

### 1. Локальный launcher в репозитории

Файл `backups3` в корне проекта можно запускать так:

```bash
./backups3
```

Он полезен для локальной работы прямо из репозитория.

### 2. Глобальная команда после установки

После `install.sh` или `setup.sh` создаётся файл:

```bash
/usr/local/bin/backups3
```

Этот launcher использует Python из:

```bash
/opt/backup-tool/venv/bin/python
```

и запускает:

```bash
/opt/backup-tool/backup_tool.py
```

Именно поэтому команда `backups3` после установки работает из любого места.

## Быстрый старт

1. Выполните one-line установку или `./setup.sh`
2. После установки программа откроется автоматически
3. В меню `Setup` добавьте хотя бы один S3-аккаунт
4. При необходимости настройте Telegram
5. При необходимости включите шифрование
6. Для авто-backup задайте расписание и пути

Если позже нужно открыть инструмент снова:

```bash
backups3
```

## Основные команды

### Backup

```bash
backups3 backup --path /home/user/documents
```

### Restore

```bash
backups3 restore
backups3 restore --overwrite
```

### Список backup в S3

```bash
backups3 list
```

### Настройка

```bash
backups3 setup
```

### Автозапуск для cron

```bash
backups3 --auto
```

## Restore

Поддерживаются два режима:

- `safe` по умолчанию: восстановление в отдельную директорию вида `~/backup_restore_YYYY-MM-DD_HH-MM-SS/`
- `overwrite`: восстановление в текущую директорию с перезаписью файлов

## Настройка S3

Поддерживаются:

- AWS S3
- MinIO
- Yandex Cloud Object Storage
- DigitalOcean Spaces
- другие S3-совместимые хранилища

Используются параметры:

- `endpoint_url`
- `access_key`
- `secret_key`
- `region`
- `bucket`
- `prefix`

## Telegram-уведомления

Поддерживаются:

- личные сообщения
- группы
- форум-топики через `topic_id`

Для настройки нужны:

- `BOT_TOKEN`
- `CHAT_ID`
- опционально `TOPIC_ID`

## Шифрование

Если включено шифрование, архив перед загрузкой в S3 шифруется через:

```bash
gpg --symmetric
```

Для установки:

```bash
sudo apt install gnupg
```

Важно:

- пароль шифрования сейчас хранится в `~/.backup_tool/config.json`
- для production лучше использовать отдельное хранилище секретов или S3 SSE

## Auto-backup через cron

Скрипт можно запускать автоматически через `cron`.

Логика:

- `cron` запускает команду каждую минуту
- инструмент сверяет текущее время со списком `backup_times`
- при совпадении создаёт backup для всех путей из `backup_paths`

Установить cron-задачу можно через меню или командами:

```bash
backups3 install-cron-cmd
backups3 remove-cron-cmd
```

## Конфиг

Файл настроек:

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

## Troubleshooting

### `backups3: command not found`

Проверьте:

```bash
which backups3
echo $PATH
ls -l /usr/local/bin/backups3
```

### Не работает one-line установка

Проверьте наличие `curl` или `wget`:

```bash
which curl
which wget
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
