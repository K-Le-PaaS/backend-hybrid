import os
import sys

# Ensure `app` package is importable in tests
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
APP_PATH = os.path.join(PROJECT_ROOT, 'app')
if APP_PATH not in sys.path:
    sys.path.insert(0, APP_PATH)

