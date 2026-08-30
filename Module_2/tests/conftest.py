import sys
from pathlib import Path

module_dir = Path(__file__).resolve().parent.parent  # Module_2
repo_root = module_dir.parent  # repo root

sys.path.insert(0, str(module_dir))
sys.path.insert(0, str(repo_root))
