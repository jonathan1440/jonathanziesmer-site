#!/usr/bin/env python3
"""
Merge and validate spec story/AC subagent output.

Usage:
  spec-story-ac-merge.py validate-stories --input FILE [FILE ...]
  spec-story-ac-merge.py merge-stories --input FILE [FILE ...] [--output PATH]
  spec-story-ac-merge.py validate-ac --input FILE [FILE ...]
  spec-story-ac-merge.py merge-ac --stories PATH --input FILE [FILE ...] [--output PATH]
  spec-story-ac-merge.py write-artifact --stories PATH --ac PATH --output PATH
      [--split-threshold-stories N] [--split-threshold-ac N]
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


STORY_BLOCK_RE = re.compile(r"^## Story:\s*(.+)$", re.MULTILINE)
STORY_HEADING_RE = re.compile(r"^###\s*(US-[^\s:]+):\s*(.+)$", re.MULTILINE)
STORY_LINE_RE = re.compile(r"^As a .+, I want .+, so that .+\.?\s*$", re.MULTILINE)
RECOMMENDATION_RE = re.compile(
    r"^### Recommendation\s*\n\s*(accept|revise|split|reject)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

AC_STORY_BLOCK_RE = re.compile(r"^## (US-\d+):\s*(.+)$", re.MULTILINE)
AC_SCENARIO_RE = re.compile(
    r"^\s*(\d+)\.\s+\*\*(AC-[^*]+)\*\*\s*—\s*(.+)$",
    re.MULTILINE,
)
GWT_RE = re.compile(r"^\s*-\s+\*\*(Given|When|Then)\*\*\s+(.+)$", re.MULTILINE)

VALID_RECOMMENDATIONS = {"accept", "revise", "split", "reject"}


@dataclass
class StoryBlock:
    source: str
    story_id: str
    recommendation: str | None
    titles: list[tuple[str, str]]  # (US-id, title)
    story_lines: list[str]  # "As a ..." lines
    raw: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class ACScenario:
    local_id: str
    name: str
    given: str
    when: str
    then: str


@dataclass
class ACStoryBlock:
    story_id: str
    title: str
    story_line: str
    scenarios: list[ACScenario]
    raw: str
    warnings: list[str] = field(default_factory=list)


def read_inputs(paths: Iterable[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        parts.append(text.strip())
    return "\n\n".join(parts)


def split_story_blocks(text: str) -> list[str]:
    chunks = re.split(r"(?=^## Story:)", text.strip(), flags=re.MULTILINE)
    return [c.strip() for c in chunks if c.strip().startswith("## Story:")]


def split_ac_blocks(text: str) -> list[str]:
    chunks = re.split(r"(?=^## US-\d+:)", text.strip(), flags=re.MULTILINE)
    return [c.strip() for c in chunks if re.match(r"^## US-\d+:", c.strip())]


def proposed_section(raw: str) -> str:
    match = re.search(r"### Proposed story\(ies\)\s*\n(.*)", raw, re.DOTALL | re.IGNORECASE)
    if not match:
        return raw
    tail = match.group(1)
    # Stop at next ### section (Rationale, Cross-story, etc.)
    stop = re.search(r"\n### ", tail)
    return tail[: stop.start()] if stop else tail


def parse_story_block(raw: str, source: str = "") -> StoryBlock:
    match = STORY_BLOCK_RE.search(raw)
    story_id = match.group(1).strip() if match else "UNKNOWN"
    rec_match = RECOMMENDATION_RE.search(raw)
    recommendation = rec_match.group(1).lower() if rec_match else None
    proposed = proposed_section(raw)
    titles = [(m.group(1), m.group(2).strip()) for m in STORY_HEADING_RE.finditer(proposed)]
    story_lines = [m.group(0).strip() for m in STORY_LINE_RE.finditer(proposed)]
    block = StoryBlock(
        source=source,
        story_id=story_id,
        recommendation=recommendation,
        titles=titles,
        story_lines=story_lines,
        raw=raw,
    )
    if recommendation is None:
        block.warnings.append("missing or invalid Recommendation (accept|revise|split|reject)")
    elif recommendation not in VALID_RECOMMENDATIONS:
        block.warnings.append(f"invalid Recommendation: {recommendation}")
    if not story_lines:
        block.warnings.append("no 'As a … I want … so that …' line in Proposed story(ies)")
    if recommendation in {"revise", "split"} and "### Original" not in raw:
        block.warnings.append(f"Recommendation is {recommendation} but ### Original section missing")
    return block


def parse_ac_block(raw: str) -> ACStoryBlock:
    header = AC_STORY_BLOCK_RE.search(raw)
    story_id = header.group(1) if header else "US-00"
    title = header.group(2).strip() if header else "Unknown"
    story_line_match = STORY_LINE_RE.search(raw)
    story_line = story_line_match.group(0).strip() if story_line_match else ""
    scenarios: list[ACScenario] = []
    block = ACStoryBlock(
        story_id=story_id,
        title=title,
        story_line=story_line,
        scenarios=scenarios,
        raw=raw,
    )
    if not story_line:
        block.warnings.append("missing story line (As a … I want … so that …)")
    if "**Acceptance scenarios:**" not in raw:
        block.warnings.append("missing **Acceptance scenarios:** section")

    for scenario_match in AC_SCENARIO_RE.finditer(raw):
        local_id = scenario_match.group(2).strip()
        name = scenario_match.group(3).strip()
        start = scenario_match.end()
        next_match = AC_SCENARIO_RE.search(raw, start)
        end = next_match.start() if next_match else len(raw)
        chunk = raw[start:end]
        gwt = {m.group(1): m.group(2).strip() for m in GWT_RE.finditer(chunk)}
        scenario = ACScenario(
            local_id=local_id,
            name=name,
            given=gwt.get("Given", ""),
            when=gwt.get("When", ""),
            then=gwt.get("Then", ""),
        )
        scenarios.append(scenario)
        if not all([scenario.given, scenario.when, scenario.then]):
            block.warnings.append(f"{local_id}: incomplete Given/When/Then")

    if not scenarios:
        block.warnings.append("no acceptance scenarios found")
    return block


def emit_errors(label: str, items: Iterable[tuple[str, list[str]]]) -> bool:
    ok = True
    for name, warnings in items:
        if not warnings:
            continue
        ok = False
        print(f"{label} {name}:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
    return ok


def cmd_validate_stories(args: argparse.Namespace) -> int:
    text = read_inputs(args.input)
    blocks = [parse_story_block(b, b[:40]) for b in split_story_blocks(text)]
    if not blocks:
        print("validate-stories: no ## Story: blocks found", file=sys.stderr)
        return 1
    ok = emit_errors("story", [(b.story_id, b.warnings) for b in blocks])
    revise_split = [b for b in blocks if b.recommendation in {"revise", "split"}]
    for b in revise_split:
        print(f"note: {b.story_id} → {b.recommendation}", file=sys.stderr)
    if ok:
        print(f"validate-stories: ok ({len(blocks)} block(s))")
        return 0
    return 1


def pick_primary_story(block: StoryBlock) -> tuple[str, str, str]:
    if block.titles:
        us_id, title = block.titles[-1]
    else:
        us_id, title = "US-??", "Untitled"
    line = block.story_lines[0] if block.story_lines else ""
    return us_id, title, line


def cmd_merge_stories(args: argparse.Namespace) -> int:
    text = read_inputs(args.input)
    blocks = [parse_story_block(b) for b in split_story_blocks(text)]
    if not blocks:
        print("merge-stories: no ## Story: blocks found", file=sys.stderr)
        return 1
    emit_errors("story", [(b.story_id, b.warnings) for b in blocks])

    lines: list[str] = ["# Merged user stories", ""]
    for idx, block in enumerate(blocks, start=1):
        us_id = f"US-{idx:02d}"
        _, title, story_line = pick_primary_story(block)
        if block.recommendation in {"revise", "split"}:
            print(
                f"warning: {block.story_id} recommends {block.recommendation} — present ORIGINAL vs PROPOSED to user",
                file=sys.stderr,
            )
        lines.append(f"### {us_id}: {title}")
        if story_line:
            lines.append(story_line)
        lines.append("")

    output = "\n".join(lines).rstrip() + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"merge-stories: wrote {args.output}")
    else:
        sys.stdout.write(output)
    return 0


def parse_merged_stories(path: Path) -> list[tuple[str, str, str]]:
    text = path.read_text(encoding="utf-8")
    stories: list[tuple[str, str, str]] = []
    for match in re.finditer(
        r"^### (US-\d+):\s*(.+)\n(As a .+\n?)",
        text,
        re.MULTILINE,
    ):
        stories.append((match.group(1), match.group(2).strip(), match.group(3).strip()))
    return stories


def cmd_validate_ac(args: argparse.Namespace) -> int:
    text = read_inputs(args.input)
    blocks = [parse_ac_block(b) for b in split_ac_blocks(text)]
    if not blocks:
        print("validate-ac: no ## US-NN: blocks found", file=sys.stderr)
        return 1
    ok = emit_errors("ac", [(b.story_id, b.warnings) for b in blocks])
    names: dict[str, list[str]] = {}
    for block in blocks:
        for s in block.scenarios:
            names.setdefault(s.name.lower(), []).append(f"{block.story_id}/{s.local_id}")
    for name, refs in names.items():
        if len(refs) > 1:
            print(f"warning: duplicate scenario name '{name}' in {', '.join(refs)}", file=sys.stderr)
    if ok:
        print(f"validate-ac: ok ({len(blocks)} story block(s))")
        return 0
    return 1


def cmd_merge_ac(args: argparse.Namespace) -> int:
    story_order = parse_merged_stories(args.stories)
    if not story_order:
        print(f"merge-ac: no stories in {args.stories}", file=sys.stderr)
        return 1

    text = read_inputs(args.input)
    ac_blocks = {b.story_id: b for b in (parse_ac_block(b) for b in split_ac_blocks(text))}
    # Also match by order when subagent kept temp IDs
    ac_list = [parse_ac_block(b) for b in split_ac_blocks(text)]

    lines: list[str] = ["# User Stories & Acceptance Criteria", ""]
    ac_counter = 0
    seen_names: dict[str, str] = {}

    for idx, (us_id, title, story_line) in enumerate(story_order):
        block = ac_list[idx] if idx < len(ac_list) else ac_blocks.get(us_id)
        if block is None:
            print(f"warning: no AC block for {us_id}", file=sys.stderr)
            lines.extend([f"### {us_id}: {title}", story_line, ""])
            continue
        emit_errors("ac", [(block.story_id, block.warnings)])
        lines.append(f"### {us_id}: {title}")
        lines.append(story_line)
        lines.append("")
        lines.append("**Acceptance scenarios:**")
        lines.append("")
        for scenario in block.scenarios:
            ac_counter += 1
            ac_id = f"AC-{ac_counter:02d}"
            key = scenario.name.lower()
            if key in seen_names:
                print(
                    f"warning: overlapping scenario '{scenario.name}' ({seen_names[key]} vs {ac_id})",
                    file=sys.stderr,
                )
            else:
                seen_names[key] = ac_id
            lines.append(f"{ac_counter}. **{ac_id}** — {scenario.name}")
            lines.append(f"   - **Given** {scenario.given}")
            lines.append(f"   - **When** {scenario.when}")
            lines.append(f"   - **Then** {scenario.then}")
            lines.append("")
        lines.append("")

    output = "\n".join(lines).rstrip() + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(f"merge-ac: wrote {args.output} ({ac_counter} scenario(s))")
    else:
        sys.stdout.write(output)
    return 0


def cmd_write_artifact(args: argparse.Namespace) -> int:
    stories = parse_merged_stories(args.stories)
    ac_text = args.ac.read_text(encoding="utf-8")
    ac_count = len(AC_SCENARIO_RE.findall(ac_text))
    story_count = len(stories)

    if story_count > args.split_threshold_stories or ac_count > args.split_threshold_ac:
        print(
            f"note: {story_count} stories, {ac_count} AC — consider docs/acceptance-criteria.md + link from SPEC.md",
            file=sys.stderr,
        )

    # merge-ac output or ac file may already be formatted; prefer ac file if it has ### US-
    if re.search(r"^### US-\d+:", ac_text, re.MULTILINE):
        body = ac_text.strip()
        if not body.startswith("#"):
            body = "# User Stories & Acceptance Criteria\n\n" + body
    else:
        body = ac_text

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body.rstrip() + "\n", encoding="utf-8")
    print(f"write-artifact: wrote {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_inputs(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--input",
            type=Path,
            nargs="+",
            required=True,
            help="Input markdown file(s)",
        )

    p_val_stories = sub.add_parser("validate-stories", help="Validate subagent story output")
    add_inputs(p_val_stories)

    p_merge_stories = sub.add_parser("merge-stories", help="Merge and renumber stories to US-01…")
    add_inputs(p_merge_stories)
    p_merge_stories.add_argument("--output", type=Path, help="Output path (default: stdout)")

    p_val_ac = sub.add_parser("validate-ac", help="Validate subagent AC output")
    add_inputs(p_val_ac)

    p_merge_ac = sub.add_parser("merge-ac", help="Merge AC and assign global AC-01…")
    p_merge_ac.add_argument("--stories", type=Path, required=True, help="Merged stories file")
    add_inputs(p_merge_ac)
    p_merge_ac.add_argument("--output", type=Path, help="Output path (default: stdout)")

    p_write = sub.add_parser("write-artifact", help="Write acceptance criteria artifact")
    p_write.add_argument("--stories", type=Path, required=True)
    p_write.add_argument("--ac", type=Path, required=True)
    p_write.add_argument("--output", type=Path, required=True)
    p_write.add_argument("--split-threshold-stories", type=int, default=3)
    p_write.add_argument("--split-threshold-ac", type=int, default=12)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    handlers = {
        "validate-stories": cmd_validate_stories,
        "merge-stories": cmd_merge_stories,
        "validate-ac": cmd_validate_ac,
        "merge-ac": cmd_merge_ac,
        "write-artifact": cmd_write_artifact,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
