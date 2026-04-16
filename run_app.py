#!/usr/bin/env python3
"""Debug script to run the Flask app with explicit logging"""
import sys
import os

# Ensure we're using the right path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run
from dashboard.app import app

if __name__ == "__main__":
    print("=" * 70)
    print("DEBUG: Starting Flask app from run_app.py")
    print(f"App object: {app}")
    print(f"App routes before start:")
    for rule in app.url_map.iter_rules():
        if 'iterate' in rule.rule:
            print(f"  {rule}")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5050, debug=False)
