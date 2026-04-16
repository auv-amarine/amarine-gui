#!/usr/bin/env python3
"""
ROS2 Command GUI - Interface to run commands from bashrc
Grouped by categories: Gazebo, Vision, ArduPilot, and ROS2
"""

import sys
import os
import subprocess
import threading
import warnings
import time
import signal
import re
from threading import Lock
from queue import Queue

# Suppress PyQt5 deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTabWidget, QTextEdit, QLabel, QComboBox, QStyleFactory,
    QSplitter
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
    # Remove all ANSI escape sequences
    return re.sub(r'\033\[[0-9;]*m|\x1b\[[0-9;]*m', '', text)

# Mapping commands from bashrc
COMMANDS = {
    "Gazebo": {
        "Qualification World": "gz sim -v 3 -r sauvc_qualification.world",
        "Final World": "gz sim -v 3 -r sauvc_final.world",
    },
    "Vision": {
        "Docker Container": "docker start -ai be537dc7c441",
        "Front Camera Bridge": "ros2 run ros_gz_bridge parameter_bridge '/front_camera@sensor_msgs/msg/Image@gz.msgs.Image'",
    },
    "RQT": {
        "RQT Image View": "ros2 run rqt_image_view rqt_image_view",
    },
    "ArduPilot": {
        "Start SITL": "cd ~/ardupilot && Tools/autotest/sim_vehicle.py -L RATBeach -v ArduSub -f vectored --model=JSON --out=udp:0.0.0.0:14550 --console",
        "--- MAVRoS ---": "",  # Visual separator
        "Launch MAVRoS": "ros2 launch mavros apm.launch fcu_url:=udp://:14550@localhost:14555",
    },
    "ROS2": {
        "Build Package": "cd ~/ros2_ws && colcon build --packages-select sauvc26_code",
        "--- Mission Control ---": "",  # Visual separator
        "Arm": "ros2 run sauvc26_code arm",
        "Qualification": "ros2 run sauvc26_code qualification",
        "Final": "ros2 run sauvc26_code final",
        "Test": "ros2 run sauvc26_code test",
    }
}


class CommandExecutor:
    """Worker to run commands without freezing GUI"""

    def __init__(self, output_queue=None):
        self.process = None
        self.output_queue = output_queue  # Queue for posting output

    def append_to_queue(self, text):
        """Post text to output queue"""
        if self.output_queue:
            self.output_queue.put(text.rstrip('\n'))

    def run_command(self, command):
        """Run command and post output to queue"""
        try:
            text = f"▶ Running: {command}\n"
            self.append_to_queue(text)
            self.append_to_queue("─" * 80)

            # Set up environment for unbuffered output
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'

            # Run command using shell, with new process group for proper cleanup
            # preexec_fn=os.setsid creates a new session, so killpg only affects this command
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

            # Read output in real-time
            try:
                if self.process.stdout:
                    while True:
                        try:
                            line = self.process.stdout.readline()
                            if not line:
                                break
                            if line.strip():  # Only append non-empty lines
                                self.append_to_queue(line)
                        except ValueError:
                            # This happens when stdout is closed (process killed)
                            break
            except Exception as e:
                pass

            self.process.wait()
            self.append_to_queue("─" * 80)
            self.append_to_queue(f"✓ Command finished (exit code: {self.process.returncode})\n")

        except Exception as e:
            self.append_to_queue(f"✗ Error: {str(e)}\n")

    def kill_process(self):
        """Kill the running process and all its children like Ctrl+C in terminal"""
        if not self.process:
            print("[KILL] No process"); sys.stdout.flush()
            return
        
        print(f"[KILL] START - PID={self.process.pid}"); sys.stdout.flush()
        
        if self.output_queue:
            self.output_queue.put("\n✗ KILLING PROCESS (all children processes)...")
        
        try:
            pid = self.process.pid
            print(f"[KILL] Got PID={pid}"); sys.stdout.flush()
            
            # Get process group ID - with preexec_fn=os.setsid, this process has its own group
            # Killing the group will kill this process AND all child processes
            try:
                pgid = os.getpgid(pid)
                print(f"[KILL] Got PGID={pgid}"); sys.stdout.flush()
            except OSError as e:
                print(f"[KILL] Could not get PGID: {e}, using PID as fallback"); sys.stdout.flush()
                pgid = pid
            
            # Step 1: Send SIGINT (like Ctrl+C) to the entire process group
            print(f"[KILL] Sending SIGINT to process group {pgid}"); sys.stdout.flush()
            try:
                os.killpg(pgid, signal.SIGINT)
                if self.output_queue:
                    self.output_queue.put(f"[1] Sent SIGINT to process group {pgid}")
                time.sleep(0.5)
            except Exception as e:
                print(f"[KILL] SIGINT failed: {e}"); sys.stdout.flush()
            
            if self.process.poll() is not None:
                print(f"[KILL] Process dead after SIGINT"); sys.stdout.flush()
                if self.output_queue:
                    self.output_queue.put(f"✓ Process exited (code: {self.process.returncode})")
                return
            
            # Step 2: Send SIGTERM (graceful termination)
            print(f"[KILL] Sending SIGTERM to process group {pgid}"); sys.stdout.flush()
            try:
                os.killpg(pgid, signal.SIGTERM)
                if self.output_queue:
                    self.output_queue.put(f"[2] Sent SIGTERM to process group {pgid}")
                time.sleep(0.5)
            except Exception as e:
                print(f"[KILL] SIGTERM failed: {e}"); sys.stdout.flush()
            
            if self.process.poll() is not None:
                print(f"[KILL] Process dead after SIGTERM"); sys.stdout.flush()
                if self.output_queue:
                    self.output_queue.put(f"✓ Process terminated (code: {self.process.returncode})")
                return
            
            # Step 3: Send SIGKILL (forcefully kill entire process group)
            print(f"[KILL] Sending SIGKILL to process group {pgid}"); sys.stdout.flush()
            try:
                os.killpg(pgid, signal.SIGKILL)
                if self.output_queue:
                    self.output_queue.put(f"[3] Sent SIGKILL to process group {pgid}")
                time.sleep(0.2)
            except Exception as e:
                print(f"[KILL] SIGKILL failed: {e}"); sys.stdout.flush()
            
            final_code = self.process.poll()
            print(f"[KILL] Final poll: {final_code}"); sys.stdout.flush()
            
            if final_code is not None:
                if self.output_queue:
                    self.output_queue.put(f"✓ All processes killed (code: {final_code})")
            else:
                if self.output_queue:
                    self.output_queue.put("ERROR: Process still alive after SIGKILL!")
                    
        except Exception as e:
            print(f"[KILL] Exception: {e}"); sys.stdout.flush()
            if self.output_queue:
                self.output_queue.put(f"Kill error: {str(e)}")
        
        print(f"[KILL] DONE"); sys.stdout.flush()


class CommandButtonWidget(QWidget):
    """Composite widget: command button + dynamic kill button when running"""
    
    def __init__(self, cmd_name, on_run, on_kill, parent=None):
        super().__init__(parent)
        self.cmd_name = cmd_name
        self.on_run = on_run
        self.on_kill = on_kill
        self.is_running = False
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Command button - fills available space
        self.cmd_btn = QPushButton(cmd_name)
        self.cmd_btn.setFont(QFont("Arial", 10))
        self.cmd_btn.setMinimumHeight(40)
        self.cmd_btn.setMaximumHeight(80)
        self.cmd_btn.clicked.connect(self._on_cmd_clicked)
        layout.addWidget(self.cmd_btn, 1)
        
        # Kill button - appears only when running
        self.kill_btn = QPushButton("✕")
        self.kill_btn.setFont(QFont("Arial", 12, QFont.Bold))
        self.kill_btn.setMaximumWidth(45)
        self.kill_btn.setMinimumHeight(40)
        self.kill_btn.setStyleSheet("background-color: #ff6b6b; color: white;")
        self.kill_btn.clicked.connect(self._on_kill_clicked)
        self.kill_btn.hide()  # Hidden by default
        layout.addWidget(self.kill_btn)
    
    def _on_cmd_clicked(self):
        """Handle command button click"""
        self.on_run(self.cmd_name)
        self.set_running(True)
    
    def _on_kill_clicked(self):
        """Handle kill button click"""
        self.on_kill(self.cmd_name)
        self.set_running(False)
    
    def set_running(self, is_running):
        """Update state and show/hide kill button"""
        self.is_running = is_running
        if is_running:
            self.cmd_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            self.kill_btn.show()
        else:
            self.cmd_btn.setStyleSheet("")
            self.kill_btn.hide()
    
    def set_enabled(self, enabled):
        """Enable/disable command button"""
        self.cmd_btn.setEnabled(enabled)


class ROS2CommandGUI(QMainWindow):
    """Main GUI Application"""

    def __init__(self):
        super().__init__()
        self.output_widgets = {}  # Store output text widgets for each category
        self.output_queues = {}   # Store output queues for each category
        self.worker_threads = {}  # Store worker threads for each category
        self.executors = {}  # Store executors for each category
        self.command_output_map = {}  # Map command name to its output widget key
        self.command_widgets = {}  # Store CommandButtonWidget instances
        self.section_groups = {}  # Track button groups by section for disabling
        self.init_ui()
        
        # Start a timer to process output queues
        self.queue_timer = QTimer()
        self.queue_timer.timeout.connect(self.process_output_queues)
        self.queue_timer.start(100)  # Process every 100ms

    def init_ui(self):
        """Initialize UI"""
        self.setWindowTitle("ROS2 Command GUI")
        self.setGeometry(100, 100, 1200, 800)

        # Set style
        QApplication.setStyle(QStyleFactory.create('Fusion'))

        # Main widget
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        # Main layout
        layout = QVBoxLayout(main_widget)

        # Tab widget - each tab has its own commands and terminal
        self.tab_widget = QTabWidget()
        self.create_tabs()
        layout.addWidget(self.tab_widget, 1)

    def process_output_queues(self):
        """Process output from all queues and update widgets"""
        for output_key, output_queue in self.output_queues.items():
            if output_queue and output_key in self.output_widgets:
                output_widget = self.output_widgets[output_key]
                try:
                    while True:
                        text = output_queue.get_nowait()
                        # Clean ANSI codes
                        clean_text = strip_ansi(text)
                        
                        # Check for common patterns and apply colors
                        if clean_text.startswith('✓') or 'success' in clean_text.lower():
                            output_widget.setTextColor(QColor(ANSI_COLORS['32']))  # Green
                        elif clean_text.startswith('✗') or 'error' in clean_text.lower() or 'failed' in clean_text.lower():
                            output_widget.setTextColor(QColor(ANSI_COLORS['91']))  # Bright red
                        elif clean_text.startswith('[') or '---' in clean_text or '===' in clean_text:
                            output_widget.setTextColor(QColor(ANSI_COLORS['36']))  # Cyan
                        elif 'warning' in clean_text.lower() or clean_text.startswith('⚠'):
                            output_widget.setTextColor(QColor(ANSI_COLORS['93']))  # Yellow
                        else:
                            output_widget.setTextColor(QColor(ANSI_COLORS['37']))  # White/default
                        
                        output_widget.append(clean_text)
                except:
                    # Queue is empty
                    pass
        
        # Monitor process completion and reset button states
        self._monitor_process_completion()

    def _monitor_process_completion(self):
        """Monitor running processes and reset button states when they complete"""
        for category in list(self.command_widgets.keys()):
            for cmd_name, cmd_widget in list(self.command_widgets[category].items()):
                # Find the matching executor (consistent format for all categories)
                exec_key = f"{category}_{cmd_name}"
                
                if exec_key in self.executors:
                    executor = self.executors[exec_key]
                    # If process has finished but button still shows as running, reset it
                    if executor and executor.process and executor.process.poll() is not None:
                        if cmd_widget.is_running:
                            cmd_widget.set_running(False)
                            
                            # Update ROS2 section buttons if process in ROS2
                            if category == "ROS2":
                                self._update_ros2_section_buttons()

    def create_tabs(self):
        """Create tabs for each category with separate output terminals"""
        # Pre-set command_output_map for commands without console
        self.command_output_map["Front Camera Bridge"] = None  # No output for Front Camera
        
        for category, commands in COMMANDS.items():
            # Check if this category should display output
            has_output = category not in ["RQT"]
            
            # Special handling for ArduPilot (2 output terminals)
            if category == "ArduPilot":
                self.create_ardupilot_tab(commands)
            # Special handling for ROS2 (2 sections with single output terminal)
            elif category == "ROS2":
                self.create_ros2_tab(commands)
            else:
                # Create main container for this category
                tab_container = QWidget()
                if has_output:
                    tab_layout = QHBoxLayout(tab_container)
                else:
                    tab_layout = QVBoxLayout(tab_container)

                # Left side - Command buttons
                left_widget = QWidget()
                left_layout = QVBoxLayout(left_widget)

                # Title
                title = QLabel(category)
                title.setFont(QFont("Arial", 12, QFont.Bold))
                left_layout.addWidget(title)

                # Buttons for each command
                for cmd_name, cmd_string in commands.items():
                    # Check if this is a separator
                    is_separator = cmd_string == ""
                    
                    if is_separator:
                        # Add spacer instead of separator button (height matches button)
                        left_layout.addSpacing(80)
                    else:
                        # Create composite widget (button + dynamic kill)
                        cmd_widget = CommandButtonWidget(
                            cmd_name,
                            on_run=lambda name, cat=category, cmd=cmd_string: self.on_command_start(cat, cmd, name),
                            on_kill=lambda name, cat=category: self.on_command_kill(cat, name)
                        )
                        left_layout.addWidget(cmd_widget)
                        
                        # Store widget for later access
                        if category not in self.command_widgets:
                            self.command_widgets[category] = {}
                        self.command_widgets[category][cmd_name] = cmd_widget

                # Spacer
                left_layout.addStretch()
                
                # Kill Terminal button for entire category (legacy, kept for backup)
                if has_output:
                    kill_btn = QPushButton("Kill All")
                    kill_btn.setStyleSheet("background-color: #ff6b6b; color: white; font-weight: bold;")
                    kill_btn.clicked.connect(lambda checked, cat=category: self.kill_terminal(cat))
                    left_layout.addWidget(kill_btn)

                if has_output:
                    # Right side - Output terminal for this category
                    output_layout = QVBoxLayout()
                    output_label = QLabel(f"{category} Output Console")
                    output_label.setFont(QFont("Arial", 10, QFont.Bold))
                    output_layout.addWidget(output_label)

                    output_text = QTextEdit()
                    output_text.setReadOnly(True)
                    output_text.setFont(QFont("Courier", 9))
                    # Dark background like terminal
                    output_text.setStyleSheet("""
                        QTextEdit {
                            background-color: #1e1e1e;
                            color: #e0e0e0;
                            border: 1px solid #333;
                        }
                    """)
                    output_layout.addWidget(output_text)

                    # Store output widget and queue for this category
                    self.output_widgets[category] = output_text
                    self.output_queues[category] = Queue()

                    # Button layout for clear and kill
                    button_layout = QHBoxLayout()
                    clear_btn = QPushButton("Clear Output")
                    clear_btn.clicked.connect(output_text.clear)
                    button_layout.addWidget(clear_btn)
                    
                    output_layout.addLayout(button_layout)

                    right_widget = QWidget()
                    right_widget.setLayout(output_layout)

                    # Add left and right to tab
                    tab_layout.addWidget(left_widget, 1)
                    tab_layout.addWidget(right_widget, 1)
                else:
                    # For categories without output (like RQT)
                    tab_layout.addWidget(left_widget, 1)

                # Add tab
                self.tab_widget.addTab(tab_container, category)

    def create_ardupilot_tab(self, commands):
        """Create ArduPilot tab with 2 separate output terminals (SITL and MAVRoS)"""
        # Create main container
        tab_container = QWidget()
        main_layout = QHBoxLayout(tab_container)

        # Left side - Command buttons in 2 weighted sections
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Title
        title = QLabel("ArduPilot")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        left_layout.addWidget(title)

        # SITL Section with weight
        sitl_section = QWidget()
        sitl_section_layout = QVBoxLayout(sitl_section)
        sitl_section_layout.setContentsMargins(0, 0, 0, 0)
        
        # Buttons for SITL
        for cmd_name, cmd_string in commands.items():
            if cmd_name == "--- SITL ---":
                sitl_section_layout.addSpacing(0)  # No visible spacer, use layout spacing
            elif cmd_name.startswith("--- "):
                break  # Stop at next section
            else:
                # Create composite widget (button + dynamic kill)
                cmd_widget = CommandButtonWidget(
                    cmd_name,
                    on_run=lambda name, cmd=cmd_string: self.on_command_start("ArduPilot", cmd, name),
                    on_kill=lambda name: self.on_command_kill("ArduPilot", name)
                )
                sitl_section_layout.addWidget(cmd_widget)
                
                # Store widget for later access
                if "ArduPilot" not in self.command_widgets:
                    self.command_widgets["ArduPilot"] = {}
                self.command_widgets["ArduPilot"][cmd_name] = cmd_widget
        
        sitl_section_layout.addStretch()
        left_layout.addWidget(sitl_section, 1)  # Give weight 1 to section

        # MAVRoS Section with weight
        mavros_section = QWidget()
        mavros_section_layout = QVBoxLayout(mavros_section)
        mavros_section_layout.setContentsMargins(0, 0, 0, 0)
        
        # Buttons for MAVRoS
        found_mavros = False
        for cmd_name, cmd_string in commands.items():
            if cmd_name == "--- MAVRoS ---":
                found_mavros = True
                continue
            elif found_mavros and cmd_string == "":
                mavros_section_layout.addSpacing(0)
            elif found_mavros:
                # Create composite widget (button + dynamic kill)
                cmd_widget = CommandButtonWidget(
                    cmd_name,
                    on_run=lambda name, cmd=cmd_string: self.on_command_start("ArduPilot", cmd, name),
                    on_kill=lambda name: self.on_command_kill("ArduPilot", name)
                )
                mavros_section_layout.addWidget(cmd_widget)
                
                # Store widget for later access
                if "ArduPilot" not in self.command_widgets:
                    self.command_widgets["ArduPilot"] = {}
                self.command_widgets["ArduPilot"][cmd_name] = cmd_widget
        
        mavros_section_layout.addStretch()
        left_layout.addWidget(mavros_section, 1)  # Give weight 1 to section
        
        # Kill All button
        kill_btn = QPushButton("Kill All")
        kill_btn.setStyleSheet("background-color: #ff6b6b; color: white; font-weight: bold;")
        kill_btn.clicked.connect(lambda checked: self.kill_terminal("ArduPilot"))
        left_layout.addWidget(kill_btn)

        # Right side - 2 output terminals stacked vertically
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)

        # SITL Terminal
        sitl_layout = QVBoxLayout()
        sitl_label = QLabel("SITL Output")
        sitl_label.setFont(QFont("Arial", 10, QFont.Bold))
        sitl_layout.addWidget(sitl_label)

        sitl_text = QTextEdit()
        sitl_text.setReadOnly(True)
        sitl_text.setFont(QFont("Courier", 9))
        sitl_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #333;
            }
        """)
        sitl_layout.addWidget(sitl_text)

        sitl_clear_btn = QPushButton("Clear")
        sitl_clear_btn.clicked.connect(sitl_text.clear)
        sitl_layout.addWidget(sitl_clear_btn)

        # Store SITL output widget and queue
        self.output_widgets["ArduPilot_SITL"] = sitl_text
        self.output_queues["ArduPilot_SITL"] = Queue()
        
        # Assign SITL commands to SITL output
        self.command_output_map["Start SITL"] = "ArduPilot_SITL"

        # MAVRoS Terminal (Output Terminal)
        mavros_layout = QVBoxLayout()
        mavros_label = QLabel("MAVRoS Output")
        mavros_label.setFont(QFont("Arial", 10, QFont.Bold))
        mavros_layout.addWidget(mavros_label)

        mavros_text = QTextEdit()
        mavros_text.setReadOnly(True)
        mavros_text.setFont(QFont("Courier", 9))
        mavros_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #333;
            }
        """)
        mavros_layout.addWidget(mavros_text)

        mavros_clear_btn = QPushButton("Clear")
        mavros_clear_btn.clicked.connect(mavros_text.clear)
        mavros_layout.addWidget(mavros_clear_btn)

        # Store MAVRoS output widget and queue
        self.output_widgets["ArduPilot_MAVRoS"] = mavros_text
        self.output_queues["ArduPilot_MAVRoS"] = Queue()
        
        # Assign MAVRoS commands to MAVRoS output
        self.command_output_map["Launch MAVRoS"] = "ArduPilot_MAVRoS"

        # Add both terminals to right layout vertically
        sitl_widget = QWidget()
        sitl_widget.setLayout(sitl_layout)
        mavros_widget = QWidget()
        mavros_widget.setLayout(mavros_layout)
        
        right_layout.addWidget(sitl_widget, 1)
        right_layout.addWidget(mavros_widget, 1)

        # Add left and right to main layout
        main_layout.addWidget(left_widget, 1)
        main_layout.addWidget(right_container, 2)

        # Add tab
        self.tab_widget.addTab(tab_container, "ArduPilot")

    def create_ros2_tab(self, commands):
        """Create ROS2 tab with 2 sections: Build Package and Mission Control
        Each section has its own output terminal with weighted layout for alignment"""
        # Create main container
        tab_container = QWidget()
        main_layout = QHBoxLayout(tab_container)

        # Left side - Command buttons in 2 weighted sections
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Title
        title = QLabel("ROS2")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        left_layout.addWidget(title)

        # Build Package Section with weight
        build_section = QWidget()
        build_section_layout = QVBoxLayout(build_section)
        build_section_layout.setContentsMargins(0, 0, 0, 0)
        
        # Section label
        build_label = QLabel("Build Package")
        build_label.setFont(QFont("Arial", 10, QFont.Bold))
        build_section_layout.addWidget(build_label)

        # Store buttons for Section 1
        if "ROS2_Section1" not in self.section_groups:
            self.section_groups["ROS2_Section1"] = []

        # Process Build Package commands
        found_build = False
        for cmd_name, cmd_string in commands.items():
            if "Build Package" in cmd_name and cmd_string != "":
                found_build = True
                cmd_widget = CommandButtonWidget(
                    cmd_name,
                    on_run=lambda name, cmd=cmd_string: self.on_ros2_command_start(name, cmd),
                    on_kill=lambda name: self.on_command_kill("ROS2", name)
                )
                build_section_layout.addWidget(cmd_widget)
                
                # Store widget for later access
                if "ROS2" not in self.command_widgets:
                    self.command_widgets["ROS2"] = {}
                self.command_widgets["ROS2"][cmd_name] = cmd_widget
                self.section_groups["ROS2_Section1"].append(cmd_widget)
        
        build_section_layout.addStretch()
        left_layout.addWidget(build_section, 1)  # Give weight 1 to section

        # Mission Control Section with weight
        mission_section = QWidget()
        mission_section_layout = QVBoxLayout(mission_section)
        mission_section_layout.setContentsMargins(0, 0, 0, 0)
        
        # Section label
        mission_label = QLabel("Mission Control")
        mission_label.setFont(QFont("Arial", 10, QFont.Bold))
        mission_section_layout.addWidget(mission_label)

        # Store buttons for Section 2
        if "ROS2_Section2" not in self.section_groups:
            self.section_groups["ROS2_Section2"] = []

        # Process Mission Control commands
        found_mission = False
        for cmd_name, cmd_string in commands.items():
            if cmd_name == "--- Mission Control ---":
                found_mission = True
                continue
            elif found_mission and cmd_string != "" and cmd_name in ["Arm", "Qualification", "Final", "Test"]:
                cmd_widget = CommandButtonWidget(
                    cmd_name,
                    on_run=lambda name, cmd=cmd_string: self.on_ros2_command_start(name, cmd),
                    on_kill=lambda name: self.on_command_kill("ROS2", name)
                )
                mission_section_layout.addWidget(cmd_widget)
                
                # Store widget for later access
                if "ROS2" not in self.command_widgets:
                    self.command_widgets["ROS2"] = {}
                self.command_widgets["ROS2"][cmd_name] = cmd_widget
                self.section_groups["ROS2_Section2"].append(cmd_widget)
        
        mission_section_layout.addStretch()
        left_layout.addWidget(mission_section, 1)  # Give weight 1 to section
        
        # Kill All button
        kill_btn = QPushButton("Kill All")
        kill_btn.setStyleSheet("background-color: #ff6b6b; color: white; font-weight: bold;")
        kill_btn.clicked.connect(lambda checked: self.kill_terminal("ROS2"))
        left_layout.addWidget(kill_btn)

        # Right side - 2 output terminals stacked vertically (Build Package and Mission Control)
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)

        # Build Package Terminal
        build_layout = QVBoxLayout()
        build_label = QLabel("Build Package Output")
        build_label.setFont(QFont("Arial", 10, QFont.Bold))
        build_layout.addWidget(build_label)

        build_text = QTextEdit()
        build_text.setReadOnly(True)
        build_text.setFont(QFont("Courier", 9))
        build_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #333;
            }
        """)
        build_layout.addWidget(build_text)

        build_clear_btn = QPushButton("Clear")
        build_clear_btn.clicked.connect(build_text.clear)
        build_layout.addWidget(build_clear_btn)

        # Store Build Package output widget and queue
        self.output_widgets["ROS2_Build"] = build_text
        self.output_queues["ROS2_Build"] = Queue()
        
        # Assign Build Package command to Build output
        self.command_output_map["Build Package"] = "ROS2_Build"

        # Mission Control Terminal
        mission_layout = QVBoxLayout()
        mission_label = QLabel("Mission Control Output")
        mission_label.setFont(QFont("Arial", 10, QFont.Bold))
        mission_layout.addWidget(mission_label)

        mission_text = QTextEdit()
        mission_text.setReadOnly(True)
        mission_text.setFont(QFont("Courier", 9))
        mission_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #e0e0e0;
                border: 1px solid #333;
            }
        """)
        mission_layout.addWidget(mission_text)

        mission_clear_btn = QPushButton("Clear")
        mission_clear_btn.clicked.connect(mission_text.clear)
        mission_layout.addWidget(mission_clear_btn)

        # Store Mission Control output widget and queue
        self.output_widgets["ROS2_Mission"] = mission_text
        self.output_queues["ROS2_Mission"] = Queue()
        
        # Assign Mission Control commands to Mission output
        for cmd in ["Arm", "Qualification", "Final", "Test"]:
            self.command_output_map[cmd] = "ROS2_Mission"

        # Add both terminals to right layout vertically
        build_widget = QWidget()
        build_widget.setLayout(build_layout)
        mission_widget = QWidget()
        mission_widget.setLayout(mission_layout)
        
        right_layout.addWidget(build_widget, 1)
        right_layout.addWidget(mission_widget, 1)

        # Add left and right to main layout
        main_layout.addWidget(left_widget, 1)
        main_layout.addWidget(right_container, 2)

        # Add tab
        self.tab_widget.addTab(tab_container, "ROS2")

    def on_command_start(self, category, command, name):
        """Handle command start - auto-kill previous command if running"""
        # SKIP auto-kill for ArduPilot (has 2 separate terminals, allows both to run)
        if category != "ArduPilot":
            # For non-ArduPilot categories, find and kill any other running command
            for cmd_key, executor in list(self.executors.items()):
                # Check if this executor belongs to this category but is a different command
                if cmd_key.startswith(category + "_"):  # Same category
                    cmd_name_in_key = cmd_key.replace(category + "_", "")
                    if cmd_name_in_key != name:  # Different command
                        if executor and executor.process and executor.process.poll() is None:
                            # Kill the previous process
                            print(f"[AUTO-KILL] Killing {cmd_key} to start {category}_{name}")
                            executor.kill_process()
                            time.sleep(0.3)
                            
                            # Reset button state
                            if category in self.command_widgets and cmd_name_in_key in self.command_widgets[category]:
                                self.command_widgets[category][cmd_name_in_key].set_running(False)
        
        # Now run the new command
        self.run_command(category, command, name)
    
    def on_command_kill(self, category, name):
        """Handle command kill from dynamic button"""
        exec_key = f"{category}_{name}"
        
        if exec_key in self.executors:
            executor = self.executors[exec_key]
            if executor and executor.process and executor.process.poll() is None:
                # Kill the process
                threading.Thread(target=executor.kill_process, daemon=True).start()
                
                # Reset button state after a delay
                def reset_button():
                    time.sleep(0.5)
                    if category in self.command_widgets:
                        cmd_btn = self.command_widgets[category].get(name)
                        if cmd_btn:
                            cmd_btn.set_running(False)
                    
                    # Re-enable buttons in section if ROS2
                    if category == "ROS2":
                        self._update_ros2_section_buttons()
                
                threading.Thread(target=reset_button, daemon=True).start()

    def on_ros2_command_start(self, name, command):
        """Handle ROS2 command start with section-based button disabling
        Mission Control section buttons are disabled when one is running"""
        
        # Find which section this command belongs to
        section_key = None
        if name == "Build Package":
            section_key = "ROS2_Section1"
        elif name in ["Arm", "Qualification", "Final", "Test"]:
            section_key = "ROS2_Section2"
        
        # If this is a Mission Control command, kill any other running in same section
        if section_key == "ROS2_Section2":
            for cmd_key, executor in list(self.executors.items()):
                if cmd_key.startswith("ROS2_"):
                    cmd_name_in_key = cmd_key.replace("ROS2_", "")
                    # Only kill if it's in the same section and different command
                    if cmd_name_in_key in ["Arm", "Qualification", "Final", "Test"] and cmd_name_in_key != name:
                        if executor and executor.process and executor.process.poll() is None:
                            print(f"[AUTO-KILL-ROS2] Killing {cmd_key} to start ROS2_{name}")
                            executor.kill_process()
                            time.sleep(0.3)
                            
                            # Reset button state
                            if "ROS2" in self.command_widgets and cmd_name_in_key in self.command_widgets["ROS2"]:
                                self.command_widgets["ROS2"][cmd_name_in_key].set_running(False)
        
        # Run the new command
        self.run_command("ROS2", command, name)
        
        # Update section button states
        self._update_ros2_section_buttons()
    
    def _update_ros2_section_buttons(self):
        """Update ROS2 section button enabled/disabled states based on running processes"""
        # Check if any Mission Control command is running
        mission_running = False
        for cmd_key in self.executors.keys():
            if cmd_key.startswith("ROS2_"):
                cmd_name = cmd_key.replace("ROS2_", "")
                if cmd_name in ["Arm", "Qualification", "Final", "Test"]:
                    executor = self.executors[cmd_key]
                    if executor and executor.process and executor.process.poll() is None:
                        mission_running = True
                        break
        
        # Disable/enable Mission Control buttons based on running state
        if "ROS2_Section2" in self.section_groups:
            for cmd_widget in self.section_groups["ROS2_Section2"]:
                cmd_widget.set_enabled(not mission_running)
    
    def run_command(self, category, command, name):
        """Run command in separate thread for specific category"""
        
        # Determine output queue for this command
        if name in self.command_output_map:
            output_key = self.command_output_map[name]
            output_queue = self.output_queues.get(output_key)
        elif category in self.output_queues:
            output_key = category
            output_queue = self.output_queues.get(output_key)
        else:
            # For RQT and other no-output categories
            output_queue = None
            output_key = None
        
        if output_queue:
            # Has output terminal - post separator to queue
            output_queue.put(f"\n{'='*80}")
            output_queue.put(f"Command: {name}")
            output_queue.put(f"{'='*80}")

            # Create unique key for tracking this execution (consistent across all categories)
            exec_key = f"{category}_{name}"

            # Create executor and thread - PASS OUTPUT QUEUE!
            executor = CommandExecutor(output_queue=output_queue)
            worker_thread = threading.Thread(target=executor.run_command, args=(command,))
            worker_thread.daemon = True

            # Store references
            self.executors[exec_key] = executor
            self.worker_threads[exec_key] = worker_thread

            # Start thread
            worker_thread.start()
        else:
            # No output - just run in background (like RQT)
            exec_key = f"{category}_{name}"
            executor = CommandExecutor(output_queue=None)
            worker_thread = threading.Thread(target=executor.run_command, args=(command,))
            worker_thread.daemon = True
            self.executors[exec_key] = executor
            self.worker_threads[exec_key] = worker_thread
            worker_thread.start()

    def kill_terminal(self, category):
        """Kill the running command in a category"""
        killed_any = False
        
        # Find all running executors for this category (new consistent format)
        for exec_key in list(self.executors.keys()):
            if exec_key.startswith(category + "_"):  # Matches category_name format
                executor = self.executors[exec_key]
                if executor and executor.process and executor.process.poll() is None:
                    # Run kill in background thread to avoid blocking GUI
                    threading.Thread(target=executor.kill_process, daemon=True).start()
                    killed_any = True
        
        # Notify output terminal(s)
        if category == "ArduPilot":
            # Notify both ArduPilot terminals
            if "ArduPilot_SITL" in self.output_queues:
                self.output_queues["ArduPilot_SITL"].put("✗ Killed by Kill All button")
            if "ArduPilot_MAVRoS" in self.output_queues:
                self.output_queues["ArduPilot_MAVRoS"].put("✗ Killed by Kill All button")
        else:
            # Notify the category terminal
            if category in self.output_queues:
                if killed_any:
                    self.output_queues[category].put("✗ Killed by Kill All button")
                else:
                    self.output_queues[category].put("ℹ No running process to kill")

    def closeEvent(self, event):
        """Kill all running processes when app closes"""
        print("[APP] Closing application, killing all processes...")
        
        # Kill all running processes
        for exec_key, executor in list(self.executors.items()):
            if executor and executor.process and executor.process.poll() is None:
                print(f"[APP] Killing {exec_key}")
                try:
                    executor.kill_process()
                except Exception as e:
                    print(f"[APP] Error killing {exec_key}: {e}")
        
        # Give processes time to terminate
        time.sleep(0.5)
        
        # Accept the close event
        event.accept()
        print("[APP] Application closed")

def main():
    app = QApplication(sys.argv)
    gui = ROS2CommandGUI()
    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
