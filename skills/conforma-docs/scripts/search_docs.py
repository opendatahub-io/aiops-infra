#!/usr/bin/env python3
"""Full-text search across conforma documentation and reference files.

Indexes YAML reference data and markdown documentation, then performs
keyword search with ranked results.

Usage:
    python3 scripts/search_docs.py --query "hermetic build"
    python3 scripts/search_docs.py --query "rpm signing key" --format json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
REFERENCES_DIR = SKILL_DIR / "references"
EXCEPTION_REFS_DIR = SKILL_DIR.parent / "conforma-exception" / "references"


def _load_policy_rules() -> list[dict]:
    """Load policy rules from reference YAML files."""
    entries = []
    for refs_dir in [REFERENCES_DIR, EXCEPTION_REFS_DIR]:
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
    """Load markdown documentation files."""
    docs = []
    for refs_dir in [REFERENCES_DIR, EXCEPTION_REFS_DIR]:
        if not refs_dir.is_dir():
            continue
        for md_file in refs_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            docs.append({
                "source": str(md_file.relative_to(SKILL_DIR.parent)),
                "title": md_file.stem.replace("-", " ").title(),
                "content": content,
            })
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
            results.append({
                "type": "policy_rule",
                "score": score,
                "code": rule.get("code", rule.get("name", "")),
                "title": rule.get("title", rule.get("name", "")),
                "description": rule.get("description", ""),
                "solution": rule.get("solution", ""),
                "source": "conforma-release-policy-rules.yaml",
            })

    for doc in _load_markdown_docs():
        score = _score_match(doc["content"], query_terms)
        if score > 0:
            snippet_start = -1
            for term in query_terms:
                idx = doc["content"].lower().find(term.lower())
                if idx >= 0 and (snippet_start < 0 or idx < snippet_start):
                    snippet_start = idx

            snippet = ""
            if snippet_start >= 0:
                start = max(0, snippet_start - 100)
                end = min(len(doc["content"]), snippet_start + 300)
                snippet = doc["content"][start:end].strip()

            results.append({
                "type": "documentation",
                "score": score,
                "title": doc["title"],
                "snippet": snippet,
                "source": doc["source"],
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:max_results]


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
