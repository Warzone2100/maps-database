#!/usr/bin/env python3
# encoding: utf-8
# SPDX-FileCopyrightText: 2023 past-due <https://github.com/past-due>
# SPDX-License-Identifier: GPL-2.0-or-later

import jwt # PyJWT
import requests
import subprocess
import time
import sys
import json
from .gen_map_info import MapRepoExternalTools

GH_REST_API_VERSION = '2022-11-28'

class WZGithubAppTokenProvider:
    def __init__(self, app_id: str, private_key: bytes):
        self.__app_id = app_id
        self.__private_key = private_key
        
    def get_access_token(self, gh_org: str, gh_repo_name: str, tools: MapRepoExternalTools):
        if not self.__private_key:
            return None
        
        payload = {
            # Issued at time
            'iat': int(time.time()),
            # JWT expiration time (10 minutes maximum - use 2 minutes)
            'exp': int(time.time()) + 120,
            # GitHub App's identifier
            'iss': str(self.__app_id)
        }
        app_encoded_jwt = jwt.encode(payload, self.__private_key, algorithm="RS256")
        
        session = requests.Session()
        
        authorized_headers = {}
        authorized_headers.update({'Accept': 'application/vnd.github+json'})
        authorized_headers.update({'Authorization': 'Bearer ' + app_encoded_jwt})
        authorized_headers.update({'X-GitHub-Api-Version': GH_REST_API_VERSION})
        
        installation_query_response = session.get('https://api.github.com/repos/{0}/{1}/installation'.format(gh_org, gh_repo_name), allow_redirects=True, headers=authorized_headers)
        if installation_query_response.status_code != requests.codes.ok:
            print('Failed getting installation for {0}/{1}, with error: {2}'.format(gh_org, gh_repo_name, installation_query_response.status_code), file=sys.stderr)
            return None
        try:
            installation_id = installation_query_response.json()['id']
        except ValueError:
            print('Failed to parse response for installation id: repos/{0}/{1}/installation'.format(gh_org, gh_repo_name), file=sys.stderr)
            return None
        
        # Get repository id
        # Use GH CLI to take advantage of any configured general access token
        gh_repo_get_result = subprocess.run([tools.gh_cli_exe, 'api', '-H', 'Accept: application/vnd.github+json', '-H', 'X-GitHub-Api-Version: {0}'.format(GH_REST_API_VERSION), '/repos/{0}/{1}'.format(gh_org, gh_repo_name)], stdout=subprocess.PIPE)
        if not gh_repo_get_result.returncode == 0:
            print('Failed to get repository id for: {0}/{1}'.format(gh_org, gh_repo_name), file=sys.stderr)
            return None
        try:
            repository_id = int(json.loads(gh_repo_get_result.stdout)['id'])
        except ValueError:
            print('Failed to parse repo info for repository id: {0}/{1}'.format(gh_org, gh_repo_name), file=sys.stderr)
            return None
        
        limit_scope_json = {'repository_ids': [repository_id]}
        get_access_tokens_response = requests.post('https://api.github.com/app/installations/{0}/access_tokens'.format(installation_id), json=limit_scope_json, headers=authorized_headers)
        if not get_access_tokens_response.ok: # likely returns 201, so just check for any "okay" response (i.e. < 400)
            print('Failed calling: api.github.com/app/installations/{0}/access_tokens, with error: {1}'.format(installation_id, get_access_tokens_response.status_code), file=sys.stderr)
            return None
        try:
            app_installation_token = get_access_tokens_response.json()['token']
        except ValueError:
            print('Failed to parse access_tokens info for installation associated with: {0}/{1}'.format(gh_org, gh_repo_name), file=sys.stderr)
            return None
        
        authorized_headers.clear()
        session.close()
        return app_installation_token
