#!/usr/bin/env python3
"""Live regression: CUA must open Warband's module dropdown in the background."""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

SOCKET = str(Path.home() / '.cache/cua-driver/cua-driver-x11.sock')
OUT = Path('/tmp/shuvcode')


def call(tool, args):
    result = subprocess.run(
        ['cua-driver-main', 'call', tool, json.dumps({'session': 'warband', **args}),
         '--socket', SOCKET], text=True, capture_output=True, timeout=30,
    )
    data = json.loads(result.stdout)
    return result.returncode, data


def main():
    _, data = call('list_windows', {})
    windows = [w for w in data['windows']
               if w['app_name'] == 'steam_app_48700' and w['width'] == 640]
    if len(windows) != 1:
        raise RuntimeError('Expected exactly one Warband launcher')
    window = windows[0]
    target = {k: window[k] for k in ('pid', 'window_id')}
    before = OUT / 'warband-cua-before.png'
    after = OUT / 'warband-cua-after.png'
    capture_args = {**target, 'include_accessibility_tree': False}
    rc, capture = call('get_window_state', {
        **capture_args, 'screenshot_out_file': str(before),
    })
    if rc:
        raise RuntimeError(capture)
    rc, action = call('click', {
        **target, 'x': 562, 'y': 117, 'delivery_mode': 'background',
        'capture_id': capture['capture_id'],
    })
    print(json.dumps({'action': action}, indent=2))
    call('get_window_state', {**capture_args, 'screenshot_out_file': str(after)})
    # Only the dropdown area; exclude cursor overlays and unrelated rendering.
    region = (180, 105, 575, 250)
    diff = ImageChops.difference(Image.open(before).convert('RGB').crop(region),
                                Image.open(after).convert('RGB').crop(region))
    changed = sum(any(pixel) for pixel in diff.getdata())
    passed = rc == 0 and changed > 1000
    print(f'{"PASS" if passed else "FAIL"}: dropdown changed pixels={changed}')
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
