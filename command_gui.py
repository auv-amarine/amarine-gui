#!/usr/bin/env python3
"""
ROS2 Command GUI - Interface to run commands from bashrc
Grouped by categories: Gazebo, Vision, ArduPilot, and ROS2
"""

import sys
import subprocess
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTabWidget, QTextEdit, QLabel, QComboBox, QStyleFactory
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QIcon

# Mapping commands from bashrc
COMMANDS = {
    "Gazebo": {
        "Qualification World": "gz sim -v 3 -r sauvc_qualification.world",
        "Final World": "gz sim -v 3 -r sauvc_final.world",
    },
    "Vision": {
        "Front Camera Bridge": "ros2 run ros_gz_bridge parameter_bridge '/front_camera@sensor_msgs/msg/Image@gz.msgs.Image'",
        "Docker Container": "docker start -ai be537dc7c441",
        "RQT Image View": "ros2 run rqt_image_view rqt_image_view",
        "Echo YOLO Target": "ros2 topic echo /yolo_target_coord",
        "Stop Docker": "docker stop be537dc7c441",
    },
    "ArduPilot": {
        "Start SITL": "cd ~/ardupilot && Tools/autotest/sim_vehicle.py -L RATBeach -v ArduSub -f vectored --model=JSON --out=udp:0.0.0.0:14550 --console",
        "Launch MAVRoS": "ros2 launch mavros apm.launch fcu_url:=udp://:14550@localhost:14555",
    },
    "ROS2": {
        "Build Package": "cd ~/ros2_ws && colcon build --packages-select sauvc26_code",
        "Arm": "ros2 run sauvc26_code arm",
        "Qualification": "ros2 run sauvc26_code qualification",
        "Final": "ros2 run sauvc26_code final",
        "Move": "ros2 run sauvc26_code move",
        "Test": "ros2 run sauvc26_code test",
        "Teleop Keyboard": "ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=/mavros/setpoint_velocity/cmd_vel_unstamped",
    }
}


class CommandExecutor(QObject):
    """Worker thread to run commands without freezing GUI"""
    output_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def run_command(self, command):
        """Run command and emit output"""
        try:
            self.output_signal.emit(f"▶ Running: {command}\n")
            self.output_signal.emit("─" * 80 + "\n")

            # Run command using shell
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Read output in real-time
            for line in process.stdout:
                self.output_signal.emit(line)

            process.wait()
            self.output_signal.emit("─" * 80 + "\n")
            self.output_signal.emit(f"✓ Command finished (exit code: {process.returncode})\n\n")

        except Exception as e:
            self.output_signal.emit(f"✗ Error: {str(e)}\n\n")

        finally:
            self.finished_signal.emit()


class ROS2CommandGUI(QMainWindow):
    """Main GUI Application"""

    def __init__(self):
        super().__init__()
        self.executor = None
        self.worker_thread = None
        self.init_ui()

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
        layout = QHBoxLayout(main_widget)

        # Left side - Tab for categories
        self.tab_widget = QTabWidget()
        self.create_tabs()
        layout.addWidget(self.tab_widget, 1)

        # Right side - Output panel
        output_layout = QVBoxLayout()
        output_label = QLabel("Output Console")
        output_label.setFont(QFont("Arial", 10, QFont.Bold))
        output_layout.addWidget(output_label)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setFont(QFont("Courier", 9))
        output_layout.addWidget(self.output_text)

        # Clear output button
        clear_btn = QPushButton("Clear Output")
        clear_btn.clicked.connect(self.output_text.clear)
        output_layout.addWidget(clear_btn)

        right_widget = QWidget()
        right_widget.setLayout(output_layout)
        layout.addWidget(right_widget, 1)

        # Set layout ratio
        layout.setStretch(0, 1)
        layout.setStretch(1, 1)

    def create_tabs(self):
        """Create tabs for each category"""
        for category, commands in COMMANDS.items():
            tab = QWidget()
            layout = QVBoxLayout(tab)

            # Title
            title = QLabel(category)
            title.setFont(QFont("Arial", 12, QFont.Bold))
            layout.addWidget(title)

            # Buttons for each command
            for cmd_name, cmd_string in commands.items():
                btn = QPushButton(cmd_name)
                btn.setFont(QFont("Arial", 10))
                btn.setMinimumHeight(40)
                btn.clicked.connect(lambda checked, cmd=cmd_string, name=cmd_name: self.run_command(cmd, name))
                layout.addWidget(btn)

            # Spacer
            layout.addStretch()

            # Add tab
            self.tab_widget.addTab(tab, category)

    def run_command(self, command, name):
        """Run command in separate thread"""
        self.output_text.append(f"\n{'='*80}\n")
        self.output_text.append(f"Command: {name}\n")
        self.output_text.append(f"{'='*80}\n")

        # Stop previous worker thread if still running
        if self.worker_thread and self.worker_thread.isAlive():
            self.output_text.append("⚠ Previous command is still running...\n")
            return

        # Create executor and thread
        self.executor = CommandExecutor()
        self.worker_thread = threading.Thread(target=self.executor.run_command, args=(command,))
        self.worker_thread.daemon = True

        # Connect signals
        self.executor.output_signal.connect(self.append_output)
        self.executor.finished_signal.connect(self.command_finished)

        # Start thread
        self.worker_thread.start()

    def append_output(self, text):
        """Display output to text widget"""
        self.output_text.moveCursor(self.output_text.textCursor().End)
        self.output_text.insertPlainText(text)
        self.output_text.ensureCursorVisible()

    def command_finished(self):
        """Called when command finishes"""
        pass


def main():
    app = QApplication(sys.argv)
    gui = ROS2CommandGUI()
    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
