#!/usr/bin/env bash
# Report-only check of a locally built OS image against Fedora's security
# advisories (audit F26):
#
#     ci-os-scan.sh LOCAL-REF
#
# Every file in the image comes from a Fedora package, so the one finding
# this repo can act on is a security update Fedora has shipped and the image
# lacks: the build is stale, and a rebuild picks the update up. dnf inside the
# image answers exactly that from Fedora's own updateinfo. A scanner's matches
# in the Go modules vendored into podman or skopeo, or in the NVD entries for
# the kernel, name nothing a rebuild or this repo can change.
#
# A missing update, or a check that could not run, is a warning in the job,
# never a failure: a failing check would hold every host's OS update.
set -uo pipefail

ref=$1
# check-upgrade exits 100 when an update is available, 0 when none is, and
# anything else when the check itself failed.
out=$(sudo podman run --rm --pull=never "$ref" sh -c '
  dnf -q check-upgrade --security >/dev/null; rc=$?
  if [ "$rc" = 100 ]; then dnf -q advisory list --security --updates; fi
  exit "$rc"' 2>&1)
rc=$?
case $rc in
  0)
    echo "${ref}: no missing security updates"
    ;;
  100)
    echo "${ref}: lacks security updates Fedora has shipped:"
    echo "$out"
    awk '$2 == "security" {print $1, $3}' <<<"$out" | sort -u |
      while read -r id severity; do
        echo "::warning::${ref}: lacks ${id} (${severity})"
      done
    ;;
  *)
    echo "$out"
    echo "::warning::could not check ${ref} against Fedora's advisories (exit ${rc})"
    ;;
esac
exit 0
