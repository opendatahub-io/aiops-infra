"""Exercise the internal OS contract across schema, generation and shell consumers."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts'
BASH = shutil.which('bash')
SCHEMA = json.loads((ROOT / 'schemas/component_onboarding_details.schema.json').read_text())


def shell(name, *args):
    return subprocess.run([BASH, str(SCRIPTS / name), *args], capture_output=True, text=True)


def payload(product='RHOAI'):
    fields = dict(product_context=product, component_name='odh-example',
                  repo_url='https://github.com/example/component', repo_branch='rhoai-3.7',
                  context_path='./', dockerfile_path='Dockerfile.konflux', is_operator=False)
    if product == 'RHOAI':
        fields.update(architectures=['x86_64'], target_rhoai_version='3.7',
                      long_description='Example component', short_description='Example',
                      release_category='Generally Available')
    else:
        fields['build_type'] = 'CI'
    return {'inputs': fields}


@pytest.mark.parametrize('os', [None, 'rhel9', 'rhel10'])
def test_schema_accepts_legacy_and_supported_os(os):
    data = payload()
    if os is not None:
        data['inputs']['base_rhel_version'] = os
    Draft202012Validator(SCHEMA).validate(data)


@pytest.mark.parametrize('product,os', [('RHOAI', 'rhel8'), ('RHOAI', None),
                                       ('ODH', 'rhel9'), ('ODH', 'rhel10')])
def test_schema_rejects_invalid_or_odh_os(product, os):
    data = payload(product)
    data['inputs']['base_rhel_version'] = os
    assert list(Draft202012Validator(SCHEMA).iter_errors(data))


@pytest.mark.parametrize('os', ['rhel9', 'rhel10'])
def test_schema_rejects_os_in_component_identity(os):
    data = payload()
    data['inputs']['component_name'] += '-' + os
    assert list(Draft202012Validator(SCHEMA).iter_errors(data))


@pytest.mark.parametrize('os', [None, 'rhel9', 'rhel10'])
@pytest.mark.parametrize('category,line', [('Generally Available', 'rhoai'),
                                          ('Tech Preview', 'rhoai'),
                                          ('Beta', 'rhoai-beta'), ('DevPreview', 'rhoai-beta')])
def test_helpers_share_suffix_without_changing_version_identity(os, category, line):
    args = [] if os is None else ['--base-rhel-version', os]
    expected = os or 'rhel9'
    quay = shell('derive_quay_vars.sh', '--product-context', 'RHOAI',
                 '--component-name', 'odh-example', *args)
    version = shell('parse_rhoai_version.sh', '--version', '3.7', '--component',
                    'odh-example', '--release-category', category, *args)
    assert quay.returncode == version.returncode == 0, quay.stderr + version.stderr
    assert f'QUAY_REPO_URI=quay.io/rhoai/odh-example-{expected}\n' in quay.stdout
    assert f'REPOSITORY_NAME={line}/odh-example-{expected}\n' in version.stdout
    for output in [quay.stdout, version.stdout]:
        assert f'BASE_RHEL_VERSION={expected}\n' in output
        assert f'IMAGE_REPO_SUFFIX=-{expected}\n' in output
    assert 'VERSION_VAR=v3-7\n' in version.stdout
    assert 'BRANCH_NAME=rhoai-3.7\n' in version.stdout


def test_odh_stays_unsuffixed_and_rejects_explicit_os():
    args = ['--product-context', 'ODH', '--component-name', 'odh-example']
    result = shell('derive_quay_vars.sh', *args)
    assert result.returncode == 0, result.stderr
    assert 'QUAY_REPO_URI=quay.io/opendatahub/odh-example\n' in result.stdout
    assert shell('derive_quay_vars.sh', *args, '--base-rhel-version', 'rhel9').returncode != 0


@pytest.mark.parametrize('script,args', [
    ('derive_quay_vars.sh', ['--product-context', 'RHOAI', '--component-name', 'odh-example']),
    ('parse_rhoai_version.sh', ['--version', '3.7'])])
@pytest.mark.parametrize('os', ['', 'rhel8', '10'])
def test_helpers_fail_on_invalid_os(script, args, os):
    assert shell(script, *args, '--base-rhel-version', os).returncode != 0


@pytest.mark.parametrize('product,os', [('RHOAI', None), ('RHOAI', 'rhel9'),
                                      ('RHOAI', 'rhel10'), ('ODH', None)])
def test_generator_round_trip(tmp_path, product, os):
    out = tmp_path / 'component_onboarding_details.yaml'
    args = []
    for key, value in payload(product)['inputs'].items():
        if key in ['architectures', 'is_operator']:
            continue
        args.extend(['--' + key.replace('_', '-'), str(value)])
    if os is not None:
        args.extend(['--base-rhel-version', os])
    result = subprocess.run([sys.executable, str(SCRIPTS / 'generate_onboarding_yaml.py'),
                             '--output', str(out), '--slack-team-handle', 'ai-core-platform',
                             *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = yaml.safe_load(out.read_text())
    Draft202012Validator(SCHEMA).validate(data)
    if product == 'RHOAI':
        assert data['inputs']['base_rhel_version'] == (os or 'rhel9')
    else:
        assert 'base_rhel_version' not in data['inputs']


@pytest.mark.parametrize('os', [None, 'rhel9', 'rhel10'])
def test_component_parser_persists_resolved_contract(tmp_path, os):
    data = payload()
    if os is not None:
        data['inputs']['base_rhel_version'] = os
    (tmp_path / 'component_onboarding_details.yaml').write_text(yaml.safe_dump(data))
    state = tmp_path / 'pipeline_state.json'
    state.write_text('{}')
    result = shell('parse_component_details.sh', '--workdir', str(tmp_path),
                   '--jira-id', 'RHAI-1', '--scripts-dir', str(SCRIPTS),
                   '--pipeline-state', str(state))
    assert result.returncode == 0, result.stderr
    expected = os or 'rhel9'
    assert f'BASE_RHEL_VERSION={expected}\n' in result.stdout
    assert f'QUAY_REPO_URI=quay.io/rhoai/odh-example-{expected}\n' in result.stdout

    saved = json.loads(state.read_text())
    assert saved['base_rhel_version'] == expected
    assert saved['image_repo_suffix'] == '-' + expected
    assert saved['quay_repo_uri'] == 'quay.io/rhoai/odh-example-' + expected


@pytest.mark.parametrize('extra', [
    ['--base-rhel-version', 'rhel9'],
    ['--base-rhel-version', 'rhel10'],
    ['--base-rhel-version', 'rhel8'],
    ['--component-name', 'odh-example-rhel9'],
    ['--component-name', 'odh-example-rhel10'],
])
def test_generator_rejects_invalid_odh_contract_before_writing(tmp_path, extra):
    out = tmp_path / 'result.yaml'
    args = []
    for key, value in payload('ODH')['inputs'].items():
        if key != 'is_operator':
            args.extend(['--' + key.replace('_', '-'), str(value)])
    result = subprocess.run([sys.executable, str(SCRIPTS / 'generate_onboarding_yaml.py'),
                             '--output', str(out), '--slack-team-handle', 'ai-core-platform',
                             *args, *extra], capture_output=True, text=True)
    assert result.returncode != 0
    assert not out.exists()


@pytest.mark.parametrize('product,os', [('RHOAI', 'rhel8'), ('ODH', 'rhel10')])
def test_component_parser_failure_does_not_mutate_state(tmp_path, product, os):
    data = payload(product)
    data['inputs']['base_rhel_version'] = os
    (tmp_path / 'component_onboarding_details.yaml').write_text(yaml.safe_dump(data))
    state = tmp_path / 'state.json'
    state.write_text('{}')
    result = shell('parse_component_details.sh', '--workdir', str(tmp_path),
                   '--jira-id', 'RHAI-1', '--scripts-dir', str(SCRIPTS),
                   '--pipeline-state', str(state))
    assert result.returncode != 0
    assert state.read_text() == '{}'


@pytest.mark.parametrize('os_line', [
    '  "base_rhel_version": "rhel10" # selected by policy',
    "  'base_rhel_version': 'rhel10'",
    '  base_rhel_version: >-\n    rhel10',
])
def test_component_parser_reads_yaml_os_semantics(tmp_path, os_line):
    data = payload()
    text = yaml.safe_dump(data) + os_line + '\n'
    Draft202012Validator(SCHEMA).validate(yaml.safe_load(text))
    (tmp_path / 'component_onboarding_details.yaml').write_text(text)
    result = shell('parse_component_details.sh', '--workdir', str(tmp_path),
                   '--jira-id', 'RHAI-1', '--scripts-dir', str(SCRIPTS))
    assert result.returncode == 0, result.stderr
    assert 'BASE_RHEL_VERSION=rhel10\n' in result.stdout
    assert 'QUAY_REPO_URI=quay.io/rhoai/odh-example-rhel10\n' in result.stdout


@pytest.mark.parametrize('product,os', [('RHOAI', None), ('RHOAI', 'rhel10'), ('ODH', None)])
def test_parser_ignores_stale_environment_and_quotes_shell_values(tmp_path, product, os):
    import os as environ_module

    data = payload(product)
    marker = tmp_path / 'must-not-exist'
    data['inputs']['repo_branch'] = f'$(touch {marker}); echo injected'
    if os is not None:
        data['inputs']['base_rhel_version'] = os
    source = tmp_path / 'component_onboarding_details.yaml'
    source.write_text(yaml.safe_dump(data, default_style='"'))
    state = tmp_path / 'state.json'
    state.write_text('{}')
    env = dict(environ_module.environ, BASE_RHEL_VERSION='rhel10', IMAGE_REPO_SUFFIX='-rhel10')
    result = subprocess.run([BASH, str(SCRIPTS / 'parse_component_details.sh'),
                             '--workdir', str(tmp_path), '--jira-id', 'RHAI-1',
                             '--scripts-dir', str(SCRIPTS), '--pipeline-state', str(state)],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    saved = json.loads(state.read_text())
    expected = (os or 'rhel9') if product == 'RHOAI' else ''
    assert saved['base_rhel_version'] == expected
    expected_uri = ('quay.io/rhoai/odh-example-' + expected if product == 'RHOAI'
                    else 'quay.io/opendatahub/odh-example')
    assert saved['quay_repo_uri'] == expected_uri


@pytest.mark.parametrize('value', ['', None, 10, ['rhel10'], 'rhel10; echo injected'])
def test_invalid_os_never_changes_existing_state(tmp_path, value):
    data = payload()
    data['inputs']['base_rhel_version'] = value
    (tmp_path / 'component_onboarding_details.yaml').write_text(yaml.safe_dump(data))
    state = tmp_path / 'state.json'
    original = '{"base_rhel_version":"rhel9","quay_repo_uri":"existing"}'
    state.write_text(original)
    result = shell('parse_component_details.sh', '--workdir', str(tmp_path),
                   '--jira-id', 'RHAI-1', '--scripts-dir', str(SCRIPTS),
                   '--pipeline-state', str(state))
    assert result.returncode != 0
    assert state.read_text() == original


@pytest.mark.parametrize('version,identity,branch', [
    ('3.7-ea-2', 'v3-7-ea-2', 'rhoai-3.7-ea.2'),
    ('4.0', 'v4-0', 'rhoai-4.0'),
])
def test_non_ga_version_identities_are_os_free(version, identity, branch):
    result = shell('parse_rhoai_version.sh', '--version', version,
                   '--component', 'odh-example', '--base-rhel-version', 'rhel10')
    assert result.returncode == 0, result.stderr
    assert f'VERSION_VAR={identity}\n' in result.stdout
    assert f'BRANCH_NAME={branch}\n' in result.stdout
    assert 'REPOSITORY_NAME=rhoai/odh-example-rhel10\n' in result.stdout
