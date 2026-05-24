"""
NOAH-PRIME · Web 入口 - web/main.py

重新导出 server.py 的 FastAPI app，使 `uvicorn web.main:app` 可用。
"""
import sys
from pathlib import Path

PRIME_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PRIME_ROOT))

from server import app
