# Fedora bootc minimal plus workloadctl, its VM tools and moatery, from their
# Copr projects, and what the minimal base lacks to run them and the bundles
# workloadctl ships. Freestanding: it reads nothing from the build context, so
# it builds from an empty directory:
#
#   podman build -f workload-host.Containerfile -t workload-host "$(mktemp -d)"
ARG FEDORA_VERSION=44
FROM ghcr.io/bensmith/fedora-bootc-minimal:${FEDORA_VERSION}

LABEL org.opencontainers.image.title="Workload host bootc image"
LABEL org.opencontainers.image.description="Fedora bootc minimal with workloadctl, its VM tools and moatery"

# The base has no dnf copr plugin, so it comes first.
# NetworkManager because the base configures no network at all.
# The SELinux policy store is copied into this layer first: Fedora 44's
# libsemanage cannot rename a directory in a lower overlay layer, and its
# fallback can break the store, which drops the modules workloadctl's %post
# loads without failing the install.
RUN <<'EOF'
set -eu
dnf install -y dnf5-plugins
dnf copr enable -y benjamin-coder-smith/workloadctl
dnf copr enable -y benjamin-coder-smith/moatery
cp -a /etc/selinux/targeted /etc/selinux/.targeted
rm -rf /etc/selinux/targeted
mv /etc/selinux/.targeted /etc/selinux/targeted
dnf install -y workloadctl workloadctl-vm NetworkManager
dnf clean all
EOF

# Workloads publish DNS, HTTP and SMB as their own unprivileged users, and by
# default the kernel lets no unprivileged user bind a port below 1024.
COPY <<'EOF' /usr/lib/sysctl.d/50-privileged-ports.conf
net.ipv4.ip_unprivileged_port_start = 0
EOF

# The game-streaming workloads synthesize input through /dev/uinput, as a user
# in the uinput group, which opens it and the input nodes it makes but not the
# host's own keyboards and mice.
COPY <<'EOF' /usr/lib/modules-load.d/uinput.conf
uinput
EOF
COPY <<'EOF' /usr/lib/udev/rules.d/72-uinput-input.rules
KERNEL=="uinput", GROUP="uinput", MODE="0660"
SUBSYSTEM=="input", DEVPATH=="/devices/virtual/input/*", KERNEL=="event*|js*|mouse*", GROUP="uinput", MODE="0660"
EOF
COPY <<'EOF' /usr/lib/sysusers.d/uinput.conf
g uinput - -
EOF

# pasta's loopback splice path stalls a connection whose reader applies
# backpressure, such as a reverse proxy in front of a registry, at a few MB/s.
COPY <<'EOF' /etc/containers/containers.conf.d/10-pasta-no-splice.conf
[network]
pasta_options = ["--no-splice"]
EOF

# The hypervisor hosts' container signature policy, in place of the minimal
# base's, which refuses every registry but ghcr.io and registry.local: a
# workload pulling from docker.io, quay.io or the like could not start. Images
# from ghcr.io/bensmith and registry.local must carry a sigstore signature by
# the key the base ships in /etc/pki/containers/cosign.pub; the public
# registries the bundles pull from are accepted as they are; anything else is
# refused.
COPY <<'EOF' /etc/containers/policy.json
{
  "default": [{"type": "reject"}],
  "transports": {
    "docker": {
      "ghcr.io/bensmith": [{"type": "sigstoreSigned", "keyPath": "/etc/pki/containers/cosign.pub", "signedIdentity": {"type": "matchRepository"}}],
      "registry.local": [{"type": "sigstoreSigned", "keyPath": "/etc/pki/containers/cosign.pub", "signedIdentity": {"type": "matchRepository"}}],
      "docker.io": [{"type": "insecureAcceptAnything"}],
      "ghcr.io": [{"type": "insecureAcceptAnything"}],
      "quay.io": [{"type": "insecureAcceptAnything"}],
      "codeberg.org": [{"type": "insecureAcceptAnything"}],
      "mcr.microsoft.com": [{"type": "insecureAcceptAnything"}],
      "registry.fedoraproject.org": [{"type": "insecureAcceptAnything"}]
    },
    "containers-storage": {"": [{"type": "insecureAcceptAnything"}]},
    "docker-archive": {"": [{"type": "insecureAcceptAnything"}]},
    "oci-archive": {"": [{"type": "insecureAcceptAnything"}]},
    "docker-daemon": {"": [{"type": "insecureAcceptAnything"}]}
  }
}
EOF

# podman fetches those signatures from the registry itself, where CI pushes
# them; without this a signed image, this one's own upgrades included, fails
# verification.
COPY <<'EOF' /etc/containers/registries.d/ghcr.io.yaml
docker:
  ghcr.io:
    use-sigstore-attachments: true
EOF
COPY <<'EOF' /etc/containers/registries.d/registry-local.yaml
docker:
  registry.local:
    use-sigstore-attachments: true
EOF

# Fail the build if the SELinux policy store lacks a module the installed
# packages load. dnf does not fail a transaction whose %post failed, so a
# module semodule could not load leaves a green build and an image without it.
# The expected set is derived from what the packages ship: compiled modules
# under /usr/share/selinux/packages, and the CIL modules workloadctl's %post
# loads from /usr/share/workloadctl, each named for its file.
RUN <<'EOF'
set -eu
fail=0
for debris in /etc/selinux/targeted/tmp /etc/selinux/targeted/previous; do
    if [ -e "$debris" ]; then
        echo "$debris exists: a semodule transaction did not complete" >&2
        fail=1
    fi
done
modules=$(semodule -l)
for file in /usr/share/selinux/packages/*.pp /usr/share/selinux/packages/*.pp.bz2 \
            /usr/share/selinux/packages/targeted/*.pp \
            /usr/share/selinux/packages/targeted/*.pp.bz2 \
            /usr/share/workloadctl/*.cil; do
    [ -e "$file" ] || continue
    name=${file##*/}
    name=${name%.cil}
    name=${name%%.pp*}
    if ! printf '%s\n' "$modules" | grep -qx "$name"; then
        echo "SELinux module $name is not in the policy store (shipped as $file)" >&2
        fail=1
    fi
done
[ "$fail" -eq 0 ]
echo "SELinux policy store OK ($(printf '%s\n' "$modules" | wc -l) modules)"
EOF

RUN bootc container lint
