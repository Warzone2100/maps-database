#!/bin/bash

# Used by various workflows in .github/workflows to install maptools
# - install folder: (pwd)/maptools-cli
# - output the install folder path to GITHUB_OUTPUT
# - prepend the install folder path to the system path (using GITHUB_PATH)

# When updating maptools, make sure all the scripts/* can handle any breaking changes
MAPTOOLS_DL_URL="https://github.com/Warzone2100/maptools-cli/releases/download/v1.3.1/maptools-linux.zip"
MAPTOOLS_DL_SHA512="272735c4f608df33fd5bcf6d105a67e8b2c4046cfb33a39e55ef18c959aa516f977ad5e4a932fe553df48f0c1e371d6786392858885cd70d5709bda8f8675948"

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
