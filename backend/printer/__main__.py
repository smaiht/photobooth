"""python -m backend.printer PORT: ask the DS-RX1 for its status in a process of its own.

The caller kills this process when the printer does not answer (see _ask_dnp).
"""

import json
import sys

from . import _read_dnp_counters

try:
    print(json.dumps({"value": _read_dnp_counters(sys.argv[1])}))
except RuntimeError as exc:
    print(json.dumps({"error": str(exc)}))
