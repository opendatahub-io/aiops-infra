#!/usr/bin/env python3
"""Generate a Cursor Canvas report from assessed expired exceptions.

Reads the assessed-exceptions.yaml (output of manage_exceptions.py --assess-expired)
and produces a .canvas.tsx file with all data embedded for interactive viewing.

Usage:
    python3 scripts/generate_report.py \\
      --assessed-input /tmp/assessed-exceptions.yaml \\
      --output ~/.cursor/projects/<workspace>/canvases/conforma-expired-exceptions.canvas.tsx
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

import yaml


CONFORMA_REPORTER_REPO = "red-hat-data-services/conforma-reporter"


def _load_assessment(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_report_url(release: str, source_path: str = "") -> str:
    csv_path = source_path or "prod/release_day/conforma-violations-report.csv"
    return f"https://github.com/{CONFORMA_REPORTER_REPO}/blob/{release}/{csv_path}"


def _shorten_rule(rule: str, max_len: int = 35) -> str:
    if len(rule) <= max_len:
        return rule
    return rule[:max_len - 3] + "..."


def _exception_label(exc: dict) -> str:
    """Derive a human-readable label from comment headers or rule."""
    headers = exc.get("comment_header_lines", [])
    for line in headers:
        cleaned = line.lstrip("# ").strip()
        if cleaned and not cleaned.startswith("http") and not cleaned.startswith("impacted") and not cleaned.startswith("dates "):
            if len(cleaned) > 40:
                cleaned = cleaned[:37] + "..."
            return cleaned
    rule = exc.get("rule", "")
    base = rule.split(":")[0] if ":" in rule else rule
    return base


def _summarize_components(components: list[str]) -> str:
    """Summarize a component list for the matrix cell."""
    if not components:
        return "[]"
    if len(components) <= 3:
        return json.dumps(components)
    return json.dumps([f"{len(components)} components"])


def _reference_label(exc: dict) -> tuple[str, str]:
    """Extract a short label and URL for the reference field."""
    ref = exc.get("reference", "")
    if not ref:
        return ("--", "")

    if "atlassian.net/browse/" in ref:
        key = ref.split("/browse/")[-1]
        return (key, ref)
    if "issues.redhat.com/browse/" in ref:
        key = ref.split("/browse/")[-1]
        return (key, ref)
    if "github.com/" in ref:
        parts = ref.rstrip("/").split("/")
        if len(parts) >= 2:
            return (f"{parts[-2]}#{parts[-1]}", ref)
        return (ref.split("github.com/")[-1][:30], ref)

    return (ref[:30], ref)


def _policy_label(file_path: str) -> str:
    """Derive a short label from the policy file path (e.g. 'registry' or 'fbc')."""
    name = file_path.rsplit("/", 1)[-1] if "/" in file_path else file_path
    if name.startswith("fbc-"):
        return "fbc"
    if name.startswith("registry-"):
        return "registry"
    return name.replace(".yaml", "")


def generate_canvas(data: dict) -> str:
    """Generate the full .canvas.tsx source from assessment data."""
    releases = data.get("releases_checked", [])
    not_checked = data.get("releases_not_checked", [])
    exceptions = data.get("assessed_exceptions", [])
    generated_at = data.get("generated_at", "unknown")

    report_urls: dict[str, str] = {}
    for exc in exceptions:
        for rel, url in exc.get("evidence", {}).get("report_urls", {}).items():
            if rel not in report_urls and url:
                report_urls[rel] = url
    for rel in releases:
        if rel not in report_urls:
            report_urls[rel] = _build_report_url(rel)

    exc_data_lines = []
    for exc in exceptions:
        label = _exception_label(exc)
        rule = exc.get("rule", "")
        effective_until = exc.get("effective_until", "")
        expired_str = effective_until[:10] if effective_until else "--"
        days_ago = exc.get("expired_days_ago", 0)
        ref_label, ref_url = _reference_label(exc)
        classification = exc.get("classification", "unknown")
        action = exc.get("recommended_action", "review")
        is_legacy = exc.get("is_legacy", False)
        policy = _policy_label(exc.get("file", ""))

        evidence = exc.get("evidence", {})
        still_violating = evidence.get("still_violating_releases", [])
        still_components = evidence.get("still_violating_components", [])
        resolved_in = evidence.get("resolved_in_releases", [])

        components_by_release: dict[str, list[str]] = {}
        if still_components and still_violating:
            for comp in still_components:
                for rel in still_violating:
                    version_suffix = rel.replace("rhoai-", "v").replace(".", "-").replace("-ea-", "-ea-")
                    if version_suffix in comp or rel in comp:
                        components_by_release.setdefault(rel, []).append(comp)
                        break
                else:
                    for rel in still_violating:
                        components_by_release.setdefault(rel, [])

        exc_data_lines.append(
            "  {\n"
            f'    rule: {json.dumps(rule)},\n'
            f'    label: {json.dumps(label)},\n'
            f'    expired: {json.dumps(expired_str)},\n'
            f'    daysAgo: {days_ago},\n'
            f'    reference: {json.dumps(ref_label)},\n'
            f'    referenceUrl: {json.dumps(ref_url)},\n'
            f'    classification: {json.dumps(classification)},\n'
            f'    action: {json.dumps(action)},\n'
            f'    isLegacy: {"true" if is_legacy else "false"},\n'
            f'    policy: {json.dumps(policy)},\n'
            f'    components: {json.dumps(components_by_release)},\n'
            f'    resolvedIn: {json.dumps(resolved_in)},\n'
            "  }"
        )

    exc_array = ",\n".join(exc_data_lines)

    total = len(exceptions)
    still_needed = sum(1 for e in exceptions if e.get("classification") == "still_needed")
    no_longer = sum(1 for e in exceptions if e.get("classification") == "no_longer_needed")
    partial = sum(1 for e in exceptions if e.get("classification") == "partially_needed")
    need_modernize = sum(1 for e in exceptions if "modernize" in e.get("recommended_action", ""))

    action_pill_map = {
        "extend": {"tone": "info", "text": "extend", "detail": "extend effectiveUntil date"},
        "extend_and_modernize": {"tone": "warning", "text": "extend + modernize", "detail": "remove legacy block, create new per-componentName exceptions"},
        "narrow_and_extend": {"tone": "warning", "text": "narrow + extend", "detail": "reduce scope to still-violating releases, extend date"},
        "modernize_and_narrow": {"tone": "warning", "text": "modernize + narrow", "detail": "remove legacy block, create per-componentName exceptions for remaining violations only"},
        "remove": {"tone": "success", "text": "remove", "detail": "violation resolved, delete exception block"},
    }

    canvas = textwrap.dedent(f'''\
    import {{
      Stack, Row, Grid, H1, H2, Text, Code, Link, Table, Stat, Pill,
      Callout, Divider, CollapsibleSection, useHostTheme,
    }} from "cursor/canvas";

    const RELEASES = {json.dumps(releases)};
    const REPORT_URLS: Record<string, string> = {json.dumps(report_urls, indent=2)};
    const NOT_CHECKED = {json.dumps(not_checked, indent=2)};

    interface ExceptionData {{
      rule: string;
      label: string;
      expired: string;
      daysAgo: number;
      reference: string;
      referenceUrl: string;
      classification: string;
      action: string;
      isLegacy: boolean;
      policy: string;
      components: Record<string, string[]>;
      resolvedIn: string[];
    }}

    const EXCEPTIONS: ExceptionData[] = [
    {exc_array}
    ];

    const ACTION_PILLS: Record<string, {{ tone: "success" | "warning" | "info" | "neutral"; text: string; detail: string }}> = {json.dumps(action_pill_map)};

    function CellContent({{ comps, resolved }}: {{ comps: string[] | undefined; resolved: boolean }}) {{
      const theme = useHostTheme();
      if (resolved) return <Text size="small" style={{{{ color: theme.palette.green }}}}>resolved</Text>;
      if (!comps || comps.length === 0) return <Text size="small" tone="tertiary">--</Text>;
      const count = comps.length;
      return (
        <Stack gap={{2}}>
          <Text size="small" weight="semibold" style={{{{ color: theme.palette.red }}}}>
            {{count}} component{{count > 1 ? "s" : ""}}
          </Text>
          {{comps.length <= 3 && comps.map((c, i) => <Text key={{i}} size="small" tone="tertiary">{{c}}</Text>)}}
        </Stack>
      );
    }}

    export default function ConformaExpiredExceptions() {{
      const theme = useHostTheme();
      const relHeaders = RELEASES.map(r => r.replace("rhoai-", ""));

      const matrixRows = EXCEPTIONS.map(exc => {{
        const relCells = RELEASES.map(rel => (
          <CellContent comps={{exc.components[rel]}} resolved={{exc.resolvedIn.includes(rel)}} />
        ));
        const pill = ACTION_PILLS[exc.action] || {{ tone: "neutral" as const, text: exc.action, detail: "" }};
        return [
          <Stack gap={{2}}>
            <Row gap={{4}} align="center">
              <Text size="small" weight="semibold">{{exc.label}}</Text>
              {{exc.policy === "fbc" && <Pill tone="neutral" size="sm">fbc</Pill>}}
            </Row>
            <Code>{{exc.rule.length > 35 ? exc.rule.slice(0, 32) + "..." : exc.rule}}</Code>
          </Stack>,
          <Stack gap={{0}}>
            <Text size="small">{{exc.expired}}</Text>
            <Text size="small" tone="tertiary">{{exc.daysAgo}}d ago</Text>
          </Stack>,
          exc.referenceUrl
            ? <Link href={{exc.referenceUrl}}>{{exc.reference}}</Link>
            : <Text size="small">{{exc.reference}}</Text>,
          ...relCells,
          <Stack gap={{2}} align="center">
            <Pill tone={{pill.tone}} size="sm">{{pill.text}}</Pill>
            {{pill.detail && <Text size="xsmall" tone="tertiary">{{pill.detail}}</Text>}}
          </Stack>,
        ];
      }});

      return (
        <Stack gap={{20}}>
          <Stack gap={{4}}>
            <H1>RHOAI Conforma Expired Exceptions</H1>
            <Text tone="secondary">
              Assessment as of {generated_at[:10]}. Source: registry-rhoai-prod.yaml in konflux-release-data.
            </Text>
          </Stack>

          <Grid columns={{4}} gap={{12}}>
            <Stat value={{{total}}} label="Expired" tone="danger" />
            <Stat value={{{still_needed}}} label="Still needed" tone="warning" />
            <Stat value={{{no_longer}}} label="Can remove" tone="success" />
            <Stat value={{{need_modernize}}} label="Need modernizing" tone="info" />
          </Grid>

          <Stack gap={{8}}>
            <H2>Exception / Release Matrix</H2>
            <Text size="small" tone="secondary">
              Red = violation active. Green = resolved. Click "report" under each release to view the violation CSV.
            </Text>
          </Stack>

          <Table
            headers={{[
              "Exception", "Expired", "Ref",
              ...relHeaders.map((h, i) => {{
                const url = REPORT_URLS[RELEASES[i]];
                return (
                  <Stack gap={{2}} align="center">
                    <Text size="small" weight="semibold">{{h}}</Text>
                    {{url && <Link href={{url}}><Text size="xsmall" tone="tertiary">report</Text></Link>}}
                  </Stack>
                );
              }}),
              "Action",
            ]}}
            rows={{matrixRows}}
            columnAlign={{["left", "left", "left", ...RELEASES.map(() => "center" as const), "center"]}}
            striped
            stickyHeader
          />
    ''')

    if not_checked:
        canvas += textwrap.dedent(f'''\

          <Callout tone="warning" title="Not checked">
            <Text size="small">
              {". ".join(f"{nc['release']}: {nc['error']}" for nc in not_checked)}.
            </Text>
          </Callout>
    ''')

    canvas += textwrap.dedent(f'''\

          <Stack gap={{8}}>
            <H2>Detailed component lists</H2>
            <Text size="small" tone="secondary">Expand each exception for full per-release breakdown.</Text>
          </Stack>

          {{EXCEPTIONS.map((exc, idx) => (
            <CollapsibleSection
              key={{idx}}
              label={{`${{exc.label}} -- ${{exc.rule}}`}}
              trailing={{
                <Row gap={{6}} align="center">
                  <Text size="small" tone="tertiary">expired {{exc.expired}}</Text>
                  {{(() => {{ const p = ACTION_PILLS[exc.action] || {{ tone: "neutral" as const, text: exc.action, detail: "" }}; return <Stack gap={{2}} align="center"><Pill tone={{p.tone}} size="sm">{{p.text}}</Pill>{{p.detail && <Text size="xsmall" tone="tertiary">{{p.detail}}</Text>}}</Stack>; }})()}}
                </Row>
              }}
            >
              <Stack gap={{8}}>
                <Row gap={{16}} align="center">
                  {{exc.referenceUrl && <Text size="small">Reference: <Link href={{exc.referenceUrl}}>{{exc.reference}}</Link></Text>}}
                  {{exc.resolvedIn.length > 0 && (
                    <Text size="small" style={{{{ color: theme.palette.green }}}}>
                      Resolved in: {{exc.resolvedIn.join(", ")}}
                    </Text>
                  )}}
                  {{exc.isLegacy && <Pill tone="info" size="sm">legacy</Pill>}}
                  {{exc.policy === "fbc" && <Pill tone="neutral" size="sm">fbc policy</Pill>}}
                </Row>
                <Table
                  headers={{["Release", "Status", "Components"]}}
                  rows={{RELEASES.map(rel => {{
                    const comps = exc.components[rel];
                    const resolved = exc.resolvedIn.includes(rel);
                    const url = REPORT_URLS[rel];
                    const relCell = url ? <Link href={{url}}>{{rel}}</Link> : rel;
                    if (resolved) return [relCell, <Pill tone="success" size="sm">resolved</Pill>, "--"];
                    if (!comps || comps.length === 0) return [relCell, <Text tone="tertiary">--</Text>, "--"];
                    return [
                      relCell,
                      <Pill tone="warning" size="sm">violating</Pill>,
                      <Stack gap={{2}}>{{comps.map((c, i) => <Text key={{i}} size="small"><Code>{{c}}</Code></Text>)}}</Stack>,
                    ];
                  }})}}
                  striped
                />
              </Stack>
            </CollapsibleSection>
          ))}}

          <Divider />
          <Text size="small" tone="quaternary">
            Generated by conforma-analyze + conforma-exception skills.
          </Text>
        </Stack>
      );
    }}
    ''')

    return canvas


def build_action_plan(data: dict) -> dict:
    """Build a machine-readable action plan from the assessment data.

    Returns a JSON-serializable dict with structured action items the
    agent can iterate over to create MRs.
    """
    exceptions = data.get("assessed_exceptions", [])
    generated_at = data.get("generated_at", "unknown")

    ACTION_ORDER = {"remove": 0, "extend": 1, "narrow_and_extend": 2,
                    "extend_and_modernize": 3, "modernize_and_narrow": 4}

    actions = []
    for exc in exceptions:
        action = exc.get("recommended_action", "review")
        evidence = exc.get("evidence", {})
        still_violating = evidence.get("still_violating_releases", [])
        still_components = evidence.get("still_violating_components", [])

        versions: dict[str, list[str]] = {}
        for comp in still_components:
            for rel in still_violating:
                suffix = rel.replace("rhoai-", "v").replace(".", "-")
                if suffix in comp or rel in comp:
                    versions.setdefault(rel, []).append(comp)
                    break
            else:
                for rel in still_violating:
                    versions.setdefault(rel, [])

        actions.append({
            "rule": exc.get("rule", ""),
            "label": _exception_label(exc),
            "action": action,
            "classification": exc.get("classification", "unknown"),
            "policy_file": exc.get("file", ""),
            "old_effective_until": exc.get("effective_until", ""),
            "is_legacy": exc.get("is_legacy", False),
            "reference": exc.get("reference", ""),
            "versions": versions,
            "resolved_in": evidence.get("resolved_in_releases", []),
        })

    actions.sort(key=lambda a: ACTION_ORDER.get(a["action"], 99))

    return {
        "generated_at": generated_at,
        "total_actions": len(actions),
        "actions": actions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Cursor Canvas report from assessed exceptions"
    )
    parser.add_argument(
        "--assessed-input",
        required=True,
        help="Path to assessed-exceptions.yaml",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for the .canvas.tsx file",
    )
    parser.add_argument(
        "--action-plan-output",
        default=None,
        help="Write a JSON action plan for the agent to iterate over",
    )
    args = parser.parse_args()

    input_path = Path(args.assessed_input)
    if not input_path.is_file():
        print(f"Error: assessment file not found: {input_path}", file=sys.stderr)
        return 1

    data = _load_assessment(input_path)
    canvas_source = generate_canvas(data)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(canvas_source, encoding="utf-8")

    exc_count = len(data.get("assessed_exceptions", []))
    rel_count = len(data.get("releases_checked", []))
    print(
        f"Generated canvas: {exc_count} exceptions x {rel_count} releases -> {output_path}",
        file=sys.stderr,
    )

    if args.action_plan_output:
        plan = build_action_plan(data)
        plan_path = Path(args.action_plan_output)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        print(
            f"Action plan: {plan['total_actions']} actions -> {plan_path}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
