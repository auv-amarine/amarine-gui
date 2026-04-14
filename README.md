# Amarine Command GUI

GUI to easily run frequently used ROS2, Gazebo, Vision, and ArduPilot commands.

## Quick Start

### 1. Install Dependencies

```bash
cd ~/ros2_ws/src/sauvc26-code
bash setup_gui.sh
```

### 2. Run the GUI

```bash
cd ~/ros2_ws/src/sauvc26-code
python3 command_gui.py
```

### 3. (Optional) Setup Alias

Add to `~/.bashrc`:
```bash
alias gui='cd ~/ros2_ws/src/sauvc26-code && python3 command_gui.py'
```

## Adding New Commands

Edit the `command_gui.py` file and modify the `COMMANDS` dictionary:

```python
COMMANDS = {
    "Gazebo": {
        "Qualification World": "gz sim -v 3 -r sauvc_qualification.world",
        "Final World": "gz sim -v 3 -r sauvc_final.world",
        "Your New Command": "your command here",  # ← Add here
    },
    # ... other categories
}
```

Restart the GUI to see the new command.
