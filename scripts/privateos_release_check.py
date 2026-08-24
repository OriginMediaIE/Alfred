#!/usr/bin/env python3
"""Run the Alfred Private OS local release gate and record real-use evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.release_service import ReleaseService  # noqa: E402
from src.constants import DATA_DIR  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Private OS release readiness")
    parser.add_argument("--data-dir", default=os.getenv("ODYSSEUS_DATA_DIR", DATA_DIR))
    parser.add_argument("--owner", default=None)
    parser.add_argument("--record-soak", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--restore-rehearsal", action="store_true")
    parser.add_argument("--require-soak", action="store_true")
    args = parser.parse_args()
    service = ReleaseService(args.data_dir)
    result = {"preflight": service.preflight(args.owner)}
    if args.restore_rehearsal:
        result["restore_rehearsal"] = service.rehearse_restore()
    result["soak"] = service.record_soak_day(args.owner, note=args.note) if args.record_soak else service.soak_status()
    result["passed"] = result["preflight"]["passed"] and result.get("restore_rehearsal", {"passed": True})["passed"] and (result["soak"]["acceptance_met"] or not args.require_soak)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
