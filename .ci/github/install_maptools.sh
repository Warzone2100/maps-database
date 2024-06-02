#!/bin/bash

# Used by various workflows in .github/workflows to install maptools
# - install folder: (pwd)/maptools-cli
# - output the install folder path to GITHUB_OUTPUT
# - prepend the install folder path to the system path (using GITHUB_PATH)

# When updating maptools, make sure all the scripts/* can handle any breaking changes
MAPTOOLS_DL_URL="https://github.com/Warzone2100/maptools-cli/releases/download/v1.2.5/maptools-linux.zip"
MAPTOOLS_DL_SHA512="41a0f44cac63e4d6bafa1996a1bad73fc7ed9fb84076589afceb80876326c2c77e19ff32015b47c453d12eac7b1a6586f70fc8cb0a27d75fa5deb62c106eb1d1"

curl -L --retry 3 --output "maptools-linux.zip" "${MAPTOOLS_DL_URL}"
DL_SHA512=$(sha512sum --binary "maptools-linux.zip" | cut -d " " -f 1)
if [ "${DL_SHA512}" != "${MAPTOOLS_DL_SHA512}" ]; then
  echo "::error::maptools download has wrong hash (received: ${DL_SHA512}, expecting: ${MAPTOOLS_DL_SHA512})"
  exit 1
fi
unzip "maptools-linux.zip" -d "maptools-cli"
rm "maptools-linux.zip"
MAPTOOLS_BIN_DIR="$(pwd)/maptools-cli"
echo "MAPTOOLS_BIN_DIR=${MAPTOOLS_BIN_DIR}"
echo "MAPTOOLS_BIN_DIR=${MAPTOOLS_BIN_DIR}" >> "$GITHUB_OUTPUT"
"${MAPTOOLS_BIN_DIR}/maptools" --version
echo "${MAPTOOLS_BIN_DIR}" >> $GITHUB_PATH
