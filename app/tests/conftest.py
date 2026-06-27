import sys
from pathlib import Path

# Allow test files to import from src/ using the same absolute-import style
# that main.py and the container use (e.g. "from classifier import Classifier").
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
