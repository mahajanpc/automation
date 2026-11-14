#!/usr/bin/env bash
set -e

echo "=== Setting up Instagram Reel Automation ==="

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed."
    exit 1
fi

# Check FFmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Warning: ffmpeg is not found. Please install ffmpeg using: sudo apt install ffmpeg"
fi

# Create virtualenv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv..."
    python3 -m venv .venv
fi

echo "Installing Python dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# Copy .env.example to .env if not present
if [ ! -f ".env" ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

echo ""
echo "=== Setup Complete! ==="
echo "1. Activate virtual environment: source .venv/bin/activate"
echo "2. Edit .env and enter your API keys."
echo "3. Run a test dry-run: python main.py --dry-run --mock"

