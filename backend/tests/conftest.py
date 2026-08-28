import sys
from pathlib import Path

# Add the backend root to the Python path so imports work
backend_root = Path(__file__).parent.parent
sys.path.insert(0, str(backend_root))
