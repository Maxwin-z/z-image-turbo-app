#!/bin/bash
set -e

echo "Syncing dependencies..."
uv sync

echo "Starting server..."
uv run python server.py
