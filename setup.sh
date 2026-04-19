#!/bin/bash

set -euo pipefail

APP_DIR="/opt/backup-tool"
VENV_DIR="$APP_DIR/venv"
LAUNCHER="/usr/local/bin/backups3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

download_file() {
    local url="$1"
    local output="$2"

    if have_cmd curl; then
        curl -fsSL "$url" -o "$output"
        return
    fi

    if have_cmd wget; then
        wget -qO "$output" "$url"
        return
    fi

    echo "curl or wget is required."
    exit 1
}

detect_pkg_manager() {
    if have_cmd apt-get; then
        echo "apt"
        return
    fi
    if have_cmd dnf; then
        echo "dnf"
        return
    fi
    if have_cmd yum; then
        echo "yum"
        return
    fi
    if have_cmd pacman; then
        echo "pacman"
        return
    fi
    if have_cmd zypper; then
        echo "zypper"
        return
    fi
    echo ""
}

install_packages() {
    local manager="$1"
    shift

    case "$manager" in
        apt)
            run_root apt-get update
            run_root apt-get install -y "$@"
            ;;
        dnf)
            run_root dnf install -y "$@"
            ;;
        yum)
            run_root yum install -y "$@"
            ;;
        pacman)
            run_root pacman -Sy --noconfirm "$@"
            ;;
        zypper)
            run_root zypper --non-interactive install "$@"
            ;;
        *)
            echo "Unsupported package manager. Install dependencies manually: $*"
            exit 1
            ;;
    esac
}

ensure_python3() {
    if have_cmd python3; then
        return
    fi

    local manager
    manager="$(detect_pkg_manager)"

    echo "Python 3 not found. Installing..."
    case "$manager" in
        apt|dnf|yum|zypper)
            install_packages "$manager" python3
            ;;
        pacman)
            install_packages "$manager" python
            ;;
        *)
            echo "Python 3 is required."
            exit 1
            ;;
    esac
}

ensure_venv_support() {
    local test_dir
    test_dir="$(mktemp -d)"

    if python3 -m venv "$test_dir/test-venv" >/dev/null 2>&1; then
        rm -rf "$test_dir"
        return
    fi

    rm -rf "$test_dir"

    local manager
    manager="$(detect_pkg_manager)"
    local py_version
    py_version="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

    echo "Installing Python venv support..."

    case "$manager" in
        apt)
            run_root apt-get update
            run_root apt-get install -y "python${py_version}-venv" || run_root apt-get install -y python3-venv
            ;;
        dnf|yum)
            install_packages "$manager" python3-pip python3-virtualenv
            ;;
        pacman)
            install_packages "$manager" python-virtualenv
            ;;
        zypper)
            install_packages "$manager" python3-virtualenv
            ;;
        *)
            echo "Could not install venv support automatically."
            exit 1
            ;;
    esac

    test_dir="$(mktemp -d)"
    if ! python3 -m venv "$test_dir/test-venv" >/dev/null 2>&1; then
        rm -rf "$test_dir"
        echo "python3 -m venv is still unavailable after dependency installation."
        exit 1
    fi
    rm -rf "$test_dir"
}

ensure_system_pip_support() {
    local manager
    manager="$(detect_pkg_manager)"

    case "$manager" in
        apt|dnf|yum|zypper)
            install_packages "$manager" python3-pip
            ;;
        pacman)
            install_packages "$manager" python-pip
            ;;
        *)
            echo "Could not install pip automatically."
            exit 1
            ;;
    esac
}

venv_has_python() {
    [ -x "$VENV_DIR/bin/python" ]
}

venv_has_working_pip() {
    venv_has_python && run_root "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1
}

bootstrap_pip_in_venv() {
    if ! venv_has_python; then
        return 1
    fi

    if run_root "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1; then
        return 0
    fi

    if run_root "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

install_pip_with_get_pip() {
    if ! venv_has_python; then
        return 1
    fi

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    download_file "https://bootstrap.pypa.io/get-pip.py" "$tmp_dir/get-pip.py"

    if run_root "$VENV_DIR/bin/python" "$tmp_dir/get-pip.py" >/dev/null 2>&1; then
        rm -rf "$tmp_dir"
        return 0
    fi

    rm -rf "$tmp_dir"
    return 1
}

recreate_venv() {
    echo "Recreating virtual environment..."
    run_root rm -rf "$VENV_DIR"
    run_root python3 -m venv "$VENV_DIR"
}

ensure_valid_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment..."
        run_root python3 -m venv "$VENV_DIR"
    fi

    if ! venv_has_python; then
        recreate_venv
    fi

    if venv_has_working_pip; then
        return
    fi

    echo "Repairing missing pip inside virtual environment..."
    if bootstrap_pip_in_venv && venv_has_working_pip; then
        return
    fi

    ensure_system_pip_support
    recreate_venv

    if bootstrap_pip_in_venv && venv_has_working_pip; then
        return
    fi

    echo "Falling back to get-pip.py..."
    if install_pip_with_get_pip && venv_has_working_pip; then
        return
    fi

    echo "pip is still unavailable inside the virtual environment."
    exit 1
}

echo "Installing Backup Tool..."

ensure_python3
ensure_venv_support

echo "Preparing application directory..."
run_root mkdir -p "$APP_DIR"

echo "Copying project files..."
run_root cp "$SCRIPT_DIR/backup_tool.py" "$APP_DIR/backup_tool.py"
run_root cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/requirements.txt"

ensure_valid_venv

echo "Installing Python dependencies..."
run_root "$VENV_DIR/bin/python" -m pip install --upgrade pip
run_root "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

echo "Installing global launcher..."
run_root tee "$LAUNCHER" > /dev/null <<EOF
#!/bin/bash
if [ ! -t 0 ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
    exec </dev/tty >/dev/tty 2>/dev/tty
fi
exec "$VENV_DIR/bin/python" "$APP_DIR/backup_tool.py" "\$@"
EOF

run_root chmod +x "$LAUNCHER"

echo ""
echo "Installation completed."
echo "You can now run the tool from any directory with:"
echo "  backups3"
echo ""
echo "Launching Backup Tool..."
if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    exec "$LAUNCHER" </dev/tty >/dev/tty 2>/dev/tty
fi

echo "Interactive terminal is unavailable, so the program was not auto-launched."
echo "Run it manually with:"
echo "  backups3"
