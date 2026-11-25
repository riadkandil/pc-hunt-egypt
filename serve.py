"""Start the PC Hunt website: python egypt_pc_stores/serve.py [port]   (default http://127.0.0.1:8790)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pchunt import server  # noqa: E402

server.main()
