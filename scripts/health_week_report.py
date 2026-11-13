"""Private report on stdout only; never publish to Instagram.

Run from repository root: python -m scripts.health_week_report --date 2026-11-13
"""
import argparse
import asyncio
import json

from app.services.diet_mcp_client import fetch_health_week_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', help='YYYY-MM-DD; defaults to today JST')
    args = parser.parse_args()
    report = asyncio.run(fetch_health_week_summary(args.date))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
