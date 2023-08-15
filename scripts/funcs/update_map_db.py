#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import subprocess
import re
import json
import os
import shutil
import string
import sys
import argparse
import time
import requests
from collections import OrderedDict
from pathlib import Path
from datetime import timezone, datetime
from .map_funcs import validate_map_info, MapInfoValidationResult, convert_map_info_json_to_map_database_json, convert_map_info_date_to_yyyy_mm_dd
from .process_map_repo import get_map_release_upload_date
from .gen_map_info import MapRepoExternalTools, generate_release_maps_info

GITHUB_ORG = 'Warzone2100'
DEFAULT_MAX_MAPS_PER_INDEX_FILE = 3000

class MapDatabaseExternalTools(MapRepoExternalTools):
    def __init__(self):
        super().__init__()
        self.pngquant_exe = shutil.which('pngquant')
        self.optipng_exe = shutil.which('optipng')

class MapDBPublicURLPaths:
    def __init__(self, map_db_urls_config_json: Path, map_db_data_root_relurl: str = ''):
        # Exposed paths (in various output)
        # The relative url path components of the map_db_data_root underneath the map_db_root
        self.map_db_data_root_relurl_components = list(filter(None, map_db_data_root_relurl.split('/')))
        
        with open(map_db_urls_config_json, 'r', encoding='utf-8') as f:
            map_db_urls_json = json.load(f, object_pairs_hook=OrderedDict)
        
        if not 'asset-url-templates' in map_db_urls_json:
            raise ValueError('Invalid / unexpected contents in: {0}'.format(str(map_db_urls_config_json)))
            
        self.asset_url_templates = map_db_urls_json['asset-url-templates']
    
    def prepend_data_root_relurl_components(self, url_components: [str]) -> [str]:
        return self.map_db_data_root_relurl_components + url_components

def compress_map_preview_png(png_fullpath: str, tools: MapDatabaseExternalTools, allowLossy=True):
    # Run pngquant (if available)
    if allowLossy and tools.pngquant_exe:
        original_png_filesize = os.stat(png_fullpath).st_size
        try_64_colors = (original_png_filesize >= 8096)
        try_256_colors = not try_64_colors
        
        if try_64_colors:
            # Try 64 colors first
            pngquant_result = subprocess.run([tools.pngquant_exe, '--force', '--skip-if-larger', '--output', png_fullpath, '--strip', '--quality', '93-100', '64', png_fullpath])
            if not pngquant_result.returncode == 0:
                try_256_colors = True
            
        if try_256_colors:
            # Try 256 colors
            pngquant_result = subprocess.run([tools.pngquant_exe, '--force', '--skip-if-larger', '--output', png_fullpath, '--strip', '--quality', '93-100', '256', png_fullpath])
    
    # Run optipng (if available)
    if tools.optipng_exe:
         optipng_result = subprocess.run([tools.optipng_exe, '-o7', png_fullpath], capture_output=True)
         if not optipng_result.returncode == 0:
             print('Warning: optipng -o7 {0} command failed with exit code: {1}'.format(png_fullpath, optipng_result.returncode))

# -----------------------------

def generate_map_info_path_components(map_hash: str, additional_map_files_dir: str):
    return [additional_map_files_dir, map_hash[:2]]
        

def merge_dicts_shallow(a, b):
    c = a.copy()
    c.update(b)
    return c

def publish_maprepo_release_to_mapassets_database(map_repo_name: str, release_tag_name: str, release_maps_info_folder: str, map_db_assets_root: str, tools: MapDatabaseExternalTools) -> list[OrderedDict]:
    
    # Read in the release-map-info.json file from the release_maps_info_folder
    with open(os.path.join(release_maps_info_folder, 'release-map-info.json'), 'r', encoding='utf-8') as f:
        releaseMapsInfo = json.load(f, object_pairs_hook=OrderedDict)
    
    maps_added = []
    
    for map_details in releaseMapsInfo:
        # Convert the map info to the map database json format, and merge in the additional download details
        map_db_formatted_info = convert_map_info_json_to_map_database_json(map_details['map_info'])
        map_db_formatted_info['download'] = merge_dicts_shallow(map_db_formatted_info['download'], map_details['download'])
        
        map_hash = map_db_formatted_info['download']['hash']
        
        api_map_info_json_components = generate_map_info_path_components(map_hash, 'info')
        map_info_file_dir = os.path.join(map_db_assets_root, *api_map_info_json_components)
        os.makedirs(map_info_file_dir, exist_ok=True)
        map_info_file_path = os.path.join(map_info_file_dir, '{0}.json'.format(map_hash))
        
        # Output the map_db_formatted_info to /<assets_dir>/info/<first two of hash>/<hash>.json
        with open(map_info_file_path, 'w', encoding='utf-8') as f:
            json.dump(map_db_formatted_info, f, ensure_ascii=False, indent=None, separators=(',', ':'))
        
        # Get the source assets dir
        source_assets_dir = os.path.join(release_maps_info_folder, map_hash)
        
        # Output the readme (if any) to /<assets_dir>/readme/<first two of hash>/<hash>.md
        api_map_readme_components = generate_map_info_path_components(map_hash, 'readme')
        map_readme_dir = os.path.join(map_db_assets_root, *api_map_readme_components)
        src_readme_path = os.path.join(source_assets_dir, 'README.md')
        if os.path.exists(src_readme_path):
            os.makedirs(map_readme_dir, exist_ok=True)
            shutil.copy2(src_readme_path, os.path.join(map_readme_dir, '{0}.md'.format(map_hash)))
        
        # Output the preview.png to /<assets_dir>/preview/<first two of hash>/<hash>.png
        api_map_preview_components = generate_map_info_path_components(map_hash, 'preview')
        map_preview_dir = os.path.join(map_db_assets_root, *api_map_preview_components)
        map_preview_png_path = os.path.join(map_preview_dir, '{0}.png'.format(map_hash))
        src_preview_path = os.path.join(source_assets_dir, 'preview.png')
        if os.path.exists(src_preview_path):
            os.makedirs(map_preview_dir, exist_ok=True)
            shutil.copy2(src_preview_path, map_preview_png_path)
            
            # Optimize the preview PNG (in-place)
            original_png_filesize = os.stat(map_preview_png_path).st_size
            compress_map_preview_png(map_preview_png_path, tools, allowLossy=True)
            resulting_png_filesize = os.stat(map_preview_png_path).st_size
            if resulting_png_filesize != original_png_filesize:
                print("Optimized PNG: {0:.3f} - {1}".format((original_png_filesize - resulting_png_filesize) / original_png_filesize, os.path.basename(map_preview_png_path)))
        else:
            print('Warning: Missing preview image: {0}'.format(map_preview_png_path))
        
        maps_added.append(map_db_formatted_info)
    
    return maps_added

class GithubAPIFetchException(Exception):
    """Exception raised for errors fetching data from GitHub API.

    Attributes:
        status_code -- status_code returned by the GitHub API
        message -- explanation of the error
    """

    def __init__(self, status_code):
        self.status_code = status_code
        self.message = 'GitHub API returned status code: {0}'.format(status_code)
        super().__init__(self.message)

def get_github_releases(github_repo, session, since_release_tag=None):
    url = "https://api.github.com/repos/"+github_repo+"/releases"
    response = session.get(url, allow_redirects=True)

    if response.status_code != 200:
        print("Failed to retrieve releases list with status_code: {}".format(response.status_code))
        raise GithubAPIFetchException(response.status_code)
    
    releases = response.json()

    if not isinstance(releases, (list, tuple)):
        print("Unexpected type returned from parsing releases list JSON: {}".format(type(releases)))
        print(releases)
        return None

    curr_page_num = 1
    while ('next' in response.links.keys()):
        print('- Fetching page ({}): {}'.format(curr_page_num, response.links['next']['url']))
        response = session.get(response.links['next']['url'], allow_redirects=True)

        if response.status_code != 200:
            print("Failed to retrieve releases list (page: {}) with status_code: {}".format(curr_page_num, response.status_code))
            raise GithubAPIFetchException(response.status_code)

        page_json = response.json()
        if not isinstance(page_json, (list, tuple)):
            print("Unexpected type returned from parsing releases list (page: {}) JSON: {}".format(curr_page_num, type(page_json)))
            print(page_json)
            return None

        releases.extend(page_json)
        curr_page_num += 1

    # sort the releases
    releases = sorted(releases, key=lambda x: datetime.strptime(x['published_at'],"%Y-%m-%dT%H:%M:%SZ")) # ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)

    if since_release_tag:
        # filter the list of releases for only the releases *since* the release tag
        # find the starting release tag (and index)
        since_release_tag_index = next((i for i, item in enumerate(releases) if item['tag_name'] == since_release_tag), None)
        if not since_release_tag_index is None:
            releases = releases[since_release_tag_index+1:]

    return releases


def publish_maprepo_new_releases_to_mapassets_database(github_repo: str, new_releases: list, map_repo_release_info_folder: str, map_db_assets_root: str, tools: MapDatabaseExternalTools) -> list[OrderedDict]:

    MAP_REPO_SPLIT = github_repo.split('/')
    if not MAP_REPO_SPLIT[0] == GITHUB_ORG:
        raise ValueError('Unexpected map repo name - expected to start with "{0}/"'.format(GITHUB_ORG))
    MAP_REPO_NAME = MAP_REPO_SPLIT[1]
    
    maps_added = []
    
    for release in new_releases:
        release_maps_info_folder = os.path.join(map_repo_release_info_folder, release)
        # Check if we already have a downloaded maps info folder for this release 
        if not os.path.isdir(release_maps_info_folder) or not os.path.exists(os.path.join(release_maps_info_folder, 'release-map-info.json')):
            temp_assets_dl_folder = os.path.join(map_repo_release_info_folder, '_tmp_assets')
            os.makedirs(temp_assets_dl_folder, exist_ok=True)
            
            # Fetch the release assets to temp_assets_dl_folder
            # NOTE: This uses the /repos/{owner}/{repo}/releases/tags/{tag} or /repos/{owner}/{repo}/releases/latest endpoints
            # Testing indicates that these should return all of the assets in the release (no pagination needed if, for example > 100)
            # gh release --repo {github_repo} download {release} --dir {temp_assets_dl_folder}
            gh_release_latest_view_result = subprocess.run([tools.gh_cli_exe, 'release', '--repo', github_repo, 'download', release, '--dir', temp_assets_dl_folder], check=True)
            
            # Get the published-at date directly from the GitHub release, and convert to YYYY-MM-DD HH:MM:SS
            release_upload_date = get_map_release_upload_date(release, github_repo, tools)
            
            # Generate the release map info
            maps_info_output_dir = os.path.join(map_repo_release_info_folder, release)
            os.makedirs(maps_info_output_dir, exist_ok=True)
            generate_release_maps_info(temp_assets_dl_folder, MAP_REPO_NAME, release, release_upload_date, maps_info_output_dir, tools)
            
            # Delete temp_assets_dl_folder
            shutil.rmtree(temp_assets_dl_folder)
        
        # Publish the release's maps to the map database
        maps_added_in_release = publish_maprepo_release_to_mapassets_database(MAP_REPO_NAME, release, release_maps_info_folder, map_db_assets_root, tools)
        
        maps_added.extend(maps_added_in_release)
    
    return maps_added

def generate_full_index_page_path_components(pagenum: int):
    # The first page is located at <data_root>/v1/full.json
    # Any additional pages are located at <data_root>/v1/full/page/<number>.json
    if pagenum > 1:
        return ['v1', 'full', 'page', '{0}.json'.format(pagenum)]
    elif pagenum == 1:
        return ['v1', 'full.json']
    else:
        raise ValueError('Invalid pagenum: {0}'.format(pagenum))

def generate_full_index_page_path(map_db_data_root: str, pagenum: int):
    rel_path_components = generate_full_index_page_path_components(pagenum)
    return os.path.join(map_db_data_root, *rel_path_components)

def map_db_full_index_pages(map_db_data_root: str):
    current_pagenum = 1
    current_path = generate_full_index_page_path(map_db_data_root, current_pagenum)
    while os.path.exists(current_path):
        yield (current_pagenum, current_path)
        current_pagenum += 1
        current_path = generate_full_index_page_path(map_db_data_root, current_pagenum)

def get_current_index_page(map_db_data_root: str):
    curr_index_pagenum = 1
    curr_index_path = generate_full_index_page_path(map_db_data_root, curr_index_pagenum)
    for pagenum, path in map_db_full_index_pages(map_db_data_root):
        curr_index_pagenum = pagenum
        curr_index_path = path
    return (curr_index_pagenum, curr_index_path)

def update_mapdatabase_versions_file(map_db_data_root: str):
    # Read in each index page, and build the versions file from the 'version' field in each page
    versions = []
    for pagenum, path in map_db_full_index_pages(map_db_data_root):
        with open(path, 'r', encoding='utf-8') as f:
            curr_index_page_json = json.load(f, object_pairs_hook=OrderedDict)
            
        page_version_info = OrderedDict()
        page_version_info['page'] = curr_index_page_json['links']['self']
        page_version_info['version'] = curr_index_page_json['version']
        
        versions.append(page_version_info)
    
    contents = OrderedDict()
    contents['type'] = 'wz2100.mapdatabase.versions.v1'
    contents['id'] = 'versions'
    contents['versions'] = versions
    
    versions_path = os.path.join(map_db_data_root, 'v1', 'versions.json')
    os.makedirs(os.path.dirname(versions_path), exist_ok=True)
    with open(versions_path, 'w', encoding='utf-8') as f:
        json.dump(contents, f, ensure_ascii=False, indent=None, separators=(',', ':'))

def initialize_new_index_page(pagenum: int, map_db_urls: MapDBPublicURLPaths):
    contents = OrderedDict()
    contents['type'] = 'wz2100.mapdatabase.full.v1'
    contents['id'] = 'full-page-' + str(pagenum)
    contents['version'] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    contents['links'] = OrderedDict()
    contents['links']['self'] = '/'+'/'.join(map_db_urls.prepend_data_root_relurl_components(generate_full_index_page_path_components(pagenum)))
    if pagenum > 1:
        contents['links']['prev'] = '/'+'/'.join(map_db_urls.prepend_data_root_relurl_components(generate_full_index_page_path_components(pagenum-1)))
    contents['asset-url-templates'] = map_db_urls.asset_url_templates
    contents['maps'] = []
    return contents

def add_to_mapdatabase_index(new_maps: list, map_db_data_root: str, map_db_urls: MapDBPublicURLPaths, max_maps_per_index_file=DEFAULT_MAX_MAPS_PER_INDEX_FILE):
    curr_index_pagenum, curr_index_path = get_current_index_page(map_db_data_root)
    
    new_maps_start = 0
    
    while new_maps_start < len(new_maps):
    
        # load in the current page
        curr_index_page_json = OrderedDict()
        if os.path.exists(curr_index_path):
            with open(curr_index_path, 'r', encoding='utf-8') as f:
                curr_index_page_json = json.load(f, object_pairs_hook=OrderedDict)
        else:
            curr_index_page_json = initialize_new_index_page(curr_index_pagenum, map_db_urls)
    
        num_maps_in_page = len(curr_index_page_json['maps'])
    
        # add the new maps to the "maps" array (paying attention to the limit)
        new_maps_end = min(new_maps_start + max_maps_per_index_file, len(new_maps))
        curr_index_page_json['maps'].extend(new_maps[new_maps_start:new_maps_end])
        new_maps_start = new_maps_end
        
        curr_index_page_json['version'] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        if new_maps_start < len(new_maps):
            # will end up creating another page, so add the "links/next" entry to this one
            curr_index_page_json['links']['next'] = '/'+'/'.join(map_db_urls.prepend_data_root_relurl_components(generate_full_index_page_path_components(curr_index_pagenum+1)))
            
        # write out the current page
        os.makedirs(os.path.dirname(curr_index_path), exist_ok=True)
        with open(curr_index_path, 'w', encoding='utf-8') as f:
            json.dump(curr_index_page_json, f, ensure_ascii=False, indent=None, separators=(',', ':'))
        
        # increment some variables, in case we need to create a new index page
        curr_index_pagenum += 1
        curr_index_path = generate_full_index_page_path(map_db_data_root, curr_index_pagenum)
    
    # update the versions.json file to match the updated index pages
    update_mapdatabase_versions_file(map_db_data_root)

def rebuild_mapdatabase_index(map_db_data_root: str, map_db_assets_root: str, max_maps_per_index_file=DEFAULT_MAX_MAPS_PER_INDEX_FILE):
    # Enumerates the map database index files, and copies over the latest map info json for each map (preserving the existing order of the maps in the index files)
    
    for curr_index_pagenum, curr_index_path in map_db_full_index_pages(map_db_data_root):
        
        # load in the current page
        with open(curr_index_path, 'r', encoding='utf-8') as f:
            curr_index_page_json = json.load(f, object_pairs_hook=OrderedDict)
        
        for index, map_item in enumerate(curr_index_page_json['maps']):
            # Read in the separate map json file
            map_hash = map_item['download']['hash']
            api_map_info_json_components = generate_map_info_path_components(map_hash, 'info')
            map_info_file_path = os.path.join(os.path.join(map_db_assets_root, *api_map_info_json_components), '{0}.json'.format(map_hash))
            try:
                with open(map_info_file_path, 'r', encoding='utf-8') as f:
                    latest_map_data_json = json.load(f, object_pairs_hook=OrderedDict)
                
                # Update the data in the index file
                curr_index_page_json['maps'][index] = latest_map_data_json
                
            except FileNotFoundError as e:
                print('Error: Missing expected file (skipping update): {0}'.format(map_info_file_path))
        
        curr_index_page_json['version'] = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        
        # write out the current page
        os.makedirs(os.path.dirname(curr_index_path), exist_ok=True)
        with open(curr_index_path, 'w', encoding='utf-8') as f:
            json.dump(curr_index_page_json, f, ensure_ascii=False, indent=None)
    
    # update the versions.json file to match the updated index pages
    update_mapdatabase_versions_file(map_db_data_root)

def publish_map_releases_to_mapdatabase(map_repos: list, map_repo_new_releases: list, parent_release_maps_info_folder: str, map_db_data_root: str, map_db_assets_root: str, map_db_urls: MapDBPublicURLPaths, tools: MapDatabaseExternalTools) -> list[OrderedDict]:

    maps_added = []

    for i, map_repo in enumerate(map_repos):
        github_repo = map_repo['github_repo']
        map_repo_last_release_processed = 'v0'
        if 'last_release' in map_repo:
            map_repo_last_release_processed = map_repo['last_release']
        new_releases = map_repo_new_releases[i]
        
        map_repo_release_info_folder = os.path.join(parent_release_maps_info_folder, github_repo)
        
        maps_added_from_this_repo = publish_maprepo_new_releases_to_mapassets_database(github_repo, new_releases, map_repo_release_info_folder, map_db_assets_root, tools)
        
        maps_added.extend(maps_added_from_this_repo)
    
    # Take the maps added, and add to the map database index
    add_to_mapdatabase_index(maps_added, map_db_data_root, map_db_urls)
    
    return maps_added
    

class UpdateMapDBResult:
    def __init__(self, updated_map_repos: list, maps_added: list[OrderedDict]):
        self.map_repos = updated_map_repos
        self.maps_added = maps_added
    
    def num_maps_added(self) -> int:
        return len(self.maps_added)
    
    def maps_added_names(self) -> list[str]:
        return [info['name'] for info in self.maps_added]

def update_map_db(map_repos: list, parent_release_maps_info_folder: str, map_db_data_root: str, map_db_assets_root: str, map_db_urls: MapDBPublicURLPaths, tools: MapDatabaseExternalTools, dry_run: bool = False):
    
    if not tools.pngquant_exe:
        print('Warning: pngquant not found, map png previews will not be fully optimized')
    
    if not tools.optipng_exe:
        print('Warning: optipng not found, map png previews will not be fully optimized')
    
    github_token = os.getenv("GH_TOKEN", default=None)
    session = requests.Session()
    session.headers.update({'Accept': 'application/vnd.github+json'})
    session.headers.update({'X-GitHub-Api-Version': '2022-11-28'})
    # If specified, set up authorization with GH_TOKEN (increases rate limits)
    if github_token is not None:
        session.headers.update({"Authorization": "Bearer " + github_token})
    
    map_repo_new_releases = []
    
    for i, map_repo in enumerate(map_repos):
        github_repo = map_repo['github_repo']
        map_repo_last_release_processed = 'v0'
        if 'last_release' in map_repo:
            map_repo_last_release_processed = map_repo['last_release']
        
        # Get list of all releases in this map repo since map_repo_last_release_processed
        try:
            new_release_tags = []
            new_releases = get_github_releases(github_repo, session, map_repo_last_release_processed)
            if new_releases:
                # Ensure that are sorted in *ascending* order (by published_at) - oldest first, latest last
                new_releases = sorted(new_releases, key=lambda x: datetime.strptime(x['published_at'],"%Y-%m-%dT%H:%M:%SZ")) # ISO 8601 format (YYYY-MM-DDTHH:MM:SSZ)
        
                # Extract just the tag_name from each release
                new_release_tags = [release['tag_name'] for release in new_releases]
            
            if dry_run:
                # Enumerate the map_repo_release_info_folder to get the on-disk releases (which haven't been persisted)
                on_disk_releases = []
                if os.path.exists(os.path.join(parent_release_maps_info_folder, github_repo)):
                    on_disk_releases = [f.name for f in os.scandir(os.path.join(parent_release_maps_info_folder, github_repo)) if f.is_dir()]
                try:
                    on_disk_releases = sorted(on_disk_releases, key=lambda x: int(x[1:]))
                    if map_repo_last_release_processed:
                        # filter the list of releases for only the releases *since* the last release processed
                        # find the starting release tag (and index)
                        since_release_tag_index = next((i for i, item in enumerate(on_disk_releases) if item == map_repo_last_release_processed), None)
                        if not since_release_tag_index is None:
                            on_disk_releases = on_disk_releases[since_release_tag_index+1:]
                    new_release_tags.extend(on_disk_releases)
                except ValueError as e:
                    print('Failed to sort on-disk releases - something seems to have gone wrong: {0}'.format(str(on_disk_releases)))
            
            map_repo_new_releases.append(new_release_tags)
        except GithubAPIFetchException as e:
            print('Error: Failed to get release list from GitHub API for repo {0} with error: {1} - skipping this repo'.format(map_repo, e))
            map_repo_new_releases.append([])
            continue
        
    print(map_repo_new_releases)
    
    # publish the new releases for each map repo
    maps_added = publish_map_releases_to_mapdatabase(map_repos, map_repo_new_releases, parent_release_maps_info_folder, map_db_data_root, map_db_assets_root, map_db_urls, tools)
    
    # Update the 'last-release' entry in map-repos.json for every repo
    new_last_releases = [item[-1] if item else None for item in map_repo_new_releases]
    for i, map_repo in enumerate(map_repos):
        if new_last_releases[i] is not None:
            map_repos[i]['last_release'] = new_last_releases[i]
    
    return UpdateMapDBResult(map_repos, maps_added)

