#!/usr/bin/env python3
"""Fail if any SKILL.md's frontmatter `description` is 1024 characters or longer.

Skill-loading platforms enforce a 1024-char cap on this field; anything at
or over that gets truncated or rejected at load time, so this is checked
in CI rather than discovered after merge.
"""
import re
import sys
from pathlib import Path

import yaml

LIMIT = 1024
REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_FILES = [
    REPO_ROOT / "daily-brief-generation" / "SKILL.md",
    REPO_ROOT / "account-environments-discovery" / "SKILL.md",
]


def check_file(skill_file: Path) -> bool:
    if not skill_file.exists():
        print(f"::error::{skill_file} not found")
        return False

    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not match:
        print(f"::error::{skill_file} has no YAML frontmatter")
        return False

    frontmatter = yaml.safe_load(match.group(1)) or {}
    description = frontmatter.get("description")
    if description is None:
        print(f"::error::{skill_file} frontmatter has no 'description' field")
        return False

    length = len(description)
    if length >= LIMIT:
        print(
            f"::error file={skill_file}::description is {length} characters, "
            f"which is at or over the {LIMIT}-character limit. Shorten it by "
            f"at least {length - LIMIT + 1} characters."
        )
        return False

    print(f"OK: {skill_file} description is {length} characters (limit {LIMIT}).")
    return True


def main() -> int:
    ok = True
    for skill_file in SKILL_FILES:
        if not check_file(skill_file):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
