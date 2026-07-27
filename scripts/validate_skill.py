#!/usr/bin/env python3
"""Validate the repository's Context Tree Insights skill contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "context-tree-insights"
SKILL_MD = SKILL_ROOT / "SKILL.md"
OPENAI_YAML = SKILL_ROOT / "agents" / "openai.yaml"
EXPECTED_FILES = (
    SKILL_MD,
    OPENAI_YAML,
    SKILL_ROOT / "VERSION",
    SKILL_ROOT / "scripts" / "context_tree_insights.py",
    SKILL_ROOT / "references" / "evidence-schema.md",
    SKILL_ROOT / "references" / "task-analysis-schema.md",
)
FORBIDDEN_PATH_FRAGMENTS = ("/Users/", "\\Users\\")
FORBIDDEN_ARTIFACT_NAMES = {
    "REPORT.md",
    "evidence.jsonl",
    "candidates.jsonl",
    "chats.jsonl",
    "judgments.jsonl",
    "task-judgments.jsonl",
}


def fail(message: str) -> None:
    raise ValueError(message)


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        fail("SKILL.md must start with YAML frontmatter.")
    try:
        closing = lines.index("---", 1)
    except ValueError as error:
        raise ValueError("SKILL.md frontmatter is not closed.") from error
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator or not key.strip() or not value.strip():
            fail(f"Unsupported frontmatter line: {line}")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def validate() -> None:
    for path in EXPECTED_FILES:
        if not path.is_file():
            fail(f"Missing required skill file: {path.relative_to(ROOT)}")
        if path.is_symlink():
            fail(f"Skill files must not be symlinks: {path.relative_to(ROOT)}")

    skill_text = SKILL_MD.read_text(encoding="utf-8")
    frontmatter = parse_frontmatter(skill_text)
    if set(frontmatter) != {"name", "description"}:
        fail("SKILL.md frontmatter must contain only name and description.")
    if frontmatter["name"] != SKILL_ROOT.name:
        fail("Skill name must match its directory name.")
    if not frontmatter["description"]:
        fail("Skill description must not be empty.")
    version = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        fail("VERSION must contain one semantic version.")

    openai_text = OPENAI_YAML.read_text(encoding="utf-8")
    if not re.search(
        r"(?ms)^policy:\s*\n(?:^[ \t]+.*\n)*?^[ \t]+allow_implicit_invocation:\s*false\s*$",
        openai_text,
    ):
        fail("agents/openai.yaml must disable implicit invocation.")
    if "$context-tree-insights" not in openai_text:
        fail("agents/openai.yaml default prompt must mention $context-tree-insights.")

    for path in SKILL_ROOT.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            fail(f"Skill payload must not contain symlinks: {path.relative_to(ROOT)}")
        if not path.is_file():
            continue
        if path.suffix not in {"", ".md", ".py", ".yaml", ".yml"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "TODO" in text:
            fail(f"Unresolved TODO in {path.relative_to(ROOT)}")
        for fragment in FORBIDDEN_PATH_FRAGMENTS:
            if fragment in text:
                fail(f"Personal absolute path in {path.relative_to(ROOT)}")

    for path in ROOT.rglob("*"):
        if path.is_file() and path.name in FORBIDDEN_ARTIFACT_NAMES:
            if "tests/fixtures" not in path.relative_to(ROOT).as_posix():
                fail(f"Generated audit artifact is committed: {path.relative_to(ROOT)}")


def main() -> int:
    try:
        validate()
    except (OSError, UnicodeError, ValueError) as error:
        print(f"skill validation failed: {error}", file=sys.stderr)
        return 1
    print("skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
