"""conforma_slack_ops.py -- Conforma Slack thread discovery primitives (dual-mode: CLI + importable)."""

from __future__ import annotations

import argparse
import json
import re

import slack_ops

_VERSION_SUFFIX_RE = re.compile(r"-v\d+[-.\d\w]*$")


def _component_search_stems(component: str) -> list[str]:
    """Generate search stems for fuzzy component matching in Slack text.

    Given ``odh-ogx-core-v3-5-ea-1``, returns::

        ["odh-ogx-core-v3-5-ea-1", "odh-ogx-core", "ogx-core"]

    The full name is kept for exact matches, the version-stripped form is
    the most common way people reference components in Slack, and the
    prefix-stripped form catches shorthand references.
    """
    stems = [component]
    base = _VERSION_SUFFIX_RE.sub("", component)
    if base != component:
        stems.append(base)
    if base.startswith("odh-"):
        stems.append(base[4:])
    elif base.startswith("rhoai-"):
        stems.append(base[6:])
    return stems


def _thread_mentions_component(
    text: str,
    component_stems: list[str],
) -> bool:
    """Return True if *text* contains any of the component stems (case-insensitive)."""
    if not text:
        return False
    text_lower = text.lower()
    return any(stem.lower() in text_lower for stem in component_stems)


def prefetch_open_slack_threads(
    rules: list[str],
    rule_to_components: dict[str, list[str]] | None = None,
) -> dict[str, list[dict]]:
    """Search Slack for messages mentioning each violation rule (last 30 days).

    Per-rule search with suffix fallback (same pattern as MR search).
    Results are grouped by thread.  Returns ``rule -> list[thread_match]``.

    When *rule_to_components* is provided, results are filtered to only
    include threads whose message text mentions at least one affected
    component (using stemmed/fuzzy matching).  The ``text`` field is
    stripped from the output to keep the JSON compact.
    """
    rule_to_threads: dict[str, list[dict]] = {r: [] for r in rules}

    for rule in rules:
        seen: set[tuple[str, str]] = set()
        results = slack_ops.search_messages(query=rule, after_days=30)

        if ":" in rule:
            suffix = rule.rsplit(":", 1)[1]
            if suffix and suffix != rule:
                results.extend(slack_ops.search_messages(query=suffix, after_days=30))

        components = (rule_to_components or {}).get(rule, [])
        all_stems = []
        for comp in components:
            all_stems.extend(_component_search_stems(comp))

        for match in results:
            key = (match.get("channel_id", ""), match.get("thread_ts", ""))
            if key in seen:
                continue
            seen.add(key)

            if all_stems and not _thread_mentions_component(match.get("text", ""), all_stems):
                continue

            entry = {k: v for k, v in match.items() if k != "text"}
            rule_to_threads[rule].append(entry)

    return rule_to_threads


def main() -> None:
    parser = argparse.ArgumentParser(description="Conforma Slack thread discovery primitives")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search-threads")
    p_search.add_argument("--rules", required=True)
    p_search.add_argument("--components")

    args = parser.parse_args()

    if args.command == "search-threads":
        rules = [r.strip() for r in args.rules.split(",")]
        rule_to_components = None
        if args.components:
            components = [c.strip() for c in args.components.split(",")]
            rule_to_components = {rule: components for rule in rules}
        result = prefetch_open_slack_threads(rules, rule_to_components=rule_to_components)
    else:
        parser.print_help()
        raise SystemExit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
