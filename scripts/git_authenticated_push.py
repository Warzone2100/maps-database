#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import subprocess
import sys
import os
import argparse
from pathlib import Path
from funcs.gh_app_token_provider import WZGithubAppTokenProvider
from funcs.gen_map_info import MapRepoExternalTools

def handle_gh_git_authenticated_push(gh_repo: str, local_branch: str, remote_branch: str, cwd=None, force_push: bool = False, dry_run: bool = False, gh_app_token_provider: WZGithubAppTokenProvider | None = None, tools: MapRepoExternalTools = MapRepoExternalTools()) -> bool:
    
    # Push to a repo (potentially using an access token)
    repo_push_auth_prefix = ''
    if gh_app_token_provider:
        if not dry_run:
            repo_split = gh_repo.split('/', 1)
            repo_push_access_token = gh_app_token_provider.get_access_token(repo_split[0], repo_split[1], tools)
            if not repo_push_access_token:
                print('Failed to get access token')
                return False
            repo_push_auth_prefix = 'x-access-token:{0}@'.format(repo_push_access_token)
            repo_push_access_token = None
            print('Configured access token')
        else:
            print('DRYRUN - Would request access token from token provider')
    
    if not dry_run:
        git_push_arguments = [tools.git_exe, 'push']
        if force_push:
            git_push_arguments.append('-f')
        git_push_arguments.append('https://{0}github.com/{1}.git'.format(repo_push_auth_prefix, gh_repo))
        git_push_arguments.append('{0}:{1}'.format(local_branch, remote_branch))
        git_push_result = subprocess.run(git_push_arguments, cwd=cwd)
        git_push_arguments.clear()
        if git_push_result.returncode != 0:
            print('Failed to push to {0}'.format(gh_repo), file=sys.stderr)
            return False
    else:
        print('DRYRUN - Would push from local branch {0} to: https://github.com/{1}.git:{2}'.format(local_branch, gh_repo, remote_branch))
    
    return True

def main(argv):
    
    tools = MapRepoExternalTools()

    parser = argparse.ArgumentParser(description='Git push to a repo, potentially using an access token from a GitHub App')
    parser.add_argument('--github-repo', type=str, required=True, help='The Github "org/repo" string for the target remote repo')
    parser.add_argument('--local-branch', type=str, required=True)
    parser.add_argument('--remote-branch', type=str, required=True)
    parser.add_argument('--force', action='store_true', required=False, help='Force-push')
    parser.add_argument('--cwd', type=Path, required=False)
    parser.add_argument('--dry-run', action='store_true', required=False, help='Skip actions that would modify data on any repos, logging them instead')
    args = parser.parse_args()
    
    cwd_path_str = None
    if args.cwd:
        if args.cwd.exists():
            cwd_path_str = str(args.cwd)
        else:
            print('cwd path should exist (and be a git repo)', file=sys.stderr)
            exit(1)
    
    target_repo_token_provider = None
    if all(x in os.environ for x in ['WZ_GH_APP_GIT_PUSH_APP_ID', 'WZ_GH_APP_GIT_PUSH_PRIVATE_KEY_SECRET']):
        target_repo_token_provider = WZGithubAppTokenProvider(os.getenv('WZ_GH_APP_GIT_PUSH_APP_ID'), os.getenv('WZ_GH_APP_GIT_PUSH_PRIVATE_KEY_SECRET').encode('utf-8'))
    else:
        print('Not configured to use app token provider')
    
    ret = handle_gh_git_authenticated_push(args.github_repo, args.local_branch, args.remote_branch, cwd = cwd_path_str, force_push = args.force, dry_run = args.dry_run, gh_app_token_provider = target_repo_token_provider, tools = tools)
    if not ret:
        exit(1)
    
    exit(0)

if __name__ == "__main__":
    main(sys.argv[1:])
