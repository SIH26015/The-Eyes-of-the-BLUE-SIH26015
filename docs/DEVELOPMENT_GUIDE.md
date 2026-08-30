# Development Guide

## Setup

```bash
# Clone repository
git clone <repo-url>
cd The-Eyes-of-the-BLUE-SIH26015

# Python environment (Module 2)
cd Module_2
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt

# Node environment (Module 1)
cd ../Module_1
npm install
```

## Running

```bash
# Terminal 1: Module 2 backend
cd Module_2
uvicorn backend.app.main:app --reload --port 8000

# Terminal 2: Module 1 frontend
cd Module_1
node server.js

# Terminal 3: Module 0 (optional)
cd Module_0
pip install -e ".[dev]"
python -m module0.main
```

## Testing

```bash
# Module 2 tests
cd Module_2
pytest

# Module 3 tests (when added)
cd Module_3
pytest
```

## Code Style

- Python: Follow PEP 8
- JavaScript: Follow Airbnb style guide
- Commit messages: Conventional commits (feat:, fix:, docs:, etc.)

## Module Dependencies

- Module 1 may call Module 2 via HTTP
- Module 2 may import Module 3
- Module 3 must NOT import Module 2
- Module 0 has no runtime dependency on other modules
