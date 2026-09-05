"""Prepare JSON (valid YAML) for the official action; never deploy or log secrets."""
import copy
import json
import os
import re
import subprocess
from pathlib import Path

SECRET_ENV = {'DISCORD_TOKEN': 'discord', 'YT_COOKIES': 'youtube', 'BILIBILI_COOKIES': 'bilibili'}


def configurations(before, existing_secrets, image, suffix, values):
    if not re.fullmatch(r'registry\.hub\.docker\.com/hleitr/reibot@sha256:[a-f0-9]{64}', image):
        raise ValueError('Expected an immutable ReiBot image digest')
    if not re.fullmatch(r'gh-[0-9]+-[0-9]+', suffix):
        raise ValueError('Invalid revision suffix')
    if not values.get('DISCORD_TOKEN', '').strip() or not values.get('YT_COOKIES', '').strip():
        raise ValueError('Required GitHub runtime secrets are missing')
    if not values['YT_COOKIES'].lstrip().startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
        raise ValueError('YouTube cookies must use Netscape cookies.txt format')
    props = before['properties']
    template = copy.deepcopy(props['template'])
    if props.get('runningStatus') != 'Running' or props['configuration'].get('activeRevisionsMode') != 'Single':
        raise ValueError('Expected a running app in Single revision mode')
    if len(template['containers']) != 1 or template['containers'][0]['name'] != 'reibot':
        raise ValueError('Expected one ReiBot container')
    if not any(v.get('storageName') == 'reibot-payg' for v in template.get('volumes', [])):
        raise ValueError('Migrated persistent storage is missing')
    if (template['scale'].get('minReplicas'), template['scale'].get('maxReplicas')) != (1, 1):
        raise ValueError('Expected exactly one bot replica')
    container = template['containers'][0]
    container['resources'].pop('ephemeralStorage', None)
    rollback = {'properties': {'template': copy.deepcopy(template)}}
    rollback['properties']['template']['revisionSuffix'] = 'rollback-' + suffix
    container['image'] = image
    container.pop('command', None)
    container.pop('args', None)
    container['env'] = [e for e in container.get('env', []) if e['name'] not in SECRET_ENV]
    secrets = {s['name']: s for s in existing_secrets}
    for name, key in SECRET_ENV.items():
        if values.get(name):
            ref = f'rb-{suffix}-{key}'
            secrets[ref] = {'name': ref, 'value': values[name]}
            container['env'].append({'name': name, 'secretRef': ref})
    template['revisionSuffix'] = suffix
    return {'properties': {'template': template, 'configuration': {'secrets': list(secrets.values())}}}, rollback


def main():
    os.umask(0o077)
    folder = Path(os.environ['RUNNER_TEMP']) / 'reibot-deploy'
    folder.mkdir(mode=0o700)
    base = 'https://management.azure.com' + os.environ['APP_ID']
    def read(method, endpoint=''):
        result = subprocess.run(['az', 'rest', '--method', method, '--url',
                                 base + endpoint + '?api-version=2025-07-01', '-o', 'json'],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    before = read('get')
    deploy, rollback = configurations(before, read('post', '/listSecrets')['value'],
        os.environ['DEPLOY_IMAGE'], os.environ['DEPLOY_SUFFIX'],
        {name: os.environ.pop(name, '') for name in SECRET_ENV})
    for name, config in [('deploy', deploy), ('rollback', rollback)]:
        (folder / (name + '.yaml')).write_text(json.dumps(config))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('previous_image=' + before['properties']['template']['containers'][0]['image'] + '\n')
    print('Private configuration prepared; existing mounts, resources and rollback references preserved.')


if __name__ == '__main__':
    main()
