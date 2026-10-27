"""The Chinese harness: `harness.py --lang zh`, kept so the commands in
STATUS.md still run. See `harness.py` for what it measures and how.

    .venv/Scripts/python.exe -X utf8 tools/zh_harness.py OUT all --source DIR
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import main  # noqa: E402

if __name__ == "__main__":
    main(default_lang="zh")
