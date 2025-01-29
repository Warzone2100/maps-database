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
import zipfile
from collections import OrderedDict
from pathlib import Path
from natsort import natsorted
from .map_funcs import validate_map_info, MapInfoValidationResult, convert_map_info_date_to_yyyy_mm_dd

class MapRepoExternalTools:
    def __init__(self):
        self.git_exe = shutil.which('git')
        self.gh_cli_exe = shutil.which('gh')
        self.maptools_exe = shutil.which('maptools') or shutil.which('maptools', path=os.getcwd())

def generate_map_preview_png(map_package_fullpath: str, png_output_fullpath: str, tools: MapRepoExternalTools):
    maptools_genpreview_result = subprocess.run([tools.maptools_exe, 'package', 'genpreview', '--playercolors=wz', '--map-seed=0', map_package_fullpath, png_output_fullpath], stdout=subprocess.PIPE)
    if not maptools_genpreview_result.returncode == 0:
        print('Warning: maptools package genpreview {0} command failed with exit code: {1}'.format(map_package, maptools_genpreview_result.returncode))
        return False
    
    return True

def generate_map_terrain_png(map_package_fullpath: str, png_output_fullpath: str, tools: MapRepoExternalTools):
    maptools_genpreview_result = subprocess.run([tools.maptools_exe, 'package', 'genpreview', '--layers=terrain', '--map-seed=0', map_package_fullpath, png_output_fullpath], stdout=subprocess.PIPE)
    if not maptools_genpreview_result.returncode == 0:
        print('Warning: maptools package genpreview {0} command failed with exit code: {1}'.format(map_package, maptools_genpreview_result.returncode))
        return False
    
    return True

def add_download_info_to_dict(archive_path: str, info_dict: OrderedDict):
    # Get SHA256 hash (and size) of file
    sha256_hash = hashlib.sha256()
    filesize = 0
    with open(archive_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
            filesize += len(byte_block)
    info_dict['hash'] = sha256_hash.hexdigest()
    info_dict['size'] = filesize

def generate_release_maps_info(assets_folder: str, map_repo_name: str, release_tag_name: str, release_uploaded_date: str, info_output_folder: str, tools: MapRepoExternalTools, verbose: bool = False):
    
    # Process map repo name for identifying portion
    if not map_repo_name.startswith('maps-'):
        raise ValueError('Invalid map repo name - expected to start with "maps-"')
    MAP_REPO_NAME_SUFFIX = map_repo_name.removeprefix('maps-')
    
    map_packages = [f for f in os.listdir(assets_folder) if re.match(r'.*\.wz', f)]
    
    if not map_packages:
        print('Warning: No valid .wz map packages in folder: {0}'.format(assets_folder))
        return {}
        
    map_packages = natsorted(map_packages)
    
    release_assets_info = []
    
    for map_package in map_packages:
        
        map_package_fullpath = os.path.join(assets_folder, map_package)
        
        # Extract map info
        maptools_info_result = subprocess.run([tools.maptools_exe, 'package', 'info', '--map-seed=0', map_package_fullpath], stdout=subprocess.PIPE)
        if not maptools_info_result.returncode == 0:
            print('Error: {0} - maptools package info command failed with exit code: {1}'.format(map_package, maptools_info_result.returncode))
            continue
        map_info_json = json.loads(maptools_info_result.stdout, object_pairs_hook=OrderedDict)
        
        # Validate map info
        map_validation_result = validate_map_info(map_info_json)
        if len(map_validation_result.errors) > 0:
            #print("{0}: Validation Errors: {1}".format(map_package, pprint.pformat(map_validation_result.errors)))
            print("Error: {0} - Validation Errors \n\t{1}".format(map_package, '\n\t'.join(map_validation_result.errors)))
            continue
        if len(map_validation_result.errors_non_fatal) > 0:
            print('Warning: {0} - Validation Errors (Non-Fatal): \n\t{1}'.format(map_package, '\n\t'.join(map_validation_result.errors_non_fatal)))
        if len(map_validation_result.warnings) > 0:
            print('Warning: {0} - Validation Warnings: \n\t{1}'.format(map_package, '\n\t'.join(map_validation_result.warnings)))
        
        output_map_info = OrderedDict()
        output_map_info['map_info'] = map_info_json
        
        download_info = OrderedDict()
        download_info['repo'] = MAP_REPO_NAME_SUFFIX
        download_info['path'] = '{0}/{1}'.format(release_tag_name, Path(map_package).name)
        try:
            download_info['uploaded'] = convert_map_info_date_to_yyyy_mm_dd(release_uploaded_date)
        except ValueError as e:
            print('{0}: {1}'.format(map_info_json['name'], str(e)))
        add_download_info_to_dict(map_package_fullpath, download_info)
        
        output_map_info['download'] = download_info
        
        release_assets_info.append(output_map_info)
        
        os.makedirs(os.path.join(info_output_folder, download_info['hash']), exist_ok=True)
        
        # Generate a preview PNG
        generate_map_preview_png(map_package_fullpath, os.path.join(info_output_folder, download_info['hash'], 'preview.png'), tools)
        
        # Generate a terrain PNG
        generate_map_terrain_png(map_package_fullpath, os.path.join(info_output_folder, download_info['hash'], 'terrain.png'), tools)
        
        # Extract any README.md from the map package, and copy to output folder
        with zipfile.ZipFile(map_package_fullpath) as z:
            readme_output_path = os.path.join(info_output_folder, download_info['hash'], 'README.md')
            try:
                with z.open('README.md') as zf, open(readme_output_path, 'wb') as f:
                    if verbose:
                        print('Info: Copying README.md')
                    shutil.copyfileobj(zf, f)
            except KeyError:
                pass
    
    # Write out the release map info JSON
    if verbose:
        print(json.dumps(release_assets_info, ensure_ascii=False, indent=4))
    
    with open(os.path.join(info_output_folder, 'release-map-info.json'), 'w', encoding='utf-8') as f:
        json.dump(release_assets_info, f, ensure_ascii=False, indent=4)
    
    return release_assets_info
