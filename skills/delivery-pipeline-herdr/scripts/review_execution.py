#!/usr/bin/env python3
"""Herdr resolved owner 的逐轴证据适配入口；仅消费冻结 packet，无原生副作用。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'delivery-pipeline/scripts'))
import argparse
import json
from review_gate import run, record_axis_execution, round_release_blockers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', required=True)
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
        if not isinstance(data.get('review_packet'), dict):
            raise ValueError('frozen review_packet required')
        print(run(data, args.ledger))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f'review execution: {error}', file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
