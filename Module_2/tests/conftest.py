import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "backend"
module_dir = backend_dir.parent

sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(module_dir))
