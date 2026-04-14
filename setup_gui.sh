#!/bin/bash
# Setup script for ROS2 Command GUI

echo "Installing dependencies..."

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "pip3 not found. Please install Python3 first."
    exit 1
fi

# Install requirements
pip3 install -r requirements.txt

echo "Dependencies installed!"
echo ""
echo "   To run the GUI, use:"
echo "   python3 command_gui.py"
echo ""
echo "   Or setup an alias by adding to bashrc:"
echo "   alias gui='cd ~/ros2_ws/src/sauvc26-code && python3 command_gui.py'"
