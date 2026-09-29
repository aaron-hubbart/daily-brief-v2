#!/usr/bin/env python3
"""Fail if any SKILL.md's frontmatter `description` is invalid.

Checks enforced:
- Skill-loading platforms enforce a 1024-char cap on this field; anything at
  or over that gets truncated or rejected at load time.
- The field is parsed as XML-ish content by some loaders, so angle-bracket
  placeholders like "<account>" get misread as literal tags and rejected.
  Use square brackets ("[account]") for placeholders instead.

Both are checked in CI rather than discovered after merge/upload.
"""
import re
import sys
from pathlib import Path

import yaml

LIMIT = 1024
TAG_PATTERN = re.compile(r"</?[a-zA-Z][a-zA-Z0-9_-]*(?:\s[^<>]*)?>")
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

    ok = True

    length = len(description)
    if length >= LIMIT:
        print(
            f"::error file={skill_file}::description is {length} characters, "
            f"which is at or over the {LIMIT}-character limit. Shorten it by "
            f"at least {length - LIMIT + 1} characters."
        )
        ok = False

    tags = TAG_PATTERN.findall(description)
    if tags:
        print(
            f"::error file={skill_file}::description contains XML/HTML-like "
            f"tag(s) {tags}, which some skill loaders reject. Use square "
            f"brackets (e.g. \"[account]\") for placeholders instead of "
            f"angle brackets."
        )
        ok = False

    if ok:
        print(f"OK: {skill_file} description is {length} characters (limit {LIMIT}) and has no tag-like content.")
    return ok


def main() -> int:
    ok = True
    for skill_file in SKILL_FILES:
        if not check_file(skill_file):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
