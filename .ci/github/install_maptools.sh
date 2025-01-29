#!/bin/bash

# Used by various workflows in .github/workflows to install maptools
# - install folder: (pwd)/maptools-cli
# - output the install folder path to GITHUB_OUTPUT
# - prepend the install folder path to the system path (using GITHUB_PATH)

# When updating maptools, make sure all the scripts/* can handle any breaking changes
MAPTOOLS_DL_URL="https://github.com/Warzone2100/maptools-cli/releases/download/v1.3.2/maptools-linux.zip"
MAPTOOLS_DL_SHA512="afd6f7d2b91d1917df59290e82857e9c627e97f7e59cf8e1683bb99ce4f50734f51c3c50795ef64d2742d98ad7ea3e4d68f195e9735582101f902e10fe16c9e8"

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
