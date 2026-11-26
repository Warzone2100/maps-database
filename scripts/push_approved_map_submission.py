#!/usr/bin/env python3
# encoding: utf-8
# SPDX-License-Identifier: GPL-2.0-or-later

# Verifies and pushes a map repo commit exported by handle_map_submission_comment.py --approval-output-folder.
# NOTE: The bundle comes from a job that ran maptools on untrusted input, so it's treated as untrusted
# (what was approved is re-derived from GitHub, and nothing from the bundle is run or checked out).

import subprocess
import json
import os
import re
import sys
import argparse
from collections import OrderedDict
from pathlib import Path
from funcs.gen_map_info import MapRepoExternalTools
from funcs.gh_app_token_provider import WZGithubAppTokenProvider
from validate_new_map import MapReposConfig
from handle_map_submission_comment import (
    WZ_GH_APP_SECRET_ENV_VARS, MapSubmissionApprovalResult, WZMapSubmissionValidationCommentDetails,
    verify_gh_user_has_permissions_on_repo, find_approved_gh_issue_validation_comment, git_env_with_github_token,
    description_readme_bytes, approved_map_commit_title, is_valid_map_name, close_approved_map_submission_issue,
    APPROVAL_EXPORT_BUNDLE_FILENAME, APPROVAL_EXPORT_INFO_FILENAME, APPROVAL_EXPORT_BRANCH_REF,
)

MAX_APPROVED_COMMIT_TOTAL_BLOB_SIZE = 64 * 1024 * 1024
ALLOWED_FILE_MODES = ('100644', '100755')
APPROVED_REF = 'refs/wz-approved/main'
COMMIT_SHA_RE = re.compile(r'^(?:[0-9a-f]{40}|[0-9a-f]{64})\Z')

class ApprovedCommitVerificationError(ValueError): pass

def _git(tools: MapRepoExternalTools, repo_path: Path, args: list[str], input_bytes: bytes | None = None) -> bytes:
    cmd = [tools.git_exe, '-c', 'transfer.fsckObjects=true', '-c', 'fetch.fsckObjects=true', '-C', str(repo_path)] + args
    result = subprocess.run(cmd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise ApprovedCommitVerificationError('git {0} failed: {1}'.format(args[0], result.stderr.decode('utf-8', errors='replace').strip()))
    return result.stdout

def _rev_parse_commit(tools: MapRepoExternalTools, repo_path: Path, rev: str) -> str:
    return _git(tools, repo_path, ['rev-parse', '--verify', rev + '^{commit}']).decode('ascii').strip()

def verify_approved_commit(tools: MapRepoExternalTools, repo_path: Path, bundle_path: Path, map_name: str, expected_readme: bytes | None, approval_info: dict) -> str:
    if not is_valid_map_name(map_name):
        raise ApprovedCommitVerificationError('Invalid map name: {0!r}'.format(map_name))

    base_commit = _rev_parse_commit(tools, repo_path, 'refs/heads/main')

    _git(tools, repo_path, ['bundle', 'verify', str(bundle_path)])
    _git(tools, repo_path, ['fetch', '--no-tags', '--no-write-fetch-head', str(bundle_path), '+{0}:{1}'.format(APPROVAL_EXPORT_BRANCH_REF, APPROVED_REF)])
    new_commit = _rev_parse_commit(tools, repo_path, APPROVED_REF)

    if approval_info.get('commit') != new_commit:
        raise ApprovedCommitVerificationError('Bundled commit ({0}) does not match approval.json ({1!r})'.format(new_commit, approval_info.get('commit')))

    parents_line = _git(tools, repo_path, ['rev-list', '--parents', '-n', '1', new_commit]).decode('ascii').split()
    if parents_line[1:] != [base_commit]:
        raise ApprovedCommitVerificationError('Commit {0} must have exactly one parent, the current main ({1}) - got: {2}. (If main has moved since the approval was prepared, re-run /approve.)'.format(new_commit, base_commit, parents_line[1:]))

    commit_title = _git(tools, repo_path, ['log', '-1', '--format=%s', new_commit]).decode('utf-8', errors='replace').strip()
    if commit_title != approved_map_commit_title(map_name):
        raise ApprovedCommitVerificationError('Unexpected commit title: {0!r}'.format(commit_title))

    existing_maps = _git(tools, repo_path, ['ls-tree', '-z', '--name-only', base_commit, 'maps/']).split(b'\0')
    casefolded_name = map_name.casefold()
    for existing in existing_maps:
        if existing and existing.decode('utf-8', errors='replace').rsplit('/', 1)[-1].casefold() == casefolded_name:
            raise ApprovedCommitVerificationError('maps/{0} already exists (case-insensitively) in the map repo'.format(map_name))

    raw_diff = _git(tools, repo_path, ['diff-tree', '-r', '-z', '--raw', '--no-renames', '--no-commit-id', base_commit, new_commit])
    tokens = raw_diff.split(b'\0')
    if tokens and tokens[-1] == b'':
        tokens.pop()
    if len(tokens) == 0 or len(tokens) % 2 != 0:
        raise ApprovedCommitVerificationError('Commit has no changes, or unexpected diff-tree output')
    expected_prefix = 'maps/{0}/'.format(map_name)
    added_blobs = {}
    for meta, raw_path in zip(tokens[0::2], tokens[1::2]):
        # :<old mode> <new mode> <old sha> <new sha> <status>
        meta_fields = meta.decode('ascii', errors='replace').lstrip(':').split(' ')
        try:
            path = raw_path.decode('utf-8')
        except UnicodeDecodeError:
            raise ApprovedCommitVerificationError('Non-UTF-8 path in commit: {0!r}'.format(raw_path))
        if len(meta_fields) != 5:
            raise ApprovedCommitVerificationError('Unexpected diff-tree entry: {0!r}'.format(meta))
        old_mode, new_mode, _, new_sha, status = meta_fields
        if status != 'A' or old_mode != '000000':
            raise ApprovedCommitVerificationError('Commit may only add files - found status {0} for: {1}'.format(status, path))
        if new_mode not in ALLOWED_FILE_MODES:
            raise ApprovedCommitVerificationError('Commit adds a non-regular file (mode {0}): {1}'.format(new_mode, path))
        if not path.startswith(expected_prefix) or len(path) <= len(expected_prefix):
            raise ApprovedCommitVerificationError('Commit adds a file outside of {0}: {1}'.format(expected_prefix, path))
        added_blobs[path] = new_sha

    batch_input = ''.join(sha + '\n' for sha in added_blobs.values()).encode('ascii')
    total_size = 0
    for line in _git(tools, repo_path, ['cat-file', '--batch-check=%(objecttype) %(objectsize)'], input_bytes=batch_input).decode('ascii').splitlines():
        obj_type, obj_size = line.split(' ')
        if obj_type != 'blob':
            raise ApprovedCommitVerificationError('Unexpected object type: {0}'.format(obj_type))
        total_size += int(obj_size)
    if total_size > MAX_APPROVED_COMMIT_TOTAL_BLOB_SIZE:
        raise ApprovedCommitVerificationError('Commit adds too much data ({0} bytes)'.format(total_size))

    if expected_readme is not None:
        readme_path = expected_prefix + 'README.md'
        if readme_path not in added_blobs:
            raise ApprovedCommitVerificationError('Missing {0} (expected the approved description)'.format(readme_path))
        actual_readme = _git(tools, repo_path, ['cat-file', 'blob', added_blobs[readme_path]])
        if actual_readme != expected_readme:
            raise ApprovedCommitVerificationError('{0} does not match the approved description'.format(readme_path))

    return new_commit

def push_approved_map_submission(map_repos_config_json_path: Path, approval_folder: Path, output_temp_folder: Path, gh_repo: str, gh_issue_obj: dict, gh_comment_obj: dict, dry_run: bool = False, map_repo_management_token_provider: WZGithubAppTokenProvider | None = None, tools: MapRepoExternalTools = MapRepoExternalTools()) -> MapSubmissionApprovalResult:

    if gh_issue_obj['state'] != 'open':
        print('Issue {0} is not open - ignoring'.format(gh_issue_obj['number']), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    if not gh_comment_obj['body'].startswith('/approve'):
        print('ERROR: Not an /approve comment', file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE

    if not verify_gh_user_has_permissions_on_repo(gh_repo, gh_comment_obj['user']['login'], ['triage'], tools):
        print('ERROR: User does not have necessary permissions for this action', file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE_PERMISSIONS

    try:
        approved_comment_obj = find_approved_gh_issue_validation_comment(gh_repo, gh_issue_obj, gh_comment_obj, tools)
        approved_map_info = WZMapSubmissionValidationCommentDetails(approved_comment_obj, gh_issue_obj)
    except ValueError as e:
        print('ERROR: Failed to fetch approved validation with: {0}'.format(str(e)), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    if approved_map_info.status != 'pass':
        print('ERROR: Map status ({0}) is not \'pass\''.format(approved_map_info.status), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE_MAP_STATUS
    if not approved_map_info.description_body_matches_expected():
        print('ERROR: Description has been changed since the last automated analysis', file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE_DESCRIPTION_CHANGED
    map_name = approved_map_info.map_info.get('name')
    if not is_valid_map_name(map_name):
        print('ERROR: Invalid map name in approved validation comment: {0!r}'.format(map_name), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    repos_config = MapReposConfig(str(map_repos_config_json_path))
    submission_repo = repos_config.get_repo_for_new_map_submissions(approved_map_info.map_info.get('players'))
    if not submission_repo:
        print('ERROR: No map repo for players: {0!r}'.format(approved_map_info.map_info.get('players')), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    expected_readme = description_readme_bytes(approved_map_info.get_description_body())

    bundle_path = approval_folder.joinpath(APPROVAL_EXPORT_BUNDLE_FILENAME).resolve()
    try:
        with open(approval_folder.joinpath(APPROVAL_EXPORT_INFO_FILENAME), 'r', encoding='utf-8') as f:
            approval_info = json.load(f)
        if not isinstance(approval_info, dict):
            raise ValueError('approval.json is not an object')
    except (OSError, ValueError) as e:
        print('ERROR: Failed to load approval info: {0}'.format(str(e)), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    mismatches = [k for k, expected in [('repo', submission_repo), ('map_name', map_name), ('issue_number', gh_issue_obj['number']), ('approve_comment_id', gh_comment_obj['id'])] if approval_info.get(k) != expected]
    if mismatches or not isinstance(approval_info.get('commit'), str) or not COMMIT_SHA_RE.match(approval_info['commit']):
        print('ERROR: approval.json does not match the approved submission (mismatched: {0})'.format(', '.join(mismatches) or 'commit'), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    if not bundle_path.is_file():
        print('ERROR: Missing bundle: {0}'.format(bundle_path), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE

    repo_path = output_temp_folder.joinpath('push-map-repo', submission_repo).resolve()
    if repo_path.exists():
        print('ERROR: Temp map repo path already exists: {0}'.format(repo_path), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    clone_result = subprocess.run([tools.git_exe, 'clone', '--bare', '--single-branch', '--branch', 'main', '--', 'https://github.com/{0}.git'.format(submission_repo), str(repo_path)], stdout=subprocess.PIPE)
    if clone_result.returncode != 0:
        print('Failed to clone {0}'.format(submission_repo), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE

    try:
        new_commit = verify_approved_commit(tools, repo_path, bundle_path, map_name, expected_readme, approval_info)
    except ApprovedCommitVerificationError as e:
        print('ERROR: Approved commit failed verification: {0}'.format(str(e)), file=sys.stderr)
        return MapSubmissionApprovalResult.FAILURE
    print('Verified commit {0}: adds maps/{1} to {2}'.format(new_commit, map_name, submission_repo))

    if dry_run:
        print('DRYRUN - Would push {0} to: https://github.com/{1}.git:main'.format(new_commit, submission_repo))
    else:
        git_push_env = None
        map_push_access_token = None
        if map_repo_management_token_provider:
            map_repo_split = submission_repo.split('/', 1)
            map_push_access_token = map_repo_management_token_provider.get_access_token(map_repo_split[0], map_repo_split[1], tools, permissions={'contents': 'write'})
            if not map_push_access_token:
                return MapSubmissionApprovalResult.FAILURE
            git_push_env = git_env_with_github_token(map_push_access_token)
        try:
            push_result = subprocess.run([tools.git_exe, '-C', str(repo_path), 'push', 'https://github.com/{0}.git'.format(submission_repo), '{0}:refs/heads/main'.format(new_commit)], env=git_push_env)
        finally:
            git_push_env = None
            if map_push_access_token:
                WZGithubAppTokenProvider.revoke_access_token(map_push_access_token)
                map_push_access_token = None
        if push_result.returncode != 0:
            print('Failed to push to {0}'.format(submission_repo), file=sys.stderr)
            return MapSubmissionApprovalResult.FAILURE

    close_approved_map_submission_issue(gh_issue_obj, dry_run, tools)
    return MapSubmissionApprovalResult.SUCCESS

def main(argv):
    parser = argparse.ArgumentParser(description='Verify and push a map submission commit exported by handle_map_submission_comment.py --approval-output-folder')
    parser.add_argument('--map-repos-config', type=Path, required=True)
    parser.add_argument('--approval-folder', type=Path, required=True, help='Folder containing {0} and {1} from the first stage'.format(APPROVAL_EXPORT_BUNDLE_FILENAME, APPROVAL_EXPORT_INFO_FILENAME))
    parser.add_argument('--output-temp-folder', type=Path, required=True)
    parser.add_argument('--gh-repo', type=str, required=True)
    parser.add_argument('--gh-issue', type=Path, required=True)
    parser.add_argument('--gh-comment', type=Path, required=True)
    parser.add_argument('--dry-run', action='store_true', required=False, help='Skip actions that would modify data on any repos, logging them instead')
    args = parser.parse_args()

    map_repo_management_token_provider = None
    if all(os.environ.get(x) for x in WZ_GH_APP_SECRET_ENV_VARS):
        map_repo_management_token_provider = WZGithubAppTokenProvider(os.getenv('WZ_GH_APP_MAPREPO_MANAGER_APP_ID'), os.getenv('WZ_GH_APP_MAPREPO_MANAGER_PRIVATE_KEY_SECRET').encode('utf-8'))
    # Keep the App credentials out of child processes (git, gh)
    for x in WZ_GH_APP_SECRET_ENV_VARS:
        os.environ.pop(x, None)

    with open(args.gh_issue, 'r', encoding='utf-8') as f:
        gh_issue_obj = json.load(f, object_pairs_hook=OrderedDict)
    with open(args.gh_comment, 'r', encoding='utf-8') as f:
        gh_comment_obj = json.load(f, object_pairs_hook=OrderedDict)

    result = push_approved_map_submission(args.map_repos_config, args.approval_folder, args.output_temp_folder, args.gh_repo, gh_issue_obj, gh_comment_obj, args.dry_run, map_repo_management_token_provider)
    exit(int(result))

if __name__ == "__main__":
    main(sys.argv[1:])
