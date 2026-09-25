"""Unified CLI dispatcher for the budget tool."""

import argparse
import sys

from budget_parser.cli import categorize, extract, serve


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="budget",
        description="Personal budget tool — extract, categorize, and visualize bank transactions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  budget extract --year 2026
  budget categorize --year 2026
  budget categorize --year 2026 --migrate
  budget serve
  budget serve --port 8080
""",
    )
    parser.add_argument("--version", action="version", version="%(prog)s 2.0.0")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    extract.add_parser(subparsers)
    categorize.add_parser(subparsers)
    serve.add_parser(subparsers)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
