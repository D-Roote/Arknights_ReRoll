"""Offline installation check. Never connect to a device or run a game task."""
from __future__ import annotations

import argparse
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys


def verify(root: Path) -> dict:
    root = root.resolve()
    resource_dir = root / 'assets/resources'
    interface = json.loads((resource_dir / 'interface.json').read_text(encoding='utf-8-sig'))
    runtime = json.loads((root / 'deployment/runtime.json').read_text(encoding='utf-8-sig'))
    if version('MaaFw') != runtime['maafw_version']:
        raise RuntimeError('Agent SDK does not match the resource release.')
    agent = interface['agent']
    if agent['child_exec'] != '../../.venv/Scripts/python.exe' or agent['child_args'] != ['-X', 'utf8', '-u', '../agent/main.py']:
        raise RuntimeError('Unexpected Agent launch layout; review interface.json before installing.')
    if 'identifier' in agent:
        raise RuntimeError('Remove fixed Agent identifiers before using multiple instances.')
    from maa.resource import Resource
    from maa.toolkit import Toolkit

    if not Toolkit.init_option(str(root / '.setup-verification')):
        raise RuntimeError('MaaFW native runtime initialization failed.')
    resource = Resource()
    if not resource.post_bundle(str(resource_dir)).wait().succeeded:
        raise RuntimeError('MaaFW could not load the resource bundle.')
    if not resource.post_ocr_model(str(resource_dir / 'model/ocr/ko')).wait().succeeded:
        raise RuntimeError('MaaFW could not load the Korean OCR model.')
    entries = [task['entry'] for task in interface['task']]
    for name in entries:
        if resource.get_node_data(name) is None:
            raise RuntimeError(f'Unknown task entry: {name}')
    # Importing AgentServer changes MaaFW's global native backend. Host Resource
    # APIs must stay in this process; Agent registration belongs in a child.
    result = subprocess.run([sys.executable, '-I', '-X', 'utf8', str(Path(__file__).resolve()),
                             '--agent-only', str(root)], capture_output=True, text=True,
                            encoding='utf-8', timeout=30)
    if result.returncode:
        raise RuntimeError('Agent registration failed: ' + result.stdout + result.stderr)
    actions = json.loads(result.stdout.strip().splitlines()[-1])
    return {'ok': True, 'maafw': version('MaaFw'), 'python': sys.version.split()[0],
            'entries': entries, 'actions': actions, 'device_actions_executed': False}


def verify_agent(root: Path) -> list[str]:
    sys.path.insert(0, str(root.resolve() / 'assets'))
    from maa.agent.agent_server import AgentServer
    from agent.actions import create_actions

    actions = []
    for name, action in create_actions(root / 'assets/saved'):
        if not AgentServer.register_custom_action(name, action):
            raise RuntimeError(f'CustomAction registration failed: {name}')
        actions.append(name)
    return actions


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent-only', action='store_true')
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_agent(args.root) if args.agent_only else verify(args.root), ensure_ascii=False))
