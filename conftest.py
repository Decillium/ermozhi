import sys
import os

# Ensure project root is on sys.path for test discovery and module imports
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
