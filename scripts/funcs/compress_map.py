#!/usr/bin/env python3
# encoding: utf-8
# Derived from: https://github.com/obfusk/apksigcopier/blob/ddc3ff189811997bf5e97dba2ae7a79dc47216e0/apksigcopier
# SPDX-License-Identifier: GPL-3.0-or-later
# Original Author: 2021 Felix C. Stegerman <flx@obfusk.net>

import os
import sys
import zipfile
import zlib

MIN_PYTHON = (3, 7)
if sys.version_info < MIN_PYTHON:
    sys.exit("Python %s.%s or later is required.\n" % MIN_PYTHON)

DATETIMEZERO = (1980, 0, 0, 0, 0, 0)

class ReproducibleZipInfo(zipfile.ZipInfo):
    """Reproducible ZipInfo hack."""

    _override = {}  # type: Dict[str, Any]

    def __init__(self, zinfo: zipfile.ZipInfo, **override):
        if override:
            self._override = {**self._override, **override}
        for k in self.__slots__:
            if hasattr(zinfo, k):
                setattr(self, k, getattr(zinfo, k))

    def __getattribute__(self, name):
        if name != "_override":
            try:
                return self._override[name]
            except KeyError:
                pass
        return object.__getattribute__(self, name)

class WZMapZipInfo(ReproducibleZipInfo):
    """Reproducible ZipInfo for WZ files."""

    _override = dict(
        compress_type=zipfile.ZIP_DEFLATED,
        create_system=0,
        create_version=20,
        date_time=DATETIMEZERO,
        external_attr=0,
        extract_version=20,
        flag_bits=0x800,
    )

def compress_map_folder(mapFolderPath: str, outputZipPath: str, hashCollisionAvoidanceSalt=None, date_time=DATETIMEZERO):
    with zipfile.ZipFile(outputZipPath, "w") as zf_out:
        # enumerate all files in the map folder
        for folder, subs, files in os.walk(mapFolderPath):
            for filename in files:
                # read in each file as binary data
                fullFilePath = os.path.join(folder, filename)
                with open(fullFilePath, 'rb') as src:
                    fileContent = src.read()
                # add to zip file:
                zf_out.writestr(WZMapZipInfo(zipfile.ZipInfo(filename=os.path.relpath(fullFilePath, mapFolderPath), date_time=date_time)), fileContent, compresslevel=9)
        if not hashCollisionAvoidanceSalt is None:
            # Output this as an additional file to ultimately affect the hash of the output zip file
            zf_out.writestr(WZMapZipInfo(zipfile.ZipInfo(filename='.map-package-disambiguate', date_time=date_time)), hashCollisionAvoidanceSalt, compresslevel=9)
