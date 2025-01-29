#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import subprocess
import re
import json
import os
import shutil
import pprint
import hashlib
import string
import secrets
import sys
import argparse
import time
from collections import OrderedDict
from pathlib import Path
from datetime import timezone, datetime
from .map_funcs import validate_map_info, MapInfoValidationResult
from .compress_map import compress_map_folder
from .gen_map_info import MapRepoExternalTools, generate_release_maps_info
from .dry_run_wrappers import subprocess_run_modification_cmd_wrapper
from .gh_app_token_provider import WZGithubAppTokenProvider

GITHUB_ORG = 'Warzone2100'
GH_REST_API_VERSION = '2022-11-28'

def get_changed_folders_in_commit(commit: str, cwd=None, tools: MapRepoExternalTools = MapRepoExternalTools()):
    changedFoldersB = subprocess.check_output([tools.git_exe, 'diff', '--dirstat=files,0', commit + '^!'], cwd=cwd)
    changedFolders = changedFoldersB.decode("utf-8").splitlines()
    # Now strip the percentage at the beginning of each entry
    changedFolders = [re.sub(r'^[\ 0-9.]+% ', '', folder) for folder in changedFolders]
    return changedFolders

def map_has_hash_collision(archive_path: str):
    sha256_hash = hashlib.sha256()
    with open(archive_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    archive_hash = sha256_hash.hexdigest()
    # TODO: lookup in existing set of hashes to see if this is a collision
    return {'result': False, 'hash': sha256_hash}

# -----------------------------

RELEASE_VERSION_RE = re.compile("^v?(?P<major>\d+).*")

def generate_next_release_details(current_release_tagname: str, releasesGeneratedThisRun: dict):
    
    # Increment the major version in current_release_tagname
    release_version_result = RELEASE_VERSION_RE.match(current_release_tagname)
    if release_version_result:
        next_release_tagname = 'v' + str(int(release_version_result.group('major')) + 1)
    else:
        raise ValueError('Error: Invalid current release tagname: {0}'.format(current_release_tagname))
    
    releasesGeneratedThisRun[next_release_tagname] = {
        "commits": [],
        "assets": 0
    }
    
    return next_release_tagname

# Generates releases in the output folder, starting with the next commit after `last_processed_commit`
# Each release will be named with its release name, and will contain:
#   - An `assets` folder, with all of the packaged map .wz files
#   - A `release.json` file containing the following properties:
#       - target_commitish
#       - included_commits (a list of all map repo commits that were processed and included in this release)
def generate_releases_for_maprepo(repo_local_path: Path, last_processed_commit: str, output_folder: str, last_release_version: int, tools: MapRepoExternalTools, verbose: bool = False, max_assets_per_release = 100):
    # Get all commits from last processed commit
    # git rev-list --topo-order --ancestry-path --reverse --branches=main <last_processed_commit>..HEAD
    commitsB = subprocess.check_output([tools.git_exe, "rev-list", "--topo-order", "--ancestry-path", "--reverse", "--first-parent", "--branches=main", "{0}..HEAD".format(last_processed_commit)], cwd=repo_local_path)
    commits = commitsB.decode("utf-8").splitlines()
    
    releasesGeneratedThisRun = dict()
    MAP_REPO_NEW_RELEASE_TAGNAME = generate_next_release_details(last_release_version, releasesGeneratedThisRun)
    releaseList = list()
    
    for commit in commits:
        print('Info: Processing commit: {0}'.format(commit))
        
        # Get the list of changed folders in the commit
        changedFolders = get_changed_folders_in_commit(commit, cwd=repo_local_path, tools=tools)
        
        # Filter for maps folders
        changedFolders = [x for x in changedFolders if re.match(r'^maps/.+', x)]
        
        if not changedFolders:
            print('Info: No changed map folders in commit {0} ?'.format(commit))
            continue
        
        if releasesGeneratedThisRun[MAP_REPO_NEW_RELEASE_TAGNAME]['assets'] > 0 and (len(changedFolders) + releasesGeneratedThisRun[MAP_REPO_NEW_RELEASE_TAGNAME]['assets']) > max_assets_per_release:
            # append the last release
            if not MAP_REPO_NEW_RELEASE_TAGNAME in releaseList:
                releaseList.append(MAP_REPO_NEW_RELEASE_TAGNAME)
            # create a new release for the assets from this commit
            MAP_REPO_NEW_RELEASE_TAGNAME = generate_next_release_details(MAP_REPO_NEW_RELEASE_TAGNAME, releasesGeneratedThisRun)
        
        releasesGeneratedThisRun[MAP_REPO_NEW_RELEASE_TAGNAME]['commits'].append(commit)
        
        release_assets_dir = os.path.join(output_folder, MAP_REPO_NEW_RELEASE_TAGNAME, 'assets')
        os.makedirs(release_assets_dir, exist_ok=True)
        
        for mapFolder in changedFolders:
            
            print('Info: Processing map: {0}'.format(mapFolder))
            
            # Convert mapFolder to absolute path (relative to base path repo_local_path)
            mapFolderFullPath = str(repo_local_path.joinpath(mapFolder))
            
            # Extract map info
            maptools_info_result = subprocess.run([tools.maptools_exe, 'package', 'info', '--map-seed=0', mapFolderFullPath], stdout=subprocess.PIPE)
            if not maptools_info_result.returncode == 0:
                print('Error: {0} - maptools package info command failed with exit code: {1}'.format(mapFolder, maptools_info_result.returncode))
                continue
            map_info_json = json.loads(maptools_info_result.stdout, object_pairs_hook=OrderedDict)
            # Validate map info
            map_validation_result = validate_map_info(map_info_json)
            if len(map_validation_result.errors) > 0:
                #print("Error: {0} - Validation Errors \n\t{1}".format(mapFolder, pprint.pformat(map_validation_result.errors)))
                print("Error: {0} - Validation Errors \n\t{1}".format(mapFolder, '\n\t'.join(map_validation_result.errors)))
                continue
            if len(map_validation_result.errors_non_fatal) > 0:
                print('Warning: {0} - Validation Errors (Non-Fatal): \n\t{1}'.format(mapFolder, '\n\t'.join(map_validation_result.errors_non_fatal)))
            if len(map_validation_result.warnings) > 0:
                print('Warning: {0} - Validation Warnings: \n\t{1}'.format(mapFolder, '\n\t'.join(map_validation_result.warnings)))
            map_players = map_info_json['players']
            # Generate clean map name
            clean_map_name = re.sub(r'[^A-Za-z0-9\-_]', "_", map_info_json['name'])
            clean_map_name_with_players = '{0}p-{1}'.format(map_players, clean_map_name)
            # Compress the map folder into a map archive
            output_archive_path = os.path.join(output_folder, MAP_REPO_NEW_RELEASE_TAGNAME, 'assets', '{0}.wz'.format(clean_map_name_with_players))
            compress_map_folder(mapFolderFullPath, output_archive_path)
            hash_collision_result = map_has_hash_collision(output_archive_path)
            while hash_collision_result['result']:
                # Generate a random string to change the output archive hash
                alphabet = string.ascii_letters + string.digits
                hashCollisionAvoidanceSalt = ''.join(secrets.choice(alphabet) for i in range(8))
                print('Warning: {0} Collision Warning: Initial generated map package had hash {1}, which conflicted with existing map package'.format(mapFolder, hash_collision_result['hash']))
                os.remove(output_archive_path)
                compress_map_folder(mapFolderFullPath, output_archive_path, hashCollisionAvoidanceSalt)
                hash_collision_result = map_has_hash_collision(output_archive_path)
            
            releasesGeneratedThisRun[MAP_REPO_NEW_RELEASE_TAGNAME]['assets'] += 1
        
        output_info_path = os.path.join(output_folder, MAP_REPO_NEW_RELEASE_TAGNAME, 'release.json')
        release_info = {
            "target_commitish": commit,
            "included_commits": releasesGeneratedThisRun[MAP_REPO_NEW_RELEASE_TAGNAME]['commits']
        }
        with open(output_info_path, 'w', encoding='utf-8') as f:
            json.dump(release_info, f, ensure_ascii=False, indent=4)
        
        if releasesGeneratedThisRun[MAP_REPO_NEW_RELEASE_TAGNAME]['assets'] > 0 and not MAP_REPO_NEW_RELEASE_TAGNAME in releaseList:
            releaseList.append(MAP_REPO_NEW_RELEASE_TAGNAME)
    
    return releaseList

def generate_releasenotes(release: str, target_commitish: str, included_commits: list):
    release_notes = 'target_commitish: {0}'.format(target_commitish)
    if len(included_commits) > 1:
        release_notes += '\n\n';
        release_notes += 'included_commits:\n';
        for commit in included_commits:
            release_notes += '- {0}\n'.format(commit);
    return release_notes

def get_map_release_upload_date(release: str, repo: str, tools: MapRepoExternalTools):
    #  Get the published-at date directly from the GitHub release, and convert to YYYY-MM-DD HH:MM
    gh_release_view_result = subprocess.run([tools.gh_cli_exe, 'release', '--repo', repo, 'view', release, '--json', 'publishedAt'], check=True, stdout=subprocess.PIPE)
    fetched_release_info = json.loads(gh_release_view_result.stdout)
    # convert from ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ) to YYYY-MM-DD HH:MM:SS
    d = datetime.strptime(fetched_release_info['publishedAt'], "%Y-%m-%dT%H:%M:%SZ")
    current_upload_date = d.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    return current_upload_date

def upload_generated_releases(releases: list, repo: str, output_folder: str, dry_run: bool, tools: MapRepoExternalTools, map_repo_management_token_provider: WZGithubAppTokenProvider | None):
    
    release_upload_dates = []
    
    for release in releases:
        release_assets_dir = os.path.join(output_folder, release, 'assets')
        
        with open(os.path.join(output_folder, release, 'release.json')) as release_info_file:
            release_info = json.load(release_info_file)
        
        target_commitish = release_info['target_commitish']
        release_notes = generate_releasenotes(release, target_commitish, release_info['included_commits'])
        
        release_notes_temp_file = os.path.join(output_folder, release, 'tmp-gh-release-notes.md')
        with open(release_notes_temp_file, 'w', encoding='utf-8') as f:
            print(release_notes, file=f)
        
        # Sanity check: Verify there are actually map packages to upload
        map_packages = ['./{0}'.format(f) for f in os.listdir(release_assets_dir) if re.match(r'.*\.wz', f)]
        if not map_packages:
            raise ValueError('Error: No valid .wz map packages in folder: {0}'.format(release_assets_dir))
        
        # Sanity check: verify the release does *not* already exist
        gh_release_view_result = subprocess.run([tools.gh_cli_exe, 'release', '--repo', repo, 'view', release])
        if gh_release_view_result.returncode == 0:
            raise ValueError('Error: Release {0} already exists for repo {1}'.format(release, repo))
        
        # Create release with notes-file and uploading all *.wz in the release_assets_dir
        release_create_env = os.environ.copy()
        if map_repo_management_token_provider:
            if not dry_run:
                map_repo_split = repo.split('/', 1)
                map_push_access_token = map_repo_management_token_provider.get_access_token(map_repo_split[0], map_repo_split[1], tools)
                if not map_push_access_token:
                    return MapSubmissionApprovalResult.FAILED
                release_create_env['GH_TOKEN'] = map_push_access_token
                map_push_access_token = None
            else:
                print('DRYRUN - Would request access token from token provider')
        release_create_args = [tools.gh_cli_exe, 'release', '--repo', repo, 'create', release, '--target', target_commitish, '--notes-file', release_notes_temp_file]
        release_create_args.extend(map_packages)
        gh_release_create_result = subprocess_run_modification_cmd_wrapper(dry_run, release_create_args, stderr=subprocess.PIPE, env=release_create_env, cwd=release_assets_dir)
        if not gh_release_create_result.returncode == 0:
            subprocess_run_modification_cmd_wrapper(dry_run, [tools.gh_cli_exe, 'release', '--repo', repo, 'delete', release, '--yes'], env=release_create_env)
            raise ValueError('Error: gh release --repo {0} create {1} failed with exit code: {2}, and error: {3}'.format(repo, release, gh_release_create_result.returncode, gh_release_create_result.stderr))
        release_create_env = None
        
        # delete the temp release notes md file
        if not dry_run:
            os.remove(release_notes_temp_file)
        
        current_upload_date = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) # default to current date + time
        # Get the published-at date directly from the GitHub release, and convert to YYYY-MM-DD HH:MM:SS
        try:
           current_upload_date = get_map_release_upload_date(release, repo, tools)
        except subprocess.CalledProcessError as e:
            # Output warning, but just use current date and time...
            print('Warning: Unable to fetch publish date for release {0} in repo {1}: error code {2}'.format(release, repo, e.returncode))
        
        release_upload_dates.append(current_upload_date)
    
    return release_upload_dates


# -----------------------------

def process_map_repo(github_repo: str, repo_local_path: Path, output_temp_folder: Path, generate_release_maps_info_path=None, verbose: bool = False, dry_run: bool = False, tools: MapRepoExternalTools = MapRepoExternalTools(), map_repo_management_token_provider: WZGithubAppTokenProvider | None = None):

    if not tools.git_exe:
        raise ValueError('Failed to find git executable')
    if not tools.maptools_exe:
        raise ValueError('Failed to find maptools executable')
    if not tools.gh_cli_exe:
        raise ValueError('Failed to find gh cli')

    MAP_REPO_SPLIT = github_repo.split('/')
    if not MAP_REPO_SPLIT[0] == GITHUB_ORG:
        raise ValueError('Unexpected map repo name - expected to start with "{0}/"'.format(GITHUB_ORG))
    MAP_REPO_NAME = MAP_REPO_SPLIT[1]

    # Get the latest release from this map repo
    gh_release_latest_view_result = subprocess.run([tools.gh_cli_exe, 'release', '--repo', github_repo, 'view', '--json', 'name,tagName,targetCommitish'], stdout=subprocess.PIPE)
    if gh_release_latest_view_result.returncode == 0:
        latest_release_info = json.loads(gh_release_latest_view_result.stdout)
        last_processed_commit = latest_release_info['targetCommitish']
        last_release_version = latest_release_info['tagName']
    else:
        # The GH CLI doesn't distingush failures from "lack of any releases" (at least via exit code),
        # and we want to make sure there wasn't a network error
        # So: Double-check by requesting a list of releases - which should always succeed, even if there are no releases, and return an empty array
        gh_release_latest_view_result = subprocess.run([tools.gh_cli_exe, 'api', '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: {0}'.format(GH_REST_API_VERSION), '/repos/{0}/releases'.format(github_repo)], stdout=subprocess.PIPE)
        if gh_release_latest_view_result.returncode != 0:
            # Requesting a list of releases did not succeed - something is wrong with the network connection or the GitHub API
            # Do not (unsafely) assume that there are no releases - instead, just fail out
            raise RuntimeError('GH CLI does not appear to be functioning properly - there is probably either a network issue, or an issue with the GitHub API')
        else:
            release_list = json.loads(gh_release_latest_view_result.stdout)
            if not isinstance(release_list, list):
                raise RuntimeError('GH CLI returned unexpected result (requesting latest release failed, but requesting a list of releases returned a non-array) - possible network issue or issue with GitHub API?')
            if len(release_list) > 0:
                raise RuntimeError('GH CLI returned unexpected result (requesting latest release failed, but requesting a list of releases returned results) - possible transient network issue?')
        
        # Since we can be fairly confident that there are, in fact, no releases...
        # Get the initial (parentless) commit on the main branch
        last_processed_commit = subprocess.check_output([tools.git_exe, "rev-list", "--max-parents=0", "--branches=main", "HEAD"], cwd=repo_local_path).decode("utf-8").splitlines()[0]
        last_release_version = 'v0'

    # Generate releases in the output folder, starting with the next commit after `last_processed_commit`
    new_release_list = generate_releases_for_maprepo(repo_local_path, last_processed_commit, str(output_temp_folder), last_release_version, tools)

    # Upload the new generated releases (and packaged maps)
    release_upload_dates = upload_generated_releases(new_release_list, github_repo, str(output_temp_folder), dry_run, tools, map_repo_management_token_provider)

    if generate_release_maps_info_path:
        
        for idx, release in enumerate(new_release_list):
            release_assets_dir = os.path.join(str(output_temp_folder), release, 'assets')
            maps_info_output_dir = os.path.join(str(generate_release_maps_info_path), release)
            os.makedirs(maps_info_output_dir, exist_ok=True)
            generate_release_maps_info(release_assets_dir, MAP_REPO_NAME, release, release_upload_dates[idx], maps_info_output_dir, tools, verbose)

def main(argv):
    
    tools = MapRepoExternalTools()

    parser = argparse.ArgumentParser(description='Process a Warzone 2100 map repo, and generate new releases for any new commits (and maps)')
    parser.add_argument('MAP_GITHUB_REPO', type=str)
    parser.add_argument('MAP_REPO_LOCAL_PATH', type=Path)
    parser.add_argument('OUTPUT_TEMP_FOLDER', type=Path)
    parser.add_argument('--generateReleaseMapsInfo', type=Path)
    parser.add_argument('--dry-run', action='store_true', required=False, help='Skip actions that would modify data on any repos, logging them instead')
    args = parser.parse_args()

    process_map_repo(args.MAP_GITHUB_REPO, args.MAP_REPO_LOCAL_PATH, args.OUTPUT_TEMP_FOLDER, args.generateReleaseMapsInfo, True, args.dry_run, tools)

if __name__ == "__main__":
    main(sys.argv[1:])
