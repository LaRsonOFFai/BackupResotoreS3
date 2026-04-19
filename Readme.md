# 📦 Linux Backup / Restore Tool

Лёгкий CLI-инструмент для бэкапа и восстановления данных с S3, уведомлениями в Telegram и cron-планировщиком.

## 🎯 Возможности

- ✅ **Backup** — архивация директорий в tar.gz
- ☁️ **S3 хранение** — загрузка в несколько S3 аккаунтов (AWS, MinIO, Yandex Cloud, DigitalOcean и др.)
- 🔄 **Restore** — восстановление с выбором версии (SAFE/OVERWRITE режимы)
- 📲 **Telegram уведомления** — статус бэкапа/восстановления
- 🔐 **Шифрование** — GPG шифрование архивов (опционально)
- ⏱️ **Auto-backup** — автоматические бэкапы по расписанию через cron
- 🧹 **Retention policy** — автоматическое удаление старых бэкапов (по умолчанию 7 дней)

---

## 🚀 Быстрый старт

### Установка

```bash
# Клонируйте репозиторий
git clone <your-repo-url>
cd "Restore bedolaga"

# Запустите установку
chmod +x setup.sh
./setup.sh
```

### Запуск

```bash
python3 backup_tool.py
```

---

## 📋 Использование

### Главное меню

```
📦 Backup Tool - Главное меню

  1. Backup           # Создать бэкап
  2. Restore          # Восстановить бэкап
  3. List backups     # Список бэкапов в S3
  4. Setup            # Настройка инструмента
  5. Install cron     # Установить авто-бэкапы
  6. Remove cron      # Удалить авто-бэкапы
  7. Exit             # Выход
```

---

## ⚙️  Настройка (Setup)

### 1. S3 аккаунты

Вы можете добавить **несколько S3 аккаунтов** для дублирования бэкапов:

- **Endpoint URL** — оставьте пустым для AWS S3 или укажите кастомный (MinIO, Yandex Cloud, etc.)
- **Access Key / Secret Key** — учётные данные
- **Region** — регион (например `us-east-1`, `ru-central1`)
- **Bucket** — имя bucket
- **Prefix** — префикс для файлов (например `backups/`)

**Проверка подключения** выполняется автоматически при добавлении.

### 2. Telegram уведомления

Для получения уведомлений:

1. Создайте бота через [@BotFather](https://t.me/botfather) в Telegram
2. Получите **BOT_TOKEN**
3. Узнайте свой **CHAT_ID** (можно через [@userinfobot](https://t.me/userinfobot))
4. Введите данные в меню Setup → Telegram

**Тестовое сообщение** отправляется при настройке для проверки.

### 3. Шифрование

- **Включить/выключить** — настраивается в меню
- При включении запрашивается **пароль** для GPG шифрования
- Все архивы шифруются перед загрузкой в S3
- При restore автоматически запрашивается расшифровка

### 4. Расписание авто-бэкапов

Введите время запуска в формате `HH:MM`:

```
Время (через пробел): 3:00 12:00 23:00
```

### 5. Пути для авто-бэкапа

Укажите директории, которые будут бэкапиться автоматически по расписанию.

---

## 🔧 Команды CLI

Инструмент также поддерживает прямые команды:

```bash
# Создать бэкап
python3 backup_tool.py backup --path /home/user/documents

# Восстановить (SAFE MODE)
python3 backup_tool.py restore

# Восстановить (OVERWRITE MODE)
python3 backup_tool.py restore --overwrite

# Список бэкапов
python3 backup_tool.py list

# Главное меню
python3 backup_tool.py main-menu

# Авто-бэкап (для cron)
python3 backup_tool.py --auto
```

---

## ⏱️  Auto-backup (Cron)

### Как работает

- Cron запускает инструмент **каждую минуту**: `* * * * *`
- Скрипт проверяет текущее время против `BACKUP_TIMES`
- Если совпало → запускается бэкап
- Если нет → выход (без действий)

### Защита от повторного запуска

Используется **lock file** (`/tmp/backup_tool.lock`):
- Если процесс уже запущен → новый экземпляр не запускается
- Stale lock автоматически очищается

### Установка

```
Главное меню → 5. Install cron
```

### Удаление

```
Главное меню → 6. Remove cron
```

---

## 📁 Конфигурация

Все настройки хранятся в `~/.backup_tool/config.json`:

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
    "chat_id": "123456789"
  },
  "encryption": {
    "enabled": true,
    "password": "your-password"
  },
  "backup_times": ["3:00", "12:00", "23:00"],
  "backup_paths": ["/home/user/documents"],
  "retention_days": 7
}
```

---

## ☁️  S3 структура

```
s3://bucket/backups/
├── backup_documents_2026-04-14_03-00-00.tar.gz
├── backup_documents_2026-04-13_12-00-00.tar.gz
└── backup_documents_2026-04-12_03-00-00.tar.gz
```

---

## 🔄 Restore режимы

### SAFE MODE (по умолчанию)
- Восстановление в отдельную папку: `~/backup_restore_YYYY-MM-DD_HH-MM-SS/`
- **Не трогает** текущие файлы
- Безопасно для тестирования

### OVERWRITE MODE
- Восстановление в текущую директорию
- **Может перезаписать** существующие файлы
- Требует подтверждения

---

## 📲 Telegram уведомления

### События

| Событие | Описание |
|---------|----------|
| ✅ BACKUP SUCCESS | Успешный бэкап с размером и именем файла |
| ❌ BACKUP FAILED | Ошибка архивации или загрузки |
| ✅ RESTORE SUCCESS | Успешное восстановление |
| ❌ RESTORE FAILED | Ошибка восстановления |

### Пример сообщения

```
✅ Backup Tool

✅ BACKUP SUCCESS

📁 Путь: /home/user/documents
📦 Файл: backup_documents_2026-04-14_03-00-00.tar.gz
💾 Размер: 15.42 MB
☁️  Загружено в 2 аккаунт(ов)
```

---

## 🔐 Шифрование

### Требования

- Установленный `gpg`: `sudo apt install gnupg`

### Как работает

- Архив шифруется через `gpg --symmetric` перед загрузкой
- Расшифровка происходит автоматически при restore
- Пароль хранится в конфиге (**⚠️ не рекомендуется для production**)

### Для production

Рекомендуется:
- Использовать GPG ключи вместо пароля
- Хранить пароль в secrets manager (AWS Secrets, Vault)
- Или отключить шифрование и использовать S3 SSE

---

## 🧹 Retention Policy

- **По умолчанию**: 7 дней
- Старые бэкапы удаляются **только после успешного backup**
- Очистка происходит для **всех настроенных S3 аккаунтов**

---

## 🛡️  Безопасность

### Что защищено

- ✅ S3 credentials проверяются перед сохранением
- ✅ Lock file защищает от двойного запуска
- ✅ Подтверждение перед OVERWRITE restore
- ✅ Rollback при ошибках распаковки

### Что нужно улучшить (для production)

- 🔒 Пароль шифрования в plaintext в конфиге
- 🔒 Нет HTTPS enforcement для endpoint URLs
- 🔒 Нет rate limiting для Telegram

---

## 📦 Зависимости

```txt
click==8.1.7       # CLI интерфейс
boto3==1.34.0      # S3 клиент
requests==2.31.0   # Telegram API
```

**Системные требования:**
- Python 3.8+
- Linux (cron поддержка)
- GPG (опционально, для шифрования)

---

## 🐛 Troubleshooting

### Cron не работает

```bash
# Проверьте, что cron запущен
sudo systemctl status cron

# Проверьте crontab
crontab -l

# Логи
grep CRON /var/log/syslog
```

### Ошибка S3 подключения

- Проверьте Access Key / Secret Key
- Убедитесь, что bucket существует
- Для кастомных endpoint укажите полный URL (например `https://s3.yandexcloud.net`)

### Telegram не отправляет сообщения

- Проверьте BOT_TOKEN (должен быть от @BotFather)
- Проверьте CHAT_ID
- Убедитесь, что бот добавлен в чат

---

## 📄 License

MIT

---

## 🤝 Поддержка

Если возникли вопросы или нашли баги — создайте Issue в репозитории.
