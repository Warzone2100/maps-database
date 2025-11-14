#!/bin/bash

# Used by various workflows in .github/workflows to install maptools
# - install folder: (pwd)/maptools-cli
# - output the install folder path to GITHUB_OUTPUT
# - prepend the install folder path to the system path (using GITHUB_PATH)

# When updating maptools, make sure all the scripts/* can handle any breaking changes
MAPTOOLS_DL_URL="https://github.com/Warzone2100/maptools-cli/releases/download/v1.4.4/maptools-linux.zip"
MAPTOOLS_DL_SHA512="e8c28a292092f198fe2b5980202e5d4288544146d0c8f1b4b30b600553d8e9b9d146fbfbf50f9590cd1f4ef3ec9d3d6fe2873132f346fd37618c81f5ec64efe9"

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
