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
from threading import Lock
from queue import Queue

# Suppress PyQt5 deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTabWidget, QTextEdit, QLabel, QComboBox, QStyleFactory,
    QSplitter
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QIcon

# Mapping commands from bashrc
COMMANDS = {
    "Gazebo": {
        "Qualification World": "gz sim -v 3 -r sauvc_qualification.world",
        "Final World": "gz sim -v 3 -r sauvc_final.world",
    },
    "Vision": {
        "Docker Container": "docker start -ai be537dc7c441",
    },
    "RQT": {
        "RQT Image View": "ros2 run rqt_image_view rqt_image_view",
    },
    "ArduPilot": {
        "--- SITL ---": "",  # Visual separator
        "Start SITL": "cd ~/ardupilot && Tools/autotest/sim_vehicle.py -L RATBeach -v ArduSub -f vectored --model=JSON --out=udp:0.0.0.0:14550 --console",
        "--- MAVRoS ---": "",  # Visual separator
        "Launch MAVRoS": "ros2 launch mavros apm.launch fcu_url:=udp://:14550@localhost:14555",
    },
    "ROS2": {
        "Front Camera Bridge": "ros2 run ros_gz_bridge parameter_bridge '/front_camera@sensor_msgs/msg/Image@gz.msgs.Image'",
        "Build Package": "cd ~/ros2_ws && colcon build --packages-select sauvc26_code",
        "Arm": "ros2 run sauvc26_code arm",
        "Qualification": "ros2 run sauvc26_code qualification",
        "Final": "ros2 run sauvc26_code final",
        "Move": "ros2 run sauvc26_code move",
        "Test": "ros2 run sauvc26_code test",
        "Teleop Keyboard": "ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/mavros/setpoint_velocity/cmd_vel_unstamped",
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
                preexec_fn=os.setsid
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


class ROS2CommandGUI(QMainWindow):
    """Main GUI Application"""

    def __init__(self):
        super().__init__()
        self.output_widgets = {}  # Store output text widgets for each category
        self.output_queues = {}   # Store output queues for each category
        self.worker_threads = {}  # Store worker threads for each category
        self.executors = {}  # Store executors for each category
        self.command_output_map = {}  # Map command name to its output widget key
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
                        output_widget.append(text)
                except:
                    # Queue is empty
                    pass

    def create_tabs(self):
        """Create tabs for each category with separate output terminals"""
        for category, commands in COMMANDS.items():
            # Check if this category should display output
            has_output = category != "RQT"
            
            # Special handling for ArduPilot (2 output terminals)
            if category == "ArduPilot":
                self.create_ardupilot_tab(commands)
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
                    
                    btn = QPushButton(cmd_name)
                    btn.setFont(QFont("Arial", 10))
                    btn.setMinimumHeight(40)
                    
                    if is_separator:
                        # Make separator unclickable
                        btn.setEnabled(False)
                    else:
                        btn.clicked.connect(lambda checked, cat=category, cmd=cmd_string, name=cmd_name: self.run_command(cat, cmd, name))
                    
                    left_layout.addWidget(btn)

                # Spacer
                left_layout.addStretch()
                
                # Kill button for this category
                if has_output:
                    kill_btn = QPushButton("Kill Terminal")
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

        # Left side - Command buttons
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Title
        title = QLabel("ArduPilot")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        left_layout.addWidget(title)

        # Buttons for each command
        for cmd_name, cmd_string in commands.items():
            is_separator = cmd_string == ""
            
            btn = QPushButton(cmd_name)
            btn.setFont(QFont("Arial", 10))
            btn.setMinimumHeight(40)
            
            if is_separator:
                btn.setEnabled(False)
            else:
                btn.clicked.connect(lambda checked, cat="ArduPilot", cmd=cmd_string, name=cmd_name: self.run_command(cat, cmd, name))
            
            left_layout.addWidget(btn)

        # Spacer
        left_layout.addStretch()
        
        # Kill button
        kill_btn = QPushButton("Kill Terminal")
        kill_btn.setStyleSheet("background-color: #ff6b6b; color: white; font-weight: bold;")
        kill_btn.clicked.connect(lambda checked, cat="ArduPilot": self.kill_terminal(cat))
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
        sitl_layout.addWidget(sitl_text)

        sitl_clear_btn = QPushButton("Clear")
        sitl_clear_btn.clicked.connect(sitl_text.clear)
        sitl_layout.addWidget(sitl_clear_btn)

        # Store SITL output widget and queue
        self.output_widgets["ArduPilot_SITL"] = sitl_text
        self.output_queues["ArduPilot_SITL"] = Queue()
        
        # Assign SITL commands to SITL output
        self.command_output_map["Start SITL"] = "ArduPilot_SITL"

        # MAVRoS Terminal
        mavros_layout = QVBoxLayout()
        mavros_label = QLabel("MAVRoS Output")
        mavros_label.setFont(QFont("Arial", 10, QFont.Bold))
        mavros_layout.addWidget(mavros_label)

        mavros_text = QTextEdit()
        mavros_text.setReadOnly(True)
        mavros_text.setFont(QFont("Courier", 9))
        mavros_layout.addWidget(mavros_text)

        mavros_clear_btn = QPushButton("Clear")
        mavros_clear_btn.clicked.connect(mavros_text.clear)
        mavros_layout.addWidget(mavros_clear_btn)

        # Store MAVRoS output widget and queue
        self.output_widgets["ArduPilot_MAVRoS"] = mavros_text
        self.output_queues["ArduPilot_MAVRoS"] = Queue()

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

            # Create unique key for tracking this execution
            exec_key = f"{category}_{name}" if category == "ArduPilot" else category

            # Stop previous worker thread if still running
            if exec_key in self.worker_threads and self.worker_threads[exec_key] and self.worker_threads[exec_key].is_alive():
                output_queue.put("⚠ Previous command is still running...")
                return

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
            executor = CommandExecutor(output_queue=None)
            worker_thread = threading.Thread(target=executor.run_command, args=(command,))
            worker_thread.daemon = True
            self.executors[category] = executor
            self.worker_threads[category] = worker_thread
            worker_thread.start()

    def kill_terminal(self, category):
        """Kill the running command in a category"""
        killed_any = False
        
        if category == "ArduPilot":
            # Kill both SITL and MAVRoS if running (in background thread)
            for exec_key in ["ArduPilot_Start SITL", "ArduPilot_Launch MAVRoS"]:
                if exec_key in self.executors and self.executors[exec_key]:
                    executor = self.executors[exec_key]
                    if executor.process and executor.process.poll() is None:
                        # Run kill in background thread to avoid blocking GUI
                        threading.Thread(target=executor.kill_process, daemon=True).start()
                        killed_any = True
            
            # Notify both terminals via queue
            if "ArduPilot_SITL" in self.output_queues:
                self.output_queues["ArduPilot_SITL"].put("✗ Terminal killed by user")
            if "ArduPilot_MAVRoS" in self.output_queues:
                self.output_queues["ArduPilot_MAVRoS"].put("✗ Terminal killed by user")
        else:
            # For non-ArduPilot categories, find any running executor for this category
            for exec_key in list(self.executors.keys()):
                if exec_key.startswith(category) or exec_key == category:
                    executor = self.executors[exec_key]
                    if executor and executor.process and executor.process.poll() is None:
                        # Run kill in background thread to avoid blocking GUI
                        threading.Thread(target=executor.kill_process, daemon=True).start()
                        killed_any = True
            
            # Notify output terminal
            if category in self.output_queues:
                if killed_any:
                    self.output_queues[category].put("✗ Terminal killed by user")
                else:
                    self.output_queues[category].put("ℹ No running process to kill")

def main():
    app = QApplication(sys.argv)
    gui = ROS2CommandGUI()
    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
