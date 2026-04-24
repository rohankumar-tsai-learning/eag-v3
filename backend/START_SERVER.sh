#!/bin/bash
# Gandalf the Organizer - Startup Script for macOS/Linux
# This script helps start the backend server quickly

echo ""
echo "========================================"
echo "  Gandalf the Organizer - Backend"
echo "========================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python is not installed"
    echo "Please install Python 3.9+ from python.org"
    exit 1
fi

echo "✅ Python found: $(python3 --version)"
echo ""

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "ERROR: main.py not found"
    echo "Please run this script from the backend directory"
    echo "Current directory: $(pwd)"
    exit 1
fi

echo "✅ Backend directory found"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment"
        exit 1
    fi
    echo "✅ Virtual environment created"
fi

# Activate virtual environment
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate virtual environment"
    exit 1
fi

echo "✅ Virtual environment activated"
echo ""

# Check if requirements are installed
pip list | grep -q fastapi
if [ $? -ne 0 ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to install dependencies"
        exit 1
    fi
    echo "✅ Dependencies installed"
else
    echo "✅ Dependencies already installed"
fi

echo ""

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "⚠️  WARNING: .env file not found"
    echo ""
    echo "Please create .env file with:"
    echo "  1. Copy: .env.template to .env"
    echo "  2. Edit .env and add your GEMINI_API_KEY"
    echo "  3. Get key from: https://aistudio.google.com/"
    echo ""
fi

echo ""
echo "========================================"
echo "   Starting Backend Server..."
echo "========================================"
echo ""
echo "📍 Server will run on: http://localhost:8000"
echo "📚 API Docs: http://localhost:8000/docs"
echo "🧪 Health: http://localhost:8000/health"
echo ""
echo "💡 Next steps:"
echo "  1. Open Chrome → chrome://extensions/"
echo "  2. Enable 'Developer mode'"
echo "  3. Click 'Load unpacked' → select 'extension' folder"
echo "  4. Click Gandalf icon in toolbar"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python3 main.py
