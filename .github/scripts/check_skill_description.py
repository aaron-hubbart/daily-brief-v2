#!/usr/bin/env python3
"""Fail if SKILL.md's frontmatter `description` is 1024 characters or longer.

Skill-loading platforms enforce a 1024-char cap on this field; anything at
or over that gets truncated or rejected at load time, so this is checked
in CI rather than discovered after merge.
"""
import re
import sys
from pathlib import Path

import yaml

LIMIT = 1024
SKILL_FILE = Path(__file__).resolve().parents[2] / "SKILL.md"


def main() -> int:
    if not SKILL_FILE.exists():
        print(f"::error::{SKILL_FILE} not found")
        return 1

    text = SKILL_FILE.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        print(f"::error::{SKILL_FILE} has no YAML frontmatter")
        return 1

    frontmatter = yaml.safe_load(match.group(1)) or {}
    description = frontmatter.get("description")
    if description is None:
        print(f"::error::{SKILL_FILE} frontmatter has no 'description' field")
        return 1

    length = len(description)
    if length >= LIMIT:
        print(
            f"::error file={SKILL_FILE}::description is {length} characters, "
            f"which is at or over the {LIMIT}-character limit. Shorten it by "
            f"at least {length - LIMIT + 1} characters."
        )
        return 1

    print(f"OK: description is {length} characters (limit {LIMIT}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
