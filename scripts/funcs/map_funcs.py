#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import json
import license_expression
import re
from datetime import datetime
from collections import OrderedDict

licensing = license_expression.get_spdx_licensing()
expected_license_expressions = [
    # Original license options
    licensing.parse('CC0-1.0'),
    licensing.parse('GPL-2.0-or-later'),
    licensing.parse('CC-BY-3.0 OR GPL-2.0-or-later'),
    licensing.parse('CC-BY-SA-3.0 OR GPL-2.0-or-later'),
    # Additional options
    licensing.parse('CC-BY-4.0 OR GPL-2.0-or-later'),
    licensing.parse('CC-BY-SA-4.0 OR GPL-2.0-or-later')
]

DATE_FORMAT_RE = re.compile("^(?P<year>\d{3}\d+)-(?P<month>(0[1-9])|(1[0-2]))-(?P<day>0[1-9]|[1-2][0-9]|3[0-1])( (0[1-9]|1[0-9]|2[0-3]):(0[1-9]|[1-5][0-9]):(0[1-9]|[1-5][0-9]))?")
NAME_FORMAT_RE = re.compile("^[A-Za-z0-9\-_]+$")

class MapInfoValidationResult:
    def __init__(self, warnings: list, errors: list, passedFormatChecks: bool, errors_non_fatal: list[str] = []):
        self.warnings = warnings
        self.errors = errors
        self.errors_non_fatal = errors_non_fatal
        self.passedFormatChecks = passedFormatChecks

OLD_MAX_LEVEL_NAME_SIZE = 20 # Used by old .gam files
MAX_SUGGESTED_MAP_NAME_LENGTH = 30
MAX_ALLOWED_MAP_NAME_LENGTH = 60
MAX_ALLOWED_AUTHOR_NAME_LENGTH = 60

class ValidateMapWarningOptions:
    def __init__(self, short_name_warning: bool = True, missing_created_date_warning: bool = True, zero_oil_warning: bool = True, player_structure_zero_warnings: bool = True, mods_texture_overrides_warning: bool = True, mods_auto_strip_warning: bool = True, mods_no_modtypes_warning: bool = True, format_warnings: bool = True):
        self.short_name_warning = short_name_warning
        self.missing_created_date_warning = missing_created_date_warning
        self.zero_oil_warning = zero_oil_warning
        self.player_structure_zero_warnings = player_structure_zero_warnings
        self.mods_texture_overrides_warning = mods_texture_overrides_warning
        self.mods_auto_strip_warning = mods_auto_strip_warning
        self.mods_no_modtypes_warning = mods_no_modtypes_warning
        self.format_warnings = format_warnings

def validate_map_info(map_info_json: dict, enforce_format_checks: bool=True, warning_options: ValidateMapWarningOptions = ValidateMapWarningOptions()) -> MapInfoValidationResult:
    warnings =[]
    errors = []
    errors_non_fatal = []

    # - Must have a name
    if map_info_json['name']:
        # Check name length
        name_length = len(map_info_json['name'])
        if name_length < 6:
            # warn if < 6 chars
            if warning_options.short_name_warning:
                warnings.append("'name' is less than 6 chars - consider using a longer name: ('{0}')".format(map_info_json['name']))
        if name_length > MAX_ALLOWED_MAP_NAME_LENGTH:
            # error if > MAX_ALLOWED_MAP_NAME_LENGTH chars
            errors.append("'name' is > {1} chars - use a shorter name: ('{0}')".format(map_info_json['name'], MAX_ALLOWED_MAP_NAME_LENGTH))
        elif name_length > MAX_SUGGESTED_MAP_NAME_LENGTH:
            # warn if > MAX_SUGGESTED_MAP_NAME_LENGTH
            warnings.append("'name' is > {1} chars - consider using a shorter name (longer names may be truncated): ('{0}')".format(map_info_json['name'], MAX_SUGGESTED_MAP_NAME_LENGTH))
        # Check name characters - for legacy reasons, map names should generally stick to: A-Z, a-z, 0-9, '-', '_'
        if not NAME_FORMAT_RE.match(map_info_json['name']):
            errors.append("'name' has unsupported characters - for compatibility, please stick to: A-Z, a-z, 0-9, '-', '_': ('{0}')".format(map_info_json['name']))

    # - Must have a valid type
    allowed_types = ['skirmish']
    if not map_info_json['type'] in allowed_types:
        errors.append("'type' ('{0}') is not one of the allowed values: {1}".format(map_info_json['type'], allowed_types))
 
    # - Must have players (and it must be 2-10, for a skirmish map)
    if not map_info_json['players'] in range(2, 11):
         errors.append("'players' ('{0}') is not an allowed value".format(map_info_json['players']))

    # - Must have tileset (and it should be one of the 3 known values)
    allowed_tilesets = ['arizona', 'urban', 'rockies']
    if not map_info_json['tileset'] in allowed_tilesets:
        errors.append("'tileset' ('{0}') is not one of the allowed values: {1}".format(map_info_json['tileset'], allowed_tilesets))

    # - Must have a license (and it must be a valid SPDX license identifier string)
    #     - https://github.com/nexB/license-expression
    has_valid_license = False
    if not 'license' in map_info_json:
        errors.append("Missing required 'license' key")
    else:
        try:
            parsed_license = licensing.parse(map_info_json['license'], validate=True, strict=True)
            if not any(licensing.is_equivalent(parsed_license, expected_license) for expected_license in expected_license_expressions):
                errors.append("'license' value (\"{0}\") is not in the list of expected licenses: [{1}]".format(map_info_json['license'], ', '.join('"{0}"'.format(str(w)) for w in expected_license_expressions)))
            else:
                has_valid_license = True
        except license_expression.ExpressionError as e:
            errors.append("'license' value (\"{0}\") failed SPDX license expression parsing: {1}".format(map_info_json['license'], str(e)))

    # - Must* have an author name
    #   (*treated as a non-fatal error if map has a valid license)
    if not 'author' in map_info_json:
        if 'additionalAuthors' in map_info_json:
            errors.append("Missing required 'author' key, but has 'additionalAuthors'")
        else:
            if has_valid_license:
                errors_non_fatal.append("Missing 'author' key")
            else:
                errors.append("Missing required 'author' key")
    else:
        if not 'name' in map_info_json['author']:
            errors.append("Missing required 'name' key under 'author' key")
        else:
            author_name_length = len(map_info_json['author']['name'])
            if author_name_length == 0:
                warnings.append("Empty 'name' value under 'author' key")
            elif author_name_length > MAX_ALLOWED_AUTHOR_NAME_LENGTH:
                errors.append("'author.name' is > {0} chars - use a shorter author name".format(MAX_ALLOWED_AUTHOR_NAME_LENGTH))

    # - Should have a created date
    if 'created' in map_info_json:
        # Should ideally be YYYY-MM-DD (with optional HH:MM:SS and +timezone)
        created_check_result = DATE_FORMAT_RE.match(map_info_json['created'])
        if created_check_result:
            created_datetime = datetime(int(created_check_result.group('year')), int(created_check_result.group('month')), int(created_check_result.group('day')))
            delta_now = datetime.now() - created_datetime
            if delta_now.days < -1:
                errors.append("'created' ('{0}') is in the future??", map_info_json['created'])
            if int(created_check_result.group('year')) < 1999:
                errors.append("'created' ('{0}') can't be before the creation of the game", map_info_json['created'])
        else:
            errors.append("Invalid 'created' date format: {0}".format(map_info_json['created']))
    else:
        if warning_options.missing_created_date_warning:
            warnings.append("Missing 'created' date")

    # - Must have a valid mapsize (w and h must be > 0 and < 250-something?)
    map_width = map_info_json['mapsize']['w']
    map_height = map_info_json['mapsize']['h']

    if not (1 <= map_width <= 256):
        errors.append("Invalid 'mapsize.w' ('{0}')".format(map_width))
    if not (1 <= map_height <= 256):
        errors.append("Invalid 'mapsize.h' ('{0}')".format(map_height))

    # - Should have > 0 oil wells and/or resourceExtractors (but if there are droids, theoretically there can be 0 oil wells - warn, though - this should be an extremely rare exception!)
    if not (map_info_json['oilWells'] > 0 or map_info_json['player']['resourceExtractors']['min'] > 0):
        if warning_options.zero_oil_warning:
            warnings.append("'oilWells' is 0 *AND* at least one player has no starting resourceExtractors - did you forget to add oil resources / derricks?")

    # - Should have a command center / HQ for each player
    max_players = map_info_json['players']
    if max_players >= 2:
        player_hqs = map_info_json['hq']
        for i in range(2, max_players):
            try:
                if not 'x' in player_hqs[i] or not 'y' in player_hqs[i]:
                    warnings.append('player {0} has no HQ - did you forget to add an HQ / command center?'.format(i))
            except (IndexError, TypeError):
                warnings.append('player {0} has no HQ - did you forget to add an HQ / command center?'.format(i))

    # - Check player structure type counts
    #     - Ideally a map should have some structures of each type - highlight if not
    player_counts = map_info_json['player']
    if player_counts['powerGenerators']['min'] <= 0:
        if warning_options.player_structure_zero_warnings:
            warnings.append("At least one player has no starting 'powerGenerators' on map?")
    if player_counts['regFactories']['min'] <= 0 and player_counts['vtolFactories']['min'] <= 0 and player_counts['cyborgFactories']['min'] <= 0:
        if warning_options.player_structure_zero_warnings:
            warnings.append("At least one player has no starting '*Factories' on map?")
    if player_counts['researchCenters']['min'] <= 0:
        if warning_options.player_structure_zero_warnings:
            warnings.append("At least one player has no starting 'researchCenters' on map?")

    # - Must have mapmod == false (for now) or…
    if map_info_json['mapMod'] is True:
        can_strip_mods = True
        if 'modTypes' in map_info_json:
            # - If it is a mapmod, then we can auto-strip modifications as long as modTypes:
            #     - Does not include BOTH: gamemodels and datasets
            #         - These might include additional custom models in the map, so these probably have to be map mods
            if all(item in map_info_json['modTypes'] for item in ['gamemodels', 'datasets']):
                errors.append("Conversion Error: Unable to auto-strip mods, as map-mod contains both 'gamemodels' and 'datasets' modifications")
                can_strip_mods = False
            #     - Does not include: textures
            #         - Texture overrides might be used for artist intent - need to convert these to the future texture overrides format
            if all(item in map_info_json['modTypes'] for item in ['textures']):
                if warning_options.mods_texture_overrides_warning:
                    warnings.append("Conversion Warning: Map-mod contains texture overrides")
            #     - POSSIBLE FUTURE TODO: Theoretically could check for missing stats if stats overrides are found (...)
            
            #     - We should regardless warn about what we are stripping to make a “flat” plain map
            if can_strip_mods is True:
                if warning_options.mods_auto_strip_warning:
                    warnings.append("Conversion Warning: Will auto-strip the following mods (please review): {0}".format(','.join(map_info_json['modTypes'])))
        else:
            if warning_options.mods_no_modtypes_warning:
                warnings.append("Conversion Warning: mapMod is True, but no modTypes array? (Please review!)")
    
    passedFormatChecks = True
    
    # - Must have a modern level format
    allowed_levelformats = ['json']
    if not map_info_json['levelFormat'] in allowed_levelformats:
        passedFormatChecks = False
        if enforce_format_checks:
            errors.append("Map level file format must be modern ({0})".format(', '.join(allowed_levelformats)))
        else:
            if warning_options.format_warnings:
                warnings.append("Map level file format must be modern ({0})".format(', '.join(allowed_levelformats)))
    
    # - Must be a modern mapFormat
    # (prohibited: "mixed", "binary", "jsonv1")
    allowed_mapformats = ['script', 'jsonv2']
    if not map_info_json['mapFormat'] in allowed_mapformats:
        passedFormatChecks = False
        if enforce_format_checks:
            errors.append("Map format must be modern ({0})".format(', '.join(allowed_mapformats)))
        else:
            if warning_options.format_warnings:
                warnings.append("Map format must be modern ({0})".format(', '.join(allowed_mapformats)))
    
    # - Must be a flatMapPackage
    if not map_info_json['flatMapPackage'] is True:
        passedFormatChecks = False
        if enforce_format_checks:
            errors.append("Map must be a 'flatMapPackage'")
        else:
            if warning_options.format_warnings:
                warnings.append("Map must be a 'flatMapPackage'")
    
    return MapInfoValidationResult(warnings, errors, passedFormatChecks, errors_non_fatal)

def convert_map_info_date_to_yyyy_mm_dd(map_info_date: str) -> str:
    created_check_result = DATE_FORMAT_RE.match(map_info_date)
    if not created_check_result:
        raise ValueError('Invalid map info date format: {0}'.format(map_info_date))
    
    return created_check_result.group('year')+'-'+created_check_result.group('month')+'-'+created_check_result.group('day')
        

def convert_map_info_json_to_map_database_json(map_info_json: dict) -> OrderedDict:
    output = OrderedDict()
    output['name'] = map_info_json['name']
    output['slots'] = map_info_json['players']
    output['tileset'] = map_info_json['tileset']
    if not 'additionalAuthors' in map_info_json:
        if 'author' in map_info_json:
            output['author'] = map_info_json['author']['name']
    else:
        # create a list, if multiple authors
        author_list = [map_info_json['author']['name']]
        seen_authors = set(map_info_json['author']['name'])
        for author in map_info_json['additionalAuthors']:
            author_name = author['name']
            if len(author_name) > 0 and not author_name in seen_authors:
                author_list.append(author_name)
                seen_authors.add(author_name)
        output['author'] = author_list
    output['license'] = map_info_json['license']
    if 'created' in map_info_json:
        output['created'] = convert_map_info_date_to_yyyy_mm_dd(map_info_json['created'])
    output['size'] = {'w': map_info_json['mapsize']['w'], 'h': map_info_json['mapsize']['h']}
    output['scavs'] = map_info_json['scavenger']['units'] + map_info_json['scavenger']['structures']
    output['oilWells'] = map_info_json['oilWells']
    start_equality_info = map_info_json['balance']['startEquality']
    per_player_counts = map_info_json['player']
    player_balance = OrderedDict()
    player_balance['units'] = {'eq': start_equality_info['units'], 'min': per_player_counts['units']['min'], 'max': per_player_counts['units']['max']}
    player_balance['structs'] = {'eq': start_equality_info['structures'], 'min': per_player_counts['structures']['min'], 'max': per_player_counts['structures']['max']}
    player_balance['resourceExtr'] = {'eq': start_equality_info['resourceExtractors'], 'min': per_player_counts['resourceExtractors']['min'], 'max': per_player_counts['resourceExtractors']['max']}
    player_balance['pwrGen'] = {'eq': start_equality_info['powerGenerators'], 'min': per_player_counts['powerGenerators']['min'], 'max': per_player_counts['powerGenerators']['max']}
    player_balance['regFact'] = {'eq': start_equality_info['regFactories'], 'min': per_player_counts['regFactories']['min'], 'max': per_player_counts['regFactories']['max']}
    player_balance['vtolFact'] = {'eq': start_equality_info['vtolFactories'], 'min': per_player_counts['vtolFactories']['min'], 'max': per_player_counts['vtolFactories']['max']}
    player_balance['cyborgFact'] = {'eq': start_equality_info['cyborgFactories'], 'min': per_player_counts['cyborgFactories']['min'], 'max': per_player_counts['cyborgFactories']['max']}
    player_balance['researchCent'] = {'eq': start_equality_info['researchCenters'], 'min': per_player_counts['researchCenters']['min'], 'max': per_player_counts['researchCenters']['max']}
    player_balance['defStruct'] = {'eq': start_equality_info['defenseStructures'], 'min': per_player_counts['defenseStructures']['min'], 'max': per_player_counts['defenseStructures']['max']}
    output['player'] = player_balance
    output['hq'] = [[v['x'], v['y']] if ('x' in v and 'y' in v) else [] for v in map_info_json['hq']]
    if map_info_json['mapMod']:
        output['mod'] = map_info_json['mapMod']
    # if map_info_json['mapFormat'] == 'script':
    base_download_info = {'type': map_info_json['mapFormat']}
    output['download'] = base_download_info
    return output
