#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import subprocess

def subprocess_run_modification_cmd_wrapper(dry_run: bool, *args, **kwargs):
    if not dry_run:
        return subprocess.run(*args, **kwargs)
    else:
        # NOTE: Do *NOT* print out kwargs
        print('DRYRUN - Would execute: {0}'.format(' '.join('"{0}"'.format(w) if ' ' in w else w for w in args[0])))
        return subprocess.CompletedProcess([], 0, stdout=None, stderr=None)
