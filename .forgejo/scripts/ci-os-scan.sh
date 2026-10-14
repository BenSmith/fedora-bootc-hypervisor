#!/usr/bin/env bash
# Report-only grype scan of a locally built OS image (audit F26):
#
#     ci-os-scan.sh LOCAL-REF
#
# A fixable critical, a missing scanner or a scan that did not run is a
# warning in the job, never a failure: a failing scan would hold every
# host's OS update until Fedora's fix lands in a rebuild. The image is
# mounted read-only and grype reads the tree, rather than a multi-GB
# archive written out per image.
set -uo pipefail

ref=$1
here=$(dirname "$0")
if ! command -v grype >/dev/null; then
  echo "::warning::grype is not installed on the runner; ${ref} was not scanned"
  exit 0
fi
scan=$(mktemp /var/tmp/os-scan-XXXXXX.json)
trap 'sudo podman image unmount "$ref" >/dev/null 2>&1; sudo rm -f "$scan"' EXIT
if ! root=$(sudo podman image mount "$ref"); then
  echo "::warning::could not mount ${ref}; it was not scanned"
  exit 0
fi
if ! sudo grype "dir:${root}" -o json --file "$scan"; then
  echo "::warning::grype could not scan ${ref}"
  exit 0
fi
sudo chmod a+r "$scan"
python3 "${here}/ci-scan.py" report "$ref" "$scan" \
  "${here}/../cve-allowlist.txt"
exit 0
