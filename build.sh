#!/bin/bash
# Build Ghost Typer.app using PyInstaller
set -e

cd "$(dirname "$0")"

echo "Building Ghost Typer..."
python3 -m PyInstaller GhostTyper.spec --noconfirm --clean

echo ""
echo "Build complete! App is at: dist/Ghost Typer.app"
echo "To install: cp -r 'dist/Ghost Typer.app' /Applications/"
