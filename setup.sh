#!/bin/bash

echo "🚀 Installing Backup Tool dependencies..."

# Check Python version
python3 --version || { echo "❌ Python 3 is required!"; exit 1; }

# Create virtual environment (optional)
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies
echo "⬇️  Installing Python packages..."
pip install -r requirements.txt

# Создаём symlink для запуска командой 'backups3'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "🔗 Создаю команду 'backups3'..."

# Копируем backup_tool.py в /opt/backup-tool/
sudo mkdir -p /opt/backup-tool
sudo cp "$SCRIPT_DIR/backup_tool.py" /opt/backup-tool/

# Создаём скрипт в /usr/local/bin
sudo tee /usr/local/bin/backups3 > /dev/null << 'EOF'
#!/bin/bash
python3 /opt/backup-tool/backup_tool.py "$@"
EOF

sudo chmod +x /usr/local/bin/backups3

echo ""
echo "✅ Установка завершена!"
echo ""
echo "📝 Теперь можно запускать из любой директории:"
echo "   backups3"
echo ""
echo "📋 Или с флагами:"
echo "   backups3 --auto"
echo "   backups3 backup --path /home/user"
