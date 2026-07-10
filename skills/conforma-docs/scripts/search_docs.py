#!/usr/bin/env python3
"""Full-text search across conforma documentation and reference files.

Auto-discovers all skills/conforma* directories and indexes:
- references/*.md, references/*.yaml — reference data and documentation
- docs/*.md, docs/*.yaml — additional documentation
- SKILL.md — skill definitions (prose only; frontmatter and code blocks stripped)

Usage:
    python3 skills/conforma-docs/scripts/search_docs.py --query "hermetic build"
    python3 skills/conforma-docs/scripts/search_docs.py --query "rpm signing key" --format json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

import _setup_env  # noqa: F401

SKILLS_DIR = _setup_env.REPO_ROOT / "skills"


def _discover_conforma_dirs() -> list[Path]:
    """Find all conforma* skill directories (includes the router)."""
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and p.name.startswith("conforma"))


def _strip_frontmatter_and_code_blocks(text: str) -> str:
    """Remove YAML frontmatter and fenced code blocks, keeping only prose."""
    text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.DOTALL)
    text = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.DOTALL)
    return text


def _collect_dirs(subdir: str) -> list[Path]:
    """Collect existing subdirectories of the given name across all conforma skills."""
    dirs = []
    for skill_dir in _discover_conforma_dirs():
        d = skill_dir / subdir
        if d.is_dir():
            dirs.append(d)
    return dirs


def _load_policy_rules() -> list[dict]:
    """Load policy rules from conforma-release-policy-rules.yaml."""
    entries = []
    for refs_dir in _collect_dirs("references"):
        rules_file = refs_dir / "conforma-release-policy-rules.yaml"
        if rules_file.is_file():
            data = yaml.safe_load(rules_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries.extend(data)
            elif isinstance(data, dict):
                for rule in data.get("rules", data.get("policies", [])):
                    entries.append(rule)
            break
    return entries


def _load_markdown_docs() -> list[dict]:
    """Load markdown documentation from references/ and docs/ across all conforma skills."""
    docs = []
    for subdir in ["references", "docs"]:
        for d in _collect_dirs(subdir):
            for md_file in sorted(d.glob("*.md")):
                content = md_file.read_text(encoding="utf-8")
                skill_name = d.parent.name
                docs.append(
                    {
                        "source": f"{skill_name}/{subdir}/{md_file.name}",
                        "title": md_file.stem.replace("-", " ").title(),
                        "content": content,
                    }
                )
    return docs


def _load_yaml_docs() -> list[dict]:
    """Load YAML reference files as searchable text (excluding the policy-rules file)."""
    docs = []
    for subdir in ["references", "docs"]:
        for d in _collect_dirs(subdir):
            for yaml_file in sorted(d.glob("*.yaml")):
                if yaml_file.name == "conforma-release-policy-rules.yaml":
                    continue
                content = yaml_file.read_text(encoding="utf-8")
                skill_name = d.parent.name
                docs.append(
                    {
                        "source": f"{skill_name}/{subdir}/{yaml_file.name}",
                        "title": yaml_file.stem.replace("-", " ").title(),
                        "content": content,
                    }
                )
    for subdir in ["references", "docs"]:
        for d in _collect_dirs(subdir):
            for yml_file in sorted(d.glob("*.yml")):
                content = yml_file.read_text(encoding="utf-8")
                skill_name = d.parent.name
                docs.append(
                    {
                        "source": f"{skill_name}/{subdir}/{yml_file.name}",
                        "title": yml_file.stem.replace("-", " ").title(),
                        "content": content,
                    }
                )
    return docs


def _load_skill_docs() -> list[dict]:
    """Load SKILL.md files from all conforma skills (prose only)."""
    docs = []
    for skill_dir in _discover_conforma_dirs():
        skill_md = skill_dir / "SKILL.md"
        if skill_md.is_file():
            raw = skill_md.read_text(encoding="utf-8")
            content = _strip_frontmatter_and_code_blocks(raw)
            docs.append(
                {
                    "source": f"{skill_dir.name}/SKILL.md",
                    "title": skill_dir.name.replace("-", " ").title(),
                    "content": content,
                }
            )
    return docs


def _score_match(text: str, query_terms: list[str]) -> int:
    """Score how well text matches query terms (higher = better)."""
    text_lower = text.lower()
    score = 0
    for term in query_terms:
        count = text_lower.count(term.lower())
        score += count * len(term)
    return score


def search(query: str, max_results: int = 10) -> list[dict]:
    """Search across all indexed documents."""
    query_terms = [t.strip() for t in query.lower().split() if len(t.strip()) >= 2]
    if not query_terms:
        return []

    results = []

    for rule in _load_policy_rules():
        searchable = " ".join(str(v) for v in rule.values() if v)
        score = _score_match(searchable, query_terms)
        if score > 0:
            results.append(
                {
                    "type": "policy_rule",
                    "score": score,
                    "code": rule.get("code", rule.get("name", "")),
                    "title": rule.get("title", rule.get("name", "")),
                    "description": rule.get("description", ""),
                    "solution": rule.get("solution", ""),
                    "source": "conforma-release-policy-rules.yaml",
                }
            )

    for doc in _load_markdown_docs():
        score = _score_match(doc["content"], query_terms)
        if score > 0:
            snippet = _extract_snippet(doc["content"], query_terms)
            results.append(
                {
                    "type": "documentation",
                    "score": score,
                    "title": doc["title"],
                    "snippet": snippet,
                    "source": doc["source"],
                }
            )

    for doc in _load_yaml_docs():
        score = _score_match(doc["content"], query_terms)
        if score > 0:
            snippet = _extract_snippet(doc["content"], query_terms)
            results.append(
                {
                    "type": "reference_data",
                    "score": score,
                    "title": doc["title"],
                    "snippet": snippet,
                    "source": doc["source"],
                }
            )

    for doc in _load_skill_docs():
        score = _score_match(doc["content"], query_terms)
        if score > 0:
            snippet = _extract_snippet(doc["content"], query_terms)
            results.append(
                {
                    "type": "skill_doc",
                    "score": score,
                    "title": doc["title"],
                    "snippet": snippet,
                    "source": doc["source"],
                }
            )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:max_results]


def _extract_snippet(content: str, query_terms: list[str]) -> str:
    """Extract a text snippet around the first matching term."""
    snippet_start = -1
    for term in query_terms:
        idx = content.lower().find(term.lower())
        if idx >= 0 and (snippet_start < 0 or idx < snippet_start):
            snippet_start = idx

    if snippet_start < 0:
        return ""
    start = max(0, snippet_start - 100)
    end = min(len(content), snippet_start + 300)
    return content[start:end].strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Search conforma documentation")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--max-results", type=int, default=10, help="Max results")
    parser.add_argument("--format", choices=["json", "text"], default="text", help="Output format")
    args = parser.parse_args()

    results = search(args.query, args.max_results)

    if not results:
        print(f"No results found for: {args.query}", file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(f"\n{len(results)} results for: {args.query}\n")
        for i, r in enumerate(results, 1):
            print(f"  {i}. [{r['type']}] {r.get('code', r.get('title', ''))}")
            if r.get("description"):
                print(f"     {r['description'][:200]}")
            if r.get("snippet"):
                print(f"     ...{r['snippet'][:200]}...")
            print(f"     Source: {r['source']}")
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
