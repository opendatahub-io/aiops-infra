## References (load these before executing)

- `skills/references/violation-aliases.yaml` (~50 lines)

---

# Violation History Workflow

## Violation History

Trace when a specific violation type last appeared (or disappeared) in the CSV git history for a release branch. Use this when the user asks questions like:
- "When was the last time we saw X violation?"
- "When did X violation disappear for release Y?"
- "Has X violation ever appeared for release Y?"
- "Show me the history of X violation"

### Violation Code Alias Table

Users refer to violations by natural-language phrases. **Always resolve the phrase to an exact `code` value before invoking the script.** Read [`skills/references/violation-catalog.yaml`](../../references/violation-catalog.yaml) and match the user's phrase against the `aliases` field of each violation entry.

If the user's phrase does not match any alias in the catalog, first run `analyze_csv_report.py` (see Workflow step 5) to list all violation codes in the current report, then pick the matching code.

### Extracting release from user input

- Pass the user's release text (e.g. `3.5-ea.1`, `rhoai-3.5-ea.1`, or a full GitHub URL) to Step 0 (`init_conforma_run.py`) as the query text. The release context pipeline resolves it automatically from `context.yaml`. Do NOT pass `--release` to the history script — it reads from `context.yaml`.
- If the user provides a GitHub URL containing a specific CSV path (e.g. `.../prod/future/build_type_latest/...`), pass `--csv-path` to Step 3 to override the auto-detected path.
- If no URL is provided and no `--csv-path` is given, the script auto-detects which CSV path exists on the branch (same fallback order as the fetch script).

### Steps

**Script path convention**: Every `python3` command below uses `$_R` to reference the aiops-infra repo root. The `$_R` variable is resolved from `context.yaml` at the start of each command. Do NOT remove or modify the `_R="..."` prefix — it ensures scripts are found regardless of the current working directory.

0. **Initialize conforma run (REQUIRED before any script)**: Run with Bash description: `"Initialize conforma run context for <extracted_release_text>"`:

```bash
_R="${AIOPS_INFRA_ROOT:-$(python3 -c 'from _repo_root import REPO_ROOT; print(REPO_ROOT)' 2>/dev/null || git rev-parse --show-toplevel 2>/dev/null)}"
python3 "$_R/scripts/init_conforma_run.py" "<extracted_release_text>" --set violation_code "<resolved_code>"
```

   This is the **only step where user input appears on the command line**. The `--set violation_code` stores the resolved violation code in context.yaml for use by Step 3. All subsequent steps use fixed commands.

1. **Prerequisites check**: Run `_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/scripts/verify_conforma_prerequisites.py" --format markdown`. If exit code is non-zero, render the markdown output directly and stop. Do not interpret or reformat.

2. **Resolve the violation code**: Map the user's phrase to an exact `--code` value using the `aliases` field in [`skills/references/violation-catalog.yaml`](../../references/violation-catalog.yaml).

3. **Run the history script**: The script reads `--release` (from `application.release` or `user_query`), `--code` (from `violation_code`), and `--environment` (from `environment`) from context.yaml automatically.

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-analyze/scripts/violation_history.py" --format text
```

   Use `--format text` when presenting results to the user. Use `--format json` when piping output to another tool or for programmatic consumption.

   Optional flags:
   - `--csv-path <path>` — override CSV path (use when the user provides a URL containing the path)
   - `--component <name>` — filter to a specific component
   - `--until-found` — stop after finding the first commit where the violation is present (fastest for "when last seen" queries)
   - `--max-commits <N>` — limit history depth (default: 100)

### Examples

All examples assume Step 0 has already been run with the user's query (release + violation code stored in `context.yaml`). Do NOT pass `--release` or `--code` — the script reads them from `context.yaml` automatically.

**"When was the last time we saw permissive prefetch mode for 3.5-ea.1?"**

Step 0: `python3 "$_R/scripts/init_conforma_run.py" "rhoai-3.5-ea.1" --set violation_code "prefetch_dependencies.mode_not_permissive"`

Step 3:
```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-analyze/scripts/violation_history.py" --format text
```

**"When did rpm signature violations disappear for rhoai-3.4?"** (with `--until-found` for speed)

Step 0: `python3 "$_R/scripts/init_conforma_run.py" "rhoai-3.4" --set violation_code "rpm_signature.allowed"`

Step 3:
```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-analyze/scripts/violation_history.py" --until-found --format text
```

**From a URL with a specific CSV path:**

Given URL `https://github.com/red-hat-data-services/conforma-reporter/blob/rhoai-3.5-ea.1/prod/future/build_type_latest/conforma-violations-report.csv`:

Step 0: `python3 "$_R/scripts/init_conforma_run.py" "rhoai-3.5-ea.1" --set violation_code "prefetch_dependencies.mode_not_permissive"`

Step 3 (with `--csv-path` override for the non-standard CSV location):
```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-analyze/scripts/violation_history.py" \
  --csv-path prod/future/build_type_latest/conforma-violations-report.csv \
  --format text
```

### Interpreting Output

The text output includes:

| Field | Meaning |
|---|---|
| **STATUS** | Whether the violation is present in the latest (HEAD) report |
| **Last seen** | Most recent commit date where the violation was present |
| **Disappeared** | First commit after "last seen" where the violation is absent |
| **First seen** | Oldest commit in checked history where the violation appeared |
| **TIMELINE** | Visual commit-by-commit view: `██` = present, `··` = absent |

