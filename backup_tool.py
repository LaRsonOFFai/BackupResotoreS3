#!/usr/bin/env python3
"""
📦 Linux Backup / Restore Tool (S3 + Telegram + Time Scheduler)

Лёгкий CLI-инструмент для бэкапа и восстановления данных с S3,
уведомлениями в Telegram и cron-планировщиком.
"""

import os
import sys
import json
import shlex
import tarfile
import tempfile
import subprocess
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from getpass import getpass

import click
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import requests

# ─────────────────────────────────────────────
# Константы и конфигурация
# ─────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".backup_tool"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOCK_FILE = Path("/tmp/backup_tool.lock")
DEFAULT_RETENTION_DAYS = 7

os.makedirs(CONFIG_DIR, exist_ok=True)
TTY_INPUT = None


def get_input_stream():
    """Return an interactive input stream, preferring /dev/tty when available."""
    global TTY_INPUT

    if hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        return sys.stdin

    if TTY_INPUT is None:
        try:
            TTY_INPUT = open("/dev/tty", "r", encoding="utf-8", errors="ignore")
        except OSError:
            TTY_INPUT = False

    if TTY_INPUT:
        return TTY_INPUT

    return sys.stdin


# ─────────────────────────────────────────────
# Утилиты
# ─────────────────────────────────────────────

def load_config():
    """Загрузить конфигурацию из файла."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "s3_accounts": [],
        "telegram": {"bot_token": "", "chat_id": ""},
        "encryption": {"enabled": False, "password": ""},
        "backup_times": [],
        "backup_paths": []
    }


def safe_input(prompt: str = "") -> str:
    """Безопасный ввод без UnicodeDecodeError."""
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    try:
        line = get_input_stream().readline()
        if line == "":
            raise EOFError
        return line.strip()
    except UnicodeDecodeError:
        # Если Unicode ошибка — читаем как байты и декодируем
        return ""


def safe_int_input() -> int:
    """Безопасный ввод целого числа."""
    while True:
        try:
            value = int(safe_input().strip())
            return value
        except EOFError:
            click.echo("❌ Нет интерактивного ввода. Запустите команду в терминале ещё раз.")
            raise click.Abort()
        except ValueError:
            click.echo("❌ Введите число")


def ask_confirm(prompt_text: str, default: bool = True) -> bool:
    """Безопасная замена click.confirm без проблем с кодировкой."""
    suffix = "[Y/n]" if default else "[y/N]"
    print(f"{prompt_text} {suffix}")
    try:
        answer = safe_input().strip().lower()
        if not answer:
            return default
        return answer in ("y", "yes", "да", "д")
    except EOFError:
        return False


def save_config(config):
    """Сохранить конфигурацию в файл."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


def send_telegram_message(text: str, success: bool = True):
    """Отправить уведомление в Telegram."""
    config = load_config()
    bot_token = config.get("telegram", {}).get("bot_token", "")
    chat_id = config.get("telegram", {}).get("chat_id", "")
    topic_id = config.get("telegram", {}).get("topic_id", "")

    if not bot_token or not chat_id:
        return

    emoji = "✅" if success else "❌"
    message = f"{emoji} *Backup Tool*\n\n{text}"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    # Добавляем topic_id если настроен (для форум-групп)
    if topic_id:
        payload["message_thread_id"] = int(topic_id)

    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        click.echo(f"⚠️  Ошибка отправки Telegram: {e}")


def check_lock():
    """Проверить lock файл для защиты от повторного запуска."""
    if LOCK_FILE.exists():
        pid = LOCK_FILE.read_text().strip()
        # Проверяем, жив ли процесс
        try:
            os.kill(int(pid), 0)
            click.echo("⚠️  Backup уже запущен (lock file существует). Выход.")
            sys.exit(0)
        except (OSError, ValueError):
            # Процесс мёртв, удаляем stale lock
            LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()))


def release_lock():
    """Удалить lock файл."""
    LOCK_FILE.unlink(missing_ok=True)


def normalize_path(path: str) -> str:
    """Нормализовать путь (~, относительные пути)."""
    path = os.path.expanduser(path)
    path = os.path.abspath(path)
    return path


def safe_extract_tar(tar: tarfile.TarFile, destination: Path):
    """Safely extract a tar archive without allowing path traversal."""
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if os.path.commonpath([str(destination), str(member_path)]) != str(destination):
            raise ValueError(f"Unsafe path in archive: {member.name}")
    tar.extractall(path=destination)


def select_s3_account(accounts: list[dict], prompt_text: str = "Р’С‹Р±РµСЂРёС‚Рµ Р°РєРєР°СѓРЅС‚ (РЅРѕРјРµСЂ): "):
    """Select an S3 account from the configured list."""
    if not accounts:
        return None
    if len(accounts) == 1:
        return accounts[0]

    click.echo(prompt_text, nl=False)
    choice = safe_int_input()
    if not (1 <= choice <= len(accounts)):
        click.echo("вќЊ РќРµРІРµСЂРЅС‹Р№ РЅРѕРјРµСЂ")
        return None
    return accounts[choice - 1]


def get_archive_name(path: str, encrypted: bool = False) -> str:
    """Сгенерировать имя архива с timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = Path(path).name or "root"
    base_name = f"backup_{folder_name}_{timestamp}.tar.gz"
    if encrypted:
        base_name += ".gpg"
    return base_name


def test_s3_connection(client, bucket: str) -> bool:
    """Проверить подключение к S3."""
    try:
        client.head_bucket(Bucket=bucket)
        return True
    except ClientError as e:
        error_code = e.response['Error'].get('Code', '')
        if error_code == '404':
            click.echo(f"❌ Bucket '{bucket}' не найден")
        elif error_code == '403':
            click.echo(f"❌ Нет доступа к bucket '{bucket}'")
        else:
            click.echo(f"❌ Ошибка подключения: {e}")
        return False
    except Exception as e:
        click.echo(f"❌ Ошибка подключения: {e}")
        return False


def create_s3_client(account: dict):
    """Создать boto3 S3 клиент для аккаунта."""
    kwargs = {
        "aws_access_key_id": account["access_key"],
        "aws_secret_access_key": account["secret_key"],
        "region_name": account.get("region", "us-east-1")
    }
    if account.get("endpoint_url"):
        kwargs["endpoint_url"] = account["endpoint_url"]

    return boto3.client("s3", **kwargs)


# ─────────────────────────────────────────────
# S3 Функции
# ─────────────────────────────────────────────

def setup_s3_account():
    """Интерактивная настройка S3 аккаунта."""
    click.echo("\n📦 *Настройка S3 аккаунта*\n")

    endpoint_url = click.prompt("Endpoint URL (оставьте пустым для AWS S3)", default="", show_default=False)
    
    # Добавляем https:// если нет протокола
    if endpoint_url and not endpoint_url.startswith(("http://", "https://")):
        endpoint_url = "https://" + endpoint_url
    
    access_key = click.prompt("AWS Access Key ID")
    secret_key = getpass("AWS Secret Access Key: ")
    region = click.prompt("Region", default="us-east-1")
    bucket = click.prompt("Bucket name")
    prefix = click.prompt("Prefix (например backups/)", default="backups/")

    # Проверяем подключение
    click.echo("\n🔍 Проверяю подключение...")
    try:
        client = create_s3_client({
            "access_key": access_key,
            "secret_key": secret_key,
            "region": region,
            "endpoint_url": endpoint_url if endpoint_url else None
        })

        if test_s3_connection(client, bucket):
            click.echo("✅ Подключение успешно!")
        else:
            if ask_confirm("⚠️  Подключение не удалось. Всё равно сохранить?", default=False):
                pass  # Продолжаем
            else:
                return
    except Exception as e:
        click.echo(f"❌ Ошибка при проверке: {e}")
        if ask_confirm("⚠️  Подключение не удалось. Всё равно сохранить?", default=False):
            pass  # Продолжаем
        else:
            return

    config = load_config()
    account = {
        "name": click.prompt("Имя аккаунта (для отображения)", default=bucket),
        "endpoint_url": endpoint_url,
        "access_key": access_key,
        "secret_key": secret_key,
        "region": region,
        "bucket": bucket,
        "prefix": prefix
    }
    config["s3_accounts"].append(account)
    save_config(config)
    click.echo(f"✅ Аккаунт '{account['name']}' сохранён!")


def list_s3_accounts():
    """Показать список настроенных S3 аккаунтов."""
    config = load_config()
    accounts = config.get("s3_accounts", [])

    if not accounts:
        click.echo("\n⚠️  Нет настроенных S3 аккаунтов")
        return []

    click.echo("\n📦 *Настроенные S3 аккаунты:*\n")
    for i, acc in enumerate(accounts, 1):
        click.echo(f"  {i}. {acc['name']} (bucket: {acc['bucket']}, region: {acc['region']})")

    return accounts


def delete_s3_account(index: int):
    """Удалить S3 аккаунт по индексу."""
    config = load_config()
    accounts = config.get("s3_accounts", [])

    if 0 <= index < len(accounts):
        removed = accounts.pop(index)
        config["s3_accounts"] = accounts
        save_config(config)
        click.echo(f"✅ Аккаунт '{removed['name']}' удалён")
    else:
        click.echo("❌ Неверный индекс")


# ─────────────────────────────────────────────
# Telegram Функции
# ─────────────────────────────────────────────

def setup_telegram():
    """Интерактивная настройка Telegram."""
    click.echo("\n📲 *Настройка Telegram уведомлений*\n")
    
    click.echo("💡 Поддерживаются:")
    click.echo("  - Личные сообщения (chat_id)")
    click.echo("  - Группы (начинаются с -100)")
    click.echo("  - Форум-топики (с topic_id)")
    click.echo("")
    
    bot_token = click.prompt("BOT_TOKEN (от @BotFather)")
    chat_id = click.prompt("CHAT_ID (или ID группы, например -1001234567890)")
    
    # Спрашиваем про topic_id
    if chat_id.startswith("-100"):
        if ask_confirm("Это форум-группа? Настроить topic_id?", default=False):
            topic_id = click.prompt("TOPIC_ID (номер топика)")
        else:
            topic_id = ""
    else:
        topic_id = ""

    # Тестовое сообщение
    click.echo("\n🔍 Отправляю тестовое сообщение...")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ Backup Tool успешно настроен!",
        "parse_mode": "Markdown"
    }
    if topic_id:
        payload["message_thread_id"] = int(topic_id)
    
    try:
        resp = requests.post(url, json=payload, timeout=10)

        if resp.status_code == 200:
            click.echo("✅ Telegram настроен успешно!")
        else:
            click.echo(f"❌ Ошибка: {resp.json().get('description', resp.text)}")
            if not ask_confirm("⚠️  Всё равно сохранить?", default=False):
                return
    except Exception as e:
        click.echo(f"❌ Ошибка отправки: {e}")
        if not ask_confirm("⚠️  Всё равно сохранить?", default=False):
            return

    config = load_config()
    config["telegram"] = {
        "bot_token": bot_token,
        "chat_id": chat_id,
        "topic_id": topic_id
    }
    save_config(config)


# ─────────────────────────────────────────────
# Шифрование
# ─────────────────────────────────────────────

def setup_encryption():
    """Настройка шифрования."""
    config = load_config()

    enabled = ask_confirm("\n🔐 Включить шифрование архивов?", default=False)

    if enabled:
        password = getpass("Введите пароль для шифрования: ")
        password_confirm = getpass("Подтвердите пароль: ")

        if password != password_confirm:
            click.echo("❌ Пароли не совпадают!")
            return

        config["encryption"] = {"enabled": True, "password": password}
        click.echo("✅ Шифрование включено!")
    else:
        config["encryption"] = {"enabled": False, "password": ""}
        click.echo("✅ Шифрование отключено")

    save_config(config)


def encrypt_file(file_path: str, password: str) -> str:
    """Зашифровать файл через GPG."""
    encrypted_path = file_path + ".gpg"
    try:
        result = subprocess.run(
            ["gpg", "--symmetric", "--batch", "--yes", "--passphrase", password, "-o", encrypted_path, file_path],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return encrypted_path
        else:
            raise Exception(result.stderr)
    except FileNotFoundError:
        click.echo("❌ GPG не установлен. Установите: sudo apt install gnupg")
        raise
    except Exception as e:
        click.echo(f"❌ Ошибка шифрования: {e}")
        raise


def decrypt_file(encrypted_path: str, password: str, output_path: str) -> str:
    """Расшифровать файл через GPG."""
    try:
        result = subprocess.run(
            ["gpg", "--decrypt", "--batch", "--yes", "--passphrase", password, "-o", output_path, encrypted_path],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return output_path
        else:
            raise Exception(result.stderr)
    except Exception as e:
        click.echo(f"❌ Ошибка расшифровки: {e}")
        raise


# ─────────────────────────────────────────────
# Backup Функции
# ─────────────────────────────────────────────

def create_backup(path_to_backup: str):
    """Создать бэкап директории."""
    config = load_config()
    path = normalize_path(path_to_backup)

    if not os.path.exists(path):
        click.echo(f"❌ Путь '{path}' не существует!")
        send_telegram_message(f"❌ *BACKUP FAILED*\n\nПуть '{path}' не существует", success=False)
        return False

    if not os.path.isdir(path):
        click.echo(f"❌ '{path}' не является директорией!")
        send_telegram_message(f"❌ *BACKUP FAILED*\n\n'{path}' не является директорией", success=False)
        return False

    # Создаём архив
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    folder_name = Path(path).name or "root"
    archive_name = f"backup_{folder_name}_{timestamp}.tar.gz"
    archive_path = Path(tempfile.gettempdir()) / archive_name

    click.echo(f"\n📦 Создаю архив: {path}")
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(path, arcname=folder_name)

        archive_size = os.path.getsize(archive_path)
        size_mb = archive_size / (1024 * 1024)
        click.echo(f"✅ Архив создан: {size_mb:.2f} MB")

    except Exception as e:
        click.echo(f"❌ Ошибка архивации: {e}")
        send_telegram_message(f"❌ *BACKUP FAILED*\n\nОшибка архивации: {e}", success=False)
        return False

    # Шифрование если включено
    encryption_config = config.get("encryption", {})
    final_archive = archive_path

    if encryption_config.get("enabled"):
        click.echo("🔐 Шифрую архив...")
        try:
            final_archive = encrypt_file(str(archive_path), encryption_config["password"])
            os.remove(archive_path)  # Удаляем нешифрованную версию
            click.echo("✅ Архив зашифрован")
        except Exception:
            return False

    # Загрузка в S3
    accounts = config.get("s3_accounts", [])
    if not accounts:
        click.echo("❌ Нет настроенных S3 аккаунтов! Сначала выполните Setup")
        send_telegram_message("❌ *BACKUP FAILED*\n\nНет настроенных S3 аккаунтов", success=False)
        return False

    upload_success = True
    for account in accounts:
        click.echo(f"\n☁️  Загружаю в S3: {account['name']}...")
        try:
            client = create_s3_client(account)
            bucket = account["bucket"]
            prefix = account.get("prefix", "backups/")
            s3_key = f"{prefix}{archive_name}" if not encryption_config.get("enabled") else f"{prefix}{archive_name}.gpg"

            with open(final_archive, "rb") as f:
                client.upload_fileobj(f, bucket, s3_key)

            click.echo(f"✅ Загружено в {account['name']}: s3://{bucket}/{s3_key}")
        except Exception as e:
            click.echo(f"❌ Ошибка загрузки в {account['name']}: {e}")
            upload_success = False

    # Retention policy
    if upload_success:
        click.echo("\n🧹 Применяю retention policy...")
        for account in accounts:
            try:
                apply_retention(account)
            except Exception as e:
                click.echo(f"⚠️  Ошибка retention для {account['name']}: {e}")

    # Уведомление
    if upload_success:
        msg = (
            f"✅ *BACKUP SUCCESS*\n\n"
            f"📁 Путь: `{path}`\n"
            f"📦 Файл: `{archive_name}`\n"
            f"💾 Размер: `{size_mb:.2f} MB`\n"
            f"☁️  Загружено в {len(accounts)} аккаунт(ов)"
        )
        send_telegram_message(msg, success=True)
        click.echo(f"\n✅ BACKUP COMPLETED: {archive_name} ({size_mb:.2f} MB)")
    else:
        msg = f"❌ *BACKUP PARTIAL FAIL*\n\nАрхив создан, но ошибки загрузки в S3"
        send_telegram_message(msg, success=False)

    # Очистка временных файлов
    try:
        os.remove(final_archive)
    except:
        pass

    return upload_success


def apply_retention(account: dict):
    """Удалить старые бэкапы по retention policy."""
    config = load_config()
    retention_days = config.get("retention_days", DEFAULT_RETENTION_DAYS)
    cutoff = datetime.now() - timedelta(days=retention_days)

    client = create_s3_client(account)
    bucket = account["bucket"]
    prefix = account.get("prefix", "backups/")

    response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
    if "Contents" not in response:
        return

    for obj in response["Contents"]:
        obj_time = obj["LastModified"].replace(tzinfo=None)
        if obj_time < cutoff:
            click.echo(f"  🗑️  Удаляю: {obj['Key']} ({obj_time.strftime('%Y-%m-%d')})")
            client.delete_object(Bucket=bucket, Key=obj["Key"])


# ─────────────────────────────────────────────
# Restore Функции
# ─────────────────────────────────────────────

def list_backups():
    """Показать список бэкапов из S3."""
    accounts = list_s3_accounts()

    if not accounts:
        return

    # Выбор аккаунта
    if len(accounts) > 1:
        click.echo("Выберите аккаунт (номер): ", nl=False)
        choice = safe_int_input()
        if not (1 <= choice <= len(accounts)):
            click.echo("❌ Неверный номер")
            return
        account = accounts[choice - 1]
    else:
        account = accounts[0]

    click.echo(f"\n📋 Бэкапы в {account['name']}:\n")

    try:
        client = create_s3_client(account)
        bucket = account["bucket"]
        prefix = account.get("prefix", "backups/")

        response = client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        if "Contents" not in response or not response["Contents"]:
            click.echo("⚠️  Нет бэкапов")
            return

        backups = sorted(response["Contents"], key=lambda x: x["LastModified"], reverse=True)

        for i, obj in enumerate(backups, 1):
            size_mb = obj["Size"] / (1024 * 1024)
            date = obj["LastModified"].strftime("%Y-%m-%d %H:%M")
            click.echo(f"  {i}. {obj['Key']} ({size_mb:.2f} MB, {date})")

        return account, backups

    except Exception as e:
        click.echo(f"❌ Ошибка: {e}")
        return None


def restore_backup(safe_mode: bool = True):
    """Восстановить бэкап."""
    config = load_config()
    backup_listing = list_backups()

    if not backup_listing:
        return
    account, backups = backup_listing

    # Выбор бэкапа
    click.echo("Выберите бэкап (номер): ", nl=False)
    choice = safe_int_input()
    if not (1 <= choice <= len(backups)):
        click.echo("❌ Неверный номер")
        return

    backup_obj = backups[choice - 1]

    click.echo(f"\n📥 Восстанавливаю: {backup_obj['Key']}")

    # Подтверждение
    if not safe_mode:
        if not ask_confirm("⚠️  OVERWRITE MODE: файлы будут перезаписаны. Продолжить?", default=False):
            return

    try:
        client = create_s3_client(account)
        bucket = account["bucket"]

        # Скачиваем архив
        temp_path = Path(tempfile.gettempdir()) / backup_obj["Key"].split("/")[-1]
        client.download_file(bucket, backup_obj["Key"], str(temp_path))

        final_archive = str(temp_path)

        # Расшифровка если нужно
        encryption_config = config.get("encryption", {})
        if encryption_config.get("enabled") and final_archive.endswith(".gpg"):
            click.echo("🔐 Расшифровываю архив...")
            decrypted_path = str(temp_path).replace(".gpg", "")
            final_archive = decrypt_file(final_archive, encryption_config["password"], decrypted_path)
            os.remove(temp_path)

        # Определяем путь восстановления
        if safe_mode:
            restore_dir = Path.home() / f"backup_restore_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
        else:
            restore_dir = Path(".")

        os.makedirs(restore_dir, exist_ok=True)

        # Распаковка
        click.echo(f"📂 Распаковываю в: {restore_dir}")
        with tarfile.open(final_archive, "r:gz") as tar:
            safe_extract_tar(tar, Path(restore_dir))

        click.echo(f"✅ Restore завершён в: {restore_dir}")

        msg = (
            f"✅ *RESTORE SUCCESS*\n\n"
            f"📦 Файл: `{backup_obj['Key']}`\n"
            f"📂 Путь: `{restore_dir}`"
        )
        send_telegram_message(msg, success=True)

        # Очистка
        os.remove(final_archive)

    except Exception as e:
        click.echo(f"❌ Ошибка restore: {e}")
        msg = f"❌ *RESTORE FAILED*\n\nОшибка: {e}"
        send_telegram_message(msg, success=False)


# ─────────────────────────────────────────────
# Cron Scheduler
# ─────────────────────────────────────────────

def setup_schedule():
    """Настроить расписание авто-бэкапов."""
    config = load_config()

    click.echo("\n⏱️  *Настройка расписания авто-бэкапов*\n")
    click.echo("Введите время запуска в формате HH:MM (например: 3:00 12:00 23:00)")
    click.echo("Можно через пробел или запятую")
    click.echo("Время (через пробел): ", nl=False)
    times_str = safe_input().strip()

    # Заменяем запятые на пробелы и разбиваем
    times_str = times_str.replace(",", " ")
    times = [t.strip() for t in times_str.split() if t.strip()]

    # Валидация
    for t in times:
        parts = t.split(":")
        if len(parts) != 2 or not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            click.echo(f"❌ Неверное время: {t}")
            return

    config["backup_times"] = times
    save_config(config)
    click.echo(f"✅ Расписание сохранено: {', '.join(times)}")


def install_cron():
    """Установить cron задание."""
    config = load_config()

    if not config.get("backup_times"):
        click.echo("⚠️  Сначала настройте расписание (Setup → Schedule)")
        return

    script_path = shlex.quote(os.path.abspath(__file__))
    working_dir = shlex.quote(os.getcwd())
    cron_cmd = f"* * * * * cd {working_dir} && python3 {script_path} --auto >/dev/null 2>&1"

    try:
        # Читаем текущий crontab
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""

        # Проверяем, есть ли уже наше задание
        if "backup_tool.py --auto" in existing:
            click.echo("⚠️  Cron задание уже установлено")
            return

        # Добавляем
        new_crontab = existing + "\n" + cron_cmd + "\n"

        result = subprocess.run(["crontab", "-"], input=new_crontab, text=True)
        if result.returncode == 0:
            click.echo("✅ Cron задание установлено!")
            click.echo(f"   Команда: {cron_cmd}")
        else:
            click.echo("❌ Ошибка установки cron")
    except FileNotFoundError:
        click.echo("❌ Cron не установлен в системе")


def remove_cron():
    """Удалить cron задание."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            click.echo("⚠️  Cron задания не найдены")
            return

        existing = result.stdout
        new_crontab = "\n".join([
            line for line in existing.split("\n")
            if "backup_tool.py --auto" not in line
        ])

        result = subprocess.run(["crontab", "-"], input=new_crontab + "\n", text=True)
        if result.returncode == 0:
            click.echo("✅ Cron задание удалено!")
        else:
            click.echo("❌ Ошибка удаления cron")
    except FileNotFoundError:
        click.echo("❌ Cron не установлен в системе")


def auto_backup():
    """Автоматический бэкап по расписанию (вызывается из cron)."""
    check_lock()

    try:
        config = load_config()
        current_time = datetime.now().strftime("%H:%M")
        backup_times = config.get("backup_times", [])

        if current_time not in backup_times:
            sys.exit(0)  # Не время для бэкапа

        # Берём первый путь для бэкапа
        backup_paths = config.get("backup_paths", [])
        if not backup_paths:
            sys.exit(0)

        for path in backup_paths:
            create_backup(path)
    finally:
        release_lock()


def setup_backup_path():
    """Добавить или удалить путь для авто-бэкапа."""
    config = load_config()
    
    while True:
        click.echo("\n📁 *Пути для авто-бэкапа*\n")
        backup_paths = config.get("backup_paths", [])
        
        if backup_paths:
            click.echo("📋 Настроенные пути:")
            for i, p in enumerate(backup_paths, 1):
                click.echo(f"  {i}. {p}")
            click.echo(f"  {len(backup_paths) + 1}. Добавить путь")
            click.echo("  0. Назад")
        else:
            click.echo("⚠️  Нет настроенных путей")
            click.echo("  1. Добавить путь")
            click.echo("  0. Назад")
        
        click.echo("\nВыберите действие: ", nl=False)
        choice = safe_int_input()
        
        if choice == 0:
            break
        elif choice == len(backup_paths) + 1:
            # Добавить путь
            click.echo("\n📁 Введите путь для авто-бэкапа: ", nl=False)
            path = safe_input().strip()
            path = normalize_path(path)
            
            if not os.path.exists(path):
                click.echo(f"❌ Путь '{path}' не существует!")
                continue
            
            # Проверка на дубликат
            if path in config.get("backup_paths", []):
                click.echo(f"⚠️  Путь уже добавлен: {path}")
                continue
            
            config.setdefault("backup_paths", []).append(path)
            save_config(config)
            click.echo(f"✅ Путь добавлен: {path}")
            config = load_config()
        elif 1 <= choice <= len(backup_paths):
            # Удалить путь по номеру из списка
            idx = choice - 1
            path_to_delete = backup_paths[idx]
            if ask_confirm(f"Удалить путь '{path_to_delete}'?", default=False):
                removed = backup_paths.pop(idx)
                config["backup_paths"] = backup_paths
                save_config(config)
                click.echo(f"✅ Путь удалён: {removed}")
                config = load_config()
            else:
                click.echo("❌ Удаление отменено")
        else:
            click.echo("❌ Неверный номер")


# ─────────────────────────────────────────────
# CLI Меню
# ─────────────────────────────────────────────

@click.group()
def cli():
    """📦 Linux Backup / Restore Tool"""
    pass


@cli.command()
@click.option("--path", "-p", help="Путь для бэкапа")
def backup(path):
    """📦 Создать бэкап директории"""
    if not path:
        click.echo("📁 Введите путь для бэкапа: ", nl=False)
        path = safe_input().strip()
    create_backup(path)


@cli.command()
@click.option("--safe/--overwrite", default=True, help="Режим восстановления")
def restore(safe):
    """🔄 Восстановить бэкап"""
    restore_backup(safe_mode=safe)


@cli.command()
def list():
    """📋 Список бэкапов в S3"""
    list_backups()


@cli.command()
def setup():
    """⚙️  Интерактивная настройка инструмента"""
    while True:
        # Показываем текущие настройки
        config = load_config()
        backup_times = config.get("backup_times", [])
        backup_paths = config.get("backup_paths", [])
        encryption = config.get("encryption", {})
        telegram = config.get("telegram", {})
        
        click.echo("\n⚙️  *Настройка*\n")
        click.echo("📋 *Текущие настройки:*")
        click.echo(f"  S3 аккаунтов: {len(config.get('s3_accounts', []))}")
        click.echo(f"  Telegram: {'✅ настроен' if telegram.get('bot_token') else '❌ не настроен'}")
        click.echo(f"  Шифрование: {'✅ включено' if encryption.get('enabled') else '❌ отключено'}")
        click.echo(f"  ⏱️  Расписание: {', '.join(backup_times) if backup_times else 'не настроено'}")
        click.echo(f"  📁 Пути авто-бэкапа: {len(backup_paths)}")
        if backup_paths:
            for p in backup_paths:
                click.echo(f"     - {p}")
        
        click.echo("")
        click.echo("  1. S3 аккаунты")
        click.echo("  2. Telegram уведомления")
        click.echo("  3. Шифрование")
        click.echo("  4. Расписание авто-бэкапов")
        click.echo("  5. Пути для авто-бэкапа")
        click.echo("  6. Назад в главное меню")

        click.echo("\nВыберите действие (номер): ", nl=False)
        choice = safe_int_input()

        if choice == 1:
            while True:
                click.echo("\n📦 *S3 аккаунты*\n")
                accounts = list_s3_accounts()
                if accounts:
                    click.echo(f"  {len(accounts) + 1}. Добавить аккаунт")
                    click.echo(f"  {len(accounts) + 2}. Удалить аккаунт")
                    click.echo("  0. Назад")

                    click.echo("\nВыберите действие: ", nl=False)
                    sub_choice = safe_int_input()
                    if sub_choice == len(accounts) + 1:
                        setup_s3_account()
                    elif sub_choice == len(accounts) + 2:
                        idx = safe_int_input() - 1
                        delete_s3_account(idx)
                    elif sub_choice == 0:
                        break
                else:
                    click.echo("  1. Добавить аккаунт")
                    click.echo("  0. Назад")
                    click.echo("\nВыберите действие: ", nl=False)
                    sub_choice = safe_int_input()
                    if sub_choice == 1:
                        setup_s3_account()
                    elif sub_choice == 0:
                        break

        elif choice == 2:
            setup_telegram()
        elif choice == 3:
            setup_encryption()
        elif choice == 4:
            setup_schedule()
        elif choice == 5:
            setup_backup_path()
        elif choice == 6:
            break


@cli.command()
def install_cron_cmd():
    """⏱️  Установить cron задание"""
    install_cron()


@cli.command()
def remove_cron_cmd():
    """⏱️  Удалить cron задание"""
    remove_cron()


@cli.command()
def auto():
    """🤖 Автоматический бэкап (для cron)"""
    auto_backup()


@cli.command("--auto", hidden=True)
def auto_flag():
    """[Внутренняя] Флаг для cron"""
    auto_backup()


@cli.command()
def main_menu():
    """🏠 Главное меню"""
    while True:
        click.echo("\n📦 *Backup Tool - Главное меню*\n")
        
        # Показываем текущие настройки
        config = load_config()
        backup_times = config.get("backup_times", [])
        backup_paths = config.get("backup_paths", [])
        
        click.echo("📋 *Текущие настройки:*")
        if backup_times:
            click.echo(f"  ⏱️  Расписание: {', '.join(backup_times)}")
        else:
            click.echo(f"  ⏱️  Расписание: не настроено")
        
        if backup_paths:
            click.echo(f"  📁 Пути авто-бэкапа:")
            for p in backup_paths:
                click.echo(f"     - {p}")
        else:
            click.echo(f"  📁 Пути авто-бэкапа: не настроены")
        
        click.echo("")
        click.echo("📦 *Меню:*\n")
        click.echo("  1. Backup (выбор пути)")
        click.echo("  2. Backup всех настроенных путей")
        click.echo("  3. Restore")
        click.echo("  4. List backups")
        click.echo("  5. Setup")
        click.echo("  6. Install cron")
        click.echo("  7. Remove cron")
        click.echo("  8. Exit")

        click.echo("\nВыберите действие (номер): ", nl=False)
        choice = safe_int_input()

        if choice == 1:
            click.echo("📁 Введите путь для бэкапа: ", nl=False)
            path = safe_input().strip()
            create_backup(path)
        elif choice == 2:
            # Ручной запуск бэкапа для всех настроенных путей
            config = load_config()
            backup_paths = config.get("backup_paths", [])
            
            if not backup_paths:
                click.echo("⚠️  Нет настроенных путей! Сначала добавьте в Setup → Пути для авто-бэкапа")
            else:
                click.echo(f"\n🚀 Запускаю бэкап {len(backup_paths)} пути(ов):")
                for i, path in enumerate(backup_paths, 1):
                    click.echo(f"\n[{i}/{len(backup_paths)}] Бэкап: {path}")
                    create_backup(path)
                click.echo("\n✅ Все бэкапы завершены!")
        elif choice == 3:
            mode = ask_confirm("SAFE MODE? (да = восстановление в отдельную папку)", default=True)
            restore_backup(safe_mode=mode)
        elif choice == 4:
            list_backups()
        elif choice == 5:
            # Вызываем setup напрямую
            while True:
                # Показываем текущие настройки
                config = load_config()
                backup_times = config.get("backup_times", [])
                backup_paths = config.get("backup_paths", [])
                encryption = config.get("encryption", {})
                telegram = config.get("telegram", {})
                
                click.echo("\n⚙️  *Настройка*\n")
                click.echo("📋 *Текущие настройки:*")
                click.echo(f"  S3 аккаунтов: {len(config.get('s3_accounts', []))}")
                click.echo(f"  Telegram: {'✅ настроен' if telegram.get('bot_token') else '❌ не настроен'}")
                click.echo(f"  Шифрование: {'✅ включено' if encryption.get('enabled') else '❌ отключено'}")
                click.echo(f"  ⏱️  Расписание: {', '.join(backup_times) if backup_times else 'не настроено'}")
                click.echo(f"  📁 Пути авто-бэкапа: {len(backup_paths)}")
                if backup_paths:
                    for p in backup_paths:
                        click.echo(f"     - {p}")
                
                click.echo("")
                click.echo("  1. S3 аккаунты")
                click.echo("  2. Telegram уведомления")
                click.echo("  3. Шифрование")
                click.echo("  4. Расписание авто-бэкапов")
                click.echo("  5. Пути для авто-бэкапа")
                click.echo("  0. Назад")

                click.echo("\nВыберите действие: ", nl=False)
                sub_choice = safe_int_input()

                if sub_choice == 1:
                    while True:
                        click.echo("\n📦 *S3 аккаунты*\n")
                        accounts = list_s3_accounts()
                        if accounts:
                            click.echo(f"  {len(accounts) + 1}. Добавить аккаунт")
                            click.echo(f"  {len(accounts) + 2}. Удалить аккаунт")
                            click.echo("  0. Назад")

                            click.echo("\nВыберите действие: ", nl=False)
                            sub2 = safe_int_input()
                            if sub2 == len(accounts) + 1:
                                setup_s3_account()
                            elif sub2 == len(accounts) + 2:
                                idx = safe_int_input() - 1
                                delete_s3_account(idx)
                            elif sub2 == 0:
                                break
                        else:
                            click.echo("  1. Добавить аккаунт")
                            click.echo("  0. Назад")
                            click.echo("\nВыберите действие: ", nl=False)
                            sub2 = safe_int_input()
                            if sub2 == 1:
                                setup_s3_account()
                            elif sub2 == 0:
                                break

                elif sub_choice == 2:
                    setup_telegram()
                elif sub_choice == 3:
                    setup_encryption()
                elif sub_choice == 4:
                    setup_schedule()
                elif sub_choice == 5:
                    setup_backup_path()
                elif sub_choice == 0:
                    break
        elif choice == 6:
            install_cron()
        elif choice == 7:
            remove_cron()
        elif choice == 8:
            click.echo("👋 Выход")
            sys.exit(0)


if __name__ == "__main__":
    # Проверяем --auto flag
    if "--auto" in sys.argv:
        auto_backup()
    else:
        main_menu()
