#!/usr/bin/env python3
# encoding: utf-8
# SPDX-License-Identifier: GPL-2.0-or-later

# Runs maptools with resource limits and a timeout,
# and with WZ_MAPTOOLS_SANDBOX=bwrap, in a bubblewrap sandbox with access to only its declared inputs and outputs.
# Fails closed (raises MaptoolsSandboxError) if the sandbox is requested but unusable.
#
# NOTE: On Ubuntu 24.04+, bwrap needs: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

import os
import sys
import shutil
import resource
import subprocess
import tempfile
from pathlib import Path

SANDBOX_ENV_VAR = 'WZ_MAPTOOLS_SANDBOX'

DEFAULT_TIMEOUT_SECONDS = 300
TIMEOUT_EXIT_CODE = 124
REJECTED_OUTPUT_EXIT_CODE = 125

RESOURCE_LIMITS = [
    (resource.RLIMIT_AS, 4 * 1024 * 1024 * 1024),
    (resource.RLIMIT_CPU, DEFAULT_TIMEOUT_SECONDS),
    (resource.RLIMIT_FSIZE, 512 * 1024 * 1024),
    (resource.RLIMIT_CORE, 0),
]

class MaptoolsSandboxError(RuntimeError): pass

def get_sandbox_mode() -> str:
    mode = os.environ.get(SANDBOX_ENV_VAR, '').strip().lower()
    if mode in ('', 'none', 'off', '0', 'false'):
        return 'none'
    if mode == 'bwrap':
        return 'bwrap'
    raise MaptoolsSandboxError('Unknown {0} value: {1!r} (expected "bwrap" or "none")'.format(SANDBOX_ENV_VAR, mode))

def _apply_resource_limits():
    for limit, value in RESOURCE_LIMITS:
        try:
            soft, hard = resource.getrlimit(limit)
            if hard != resource.RLIM_INFINITY:
                value = min(value, hard)
            resource.setrlimit(limit, (value, value))
        except (ValueError, OSError):
            pass

def _bwrap_command(bwrap_exe: str, maptools_exe: str, input_paths: list[str], output_mounts: list[tuple[str, str]], cwd: str) -> list[str]:
    cmd = [bwrap_exe,
           '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL',
           '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/tmp',
           # maptools only needs the dynamic loader, libc and libstdc++
           '--ro-bind', '/usr', '/usr']
    for d in ['/bin', '/sbin', '/lib', '/lib32', '/lib64', '/libx32']:
        if os.path.islink(d):
            cmd += ['--symlink', os.readlink(d), d]
        elif os.path.isdir(d):
            cmd += ['--ro-bind', d, d]
    cmd += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--dir', cwd,
            '--ro-bind', maptools_exe, maptools_exe]
    # Outputs before inputs, so an input beneath an output's parent stays read-only
    for host_tmp_dir, sandbox_dir in output_mounts:
        cmd += ['--bind', host_tmp_dir, sandbox_dir]
    for p in input_paths:
        cmd += ['--ro-bind', p, p]
    cmd += ['--chdir', cwd, '--']
    return cmd

_sandbox_check_cache: dict[str, bool] = {}

def check_sandbox(maptools_exe: str, bwrap_exe: str | None = None) -> None:
    bwrap_exe = bwrap_exe or shutil.which('bwrap')
    if not bwrap_exe:
        raise MaptoolsSandboxError('{0}=bwrap, but bwrap (bubblewrap) was not found - install it, e.g. "sudo apt-get install bubblewrap"'.format(SANDBOX_ENV_VAR))
    maptools_real = os.path.realpath(maptools_exe)
    if _sandbox_check_cache.get(maptools_real):
        return
    cmd = _bwrap_command(bwrap_exe, maptools_real, [], [], os.getcwd()) + [maptools_real, '--version']
    result = subprocess.run(cmd, capture_output=True, preexec_fn=_apply_resource_limits, timeout=60)
    if result.returncode != 0:
        raise MaptoolsSandboxError('Failed to run maptools in the bwrap sandbox (exit code {0}): {1}\n'
            'Hint: on Ubuntu 24.04+, unprivileged user namespaces must be allowed: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0'.format(
            result.returncode, result.stderr.decode('utf-8', errors='replace').strip()))
    _sandbox_check_cache[maptools_real] = True

def _contains_only_regular_entries(path: str) -> bool:
    if os.path.islink(path):
        return False
    if os.path.isfile(path):
        return True
    if not os.path.isdir(path):
        return False
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            entry = os.path.join(dirpath, name)
            if os.path.islink(entry) or not (os.path.isfile(entry) or os.path.isdir(entry)):
                return False
    return True

def run_maptools(maptools_exe: str, args: list, inputs: list = [], outputs: list = [], timeout: int = DEFAULT_TIMEOUT_SECONDS, **subprocess_kwargs) -> subprocess.CompletedProcess:
    # inputs: paths maptools reads
    # outputs: paths maptools creates (their parent folders must exist)
    if not maptools_exe:
        raise ValueError('Failed to find maptools executable')
    if 'env' in subprocess_kwargs or 'preexec_fn' in subprocess_kwargs or 'cwd' in subprocess_kwargs:
        raise ValueError('run_maptools does not support env / preexec_fn / cwd')

    mode = get_sandbox_mode()
    maptools_real = os.path.realpath(maptools_exe)
    captured = subprocess_kwargs.get('capture_output') or subprocess_kwargs.get('stdout') == subprocess.PIPE

    temp_dirs = []
    output_moves = [] # (temp output path, real output path)
    try:
        if mode == 'bwrap':
            check_sandbox(maptools_real)
            cwd = os.getcwd()
            input_paths = [os.path.abspath(str(p)) for p in inputs]
            output_mounts = []
            parent_to_temp = {}
            for out in outputs:
                out_abs = os.path.abspath(str(out))
                parent = os.path.dirname(out_abs)
                if parent not in parent_to_temp:
                    temp_dir = tempfile.mkdtemp(prefix='maptools-out-')
                    temp_dirs.append(temp_dir)
                    parent_to_temp[parent] = temp_dir
                    output_mounts.append((temp_dir, parent))
                output_moves.append((os.path.join(parent_to_temp[parent], os.path.basename(out_abs)), out_abs))
            cmd = _bwrap_command(shutil.which('bwrap'), maptools_real, input_paths, output_mounts, cwd) + [maptools_real] + [str(a) for a in args]
        else:
            cmd = [maptools_real] + [str(a) for a in args]

        try:
            result = subprocess.run(cmd, preexec_fn=_apply_resource_limits, timeout=timeout, **subprocess_kwargs)
        except subprocess.TimeoutExpired as e:
            print('ERROR: maptools timed out after {0} seconds'.format(timeout), file=sys.stderr)
            stdout = e.stdout if e.stdout is not None else (b'' if captured else None)
            stderr = e.stderr if e.stderr is not None else (b'' if subprocess_kwargs.get('capture_output') or subprocess_kwargs.get('stderr') == subprocess.PIPE else None)
            if stderr is not None:
                stderr += b'maptools timed out'
            return subprocess.CompletedProcess(cmd, TIMEOUT_EXIT_CODE, stdout=stdout, stderr=stderr)

        for temp_out, real_out in output_moves:
            if not os.path.lexists(temp_out):
                continue
            if not _contains_only_regular_entries(temp_out):
                print('ERROR: maptools output contains symlinks or special files - discarding: {0}'.format(real_out), file=sys.stderr)
                return subprocess.CompletedProcess(cmd, REJECTED_OUTPUT_EXIT_CODE, stdout=result.stdout, stderr=result.stderr)
            if os.path.isdir(real_out) and not os.path.islink(real_out):
                print('ERROR: maptools output destination already exists as a folder: {0}'.format(real_out), file=sys.stderr)
                return subprocess.CompletedProcess(cmd, REJECTED_OUTPUT_EXIT_CODE, stdout=result.stdout, stderr=result.stderr)
            if os.path.lexists(real_out):
                os.remove(real_out)
            shutil.move(temp_out, real_out)
        return result
    finally:
        for temp_dir in temp_dirs:
            shutil.rmtree(temp_dir, ignore_errors=True)

def main(argv):
    import argparse
    parser = argparse.ArgumentParser(description='maptools sandbox helper')
    parser.add_argument('--check', action='store_true', required=True, help='Check that maptools runs in the configured sandbox')
    parser.add_argument('--maptools', type=str, required=False, help='Path to maptools (default: found on PATH)')
    args = parser.parse_args(argv)
    maptools_exe = args.maptools or shutil.which('maptools')
    if not maptools_exe:
        print('ERROR: maptools not found', file=sys.stderr)
        return 1
    try:
        mode = get_sandbox_mode()
        if mode == 'bwrap':
            check_sandbox(maptools_exe)
    except MaptoolsSandboxError as e:
        print('ERROR: {0}'.format(e), file=sys.stderr)
        return 1
    print('maptools sandbox mode: {0} - OK'.format(mode))
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
