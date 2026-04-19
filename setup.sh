#!/bin/bash

set -euo pipefail

APP_DIR="/opt/backup-tool"
VENV_DIR="$APP_DIR/venv"
LAUNCHER="/usr/local/bin/backups3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing Backup Tool..."

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required."
    exit 1
fi

echo "Preparing application directory..."
sudo mkdir -p "$APP_DIR"

echo "Copying project files..."
sudo cp "$SCRIPT_DIR/backup_tool.py" "$APP_DIR/backup_tool.py"
sudo cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/requirements.txt"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    sudo python3 -m venv "$VENV_DIR"
fi

echo "Installing Python dependencies..."
sudo "$VENV_DIR/bin/pip" install --upgrade pip
sudo "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "Installing global launcher..."
sudo tee "$LAUNCHER" > /dev/null <<EOF
#!/bin/bash
exec "$VENV_DIR/bin/python" "$APP_DIR/backup_tool.py" "\$@"
EOF

sudo chmod +x "$LAUNCHER"

echo ""
echo "Installation completed."
echo "You can now run the tool from any directory with:"
echo "  backups3"
echo ""
echo "Launching Backup Tool..."
exec "$LAUNCHER"
