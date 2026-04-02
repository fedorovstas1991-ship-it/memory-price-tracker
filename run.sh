#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
python -m src.main >> /tmp/memory-price-tracker.log 2>&1
