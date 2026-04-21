#!/usr/bin/env python3
"""
ROS2 Command GUI - Compact Version
Streamlined interface for AMarineUV team with monitoring
"""

import sys
import os
import subprocess
import threading
import warnings
import time
import signal
import re
import psutil
from threading import Lock
from queue import Queue

# Suppress PyQt5 deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QComboBox, QStyleFactory,
    QGridLayout, QFrame
)
from PyQt5.QtCore import Qt, QTimer, QSize
from PyQt5.QtGui import QFont, QIcon, QTextCursor, QColor

# ANSI Color codes to QColor map
ANSI_COLORS = {
    '30': '#000000',  # black
    '31': '#FF3333',  # red
    '32': '#33FF33',  # green
    '33': '#FFFF33',  # yellow
    '34': '#3333FF',  # blue
    '35': '#FF33FF',  # magenta
    '36': '#33FFFF',  # cyan
    '37': '#CCCCCC',  # white
    '90': '#666666',  # bright black
    '91': '#FF5555',  # bright red
    '92': '#55FF55',  # bright green
    '93': '#FFFF55',  # bright yellow
    '94': '#5555FF',  # bright blue
    '95': '#FF55FF',  # bright magenta
    '96': '#55FFFF',  # bright cyan
    '97': '#FFFFFF',  # bright white
}

def strip_ansi(text):
    """Remove ANSI color codes from text"""
    return re.sub(r'\033\[[0-9;]*m|\x1b\[[0-9;]*m', '', text)

# Mapping commands from bashrc
COMMANDS = {
    "Gazebo": {
        "Qualification": "gz sim -v 3 -r sauvc_qualification.world",
        "Final": "gz sim -v 3 -r sauvc_final.world",
    },
    "Vision": {
        "Docker Container": "docker start be537dc7c441 && docker exec be537dc7c441 bash -c 'cd /ultralytics && export ROS_DOMAIN_ID=0 && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && source /opt/ros/humble/setup.bash && python3 detect_ros.py'",
    },
    "ArduPilot": {
        "SITL": "cd ~/ardupilot && Tools/autotest/sim_vehicle.py -L RATBeach -v ArduSub -f vectored --model=JSON --out=udp:0.0.0.0:14550 --console",
    },
    "MAVRoS": {
        "MAVRoS": "ros2 launch mavros apm.launch fcu_url:=udp://:14550@localhost:14555",
    },
    "ROS2": {
        "Build": "cd ~/ros2_ws && colcon build --packages-select sauvc26_code",
        "Test": "ros2 run sauvc26_code test",
        "Arm": "ros2 run sauvc26_code arm",
        "Qualification": "ros2 run sauvc26_code qualification",
        "Final": "ros2 run sauvc26_code final",
    }
}

# Jetson Orin Nano Power Modes
POWER_MODES = {
    "1": "sudo nvpmodel -m 3",  # 7W
    "2": "sudo nvpmodel -m 0",  # 15W
    "3": "sudo nvpmodel -m 1",  # 25W
    "Max": "sudo nvpmodel -m 2",  # MAXN SUPER
}


class CommandExecutor:
    """Worker to run commands without freezing GUI"""

    def __init__(self, output_queue=None):
        self.process = None
        self.output_queue = output_queue
        self.is_running = False
        self.is_vision = False

    def append_to_queue(self, text):
        """Post text to output queue"""
        if self.output_queue:
            self.output_queue.put(text.rstrip('\n'))

    def run_command(self, command):
        """Run command and post output to queue"""
        try:
            self.is_running = True
            self.is_vision = 'docker exec be537dc7c441' in command
            text = f"▶ Running: {command}\n"
            self.append_to_queue(text)
            self.append_to_queue("─" * 80)

            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'

            self.process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                preexec_fn=os.setsid,
                env=env
            )

            try:
                if self.process.stdout:
                    while True:
                        try:
                            line = self.process.stdout.readline()
                            if not line:
                                break
                            if line.strip():
                                self.append_to_queue(line)
                        except ValueError:
                            break
            except Exception as e:
                pass

            self.process.wait()
            self.append_to_queue("─" * 80)
            self.append_to_queue(f"✓ Command finished (exit code: {self.process.returncode})\n")
            self.is_running = False

        except Exception as e:
            self.append_to_queue(f"✗ Error: {str(e)}\n")
            self.is_running = False

    def kill_process(self):
        """Kill the running process and all its children"""
        if not self.process:
            return

        if self.is_vision:
            if self.output_queue:
                self.output_queue.put("\n✗ KILLING VISION PROCESS...")

            # First, kill the subprocess
            try:
                pid = self.process.pid
                try:
                    pgid = os.getpgid(pid)
                except OSError:
                    pgid = pid

                os.killpg(pgid, signal.SIGTERM)
                time.sleep(0.5)
                if self.process.poll() is None:
                    os.killpg(pgid, signal.SIGKILL)
            except Exception as e:
                if self.output_queue:
                    self.output_queue.put(f"Kill subprocess error: {str(e)}")

            # Then stop docker container
            try:
                subprocess.call("docker stop be537dc7c441", shell=True)
                if self.output_queue:
                    self.output_queue.put("✓ Docker container stopped")
            except Exception as e:
                if self.output_queue:
                    self.output_queue.put(f"Docker stop error: {str(e)}")
            
            self.is_running = False
            return

        if self.output_queue:
            self.output_queue.put("\n✗ KILLING PROCESS (all children processes)...")

        try:
            pid = self.process.pid
            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = pid

            # Step 1: SIGINT
            try:
                os.killpg(pgid, signal.SIGINT)
                if self.output_queue:
                    self.output_queue.put(f"[1] Sent SIGINT to process group {pgid}")
                time.sleep(0.5)
            except Exception:
                pass

            if self.process.poll() is not None:
                if self.output_queue:
                    self.output_queue.put(f"✓ Process exited (code: {self.process.returncode})")
                self.is_running = False
                return

            # Step 2: SIGTERM
            try:
                os.killpg(pgid, signal.SIGTERM)
                if self.output_queue:
                    self.output_queue.put(f"[2] Sent SIGTERM to process group {pgid}")
                time.sleep(0.5)
            except Exception:
                pass

            if self.process.poll() is not None:
                if self.output_queue:
                    self.output_queue.put(f"✓ Process terminated (code: {self.process.returncode})")
                self.is_running = False
                return

            # Step 3: SIGKILL
            try:
                os.killpg(pgid, signal.SIGKILL)
                if self.output_queue:
                    self.output_queue.put(f"[3] Sent SIGKILL to process group {pgid}")
                time.sleep(0.2)
            except Exception:
                pass

            final_code = self.process.poll()
            if final_code is not None:
                if self.output_queue:
                    self.output_queue.put(f"✓ All processes killed (code: {final_code})")
            else:
                if self.output_queue:
                    self.output_queue.put("ERROR: Process still alive after SIGKILL!")
            
            self.is_running = False

        except Exception as e:
            if self.output_queue:
                self.output_queue.put(f"Kill error: {str(e)}")
            self.is_running = False


class ConsoleWidget(QFrame):
    """Console output widget"""

    def __init__(self, title="Console", parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Text edit
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Ubuntu Mono", 10))
        self.text_edit.setStyleSheet("background-color: #000000; color: #CCCCCC;")
        layout.addWidget(self.text_edit)

    def append_text(self, text, color='#CCCCCC'):
        """Append text with color"""
        clean_text = strip_ansi(text)
        self.text_edit.setTextColor(QColor(color))
        self.text_edit.append(clean_text)


class MonitoringPanel(QFrame):
    """System monitoring panel (placeholder)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        layout = QVBoxLayout(self)

        # Title
        title = QLabel("Monitoring")
        title.setFont(QFont("Ubuntu", 10, QFont.Bold))
        layout.addWidget(title)

        # Monitoring items
        self.stats = {
            "CPU": QLabel("CPU: --"),
            "GPU": QLabel("GPU: --"),
            "Memory": QLabel("Memory: --"),
            "Temp": QLabel("Temp: --"),
            "Watt": QLabel("Watt: --"),
        }

        for key, label in self.stats.items():
            label.setFont(QFont("Ubuntu Mono", 9))
            layout.addWidget(label)

        layout.addStretch()

    def update_stats(self):
        """Update monitoring stats"""
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            self.stats["CPU"].setText(f"CPU: {cpu}%")
            self.stats["Memory"].setText(f"Memory: {mem.percent}%")
        except Exception:
            pass


class ROS2PackageWidget(QFrame):
    """Widget for selecting and running ROS2 packages"""

    def __init__(self, console_title, on_run, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.on_run = on_run

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        # Dropdown layout
        dropdown_layout = QHBoxLayout()
        dropdown_layout.setSpacing(5)

        self.package_combo = QComboBox()
        self.package_combo.addItem("Select package...")
        for package_name in COMMANDS["ROS2"].keys():
            self.package_combo.addItem(package_name)
        self.package_combo.setFont(QFont("Ubuntu", 10))
        dropdown_layout.addWidget(self.package_combo)

        self.start_btn = QPushButton("Start")
        self.start_btn.setMaximumWidth(70)
        self.start_btn.setMaximumHeight(25)
        self.start_btn.setMinimumHeight(25)
        self.start_btn.setFont(QFont("Ubuntu", 8))
        self.start_btn.clicked.connect(self._on_start_clicked)
        dropdown_layout.addWidget(self.start_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(60)
        clear_btn.setMaximumHeight(25)
        clear_btn.setMinimumHeight(25)
        clear_btn.setFont(QFont("Ubuntu", 8))
        dropdown_layout.addWidget(clear_btn)

        layout.addLayout(dropdown_layout)

        # Console
        self.console = ConsoleWidget("")
        clear_btn.clicked.connect(self.console.text_edit.clear)
        layout.addWidget(self.console)

        self.executor = None
        self.is_running = False

    def _on_start_clicked(self):
        """Handle start/kill button click"""
        if self.is_running:
            if self.executor:
                self.executor.kill_process()
            self._set_button_state(False, "Start")
            self.is_running = False
        else:
            package_name = self.package_combo.currentText()
            if package_name in COMMANDS["ROS2"]:
                command = COMMANDS["ROS2"][package_name]
                self.on_run(package_name, command, self)
                self._set_button_state(True, "Kill")
                self.is_running = True

    def _set_button_state(self, is_running, text):
        """Set button styling based on running state"""
        self.start_btn.setText(text)
        if is_running:
            # Kill button - red with bright hover, size stays same
            self.start_btn.setStyleSheet("""
                QPushButton {
                    background-color: #FF4444;
                    color: white;
                    font-weight: bold;
                    border-radius: 3px;
                    padding: 3px;
                }
                QPushButton:hover {
                    background-color: #FF6666;
                }
            """)
        else:
            # Start button - normal
            self.start_btn.setStyleSheet("")

    def run_command(self, command):
        """Run command in executor"""
        output_queue = Queue()
        self.executor = CommandExecutor(output_queue)

        # Run in thread
        thread = threading.Thread(target=self.executor.run_command, args=(command,))
        thread.daemon = True
        thread.start()

        # Update console from queue
        self.update_console_timer = QTimer()
        self.update_console_timer.timeout.connect(lambda: self._process_queue(output_queue))
        self.update_console_timer.start(100)

    def _process_queue(self, output_queue):
        """Process output queue"""
        try:
            while True:
                text = output_queue.get_nowait()
                color = '#CCCCCC'

                if text.startswith('✓') or 'success' in text.lower():
                    color = ANSI_COLORS['32']
                elif text.startswith('✗') or 'error' in text.lower():
                    color = ANSI_COLORS['91']
                elif text.startswith('[') or '---' in text:
                    color = ANSI_COLORS['36']

                self.console.append_text(text, color)

                if 'Command finished' in text or 'killed' in text.lower():
                    self.is_running = False
                    self._set_button_state(False, "Start")
        except:
            pass


class CompactCommandGUI(QMainWindow):
    """Main GUI window"""

    def __init__(self):
        super().__init__()
        self.executors = {}
        self.output_queues = {}
        self.command_widgets = {}

        self.init_ui()
        self.setup_monitoring()

    def init_ui(self):
        """Initialize UI"""
        self.setWindowTitle("GUI Amarine v2.0")
        self.setGeometry(100, 100, 560, 1000)
        QApplication.setStyle(QStyleFactory.create('Fusion'))

        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # === TOP SECTION - Control Panel ===
        top_layout = QHBoxLayout()
        top_layout.setSpacing(2)

        # ===== COLUMN 1: GAZEBO & TEMPLATE BUTTONS =====
        col1_frame = QFrame()
        col1_layout = QVBoxLayout(col1_frame)
        col1_layout.setSpacing(5)

        # Gazebo World Option
        gazebo_frame = QFrame()
        gazebo_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        gazebo_layout = QVBoxLayout(gazebo_frame)
        gazebo_label = QLabel("Gazebo World")
        gazebo_label.setFont(QFont("Ubuntu", 8, QFont.Bold))
        gazebo_layout.addWidget(gazebo_label)

        # Gazebo combo and button in horizontal layout
        gazebo_controls = QHBoxLayout()
        self.gazebo_combo = QComboBox()
        self.gazebo_combo.addItem("Select World...")
        self.gazebo_combo.addItems(["Qualification", "Final"])
        self.gazebo_combo.setFont(QFont("Ubuntu", 7))
        self.gazebo_combo.setMaximumHeight(20)
        gazebo_controls.addWidget(self.gazebo_combo)

        self.gazebo_btn = QPushButton("Start")
        self.gazebo_btn.setMaximumWidth(55)
        self.gazebo_btn.setMaximumHeight(20)
        self.gazebo_btn.setFont(QFont("Ubuntu", 7))
        self.gazebo_btn.clicked.connect(lambda: self._toggle_gazebo_world())
        gazebo_controls.addWidget(self.gazebo_btn)
        gazebo_layout.addLayout(gazebo_controls)

        col1_layout.addWidget(gazebo_frame)

        # 8 Template buttons (4x2)
        template_grid = QGridLayout()
        template_grid.setSpacing(5)
        self.template_buttons = {}

        for row in range(4):
            for col in range(2):
                idx = row * 2 + col
                btn = QPushButton("Camera Bridge" if idx == 0 else "")
                btn.setMinimumHeight(40)
                btn.setFont(QFont("Ubuntu", 9))
                
                if idx == 0:  # Camera Bridge
                    btn.clicked.connect(lambda checked, b=btn: self._toggle_template_button(b, 0))
                else:  # Template
                    btn.clicked.connect(lambda checked, b=btn: self._toggle_template_button(b, idx))
                
                self.template_buttons[idx] = {'button': btn, 'is_running': False, 'executor': None}
                template_grid.addWidget(btn, row, col)

        col1_layout.addLayout(template_grid)
        top_layout.addWidget(col1_frame, 1)
        col1_frame.setMinimumWidth(150)

        # ===== COLUMN 2: TEMPLATE BUTTONS, POWER MODE =====
        col2_frame = QFrame()
        col2_layout = QVBoxLayout(col2_frame)
        col2_layout.setSpacing(5)

        # 6 Template buttons (3x2)
        template_grid2 = QGridLayout()
        template_grid2.setSpacing(5)
        
        button_labels = ["Open RQT", "Open RVIZ", "Open Qground", "Open Vscode", "Open Terminal", "Open BLHeli"]

        for row in range(3):
            for col in range(2):
                idx = row * 2 + col
                btn = QPushButton(button_labels[idx])
                btn.setMinimumHeight(40)
                btn.setFont(QFont("Ubuntu", 9))
                btn.clicked.connect(lambda checked, b=btn, i=idx: self._on_utility_button_clicked(i))
                self.template_buttons[100 + idx] = {'button': btn, 'is_running': False, 'executor': None}
                template_grid2.addWidget(btn, row, col)

        col2_layout.addLayout(template_grid2)

        # Power Mode Option
        power_frame = QFrame()
        power_frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        power_layout = QVBoxLayout(power_frame)
        power_label = QLabel("Power Mode Option")
        power_label.setFont(QFont("Ubuntu", 9, QFont.Bold))
        power_layout.addWidget(power_label)

        power_grid = QGridLayout()
        power_grid.setSpacing(5)
        
        for i, mode in enumerate(["1", "2", "3", "Max"]):
            btn = QPushButton(mode)
            btn.setMinimumHeight(30)
            btn.setFont(QFont("Ubuntu", 9))
            btn.clicked.connect(lambda checked, m=mode: self._set_power_mode(m))
            power_grid.addWidget(btn, 0, i)

        power_layout.addLayout(power_grid)
        col2_layout.addWidget(power_frame)

        # Settings and Kill All
        settings_layout = QHBoxLayout()
        settings_btn = QPushButton("Settings")
        settings_btn.setMinimumHeight(30)
        settings_btn.setFont(QFont("Ubuntu", 9))
        settings_layout.addWidget(settings_btn)

        kill_all_btn = QPushButton("Kill All")
        kill_all_btn.setMinimumHeight(30)
        kill_all_btn.setFont(QFont("Ubuntu", 9))
        kill_all_btn.clicked.connect(self._kill_all_processes)
        settings_layout.addWidget(kill_all_btn)

        col2_layout.addLayout(settings_layout)
        col2_layout.addStretch()

        top_layout.addWidget(col2_frame, 1)
        col2_frame.setMinimumWidth(150)

        # ===== COLUMN 3: MONITORING PANEL =====
        self.monitoring_panel = MonitoringPanel()
        monitoring_frame = QFrame()
        monitoring_layout = QVBoxLayout(monitoring_frame)
        monitoring_layout.addWidget(self.monitoring_panel)
        monitoring_layout.addStretch()
        monitoring_frame.setMinimumWidth(150)
        top_layout.addWidget(monitoring_frame, 1)

        main_layout.addLayout(top_layout)

        # === BOTTOM SECTION - CONSOLES ===
        console_grid = QGridLayout()
        console_grid.setSpacing(10)

        self.consoles = {}

        # Console 1: SITL
        self.consoles["sitl"] = self._create_command_console(
            "SITL",
            "ArduPilot",
            "SITL"
        )
        console_grid.addWidget(self.consoles["sitl"], 0, 0)

        # Console 2: MAVROS
        self.consoles["mavros"] = self._create_command_console(
            "MAVROS",
            "MAVRoS",
            "MAVRoS"
        )
        console_grid.addWidget(self.consoles["mavros"], 0, 1)

        # Console 3: Vision Docker
        self.consoles["vision"] = self._create_command_console(
            "Vision Docker",
            "Vision",
            "Docker Container"
        )
        console_grid.addWidget(self.consoles["vision"], 0, 2)

        # Consoles 4, 5, 6: ROS2 Package Selection
        for i in range(3):
            pkg_widget = ROS2PackageWidget(f"Package {i+1}", self._run_ros2_package)
            self.consoles[f"ros2_{i}"] = pkg_widget
            console_grid.addWidget(pkg_widget, 1, i)

        main_layout.addLayout(console_grid, 1)

    def _create_command_console(self, title, category, command_key):
        """Create a command console widget"""
        frame = QFrame()
        frame.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)

        # Title with command button
        title_layout = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setFont(QFont("Ubuntu", 9, QFont.Bold))
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        cmd_btn = QPushButton("Start")
        cmd_btn.setMaximumWidth(70)
        cmd_btn.setMaximumHeight(25)
        cmd_btn.setMinimumHeight(25)
        cmd_btn.setFont(QFont("Ubuntu", 8))

        clear_btn = QPushButton("Clear")
        clear_btn.setMaximumWidth(60)
        clear_btn.setMaximumHeight(25)
        clear_btn.setMinimumHeight(25)
        clear_btn.setFont(QFont("Ubuntu", 8))

        # Store state
        key = f"{category}_{command_key}"
        if key not in self.executors:
            self.executors[key] = None
            self.output_queues[key] = Queue()

        cmd_btn.clicked.connect(lambda: self._toggle_command(
            category, command_key, key, cmd_btn
        ))

        title_layout.addWidget(cmd_btn)
        title_layout.addWidget(clear_btn)
        layout.addLayout(title_layout)

        # Console
        console = ConsoleWidget("")
        clear_btn.clicked.connect(console.text_edit.clear)
        layout.addWidget(console)

        # Store console reference
        self.command_widgets[key] = {
            'console': console,
            'button': cmd_btn,
            'category': category,
            'command_key': command_key,
            'is_running': False
        }

        return frame

    def _toggle_command(self, category, command_key, key, button):
        """Toggle command execution"""
        widget = self.command_widgets[key]
        
        if widget['is_running']:
            executor = self.executors[key]
            if executor:
                executor.kill_process()
            self._set_button_state(button, False, "Start")
            widget['is_running'] = False
        else:
            command = COMMANDS[category][command_key]
            self._run_command(key, command, button)
            self._set_button_state(button, True, "Kill")
            widget['is_running'] = True

    def _toggle_template_button(self, button, idx):
        """Toggle template button execution"""
        button_data = self.template_buttons[idx]
        
        if button_data['is_running']:
            if button_data['executor']:
                button_data['executor'].kill_process()
            self._set_button_state(button, False, "Camera Bridge" if idx == 0 else "")
            button_data['is_running'] = False
        else:
            if idx == 0:  # Camera Bridge
                command = "ros2 run ros_gz_bridge parameter_bridge '/front_camera@sensor_msgs/msg/Image@gz.msgs.Image'"
            else:
                return  # Template buttons do nothing yet
            
            output_queue = Queue()
            executor = CommandExecutor(output_queue)
            button_data['executor'] = executor
            button_data['is_running'] = True
            
            self._set_button_state(button, True, "Kill")
            
            thread = threading.Thread(target=executor.run_command, args=(command,))
            thread.daemon = True
            thread.start()

    def _toggle_gazebo_world(self):
        """Toggle Gazebo world execution"""
        # Initialize executor if not exist
        if 'gazebo' not in self.executors:
            self.executors['gazebo'] = None
            self.output_queues['gazebo'] = Queue()
        
        if self.executors['gazebo'] and self.executors['gazebo'].is_running:
            # Kill process
            self.executors['gazebo'].kill_process()
            self._set_button_state(self.gazebo_btn, False, "Start")
        else:
            # Get selected world
            world_name = self.gazebo_combo.currentText()
            if world_name == "Select World...":
                return
            
            if world_name in COMMANDS["Gazebo"]:
                command = COMMANDS["Gazebo"][world_name]
                output_queue = self.output_queues['gazebo']
                executor = CommandExecutor(output_queue)
                self.executors['gazebo'] = executor
                executor.is_running = True
                
                self._set_button_state(self.gazebo_btn, True, "Kill")
                
                thread = threading.Thread(target=executor.run_command, args=(command,))
                thread.daemon = True
                thread.start()

    def _on_utility_button_clicked(self, button_idx):
        """Handle utility button clicks to open applications"""
        commands_map = {
            0: "rqt",
            1: "rviz2",
            2: "qgroundcontrol",
            3: "code ~/ros2_ws",
            4: "terminator",
            5: "BLHeliSuite32"
        }
        
        if button_idx in commands_map:
            command = commands_map[button_idx]
            thread = threading.Thread(target=lambda: subprocess.Popen(command, shell=True))
            thread.daemon = True
            thread.start()

    def _set_button_state(self, button, is_running, text):
        """Set button styling based on running state"""
        button.setText(text)
        if is_running:
            # Kill button - red with bright hover, size stays same
            button.setStyleSheet("""
                QPushButton {
                    background-color: #FF4444;
                    color: white;
                    font-weight: bold;
                    border-radius: 3px;
                    padding: 3px;
                }
                QPushButton:hover {
                    background-color: #FF6666;
                }
            """)
        else:
            # Start button - normal
            button.setStyleSheet("")

    def _run_command(self, key, command, button):
        """Run a command in background"""
        output_queue = self.output_queues[key]
        executor = CommandExecutor(output_queue)
        self.executors[key] = executor
        executor.is_running = True

        thread = threading.Thread(target=executor.run_command, args=(command,))
        thread.daemon = True
        thread.start()

        # Process queue
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(lambda: self._process_console_queue(key, button))
        self.update_timer.start(100)

    def _process_console_queue(self, key, button):
        """Process console output queue"""
        if key not in self.output_queues:
            return

        output_queue = self.output_queues[key]
        console = self.command_widgets[key]['console']

        try:
            while True:
                text = output_queue.get_nowait()
                color = '#CCCCCC'

                if text.startswith('✓') or 'success' in text.lower():
                    color = ANSI_COLORS['32']
                elif text.startswith('✗') or 'error' in text.lower():
                    color = ANSI_COLORS['91']
                elif text.startswith('[') or '---' in text:
                    color = ANSI_COLORS['36']

                console.append_text(text, color)
        except:
            pass

        # Check if process finished
        executor = self.executors[key]
        if executor and executor.process and executor.process.poll() is not None:
            self._set_button_state(button, False, "Start")
            self.command_widgets[key]['is_running'] = False
            executor.is_running = False

    def _run_command_in_console(self, name, command, console_id):
        """Run command in specific console"""
        if console_id not in self.executors:
            self.executors[console_id] = None
            self.output_queues[console_id] = Queue()
            self.command_widgets[console_id] = {
                'console': self.consoles.get(console_id),
                'button': None
            }

        executor = self.executors[console_id]
        if executor and executor.is_running:
            executor.kill_process()
        else:
            output_queue = self.output_queues[console_id]
            executor = CommandExecutor(output_queue)
            self.executors[console_id] = executor
            executor.is_running = True

            thread = threading.Thread(target=executor.run_command, args=(command,))
            thread.daemon = True
            thread.start()

    def _run_ros2_package(self, package_name, command, widget):
        """Run ROS2 package"""
        widget.run_command(command)

    def _set_power_mode(self, mode):
        """Set power mode on Jetson Orin Nano"""
        if mode in POWER_MODES:
            command = POWER_MODES[mode]
            # Run with sudo in background
            thread = threading.Thread(target=lambda: subprocess.call(f"echo 'Setting power mode {mode}' && {command}", shell=True))
            thread.daemon = True
            thread.start()

    def _kill_all_processes(self):
        """Kill all running processes"""
        for key, executor in self.executors.items():
            if executor and executor.process:
                executor.kill_process()

    def setup_monitoring(self):
        """Setup monitoring timer"""
        self.monitor_timer = QTimer()
        self.monitor_timer.timeout.connect(self._monitor_processes)
        self.monitor_timer.start(500)  # Check every 500ms

    def _monitor_processes(self):
        """Monitor all running processes and update button states"""
        self.monitoring_panel.update_stats()
        
        # Monitor Gazebo process
        if 'gazebo' in self.executors and self.executors['gazebo']:
            if self.executors['gazebo'].process and self.executors['gazebo'].process.poll() is not None:
                self._set_button_state(self.gazebo_btn, False, "Start")
                self.executors['gazebo'].is_running = False
        
        # Monitor template buttons
        for idx, button_data in self.template_buttons.items():
            if button_data['is_running'] and button_data['executor']:
                if button_data['executor'].process and button_data['executor'].process.poll() is not None:
                    button_data['is_running'] = False
                    button = button_data['button']
                    original_text = "Camera Bridge" if idx == 0 else ""
                    self._set_button_state(button, False, original_text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CompactCommandGUI()
    window.show()
    sys.exit(app.exec_())
