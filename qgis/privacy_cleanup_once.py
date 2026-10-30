"""One-time, owner-authorized cleanup of explicitly backed-up public records."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote


REPO = 'fastnsa/FastNSA-QGIS'
BRANCH = 'maintenance/privacy-cleanup-20261030'
OLD_MAIN = 'f104b3b1e5584608734c7000731e560966cf07f0'
OLD_REPAIR = 'bceec32e784a11d0876c679b6fcbc413bef11123'
OLD_TAG = '3268150208426d5d29ecac9e316966cc8a6273e7'
RELEASE_ID = 428640761
RUNS = {40998489210: OLD_MAIN, 40999969656: OLD_MAIN, 41000468564: OLD_MAIN,
        41004332511: OLD_REPAIR, 41004332603: OLD_REPAIR}
ASSETS = {
    'fastnsa_qgis-0.1.1-linux-x86_64.zip': '777a71e32ca26a5e8071ce25dc7c83ee8ae25ee5c260e3921861723f2c6732a7',
    'fastnsa_qgis-0.1.1-linux-x86_64.zip.sha256': 'ad12943b1dd424f65694981920ce6383c72b877f521fc0fe42deb59b159de18e',
    'fastnsa_qgis-0.1.1-source-only.zip': '5b237ed49f8aa409b3d7f8ee5be1f245dadb356583448fb3265d28aacd8d3c22',
    'fastnsa_qgis-0.1.1-source-only.zip.sha256': '41936c4ee8d5f8a3a52b4eeaa63d34b2736ebc6196c063bad63bc208bc7ad669',
    'fastnsa_qgis-0.1.1-windows-amd64.zip': '4588da20c5611781915f55fbed60f35b45910d251853f0d2e5ef7256f1ecfff3',
    'fastnsa_qgis-0.1.1-windows-amd64.zip.sha256': '84ecd4d5294e8035755edbb24b04650cad6c96fa31e2a405525abd70f1888300',
}
WORKFLOW_PATHS = {'.github/workflows/multiplatform.yml', '.github/workflows/release.yml',
                  '.github/workflows/draft-release.yml'}


def api(path, method='GET', missing=False, fields=()):
    command = ['gh', 'api', '--method', method, f'repos/{REPO}/{path}', *fields]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        if missing and method == 'GET' and '(HTTP 404)' in result.stderr:
            return None
        raise RuntimeError(f'GitHub request failed: {method} {path}; refusing to continue')
    return json.loads(result.stdout) if result.stdout.strip() else None


def branch_sha(name):
    return api('git/ref/heads/' + quote(name, safe=''))['object']['sha']


def check_context():
    if (os.environ.get('GITHUB_REPOSITORY') != REPO
            or os.environ.get('GITHUB_REF') != 'refs/heads/' + BRANCH
            or os.environ.get('GITHUB_ACTOR') != 'fastnsa'
            or int(os.environ.get('GITHUB_RUN_ID', '0')) in RUNS):
        raise ValueError('Cleanup is restricted to the owner and dedicated maintenance branch')


def workflows():
    inventory = api('actions/workflows?per_page=100')
    if inventory['total_count'] != len(inventory['workflows']):
        raise ValueError('Workflow inventory is incomplete')
    selected = [row for row in inventory['workflows'] if row['path'] in WORKFLOW_PATHS]
    if {row['path'] for row in selected} != WORKFLOW_PATHS:
        raise ValueError('Expected workflow definitions were not found')
    return selected


def cleanup():
    expected = {'main': OLD_MAIN, 'release/qgis-0.1.1': OLD_MAIN,
                'release/update-v0.1.1-draft': OLD_REPAIR}
    for name, sha in expected.items():
        if branch_sha(name) != sha:
            raise ValueError('A source branch changed after backup; stop before deleting anything')
        if api('branches/' + quote(name, safe='')).get('protected'):
            raise ValueError('A source branch is protected; resolve before withdrawing the release')
    if api('git/ref/tags/v0.1.1')['object']['sha'] != OLD_TAG:
        raise ValueError('Original tag changed after backup')
    release = api(f'releases/{RELEASE_ID}', missing=True)
    if release is not None:
        expected_digests = {name: 'sha256:' + value for name, value in ASSETS.items()}
        if (release['tag_name'] != 'v0.1.1' or release.get('immutable') is not False
                or {a['name']: a.get('digest') for a in release['assets']} != expected_digests
                or hashlib.sha256(release.get('body', '').encode()).hexdigest()
                != 'be0c8da9ce5d34491b9fee6c4e5fea1053934a52c5b1a974cd2fd66602fdbcb0'):
            raise ValueError('Release differs from verified backup; refusing to withdraw it')
    for run_id, sha in RUNS.items():
        run = api(f'actions/runs/{run_id}', missing=True)
        if run is not None and (run['head_sha'] != sha or run['status'] != 'completed'):
            raise ValueError('Unexpected or still-running Actions record')
    selected = workflows()
    for workflow in selected:
        if workflow['state'] == 'active':
            api(f"actions/workflows/{workflow['id']}/disable", 'PUT')
    if release is not None:
        api(f'releases/{RELEASE_ID}', 'DELETE')
    if api(f'releases/{RELEASE_ID}', missing=True) is not None:
        raise ValueError('Release withdrawal did not complete')
    for run_id in RUNS:
        if api(f'actions/runs/{run_id}', missing=True) is not None:
            api(f'actions/runs/{run_id}', 'DELETE')
        if api(f'actions/runs/{run_id}', missing=True) is not None:
            raise ValueError('An authorized old run remains')
    return {'phase': 'cleanup', 'withdrawn_release': 'v0.1.1', 'deleted_run_ids': sorted(RUNS),
            'paused_workflows': [{k: w[k] for k in ('id', 'path', 'state')} for w in selected],
            'git_refs_changed': False, 'published_v0_1_0_untouched': True}


def resume(settings):
    expected = settings['expected_refs']
    if set(expected) != {'main', 'release/qgis-0.1.1', 'release/update-v0.1.1-draft'}:
        raise ValueError('Unexpected resume scope')
    if any(branch_sha(name) != sha for name, sha in expected.items()):
        raise ValueError('Clean history is not yet installed')
    if api('git/ref/tags/v0.1.1', missing=True) is not None:
        raise ValueError('Retired tag is still reachable')
    if api(f'releases/{RELEASE_ID}', missing=True) is not None:
        raise ValueError('Retired release is still present')
    if any(api(f'actions/runs/{run_id}', missing=True) is not None for run_id in RUNS):
        raise ValueError('Old Actions records remain')
    selected = workflows()
    for workflow in selected:
        api(f"actions/workflows/{workflow['id']}/enable", 'PUT')
    api('actions/workflows/multiplatform.yml/dispatches', 'POST', fields=('-f', 'ref=main'))
    return {'phase': 'resume', 'clean_refs_verified': expected,
            'restored_workflow_ids': [w['id'] for w in selected], 'main_checks_requested': True}


def finalize(settings):
    if branch_sha('main') != settings['expected_main_sha']:
        raise ValueError('Main changed before final verification')
    release = api('releases/tags/v0.1.2')
    expected = {f'fastnsa_qgis-0.1.2-{platform}.zip{suffix}'
                for platform in ('source-only', 'linux-x86_64', 'windows-amd64')
                for suffix in ('', '.sha256')}
    if (release.get('draft') is not True or release.get('tag_name') != 'v0.1.2'
            or len(release.get('assets', [])) != 6
            or {a['name'] for a in release['assets']} != expected):
        raise ValueError('Replacement draft is not ready; leave verification available')
    api('actions/workflows/privacy-cleanup.yml/disable', 'PUT')
    return {'phase': 'finalize', 'replacement_release': {
        key: release[key] for key in ('id', 'html_url', 'tag_name', 'draft')},
        'assets': [{key: asset[key] for key in ('name', 'size', 'digest')}
                   for asset in release['assets']], 'one_time_workflow_disabled': True}


def main():
    check_context()
    settings = json.loads(Path('qgis/privacy-cleanup-phase.json').read_text())
    if settings.get('phase') == 'cleanup' and settings.get('approved_log_deletion') is True:
        result = cleanup()
    elif settings.get('phase') == 'resume':
        result = resume(settings)
    elif settings.get('phase') == 'finalize':
        result = finalize(settings)
    else:
        raise ValueError('Explicit approved phase is required')
    Path('privacy-cleanup-receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if settings.get('phase') == 'finalize':
        print('::notice title=Verified replacement draft::' + json.dumps(result))


if __name__ == '__main__':
    main()
