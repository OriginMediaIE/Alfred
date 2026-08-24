#!/usr/bin/env python3
"""Seed the synthetic Alfred Private OS release walkthrough."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from services.privateos_demo_service import PrivateOSDemoService  # noqa: E402
from src.constants import DATA_DIR  # noqa: E402


def main():
    parser=argparse.ArgumentParser(description="Seed synthetic Private OS demo data")
    parser.add_argument("--data-dir",default=DATA_DIR);parser.add_argument("--owner",required=True);parser.add_argument("--confirm",action="store_true")
    args=parser.parse_args()
    if not args.confirm:
        parser.error("--confirm is required because this writes synthetic records")
    service=PrivateOSDemoService(args.data_dir)
    try:result=service.seed(args.owner)
    finally:service.close()
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":main()
