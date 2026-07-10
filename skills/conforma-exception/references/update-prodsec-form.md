# Updating the ProdSec Exception Form Configuration

When the ProdSec team releases a new version of the Google Form, the form field
IDs may change. Follow these steps to refresh the configuration.

## When to Update

- ProdSec announces a new form URL
- The skill reports health check warnings about stale config (>180 days old)
- Pre-fill URLs produce empty or mismatched form fields
- You receive a new Google Form link from the ProdSec team

## Steps

### 1. Save the Form HTML

1. Open the new form URL in your browser (e.g., Chrome, Firefox)
2. Right-click anywhere on the page and select **View Page Source** (or press `Ctrl+U`)
3. Save the complete page source as an HTML file (e.g., `prodsec-form-2026.html`)

**Important**: Use "View Page Source", NOT "Inspect Element" or "Save Page As".
The source must contain the raw `FB_PUBLIC_LOAD_DATA_` JavaScript variable.

### 2. Run Discovery

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-exception/scripts/fill_prodsec_form.py" \
  --discover /path/to/prodsec-form-2026.html \
  --output skills/conforma-exception/scripts/prodsec_form_config.yaml
```

This parses the form HTML and generates a fresh `prodsec_form_config.yaml` with
all form field IDs, question text, types, and required flags.

### 3. Map Fields to Exception Data

Open `prodsec_form_config.yaml` and edit the `field_mapping` section. For each
entry, set the value to the internal data key that should fill that field:

```yaml
field_mapping:
  entry_1234567890: rule            # maps to --rule
  entry_9876543210: exception_scope  # maps to --exception-scope
  entry_5555555555: exception_risk   # maps to --exception-risk
  # ... etc
```

Available data keys:
- `rule` — Conforma policy rule code
- `components` — comma-separated component names
- `rhoai_version` — RHOAI version string
- `effective_until` — effectiveUntil date
- `exception_scope` — scope text
- `exception_risk` — risk text
- `exception_remediation` — remediation plan text
- `exception_impact` — impact if not approved text
- `rhoaieng_url` — RHOAIENG Jira ticket URL
- `vendor_tag` — vendor name (e.g., AMD, Intel)
- `summary_context` — brief description for titles
- `authorized_party` — senior manager accepting risk

Set fields to `null` if they should not be auto-filled.

### 4. Add the Form URL

Add the `form_url` key (or `form_id`) to the top of the config:

```yaml
form_url: "https://docs.google.com/forms/d/e/NEW_FORM_ID/viewform"
```

### 5. Validate

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-exception/scripts/fill_prodsec_form.py" --validate-config
```

This checks for staleness, unmapped required fields, and missing form URL.

### 6. Test

```bash
_R="$(grep '^aiops_infra_root:' ~/.conforma/.conforma-active/context.yaml | cut -d' ' -f2-)" && python3 "$_R/skills/conforma-exception/scripts/fill_prodsec_form.py" --generate \
  --rule hermetic_task.hermetic \
  --components "odh-mlflow-v3-3" \
  --rhoai-version rhoai-3.3 \
  --exception-scope "Test scope" \
  --dry-run
```

Open the generated URL in your browser and verify the form fields are populated.

### 7. Commit

Commit the updated `prodsec_form_config.yaml` to the repository.

## Health Check Warnings

The skill automatically checks the config at runtime and warns if:

- The config is older than 180 days
- Required form fields are not mapped
- No fields are mapped at all
- The config file is missing

These warnings appear in the script output and the agent will relay them to the user.
