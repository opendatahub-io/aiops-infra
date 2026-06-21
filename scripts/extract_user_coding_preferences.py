"""extract_user_coding_preferences.py -- Extract user coding preferences from AI session transcripts.

Dual-mode: CLI + importable. Scans AI session transcripts for user corrections,
detects terminology swaps and behavioral preferences, and either auto-adds
high-confidence rules to AGENTS.md or queues them for review.

Detection pipeline:
  1. Regex pre-filter (fast, deterministic) → HIGH confidence candidates
  2. LLM analysis (if API key available) → catches nuanced corrections
  3. Confidence scoring → auto-add or queue for review

Usage:
  # Full history scan (interactive)
  python scripts/extract_user_coding_preferences.py --all-history

  # Recent sessions only (used by git hook)
  python scripts/extract_user_coding_preferences.py --since-hours 4

  # Analyze a commit diff for terminology corrections
  python scripts/extract_user_coding_preferences.py --diff HEAD~1..HEAD

  # Force regex-only (no LLM calls)
  python scripts/extract_user_coding_preferences.py --since-hours 4 --no-llm
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATEGORIES = ("terminology", "behavior", "formatting", "structure", "code_style")

REGEX_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "terminology_swap",
        re.compile(
            r'(?i)(?:use|write)\s+"([^"]+)"\s+'
            r"(?:not|instead of|rather than|never)\s+"
            r'"([^"]+)"',
        ),
        "terminology",
    ),
    (
        "terminology_swap_unquoted",
        re.compile(
            r"(?i)(?:use|write)\s+(\S+)\s+"
            r"(?:not|instead of|rather than|never)\s+"
            r"(\S+)",
        ),
        "terminology",
    ),
    (
        "change_to",
        re.compile(
            r"(?i)(?:change|replace|fix|rename)\s+(?:all\s+)?(?:instances?\s+(?:of\s+)?)?"
            r"(\S+)\s+to\s+(.+?)(?:\s+(?:everywhere|always|please|now|again))?$",
        ),
        "terminology",
    ),
    (
        "prohibition",
        re.compile(
            r"(?i)(?:never|don'?t|do not|stop|avoid|shouldn'?t)\s+(?:use\s+|say\s+|write\s+|put\s+|add\s+)?(.+)",
        ),
        "behavior",
    ),
    (
        "preference",
        re.compile(
            r"(?i)(?:always|ensure|make sure|must)\s+(.+)",
        ),
        "behavior",
    ),
    (
        "frustration_repeat",
        re.compile(
            r"(?i)(?:I (?:already|keep) (?:told|telling|said)|again[,!]|why.+still|how many times)",
        ),
        "behavior",
    ),
]

LLM_EXTRACTION_PROMPT = """\
Analyze the following user messages from AI coding sessions. Identify messages where
the user is correcting the AI's behavior, terminology, formatting, naming conventions,
or workflow patterns.

For each correction found, extract a structured rule:

- category: one of (terminology, behavior, formatting, structure, code_style)
- rule: concise imperative statement (e.g. "Always write Merge Request in full")
- prefer: what to use (if applicable, otherwise null)
- avoid: what not to use (if applicable, otherwise null)
- confidence: high, medium, or low
- source_message: the original user message (abbreviated to first 100 chars)

Return ONLY a valid JSON array of objects. If no corrections found, return [].
Do not include explanations outside the JSON.

User messages:
{messages}
"""


@dataclass
class ProposedRule:
    """A proposed preference rule extracted from transcripts."""

    category: str
    rule: str
    prefer: str | None = None
    avoid: str | None = None
    confidence: str = "medium"
    evidence_count: int = 1
    sources: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "category": self.category,
            "rule": self.rule,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "sources": self.sources,
        }
        if self.prefer:
            d["prefer"] = self.prefer
        if self.avoid:
            d["avoid"] = self.avoid
        return d

    def matches(self, other: "ProposedRule") -> bool:
        """Check if two rules are effectively the same."""
        if self.prefer and other.prefer:
            return (
                self.prefer.lower() == other.prefer.lower()
                and (self.avoid or "").lower() == (other.avoid or "").lower()
            )
        return self.rule.lower().strip() == other.rule.lower().strip()


def discover_transcript_dirs() -> list[Path]:
    """Find transcript directories across known AI tool locations."""
    dirs: list[Path] = []
    home = Path.home()

    cursor_pattern = str(home / ".cursor" / "projects" / "*" / "agent-transcripts")
    for d in glob.glob(cursor_pattern):
        p = Path(d)
        if p.is_dir():
            dirs.append(p)

    return dirs


def parse_transcripts(
    transcript_dirs: list[Path],
    since_hours: float | None = None,
) -> list[dict[str, Any]]:
    """Parse JSONL transcripts and extract user messages.

    Returns list of dicts with keys: session_id, message, timestamp_file_mtime.
    """
    cutoff = time.time() - (since_hours * 3600) if since_hours else 0
    results: list[dict[str, Any]] = []

    for tdir in transcript_dirs:
        for jsonl_path in tdir.rglob("*.jsonl"):
            if "subagents" in str(jsonl_path):
                continue
            if since_hours and jsonl_path.stat().st_mtime < cutoff:
                continue

            session_id = jsonl_path.stem
            try:
                with open(jsonl_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if record.get("role") != "user":
                            continue
                        msg = record.get("message", {})
                        content = msg.get("content", [])
                        for block in content:
                            if block.get("type") == "text":
                                text = block["text"]
                                text = _strip_system_tags(text)
                                if text.strip():
                                    results.append(
                                        {
                                            "session_id": session_id,
                                            "message": text.strip(),
                                        }
                                    )
            except (OSError, UnicodeDecodeError):
                continue

    return results


def _strip_system_tags(text: str) -> str:
    """Remove system XML tags from user messages to get the actual user query."""
    text = re.sub(r"<timestamp>.*?</timestamp>", "", text, flags=re.DOTALL)
    text = re.sub(r"<system_reminder>.*?</system_reminder>", "", text, flags=re.DOTALL)
    text = re.sub(r"<system_notification>.*?</system_notification>", "", text, flags=re.DOTALL)
    text = re.sub(r"<user_info>.*?</user_info>", "", text, flags=re.DOTALL)
    match = re.search(r"<user_query>(.*?)</user_query>", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def detect_corrections_regex(messages: list[dict[str, Any]]) -> list[ProposedRule]:
    """Detect correction patterns using regex heuristics."""
    proposals: list[ProposedRule] = []

    for msg_data in messages:
        text = msg_data["message"]
        session_id = msg_data["session_id"]

        if len(text) > 1000:
            continue
        if len(text) < 10:
            continue

        for pattern_name, pattern, category in REGEX_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue

            if pattern_name in ("terminology_swap", "terminology_swap_unquoted"):
                prefer, avoid = match.group(1).strip(), match.group(2).strip()
                rule_text = f'Always use "{prefer}" (never "{avoid}")'
                proposals.append(
                    ProposedRule(
                        category="terminology",
                        rule=rule_text,
                        prefer=prefer,
                        avoid=avoid,
                        confidence="high",
                        sources=[{"session": session_id, "user_said": text[:200]}],
                    )
                )
            elif pattern_name == "change_to":
                avoid, prefer = match.group(1).strip(), match.group(2).strip()
                rule_text = f'Use "{prefer}" instead of "{avoid}"'
                proposals.append(
                    ProposedRule(
                        category="terminology",
                        rule=rule_text,
                        prefer=prefer,
                        avoid=avoid,
                        confidence="high",
                        sources=[{"session": session_id, "user_said": text[:200]}],
                    )
                )
            elif pattern_name in ("prohibition", "preference", "frustration_repeat"):
                rule_text = text[:200]
                proposals.append(
                    ProposedRule(
                        category=category,
                        rule=rule_text,
                        confidence="medium",
                        sources=[{"session": session_id, "user_said": text[:200]}],
                    )
                )
            break

    return proposals


def detect_corrections_llm(messages: list[dict[str, Any]]) -> list[ProposedRule]:
    """Detect correction patterns using LLM analysis."""
    api_key, provider = _resolve_api_key()
    if not api_key:
        return []

    user_texts = [m["message"] for m in messages if len(m["message"]) < 500]
    if not user_texts:
        return []

    batch_size = 30
    proposals: list[ProposedRule] = []

    for i in range(0, len(user_texts), batch_size):
        batch = user_texts[i : i + batch_size]
        batch_messages = messages[i : i + batch_size]
        numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(batch))
        prompt = LLM_EXTRACTION_PROMPT.format(messages=numbered)

        try:
            response = _call_llm(prompt, api_key, provider)
            parsed = _parse_llm_response(response)
            for item in parsed:
                source_msg = item.get("source_message", "")
                session_id = ""
                for bm in batch_messages:
                    if bm["message"][:100] in source_msg or source_msg in bm["message"][:100]:
                        session_id = bm["session_id"]
                        break

                proposals.append(
                    ProposedRule(
                        category=item.get("category", "behavior"),
                        rule=item.get("rule", ""),
                        prefer=item.get("prefer"),
                        avoid=item.get("avoid"),
                        confidence=item.get("confidence", "medium"),
                        sources=[{"session": session_id, "user_said": source_msg[:200]}],
                    )
                )
        except Exception:
            continue

    return proposals


def _resolve_api_key() -> tuple[str, str]:
    """Try API keys in order: CURSOR_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY."""
    for var, provider in [
        ("CURSOR_API_KEY", "cursor"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("OPENAI_API_KEY", "openai"),
    ]:
        val = os.environ.get(var, "").strip()
        if val:
            return val, provider

    env_file = Path(".work/.env")
    if env_file.exists():
        try:
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key in ("CURSOR_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY") and value:
                    provider = key.split("_")[0].lower()
                    return value, provider
        except OSError:
            pass

    return "", ""


def _call_llm(prompt: str, api_key: str, provider: str) -> str:
    """Call LLM API and return the response text."""
    import urllib.request
    import urllib.error

    if provider == "anthropic":
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        body = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
    elif provider == "openai" or provider == "cursor":
        url = "https://api.openai.com/v1/chat/completions"
        if provider == "cursor":
            url = "https://api.cursor.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        body = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
        }).encode()
    else:
        return ""

    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return ""

    if provider == "anthropic":
        content = data.get("content", [])
        return content[0].get("text", "") if content else ""
    else:
        choices = data.get("choices", [])
        return choices[0].get("message", {}).get("content", "") if choices else ""


def _parse_llm_response(response: str) -> list[dict[str, Any]]:
    """Parse LLM response as JSON array."""
    response = response.strip()
    json_match = re.search(r"\[.*\]", response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return []


def detect_corrections_diff(diff_ref: str) -> list[ProposedRule]:
    """Detect terminology corrections from a git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", diff_ref, "--unified=0"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    removals: list[str] = []
    additions: list[str] = []
    proposals: list[ProposedRule] = []

    for line in result.stdout.splitlines():
        if line.startswith("-") and not line.startswith("---"):
            removals.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            additions.append(line[1:])

    for rem_line in removals:
        for add_line in additions:
            swaps = _find_terminology_swaps(rem_line, add_line)
            for avoid, prefer in swaps:
                proposals.append(
                    ProposedRule(
                        category="terminology",
                        rule=f'Use "{prefer}" instead of "{avoid}"',
                        prefer=prefer,
                        avoid=avoid,
                        confidence="high",
                        sources=[{"session": "git-diff", "user_said": f"Changed in commit: {diff_ref}"}],
                    )
                )

    return proposals


def _find_terminology_swaps(removed: str, added: str) -> list[tuple[str, str]]:
    """Find word-level substitutions between a removed and added line."""
    rem_words = removed.split()
    add_words = added.split()

    if len(rem_words) != len(add_words):
        return []
    if len(rem_words) < 2:
        return []

    swaps: list[tuple[str, str]] = []
    diff_count = 0
    for rw, aw in zip(rem_words, add_words):
        if rw != aw:
            diff_count += 1
            if diff_count <= 3:
                rw_clean = rw.strip(".,;:!?\"'()[]{}")
                aw_clean = aw.strip(".,;:!?\"'()[]{}")
                if rw_clean and aw_clean and rw_clean.lower() != aw_clean.lower():
                    swaps.append((rw_clean, aw_clean))

    if diff_count > 3:
        return []
    return swaps


def deduplicate(
    proposals: list[ProposedRule],
    agents_md_path: Path,
) -> tuple[list[ProposedRule], list[ProposedRule]]:
    """Deduplicate proposals against existing AGENTS.md and merge duplicates.

    Returns (new_proposals, already_exists).
    """
    existing_text = ""
    if agents_md_path.exists():
        existing_text = agents_md_path.read_text().lower()

    merged: list[ProposedRule] = []
    for prop in proposals:
        if not prop.rule.strip():
            continue

        is_dup_of_agents = False
        if prop.prefer and prop.prefer.lower() in existing_text:
            if prop.avoid and prop.avoid.lower() in existing_text:
                is_dup_of_agents = True
        if prop.rule.lower()[:50] in existing_text:
            is_dup_of_agents = True

        if is_dup_of_agents:
            continue

        found_match = False
        for existing in merged:
            if existing.matches(prop):
                existing.evidence_count += 1
                existing.sources.extend(prop.sources)
                if prop.confidence == "high":
                    existing.confidence = "high"
                found_match = True
                break
        if not found_match:
            merged.append(prop)

    return merged, []


def score_and_split(
    proposals: list[ProposedRule],
) -> tuple[list[ProposedRule], list[ProposedRule]]:
    """Split proposals into auto-add (high confidence) and review queue.

    Auto-add criteria (ALL must be true):
      1. Regex-detected (high confidence) OR LLM-detected + seen 2+ times
      2. Category is terminology or code_style
      3. Has clear prefer/avoid pair
    """
    auto_add: list[ProposedRule] = []
    review: list[ProposedRule] = []

    for prop in proposals:
        is_auto = (
            prop.confidence == "high"
            and prop.evidence_count >= 2
            and prop.category in ("terminology", "code_style")
            and prop.prefer is not None
        )
        if is_auto:
            auto_add.append(prop)
        else:
            review.append(prop)

    return auto_add, review


def append_to_agents_md(rules: list[ProposedRule], agents_md_path: Path) -> int:
    """Append high-confidence rules to the appropriate section in AGENTS.md."""
    if not rules:
        return 0

    content = agents_md_path.read_text()

    section_markers = {
        "terminology": "### Terminology",
        "code_style": "### Code Style",
        "behavior": "### Behavior and Workflow",
        "formatting": "### Structure and Formatting",
        "structure": "### Structure and Formatting",
    }

    added = 0
    for rule in rules:
        marker = section_markers.get(rule.category, "### Terminology")
        if marker not in content:
            continue

        if rule.prefer and rule.avoid:
            new_line = f'- Always use "{rule.prefer}" (never "{rule.avoid}")\n'
        else:
            new_line = f"- {rule.rule}\n"

        marker_pos = content.index(marker)
        next_section = content.find("\n###", marker_pos + len(marker))
        if next_section == -1:
            next_section = content.find("\n##", marker_pos + len(marker))

        if next_section == -1:
            insert_pos = len(content)
        else:
            last_newline = content.rfind("\n", marker_pos, next_section)
            insert_pos = last_newline + 1

        content = content[:insert_pos] + new_line + content[insert_pos:]
        added += 1

    if added > 0:
        agents_md_path.write_text(content)

    return added


def save_proposals(proposals: list[ProposedRule], output_path: Path) -> None:
    """Save proposals to YAML file, merging with existing proposals."""
    existing: list[dict[str, Any]] = []
    if output_path.exists():
        try:
            data = yaml.safe_load(output_path.read_text()) or {}
            existing = data.get("proposed_rules", [])
        except (yaml.YAMLError, OSError):
            pass

    new_entries = [p.to_dict() for p in proposals]

    for new in new_entries:
        found = False
        for ex in existing:
            has_prefer = new.get("prefer") and ex.get("prefer")
            prefer_match = has_prefer and (
                new["prefer"] == ex["prefer"] and new.get("avoid") == ex.get("avoid")
            )
            rule_match = (
                new.get("rule", "") and ex.get("rule", "")
                and new["rule"][:50] == ex["rule"][:50]
            )
            if prefer_match or rule_match:
                ex["evidence_count"] = ex.get("evidence_count", 1) + new.get("evidence_count", 1)
                ex.setdefault("sources", []).extend(new.get("sources", []))
                found = True
                break
        if not found:
            existing.append(new)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.dump({"proposed_rules": existing}, default_flow_style=False, sort_keys=False)
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract user coding preferences from AI session transcripts."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all-history",
        action="store_true",
        help="Scan all available transcripts",
    )
    group.add_argument(
        "--since-hours",
        type=float,
        help="Only scan transcripts modified in the last N hours",
    )
    parser.add_argument(
        "--diff",
        type=str,
        help="Also analyze a git diff ref (e.g. HEAD~1..HEAD) for terminology corrections",
    )
    parser.add_argument(
        "--transcripts-dir",
        type=str,
        help="Override transcript directory path (otherwise auto-discovers)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=".work/proposed-conventions.yaml",
        help="Output path for review-queue proposals (default: .work/proposed-conventions.yaml)",
    )
    parser.add_argument(
        "--agents-md",
        type=str,
        default="./AGENTS.md",
        help="Path to AGENTS.md for dedup checking and auto-add (default: ./AGENTS.md)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Force regex-only mode (no LLM API calls)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout output (for hook usage)",
    )

    args = parser.parse_args()

    if args.transcripts_dir:
        transcript_dirs = [Path(args.transcripts_dir)]
    else:
        transcript_dirs = discover_transcript_dirs()

    if not transcript_dirs:
        if not args.quiet:
            print("No transcript directories found.", file=sys.stderr)
        return 0

    since_hours = None if args.all_history else args.since_hours
    messages = parse_transcripts(transcript_dirs, since_hours=since_hours)

    if not args.quiet:
        print(f"Found {len(messages)} user messages across {len(transcript_dirs)} transcript directories")

    all_proposals: list[ProposedRule] = []

    regex_proposals = detect_corrections_regex(messages)
    all_proposals.extend(regex_proposals)
    if not args.quiet:
        print(f"Regex detection: {len(regex_proposals)} candidates")

    if not args.no_llm:
        llm_proposals = detect_corrections_llm(messages)
        all_proposals.extend(llm_proposals)
        if not args.quiet:
            print(f"LLM detection: {len(llm_proposals)} candidates")

    if args.diff:
        diff_proposals = detect_corrections_diff(args.diff)
        all_proposals.extend(diff_proposals)
        if not args.quiet:
            print(f"Diff detection: {len(diff_proposals)} candidates")

    agents_md_path = Path(args.agents_md)
    deduped, _ = deduplicate(all_proposals, agents_md_path)

    if not args.quiet:
        print(f"After dedup: {len(deduped)} new proposals")

    auto_add, review_queue = score_and_split(deduped)

    if auto_add and agents_md_path.exists():
        added = append_to_agents_md(auto_add, agents_md_path)
        if not args.quiet:
            print(f"Auto-added {added} high-confidence rules to {agents_md_path}")

    if review_queue:
        output_path = Path(args.output)
        save_proposals(review_queue, output_path)
        if not args.quiet:
            print(f"Queued {len(review_queue)} proposals for review in {output_path}")

    total = (len(auto_add) if auto_add else 0) + len(review_queue)
    if total == 0 and not args.quiet:
        print("No new preferences detected.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
