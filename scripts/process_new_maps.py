#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import subprocess
import json
import os
import sys
import argparse
from collections import OrderedDict
from pathlib import Path
from funcs.process_map_repo import process_map_repo
from funcs.update_map_db import update_map_db, MapDBPublicURLPaths, MapDatabaseExternalTools, UpdateMapDBResult
from funcs.gh_app_token_provider import WZGithubAppTokenProvider

def load_map_repos_list(map_repos_config_json_path: str, map_db_repos_json_path: str):
    # load in map repos config
    # which takes a form like:
    # {
    #  "2": ["Warzone2100/maps-2p"],
    #  "3": ["Warzone2100/maps-3p"],
    #  ...
    # }
    # where the key is the max number of players on the map,
    # and the value is an array of map repo names (github_repo), where the last entry is the one that new maps should be added to
    with open(map_repos_config_json_path, 'r', encoding='utf-8') as f:
        map_repos_config = json.load(f, object_pairs_hook=OrderedDict)
    
    # then check the map_db_data_root for a .config/map-repos.json file
    try:
        with open(map_db_repos_json_path, 'r', encoding='utf-8') as f:
            map_repos = json.load(f, object_pairs_hook=OrderedDict)
    except FileNotFoundError:
        print ("{0} not found - initializing".format(map_db_repos_json_path))
        map_repos = []
        pass
    
    # add any missing repos from the map repos config to the map repos json, with a default version ("v0")
    missing_new_repos = [ repo for k, v in map_repos_config.items() for repo in v if not any(d['github_repo'] == repo for d in map_repos) ]
    for new_repo in missing_new_repos:
        map_repos.append({ 'github_repo': new_repo, 'last_release': 'v0' })
    
    return map_repos

def process_new_maps(map_repos_config_json_path: str, working_directory: Path, map_db_data_root: str, map_db_assets_root: str, map_db_urls: MapDBPublicURLPaths, dry_run: bool, map_repo_management_token_provider: WZGithubAppTokenProvider | None, tools = MapDatabaseExternalTools()) -> int:
    
    if not tools.git_exe:
        raise ValueError('Failed to find git executable')
    if not tools.maptools_exe:
        raise ValueError('Failed to find maptools executable')
    if not tools.gh_cli_exe:
        raise ValueError('Failed to find gh cli')
    
    parent_release_maps_info_path = os.path.join(str(working_directory), 'release-info')
    
    # load in list of map repos
    map_db_config_folder_path = os.path.join(map_db_data_root, '.config')
    map_db_repos_json_path = os.path.join(map_db_config_folder_path, 'map-repos.json')
    map_repos = load_map_repos_list(map_repos_config_json_path, map_db_repos_json_path)
    
    # publish map repo(s) new maps / releases
    for i, map_repo in enumerate(map_repos):
        github_repo = map_repo['github_repo']
        
        map_repo_local_path = os.path.join(str(working_directory), 'map-repos', github_repo)
        map_repo_output_tmp_folder = os.path.join(str(working_directory), 'temp', github_repo)
        map_repo_release_info_path = os.path.join(parent_release_maps_info_path, github_repo)
        # Clone map repo to local path
        github_repo_full_clone_url = 'https://github.com/{0}.git'.format(github_repo)
        git_clone_map_repo_result = subprocess.run([tools.git_exe, 'clone', '--', github_repo_full_clone_url, map_repo_local_path], stdout=subprocess.PIPE)
        if git_clone_map_repo_result.returncode != 0:
            print('Failed to clone {0}, with error:\n{1}'.format(github_repo_full_clone_url, git_clone_map_repo_result.stdout))
            continue
        
        print('::group::Process map repo {0}'.format(github_repo))
        process_map_repo(github_repo, Path(map_repo_local_path), Path(map_repo_output_tmp_folder), Path(map_repo_release_info_path), verbose=False, dry_run=dry_run, tools=tools, map_repo_management_token_provider=map_repo_management_token_provider)
        print('::endgroup::')
        
    # publish new map releases to map database paths
    print('::group::Update map db')
    update_map_db_result = update_map_db(map_repos, parent_release_maps_info_path, map_db_data_root, map_db_assets_root, map_db_urls, tools, dry_run=dry_run)
    print('::endgroup::')
    
    # update .config/map-repos.json
    os.makedirs(map_db_config_folder_path, exist_ok=True)
    with open(map_db_repos_json_path, 'w', encoding='utf-8') as f:
        json.dump(update_map_db_result.map_repos, f, ensure_ascii=False, indent=4)
    
    # Output information
    print('')
    print('Maps Added: {0}'.format(update_map_db_result.num_maps_added()))
    
    return update_map_db_result.num_maps_added()

def main(argv):

    parser = argparse.ArgumentParser(description='Process one or more Warzone 2100 map repos, generate new releases for any new commits (and maps), update map database repo')
    parser.add_argument('--map-repos-config', type=Path, required=True)
    parser.add_argument('--temp-working-dir', type=Path, required=True)
    parser.add_argument('--map-db-data-root', type=Path, required=True)
    parser.add_argument('--map-db-assets-root', type=Path, required=True)
    parser.add_argument('--map-db-urls-config', type=Path, required=True)
    parser.add_argument('--map-db-data-root-relurl', type=str, required=False, default='')
    parser.add_argument('--dry-run', action='store_true', required=False, help='Skip actions that would modify data on any repos, logging them instead')
    args = parser.parse_args()
    
    map_db_urls = MapDBPublicURLPaths(args.map_db_urls_config, args.map_db_data_root_relurl)
    
    map_repo_management_token_provider = None
    if all(x in os.environ for x in ['WZ_GH_APP_MAPREPO_MANAGER_APP_ID', 'WZ_GH_APP_MAPREPO_MANAGER_PRIVATE_KEY_SECRET']):
        map_repo_management_token_provider = WZGithubAppTokenProvider(os.getenv('WZ_GH_APP_MAPREPO_MANAGER_APP_ID'), os.getenv('WZ_GH_APP_MAPREPO_MANAGER_PRIVATE_KEY_SECRET').encode('utf-8'))

    num_maps_added = process_new_maps(args.map_repos_config, args.temp_working_dir, args.map_db_data_root, args.map_db_assets_root, map_db_urls, args.dry_run, map_repo_management_token_provider)

    if num_maps_added > 0:
        exit(0)
    else:
        # No maps added
        exit(1)

if __name__ == "__main__":
    main(sys.argv[1:])
