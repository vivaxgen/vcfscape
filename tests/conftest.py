"""
Test configuration for vcfscape.
Ensures src/ is automatically on sys.path for test discovery.
"""

import sys
import os

src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_path not in sys.path:
    sys.path.insert(0, src_path)
