"""Deploy only the existing ReiBot app; keep secrets out of arguments and logs."""
import copy
import json
import os
import pty
import re
import select
import subprocess
import tempfile
import time
from pathlib import Path

API = '2025-07-01'
SUBSCRIPTION = 'de7b33ea-f724-4642-abfc-a17d47306ad2'
RESOURCE = f'/subscriptions/{SUBSCRIPTION}/resourceGroups/ReiBot/providers/Microsoft.App/containerApps/reibot'
BASE = 'https://management.azure.com' + RESOURCE
SECRET_ENV = {'DISCORD_TOKEN': 'discord', 'YT_COOKIES': 'youtube', 'BILIBILI_COOKIES': 'bilibili'}


def rest(method, suffix='', body=None):
    args = ['az', 'rest', '--method', method, '--url', BASE + suffix + '?api-version=' + API,
            '--only-show-errors', '--output', 'json']
    with tempfile.TemporaryDirectory() as directory:
        if body is not None:
            path = Path(directory) / 'request.json'
            path.write_text(json.dumps(body)); path.chmod(0o600)
            args += ['--body', '@' + str(path)]
        # runningStatus can change before Azure releases its operation lock.
        for attempt in range(24):
            result = subprocess.run(args, capture_output=True, text=True, timeout=180)
            if not result.returncode or 'ContainerAppOperationInProgress' not in result.stderr:
                break
            if attempt == 0:
                print('Waiting for the previous Azure operation to finish.', flush=True)
            time.sleep(5)
    if result.returncode:
        codes = re.findall(r'"code"\s*:\s*"([A-Za-z0-9_.-]+)"', result.stderr)
        detail = ','.join(dict.fromkeys(codes)) or f'exit {result.returncode}'
        raise RuntimeError(f'Azure {method} {suffix or "app"} failed ({detail})')
    return json.loads(result.stdout) if result.stdout.strip() else None


def wait_for(predicate, label, seconds=300):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        current = rest('get')
        if predicate(current['properties']):
            print(label, flush=True)
            return current
        time.sleep(5)
    raise RuntimeError(label + ' timed out')


def template_for(before, image, suffix, values):
    template = copy.deepcopy(before['properties']['template'])
    if len(template['containers']) != 1:
        raise ValueError('Expected exactly one container')
    container = template['containers'][0]
    if container['name'] != 'reibot':
        raise ValueError('Unexpected container name')
    if not any(v.get('storageName') == 'reibot-payg' for v in template.get('volumes', [])):
        raise ValueError('Expected migrated persistent storage')
    if (template['scale'].get('minReplicas'), template['scale'].get('maxReplicas')) != (1, 1):
        raise ValueError('Expected exactly one bot replica')
    container['image'] = image
    container['resources'].pop('ephemeralStorage', None)
    # Existing mounts, CPU/memory, scale rules and other environment entries survive.
    container['env'] = [e for e in container.get('env', []) if e['name'] not in SECRET_ENV]
    container['env'] += [{'name': name, 'secretRef': f'rb-{suffix}-{key}'}
                         for name, key in SECRET_ENV.items() if values.get(name)]
    container.pop('command', None); container.pop('args', None)
    template['revisionSuffix'] = suffix
    return template


def smoke(revision, url):
    if not re.fullmatch(r'https://www\.youtube\.com/watch\?v=[A-Za-z0-9_-]{11}', url):
        raise ValueError('Smoke test must be a canonical YouTube video URL')
    master, slave = pty.openpty()
    process = subprocess.Popen(['az', 'containerapp', 'exec', '-g', 'ReiBot', '-n', 'reibot',
                                '--revision', revision, '--container', 'reibot', '--command',
                                'python /app/deploy/smoke.py ' + url],
                               stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
    os.close(slave)
    output = bytearray(); deadline = time.monotonic() + 150
    try:
        while time.monotonic() < deadline:
            readable, _, _ = select.select([master], [], [], 1)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output.extend(chunk)
            elif process.poll() is not None:
                break
        if b'REIBOT_SMOKE_OK' not in output:
            raise RuntimeError('Deployed storage/Discord/media smoke check failed')
        print('Storage, Discord readiness and remote audio decoding verified.', flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        os.close(master)


def main():
    os.umask(0o077)
    image, suffix = os.environ['DEPLOY_IMAGE'], os.environ['DEPLOY_SUFFIX']
    if not re.fullmatch(r'registry\.hub\.docker\.com/hleitr/reibot@sha256:[a-f0-9]{64}', image):
        raise ValueError('Expected a digest from the existing ReiBot repository')
    if not re.fullmatch(r'gh-[0-9]+-[0-9]+', suffix):
        raise ValueError('Invalid deployment suffix')
    values = {name: os.environ.pop(name, '') for name in SECRET_ENV}
    if not values['DISCORD_TOKEN'].strip() or not values['YT_COOKIES'].strip():
        raise ValueError('Required GitHub runtime secrets are missing')
    if not values['YT_COOKIES'].lstrip().startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
        raise ValueError('YouTube cookies must use Netscape cookies.txt format')
    before = rest('get')
    if before['properties']['configuration'].get('activeRevisionsMode') != 'Single':
        raise ValueError('Expected Single revision mode')
    if before['properties'].get('runningStatus') != 'Running':
        raise ValueError('App must be running before deployment')
    template = template_for(before, image, suffix, values)
    # Preserve registry/other secrets; add versioned app secrets for rollback.
    secrets = rest('post', '/listSecrets')['value']
    secret_map = {s['name']: s for s in secrets}
    for name, key in SECRET_ENV.items():
        if values[name]:
            secret_map[f'rb-{suffix}-{key}'] = {'name': f'rb-{suffix}-{key}', 'value': values[name]}
    configuration = copy.deepcopy(before['properties']['configuration'])
    configuration['secrets'] = list(secret_map.values())
    stopped = False; changed = False
    try:
        print('Stopping the bot for a single-replica cutover.', flush=True)
        stopped = True
        rest('post', '/stop')
        wait_for(lambda p: p.get('runningStatus') == 'Stopped', 'Previous app stopped')
        rest('patch', body={'properties': {'configuration': configuration, 'template': template}})
        changed = True
        wait_for(lambda p: p.get('provisioningState') == 'Succeeded', 'New template applied')
        rest('post', '/start')
        revision = 'reibot--' + suffix
        wait_for(lambda p: p.get('runningStatus') == 'Running' and
                 p.get('latestReadyRevisionName') == revision, 'New revision ready', 420)
        time.sleep(15)
        smoke(revision, os.environ.get('SMOKE_TEST_URL', 'https://www.youtube.com/watch?v=mYEA5A0Bjyo'))
        replicas = rest('get', '/revisions/' + revision + '/replicas')['value']
        if len(replicas) != 1 or any(c.get('restartCount', 0) or not c.get('ready')
                                   for r in replicas for c in r['properties']['containers']):
            raise RuntimeError('Unexpected replicas, readiness or restarts')
        print('DEPLOYMENT_VERIFIED ' + revision, flush=True)
    except BaseException as original:
        print('Deployment did not pass: ' + str(original), flush=True)
        try:
            current = rest('get')['properties']
            # Also handle an uncertain PATCH result by checking the actual image.
            needs_restore = changed or current['template']['containers'][0]['image'] == image
            if needs_restore:
                if current.get('runningStatus') != 'Stopped':
                    rest('post', '/stop')
                    wait_for(lambda p: p.get('runningStatus') == 'Stopped', 'Failed revision stopped')
                old = copy.deepcopy(before['properties']['template'])
                old['revisionSuffix'] = 'rollback-' + suffix
                for c in old['containers']:
                    c['resources'].pop('ephemeralStorage', None)
                rest('patch', body={'properties': {'template': old}})
                wait_for(lambda p: p.get('provisioningState') == 'Succeeded', 'Previous template restored')
        finally:
            if stopped:
                current = rest('get')['properties']
                if current.get('runningStatus') != 'Running':
                    rest('post', '/start')
                    wait_for(lambda p: p.get('runningStatus') == 'Running', 'Previous app restarted')
        raise


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('DEPLOYMENT_FAILED: ' + str(exc), flush=True)
        raise SystemExit(1)
