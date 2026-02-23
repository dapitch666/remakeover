import sys
import os

# Ensure the repository root is on the import path so `from src import ...` works
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
