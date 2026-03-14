#!/usr/bin/env bash
set -e

echo "========================================"
echo "  CineMatch Backend Setup"
echo "========================================"

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found. Install Python 3.9+ first."
  exit 1
fi

# Create venv
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

# Activate
source .venv/bin/activate

# Install deps
echo "Installing dependencies..."
pip install -r requirements.txt -q

# Import IMDB data (only if DB doesn't exist)
if [ ! -f "movies.db" ]; then
  echo ""
  echo "Downloading and importing IMDB datasets..."
  echo "This will take 10-30 minutes depending on your connection."
  echo "The database will be ~2-4 GB when complete."
  echo ""
  python import_imdb.py
else
  echo "Database already exists. Skipping import."
  echo "Run 'python import_imdb.py --force' to re-download."
fi

echo ""
echo "========================================"
echo "  Starting API server..."
echo "  Open http://localhost:8000/docs"
echo "========================================"
uvicorn main:app --reload --host 0.0.0.0 --port 8000
