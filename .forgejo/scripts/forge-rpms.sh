#!/bin/bash
# The newest workloadctl, workloadctl-vm and moatery in REPO, a Forgejo RPM
# registry, under DEST as the build contexts that stand in for
# hypervisor.Containerfile's workloadctl and moatery stages. Prints the commit
# the workloadctl RPM names, or nothing when it names none.
#
# The registry signs its metadata, not its packages: dnf refuses metadata
# the registry's key (rpm-registry.gpg) did not sign, and a package whose
# checksum is not the one the metadata names.
#
#   bash .forgejo/scripts/forge-rpms.sh "$SERVER/api/packages/$OWNER/rpm" DEST
set -euo pipefail
repo=$1
dest=$2
key=$(realpath "$(dirname "$0")/../rpm-registry.gpg")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
# A repository dnf cannot load is otherwise skipped, and then holds nothing.
from=(-y --repofrompath="forge,$repo" --repo=forge
      --setopt=forge.skip_if_unavailable=0
      --setopt=forge.repo_gpgcheck=1 --setopt=forge.gpgcheck=0
      --setopt=forge.gpgkey="file://$key")
# workloadctl-vm requires workloadctl at its exact version and release.
vr=$(dnf repoquery -q --refresh "${from[@]}" --latest-limit=1 \
  --qf '%{version}-%{release}\n' workloadctl)
if [ -z "$vr" ]; then
  echo "::error::no workloadctl in $repo" >&2
  exit 1
fi
dnf download -q "${from[@]}" --arch=noarch --destdir="$work/rpms" \
  "workloadctl-$vr" "workloadctl-vm-$vr" moatery
mkdir -p "$dest/workloadctl" "$dest/moatery"
for pair in workloadctl-[0-9]:workloadctl/workloadctl \
            workloadctl-vm-:workloadctl/workloadctl-vm moatery-:moatery/moatery; do
  # Unquoted: workloadctl-[0-9] is a pattern. mktemp names have no spaces.
  set -- $work/rpms/${pair%%:*}*.rpm
  if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "::error::expected one ${pair%%:*}* RPM, got $#" >&2
    exit 1
  fi
  install -m 0644 "$1" "$dest/${pair#*:}.rpm"
done
rpm -qp --qf '%{VCS}' "$dest/workloadctl/workloadctl.rpm" | grep -v '^(none)$' || true
