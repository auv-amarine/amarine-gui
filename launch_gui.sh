#!/bin/bash
# Wrapper script untuk menjalankan GUI Amarine dengan proper environment

LOG_FILE="$HOME/.amarine-gui.log"
PYTHON_SCRIPT="/home/amarine/amarine-gui/command_gui.py"

{
    echo "=========================================="
    echo "Amarine GUI Launch"
    echo "=========================================="
    echo "Waktu: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "User: $(whoami)"
    
    # === Source user environment ===
    echo "[*] Loading user environment..."
    
    # Try to get DISPLAY from common places
    if [ -z "$DISPLAY" ]; then
        # Try to detect from running X server
        if [ -S /tmp/.X11-unix/* ] 2>/dev/null; then
            DISPLAY=$(ps -C Xvfb -f --no-header | sed -n 's/.*Xvfb :[0-9]*/:/p' | head -n 1)
        fi
        
        # Fallback to :0
        if [ -z "$DISPLAY" ]; then
            DISPLAY=":0"
        fi
    fi
    
    # Try to get XAUTHORITY
    if [ -z "$XAUTHORITY" ]; then
        XAUTHORITY="$HOME/.Xauthority"
    fi
    
    # Try to get XDG_RUNTIME_DIR
    if [ -z "$XDG_RUNTIME_DIR" ]; then
        XDG_RUNTIME_DIR="/run/user/$(id -u)"
    fi
    
    # Export for Python subprocess
    export DISPLAY
    export XAUTHORITY
    export XDG_RUNTIME_DIR
    export QT_QPA_PLATFORM_PLUGIN_PATH=/usr/lib/x86_64-linux-gnu/qt5/plugins
    
    echo "    DISPLAY: $DISPLAY"
    echo "    XAUTHORITY: $XAUTHORITY"
    echo "    XDG_RUNTIME_DIR: $XDG_RUNTIME_DIR"
    echo ""
    
    # === Check dependencies ===
    echo "[1] Checking PyQt5..."
    if python3 -c "import PyQt5" 2>&1; then
        echo "    ✓ PyQt5 OK"
    else
        echo "    ✗ PyQt5 NOT FOUND - Installing..."
        pip3 install PyQt5==5.15.7 PyQtWebEngine==5.15.6
    fi
    
    echo "[2] Checking other dependencies..."
    python3 -c "import psutil; print('    ✓ All dependencies OK')" 2>&1 || {
        echo "    ⚠ Installing missing packages..."
        pip3 install -r "$HOME/amarine-gui/requirements.txt"
    }
    
    echo ""
    echo "[3] Starting GUI..."
    echo "    Script: $PYTHON_SCRIPT"
    echo "    PID: $$"
    echo "=========================================="
    echo ""
    
    # === Run the GUI ===
    python3 "$PYTHON_SCRIPT" 2>&1
    EXIT_CODE=$?
    
    echo ""
    echo "=========================================="
    echo "GUI closed (exit code: $EXIT_CODE)"
    echo "=========================================="
    
} >> "$LOG_FILE" 2>&1

exit 0

