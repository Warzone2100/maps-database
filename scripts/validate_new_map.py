#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import subprocess
import json
import os
import sys
import argparse
import requests
from collections import OrderedDict
from pathlib import Path
from funcs.map_funcs import validate_map_info, MapInfoValidationResult, ValidateMapWarningOptions
from funcs.gen_map_info import MapRepoExternalTools

GH_REST_API_VERSION = '2022-11-28'

class MapReposConfig:
    def __init__(self, map_repos_config_json_path: str):
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
            self.map_repos_config = json.load(f, object_pairs_hook=OrderedDict)
    
    # Returns a list of repos for a particular map's player count - the last returned item is the "newest" and desired place to upload a new map with that player count
    def get_repos_for_map(self, player_count: int) -> list[str]:
        key_str = str(player_count)
        if key_str in self.map_repos_config:
            return self.map_repos_config[key_str]
        else:
            return []
    
    def get_repo_for_new_map_submissions(self, player_count: int) -> str | None:
        repos = self.get_repos_for_map(player_count)
        if not repos:
            return None
        return repos[-1]

def path_exists_case_insensitive(parent_path: str, entry_name: str) -> bool:
    casefolded_entry_name = entry_name.casefold()
    with os.scandir(parent_path) as it:
        for entry in it:
            if entry.name.casefold() == casefolded_entry_name:
                return True
    return False

class MapNameUniquenessCheck:
    def __init__(self, output_temp_folder: Path, existing_local_repos: dict[str:Path] = {}):
        self.output_temp_folder = output_temp_folder
        self.existing_local_repos = existing_local_repos
    
    def check_name_unique_in_maprepos(self, map_name: str, map_repos: list[str], tools: MapRepoExternalTools) -> bool:
        # Check each map_repo for /maps/<mapName>/ presence
        # NOTE: Vulnerable to TOCTOU race conditions, but this is a "best effort" check
        for map_repo in map_repos:
            maprepo_local_path = self.get_local_map_repo_path(map_repo, tools)
            if maprepo_local_path.joinpath('maps', map_name).exists() or path_exists_case_insensitive(str(maprepo_local_path.joinpath('maps')), map_name):
                return False
        return True
    
    def get_local_map_repo_path(self, map_repo: str, tools: MapRepoExternalTools) -> Path:
        if map_repo in self.existing_local_repos:
            if self.existing_local_repos[map_repo].exists():
                return self.existing_local_repos[map_repo]
        
        maprepo_local_path = self.output_temp_folder.joinpath('map-repo', map_repo)
        os.makedirs(str(self.output_temp_folder.joinpath('map-repo')), exist_ok=True)
        if not maprepo_local_path.exists():
            if not tools.git_exe:
                raise ValueError('Failed to find git executable')
            github_map_repo_full_clone_url = 'https://github.com/{0}.git'.format(map_repo)
            git_clone_map_repo_result = subprocess.run([tools.git_exe, 'clone', '--', github_map_repo_full_clone_url, str(maprepo_local_path)], stdout=subprocess.PIPE)
            if git_clone_map_repo_result.returncode != 0:
                print('Failed to clone {0}, with error:\n{1}'.format(github_map_repo_full_clone_url, git_clone_map_repo_result.stdout), file=sys.stderr)
                raise RuntimeError('Failed to clone map repo: {0}'.format(map_repo))
        return maprepo_local_path

class MapValidationDetails:
    def __init__(self, map_info_json: OrderedDict, info_validation_result: MapInfoValidationResult, name_conflict: bool, mapdir_folder_name_mismatch: bool, players_count_mismatch: bool, enforce_format_checks: bool = True):
        self.map_info_json = map_info_json
        self.name_conflict = name_conflict
        self.mapdir_folder_name_mismatch = mapdir_folder_name_mismatch
        self.players_count_mismatch = players_count_mismatch
        self.info_validation_result = info_validation_result
        self.enforce_format_checks = enforce_format_checks
    
    def get_status_list(self) -> list[str]:
        status_list = []
        if self.players_count_mismatch:
            status_list.append('PlayersCountMismatch')
        if self.enforce_format_checks and self.needs_format_conversion():
            status_list.append('NeedsFormatConversion')
        if self.name_conflict:
            status_list.append('NameConflict')
        if self.mapdir_folder_name_mismatch:
            status_list.append('FolderNameDoesNotMatchMapName')
        if len(self.info_validation_result.errors) > 0:
            status_list.append('ValidationErrors')
        
        if len(status_list) == 0:
            status_list = ['Pass']
        
        return status_list
    
    def needs_format_conversion(self):
        return not self.info_validation_result.passedFormatChecks
    
    def passed_validation(self) -> bool:
        return self.get_status_list() == ['Pass']

class FailedToProcessMapError(ValueError): pass

def validate_map(map_path: Path, check_for_name_conflict: bool, repos_config: MapReposConfig, tools: MapRepoExternalTools, uniqueness_checker: MapNameUniquenessCheck, enforce_format_checks: bool = True, expected_players_count: int | None = None, validate_warning_options: ValidateMapWarningOptions = ValidateMapWarningOptions()) -> MapValidationDetails:
    if not tools.maptools_exe:
        raise ValueError('Failed to find maptools executable')
    
    # Extract map info json
    maptools_info_result = subprocess.run([tools.maptools_exe, 'package', 'info', '--map-seed=0', map_path], capture_output=True)
    if not maptools_info_result.returncode == 0:
        failure_details = ''
        if len(maptools_info_result.stdout) > 0:
            failure_details += '\n-----STDOUT:-----\n{0}\n----------'.format(maptools_info_result.stdout)
        if len(maptools_info_result.stderr) > 0:
            failure_details += '\n-----STDERR:-----\n{0}\n----------'.format(maptools_info_result.stderr)
        raise FailedToProcessMapError('Invalid map - maptools package info command failed with exit code: {0}{1}'.format(maptools_info_result.returncode, failure_details))
    
    # Validate map info json (ValidationErrors)
    map_info_json = json.loads(maptools_info_result.stdout, object_pairs_hook=OrderedDict)
    info_validation_result = validate_map_info(map_info_json, enforce_format_checks, warning_options=validate_warning_options)
    
    if len(maptools_info_result.stderr) > 0:
        # Prepend the errors output by maptools-cli to the info_validation_result.errors
        expanded_errors = maptools_info_result.stderr.decode('utf-8').splitlines()
        expanded_errors.extend(info_validation_result.errors)
        info_validation_result.errors = expanded_errors
    
    # Check for map_info_json['name'] conflict with existing map name (folder) in appropriate repo(s) (NameConflict)
    if check_for_name_conflict:
        name_conflict = not uniqueness_checker.check_name_unique_in_maprepos(map_info_json['name'], repos_config.get_repos_for_map(map_info_json['players']), tools)
    else:
        name_conflict = False
    
    mapdir_folder_name_mismatch = False
    if map_path.is_dir():
        # Additional check when validating an extracted map folder (for example, one added to a map repo in a PR / push)
        # 1.) Validate that the map info name matches the extracted folder name
        map_path_dir_name = map_path.name
        if map_path_dir_name != map_info_json['name']:
            mapdir_folder_name_mismatch = True
    
    players_count_mismatch = False
    if not expected_players_count is None:
        if map_info_json['players'] != expected_players_count:
            players_count_mismatch = True
    
    return MapValidationDetails(map_info_json, info_validation_result, name_conflict, mapdir_folder_name_mismatch, players_count_mismatch, enforce_format_checks)

def print_map_validation_details(map_path: Path, validation_details: MapValidationDetails):
    
    if validation_details.passed_validation():
        emoji_status_symbol = '\U00002705'
    else:
        emoji_status_symbol = '\N{cross mark}'
    
    try:
        print('## {0} Map: {1}'.format(emoji_status_symbol, validation_details.map_info_json['name']))
    except KeyError:
        print('## {0} Map: {1} (missing `name` property)'.format(emoji_status_symbol, map_path.name))
        pass
    print('- `{0}`'.format(map_path.name))
    try:
        print('- Author: `{0}`'.format(validation_details.map_info_json['author']['name']))
    except KeyError:
        print('- Author: (missing `author` property)')
        pass
    print('')
    print('### Status: {0}'.format(', '.join([f'`{status}`' for status in validation_details.get_status_list()])))
    if validation_details.passed_validation() and len(validation_details.info_validation_result.errors_non_fatal) > 0:
        print('\u26A0\uFE0F Non-Fatal Errors detected - please resolve if possible!')
    print('')
    
    if len(validation_details.info_validation_result.errors) > 0:
        print('### Errors:')
        print('```')
        print('\n'.join([f'\N{cross mark} {error}' for error in validation_details.info_validation_result.errors]))
        print('```')
        print('')
    
    if len(validation_details.info_validation_result.errors_non_fatal) > 0:
        print('### Non-Fatal Errors:')
        print('```')
        print('\n'.join([f'\u26A0\uFE0F {error}' for error in validation_details.info_validation_result.errors_non_fatal]))
        print('```')
        print('')
    
    if len(validation_details.info_validation_result.warnings) > 0:
        print('### Warnings:')
        print('```')
        print('\n'.join(validation_details.info_validation_result.warnings))
        print('```')
        print('')
    
    recommendation_lines = []
    if len(validation_details.info_validation_result.errors) > 0:
        recommendation_lines.append('- Resolve validation errors listed above')
    if len(validation_details.info_validation_result.errors_non_fatal) > 0:
        recommendation_lines.append('- Resolve non-fatal validation errors listed above, if at all possible')
    if validation_details.players_count_mismatch:
        recommendation_lines.append('- Map players ({0}) does not match expected number'.format(validation_details.map_info_json['players']))
        recommendation_lines.append('  - Are you uploading this map to the wrong map repo?')
    if validation_details.needs_format_conversion():
        recommendation_lines.append('- Convert the map to the latest format using [maptools-cli](https://github.com/Warzone2100/maptools-cli/releases/latest):')
        recommendation_lines.append('  ```')
        if map_path.is_dir():
            recommendation_lines.append('  maptools package convert --format=latest --output-uncompressed <path to original map .wz or extracted map folder> {0}'.format('maps/'+map_path.name))
        else:
            recommendation_lines.append('  maptools package convert --format=latest <path to original map .wz or extracted map folder> {0}'.format(map_path.stem+'_converted'+map_path.suffix))
        recommendation_lines.append('  ```')
    if validation_details.name_conflict:
        recommendation_lines.append('- Rename the map (conflicts with a map that already has the name "{0}")'.format(validation_details.map_info_json['name']))
        recommendation_lines.append('  - If this is a new version, you can append a version (ex. "{0}-v2")'.format(validation_details.map_info_json['name']))
        recommendation_lines.append('  - If this is a map made (or modified) by a different creator, you can prepend/append the additional author\'s name: (ex. "Author-{0}")'.format(validation_details.map_info_json['name']))
    if validation_details.mapdir_folder_name_mismatch:
        recommendation_lines.append('- Ensure the map folder matches the map name')
        recommendation_lines.append('  - i.e. A map named "{0}" should be in the repo at a path of `maps/{0}`'.format(validation_details.map_info_json['name']))
    
    if len(recommendation_lines) > 0:
        print('### Recommendations:')
        for line in recommendation_lines:
            print(line)
        print('')
    
    print('<details>')
    print('')
    print('<summary>Map Info JSON:</summary>')
    print('')
    print('```json')
    print(json.dumps(validation_details.map_info_json, ensure_ascii=False, indent=2))
    print('```')
    print('')
    print('</details>')
    

def print_multi_map_validation_details(validation_details: OrderedDict[Path, MapValidationDetails], maps_failed_processing: OrderedDict[Path, str]) -> int:
    
    failing_maps = {k:v for k, v in validation_details.items() if not v.passed_validation()}
    passing_maps = {k:v for k, v in validation_details.items() if v.passed_validation()}
    
    if len(failing_maps) == 0 and len(validation_details) > 0 and len(maps_failed_processing) == 0:
        overall_validation_status = "PASS"
        emoji_status_symbol = '\U00002705'
        ret_val = 0
    else:
        overall_validation_status = "FAILED"
        emoji_status_symbol = '\N{cross mark}'
        ret_val = 1
    
    # Overall Validation: FAILED
    print('# {0} Overall Validation: {1}'.format(emoji_status_symbol, overall_validation_status))
    
    if len(maps_failed_processing) > 0:
        print('')
        print('## Unprocessable / Invalid Maps:')
        for map_path, errorstr in maps_failed_processing.items():
            print('- `{0}`'.format(map_path.name))
    
    if len(failing_maps) < len(validation_details):
        print('')
        print('## Passing Maps:')
        for map_path, validation in passing_maps.items():
            print('- `{0}`'.format(map_path.name))
    
    if len(failing_maps) > 0:
        print('')
        print('## Failing Maps:')
        for map_path, validation in failing_maps.items():
            print('- `{0}`'.format(map_path.name))
    
    for map_path, validation in failing_maps.items():
        print('')
        print('---')
        print('')
        print_map_validation_details(map_path, validation)
    
    for map_path, validation in passing_maps.items():
        print('')
        print('---')
        print('')
        print_map_validation_details(map_path, validation)
    
    return ret_val


def validate_repo_map_list(map_repos_config_json_path: str, map_path_list: [Path], check_for_name_conflict: bool, expected_players_count: int | None, uniqueness_checker: MapNameUniquenessCheck, tools = MapRepoExternalTools()):
    validation_details = OrderedDict()
    maps_failed_processing = OrderedDict()
    repos_config = MapReposConfig(map_repos_config_json_path)
    for map_path in map_path_list:
        path_obj = Path(map_path)
        if path_obj.exists():
            try:
                validation_details[path_obj] = validate_map(path_obj, check_for_name_conflict, repos_config, tools, uniqueness_checker, enforce_format_checks=True, expected_players_count=expected_players_count)
            except FailedToProcessMapError as e:
                maps_failed_processing[path_obj] = str(e)
    
    print_multi_map_validation_details(validation_details, maps_failed_processing)
    num_failing_maps = sum(not v.passed_validation() for k, v in validation_details.items())
    return num_failing_maps if len(validation_details) > 0 else 1

def validate_single_map(map_repos_config_json_path: str, map_path: Path, check_for_name_conflict: bool, expected_players_count: int | None, uniqueness_checker: MapNameUniquenessCheck, tools = MapRepoExternalTools()):
    repos_config = MapReposConfig(map_repos_config_json_path)
    validation_details = validate_map(map_path, check_for_name_conflict, repos_config, tools, uniqueness_checker, enforce_format_checks=True, expected_players_count=expected_players_count)
    print_map_validation_details(map_path, validation_details)
    return 0 if validation_details.passed_validation() else 1

def build_uniqueness_checker(output_temp_folder: Path, local_map_repos_args_input: list[str] | None = None) -> MapNameUniquenessCheck:
    existing_local_repos = {}
    if local_map_repos_args_input:
        for entry in local_map_repos_args_input:
            split_entry = entry.split('@', 1)
            if len(split_entry) == 2:
                map_repo = split_entry[0]
                local_repo_path = Path(split_entry[1])
                if not local_repo_path.exists():
                    raise ValueError('Specified local repo path {0} does not exist'.format(local_repo_path))
                existing_local_repos[map_repo] = local_repo_path
            
    uniqueness_checker = MapNameUniquenessCheck(output_temp_folder, existing_local_repos)
    return uniqueness_checker

def validate_map_list_args_handler(args):
    # load in the map_path_list
    with open(args.map_list_file, 'r', encoding='utf-8') as f:
        map_path_list = [line.rstrip() for line in f]
        map_path_list = (item for item in map_path_list if item) # ignore any blank lines
    
    uniqueness_checker = build_uniqueness_checker(args.output_temp_folder, args.local_map_repo)
    
    return validate_repo_map_list(args.map_repos_config, map_path_list, not args.skip_uniqueness_checks, args.expected_players, uniqueness_checker)

def validate_single_map_args_handler(args):
    return validate_single_map(args.map_repos_config, args.map_path, not args.skip_uniqueness_checks, args.expected_players, build_uniqueness_checker(args.output_temp_folder, args.local_map_repo))

def main(argv):

    parser = argparse.ArgumentParser(description='Validate a map package, or map folders in a map repo PR')
    parser.add_argument('--map-repos-config', type=Path, required=True)
    parser.add_argument('--output-temp-folder', type=Path, required=True)
    parser.add_argument('--expected-players', type=int, required=False, help='Checks that each map has the specified number of players (ex. when checking new maps in a PR for a map repo)')
    parser.add_argument('--skip-uniqueness-checks', action='store_true', required=False)
    parser.add_argument('--local-map-repo', type=str, action='append', required=False, help='A locally-cloned map repo, specified as reponame@localpath (ex. "Warzone2100/maps-2p@./repos/maps-2p")')
    subparsers = parser.add_subparsers(help='sub-command')

    parser_map = subparsers.add_parser('map', help='Validate a single map (i.e. probably a map package .wz)')
    parser_map.add_argument('map_path', type=Path)
    parser_map.set_defaults(func=validate_single_map_args_handler)

    parser_map_list = subparsers.add_parser('map-list', help='Validate a list of maps (ex. a list of map folders from a PR for a map repo)')
    parser_map_list.add_argument('map_list_file', type=Path)
    parser_map_list.set_defaults(func=validate_map_list_args_handler)

    args = parser.parse_args()
    ret_val = args.func(args)

    exit(ret_val)

if __name__ == "__main__":
    main(sys.argv[1:])
