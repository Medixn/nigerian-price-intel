"""
Ensure the project root is on sys.path so dashboard pages can import src.*
when Streamlit runs them from the dashboard/ folder.

Streamlit adds the folder containing the entry script (dashboard/) to
sys.path, not the project root. This module (imported by every page) adds
the parent folder so `from src...` imports work.
"""
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))