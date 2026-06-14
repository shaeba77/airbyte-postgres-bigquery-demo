"""
Parse an Airbyte connector log file and surface the "real" error.

When a sync fails, Airbyte logs hundreds of INFO lines and a long Java stack trace.
This script:
  1. Filters to ERROR/FATAL/WARN lines
  2. Extracts the root cause from a stack trace (the deepest "Caused by:")
  3. Tags the error with a likely category (permissions, network, schema, etc.)

The goal is to turn 2,000 lines of log into 5 actionable lines for a support ticket.

Usage:
    python scripts/parse_logs.py /path/to/airbyte_sync.log
    docker logs airbyte-worker | python scripts/parse_logs.py -
"""

import re
import sys
from collections import Counter


# Heuristics for tagging error categories. Pattern -> category.
CATEGORY_RULES = [
    (r"must be superuser or replication role",       "permissions:postgres-replication"),
    (r"permission denied for (table|schema|relation)", "permissions:postgres-grants"),
    (r"Access Denied: Table",                          "permissions:bigquery-table"),
    (r"403\b.*forbidden",                              "permissions:cloud-iam"),
    (r"Quota exceeded",                                "quota:bigquery"),
    (r"Connection.*refused|timed out",                 "network:connectivity"),
    (r"SSLHandshakeException|PKIX",                    "network:tls"),
    (r"unknown host|UnknownHostException",             "network:dns"),
    (r"replication slot .* does not exist",            "config:missing-slot"),
    (r"publication .* does not exist",                 "config:missing-publication"),
    (r"REPLICA IDENTITY",                              "data:replica-identity"),
    (r"no primary key|primary key not found",          "data:no-primary-key"),
    (r"OutOfMemoryError|Java heap space",              "resource:memory"),
    (r"disk full|No space left",                       "resource:disk"),
    (r"schema .* does not match|column .* not found",  "schema:drift"),
]


LEVEL_PATTERN = re.compile(r"\b(ERROR|FATAL|WARN)\b")
CAUSED_BY_PATTERN = re.compile(r"Caused by: ([\w\.\$]+(?:Exception|Error)): (.+)")


def open_input(path: str):
    if path == "-":
        return sys.stdin
    return open(path, "r", encoding="utf-8", errors="replace")


def categorize(line: str) -> str:
    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, line, re.IGNORECASE):
            return category
    return "unknown"


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: parse_logs.py <logfile|->")

    error_lines = []
    causes = []
    categories = Counter()

    with open_input(sys.argv[1]) as f:
        for line in f:
            if LEVEL_PATTERN.search(line):
                error_lines.append(line.rstrip())
                categories[categorize(line)] += 1
            match = CAUSED_BY_PATTERN.search(line)
            if match:
                causes.append((match.group(1), match.group(2).strip()))

    print()
    print("=" * 70)
    print("AIRBYTE LOG SUMMARY")
    print("=" * 70)

    print(f"\nFound {len(error_lines)} ERROR/FATAL/WARN lines.")
    print(f"Found {len(causes)} 'Caused by' stack-trace entries.")

    if causes:
        # The deepest "Caused by" is usually the actual root cause
        root_exception, root_message = causes[-1]
        print("\n--- ROOT CAUSE (deepest 'Caused by') ---")
        print(f"  Exception: {root_exception}")
        print(f"  Message:   {root_message}")
        print(f"  Category:  {categorize(root_message)}")

    if categories:
        print("\n--- ERROR CATEGORIES (count) ---")
        for cat, count in categories.most_common():
            print(f"  {count:>4}  {cat}")

    if error_lines:
        print("\n--- LAST 5 ERROR LINES ---")
        for line in error_lines[-5:]:
            # Truncate long lines for readability
            print(f"  {line[:200]}")

    print()
    print("Next step: look up the category in docs/troubleshooting_playbook.md")
    print()


if __name__ == "__main__":
    main()
