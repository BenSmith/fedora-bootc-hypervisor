# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Bootc hypervisor images** — immutable Fedora bootc OS images for a homelab virtualization host. Built as a layered chain of Containerfiles, published to `ghcr.io/bensmith/`, signed with a cosign key (not keyless OIDC) and verified against the tracked `cosign.pub` — see `docs/ci-image-signing.md`. Atomic upgrades + instant rollback via `bootc`.

The image is the *delivery vehicle* for [workloadctl](https://github.com/BenSmith/workloadctl), a standalone, RPM-packaged tool that turns `/etc/workloads.d/<name>/workload.toml` bundles into isolated rootless-podman container workloads *and* KVM/QEMU VMs, and where almost all application logic lives. It is developed, tested and released in its own repository — read that repository's CLAUDE.md and llms.txt before changing anything about workloads. This repository consumes its RPM.

## Image build chain

```
fedora-bootc-minimal (built from upstream Fedora bootc manifests)
  └── hypervisor-bootc            (hypervisor.Containerfile — full stack)
      ├── hypervisor-nvidia:rpmfusion / :negativo17
      └── hypervisor-amd
```

`fedora-versions.yml` is the single source of truth for which Fedora versions build and which is `:latest`/`stable`. The root `justfile` `{{tag}}` and `{{fedora_version}}` are derived from it (via `fedora-versions.sh`).

## How the image gets workloadctl

- **Pinned releases from Copr.** `hypervisor.Containerfile` pins `ARG WORKLOADCTL_VERSION` and `ARG MOATERY_VERSION` (moatery is the egress inspector, credential broker and DNS responder workloadctl requires). One fetch stage per project downloads the RPM from its Copr project and checks it against the key committed as `copr/<project>.gpg` (`copr/fetch`). The image installs both and caches them at `/usr/share/workloadctl/{workloadctl,moatery}.rpm`, which `workload-ensure-user` puts on a VM's seed ISO. A workloadctl release that needs a newer moatery is refused by the image's own `dnf install`.
- **Local builds.** `WORKLOADCTL_LOCAL` / `MOATERY_LOCAL` (a checkout or an RPM) on `just build-base-local` replace a fetch stage with a named build context of the stage's name.
- **Bundle images.** `.forgejo/workflows/build-workload-images.yml` builds the self-built bundles' images with workloadctl's own imagebuild, from the pinned RPM unpacked (never installed) by `.forgejo/scripts/workloadctl-root`, plus this repository's `bundles/` where it has one — a bundle of the same name replaces workloadctl's. Moving the workloadctl pin rebuilds every bundle.
- **Not yet published.** workloadctl's Copr project and key do not exist yet: until `copr/workloadctl.gpg` is committed, every image build needs `WORKLOADCTL_LOCAL`, and `tests/test_copr_pins.py`'s key check is an expected failure.

## Common commands

```bash
# --- the image's checks (tests/: Containerfiles, scripts, workflows; no podman) ---
just test

# --- image builds (root, requires podman; *-local skip the registry push) ---
just build-base-local                                   # hypervisor-bootc from local minimal
WORKLOADCTL_LOCAL=../workloadctl just build-base-local  # workloadctl from a checkout (or an RPM)
MOATERY_LOCAL=../moatery just build-base-local          # moatery from a checkout (or an RPM)
just build-nvidia-rpmfusion-local
just build-all-local
just build-iso-base                    # installer ISO
just aio-local                         # build + qcow2 + deploy to a libvirt VM
```

## Docs policy: tracked files may not cite untracked docs

A citation has to be followable from a clean checkout: don't cite a doc you intend to write later; write it, or state the fact inline instead. `tests/test_doc_citations.py` enforces this repo-wide (every `*.md` reference and every markdown link target in every tracked file must resolve to a tracked file) and runs in `just test`. workloadctl's docs are its repository's, cited by URL.

## CI

GitHub Actions (`.github/workflows/`) and a mirrored Forgejo runner (`.forgejo/workflows/`) build images daily: minimal first, then every hypervisor variant on it (07:00 UTC, midnight Pacific daylight time; GitHub chains the hypervisor build to the minimal one, Forgejo schedules it at 09:00 UTC). Note (from project memory): Forgejo itself runs in a container, so container-in-container CI builds don't work there — VM workloads exist partly to provide a native build host for that.

- `image-test.yml` (both forges) — **PR gate**: `just test`.
- `build-workload-images.yml` / `scan-images.yml` (Forgejo only) — the bundle images, built, signed and scanned from the pinned workloadctl RPM (above).
- `runtime-gate.yml` (Forgejo only) — **cadence gate**: the published image turned into a qcow2 by bootc-image-builder and booted under KVM with a swtpm vTPM, with workloadctl's runtime checks run against it, checked out at the release the image pins (`v<WORKLOADCTL_VERSION>`; workloadctl's main until that tag exists). Weekly (Tue 11:00 UTC) and on dispatch.

workloadctl's own test workflows, its dev runtime rung included, are its repository's.

<!-- rtk-instructions v2 -->
# RTK (Rust Token Killer) - Token-Optimized Commands

## Golden Rule

**Always prefix commands with `rtk`**. If RTK has a dedicated filter, it uses it. If not, it passes through unchanged. This means RTK is always safe to use.

**Important**: Even in command chains with `&&`, use `rtk`:
```bash
# ❌ Wrong
git add . && git commit -m "msg" && git push

# ✅ Correct
rtk git add . && rtk git commit -m "msg" && rtk git push
```

## RTK Commands by Workflow

### Build & Compile (80-90% savings)
```bash
rtk cargo build         # Cargo build output
rtk cargo check         # Cargo check output
rtk cargo clippy        # Clippy warnings grouped by file (80%)
rtk tsc                 # TypeScript errors grouped by file/code (83%)
rtk lint                # ESLint/Biome violations grouped (84%)
rtk prettier --check    # Files needing format only (70%)
rtk next build          # Next.js build with route metrics (87%)
```

### Test (60-99% savings)
```bash
rtk cargo test          # Cargo test failures only (90%)
rtk go test             # Go test failures only (90%)
rtk jest                # Jest failures only (99.5%)
rtk vitest              # Vitest failures only (99.5%)
rtk playwright test     # Playwright failures only (94%)
rtk pytest              # Python test failures only (90%)
rtk rake test           # Ruby test failures only (90%)
rtk rspec               # RSpec test failures only (60%)
rtk test <cmd>          # Generic test wrapper - failures only
```

### Git (59-80% savings)
```bash
rtk git status          # Compact status
rtk git log             # Compact log (works with all git flags)
rtk git diff            # Compact diff (80%)
rtk git show            # Compact show (80%)
rtk git add             # Ultra-compact confirmations (59%)
rtk git commit          # Ultra-compact confirmations (59%)
rtk git push            # Ultra-compact confirmations
rtk git pull            # Ultra-compact confirmations
rtk git branch          # Compact branch list
rtk git fetch           # Compact fetch
rtk git stash           # Compact stash
rtk git worktree        # Compact worktree
```

Note: Git passthrough works for ALL subcommands, even those not explicitly listed.

### GitHub (26-87% savings)
```bash
rtk gh pr view <num>    # Compact PR view (87%)
rtk gh pr checks        # Compact PR checks (79%)
rtk gh run list         # Compact workflow runs (82%)
rtk gh issue list       # Compact issue list (80%)
rtk gh api              # Compact API responses (26%)
```

### JavaScript/TypeScript Tooling (70-90% savings)
```bash
rtk pnpm list           # Compact dependency tree (70%)
rtk pnpm outdated       # Compact outdated packages (80%)
rtk pnpm install        # Compact install output (90%)
rtk npm run <script>    # Compact npm script output
rtk npx <cmd>           # Compact npx command output
rtk prisma              # Prisma without ASCII art (88%)
```

### Files & Search (60-75% savings)
```bash
rtk ls <path>           # Tree format, compact (65%)
rtk read <file>         # Code reading with filtering (60%)
rtk grep <pattern>      # Search grouped by file (75%). Format flags (-c, -l, -L, -o, -Z) run raw.
rtk find <pattern>      # Find grouped by directory (70%)
```

### Analysis & Debug (70-90% savings)
```bash
rtk err <cmd>           # Filter errors only from any command
rtk log <file>          # Deduplicated logs with counts
rtk json <file>         # JSON structure without values
rtk deps                # Dependency overview
rtk env                 # Environment variables compact
rtk summary <cmd>       # Smart summary of command output
rtk diff                # Ultra-compact diffs
```

### Infrastructure (85% savings)
```bash
rtk docker ps           # Compact container list
rtk docker images       # Compact image list
rtk docker logs <c>     # Deduplicated logs
rtk kubectl get         # Compact resource list
rtk kubectl logs        # Deduplicated pod logs
```

### Network (65-70% savings)
```bash
rtk curl <url>          # Compact HTTP responses (70%)
rtk wget <url>          # Compact download output (65%)
```

### Meta Commands
```bash
rtk gain                # View token savings statistics
rtk gain --history      # View command history with savings
rtk discover            # Analyze Claude Code sessions for missed RTK usage
rtk proxy <cmd>         # Run command without filtering (for debugging)
rtk init                # Add RTK instructions to CLAUDE.md
rtk init --global       # Add RTK to ~/.claude/CLAUDE.md
```

## Token Savings Overview

| Category | Commands | Typical Savings |
|----------|----------|-----------------|
| Tests | vitest, playwright, cargo test | 90-99% |
| Build | next, tsc, lint, prettier | 70-87% |
| Git | status, log, diff, add, commit | 59-80% |
| GitHub | gh pr, gh run, gh issue | 26-87% |
| Package Managers | pnpm, npm, npx | 70-90% |
| Files | ls, read, grep, find | 60-75% |
| Infrastructure | docker, kubectl | 85% |
| Network | curl, wget | 65-70% |

Overall average: **60-90% token reduction** on common development operations.
<!-- /rtk-instructions -->