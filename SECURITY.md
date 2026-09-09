# Security Policy

## Reporting a vulnerability

**Do not open a public issue.** An issue is visible to everybody the moment it
is filed, including to anyone who would rather use the problem than fix it.

Report privately through GitHub's advisory form:

**<https://github.com/guilhermefeitosa66/OpenEmux/security/advisories/new>**

The form is private between you and the maintainer, it lets us discuss and
patch before anything is published, and it produces the advisory and the CVE
request at the end. If you cannot use it, email
**guilhermefeitosa66@gmail.com** with `OpenEmux security` in the subject.

Useful things to include: the OpenEmux version, how it was installed, the
distribution, what an attacker gains, and the smallest sequence of steps that
demonstrates it. A proof of concept is welcome but never required — a clear
description of the flaw is enough to start.

## What to expect

OpenEmux is maintained by one person in their own time, so these are honest
targets rather than a service agreement:

| Stage | Target |
| --- | --- |
| Acknowledgement that the report arrived | 7 days |
| Assessment, with a severity and a plan | 14 days |
| Fix released, for a confirmed vulnerability | 90 days |

You will be told what was decided and why, including when the conclusion is
that something is not a vulnerability. Disclosure is coordinated: the advisory
is published once a fixed release is out, and you are credited in it and in
[CONTRIBUTORS.md](CONTRIBUTORS.md) unless you ask not to be.

## Supported versions

Only the latest release receives security fixes. There are no maintenance
branches for older versions — a fix ships in the next release from `main`.

The version you are running is in the app's "About OpenEmux" dialog, under the
primary menu. Compare it against the
[latest release](https://github.com/guilhermefeitosa66/OpenEmux/releases/latest).

## Scope

**In scope**

- The OpenEmux application: `src/openemux/`, including how it builds the
  RetroArch invocation and writes the configuration it passes along.
- The packaging in `packaging/` — AppImage, `.deb`, `.rpm`, Flatpak, Arch and
  the Windows bundle — and the install scripts inside them.
- Everything the app fetches over the network and how it validates it: the
  libretro cores, shader packs and asset archives pulled from
  `buildbot.libretro.com` on first boot, the cover art synchronised from the
  libretro thumbnail repositories, and the RetroArch builds fetched by
  `scripts/vendor_retroarch.py` against the hashes pinned in
  `vendors/manifest.json`.
- The release artifacts themselves and the `SHA256SUMS` file published
  alongside them.
- The build and release workflows in `.github/workflows/`.

**Out of scope**

- RetroArch and the libretro cores. They are separate upstream projects that
  OpenEmux launches; report vulnerabilities in them to
  [libretro/RetroArch](https://github.com/libretro/RetroArch/security).
- ROMs and BIOS files. OpenEmux distributes neither, and a malicious ROM that
  compromises an emulator core is a core vulnerability, not a frontend one.
- Findings that require an attacker who already has local code execution as
  your user. At that point they can edit `~/.openemux/config.yaml` themselves.
- Reports produced by a scanner with no analysis of whether the finding is
  reachable in this application.
- The absence of a hardening measure, on its own, without a demonstrated
  impact.

## Verifying what you downloaded

Every release ships a `SHA256SUMS` covering all its artifacts. Download it next
to the file you fetched and check them together:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

The Flatpak build is published from a tagged commit through the workflow in
[openemux-flatpak](https://github.com/guilhermefeitosa66/openemux-flatpak), so
what `flatpak update` installs is built from the same tag as the release.

## How this repository is protected

So you know what an attacker would have to get past, and so a report about a
gap here is easy to write:

- `develop` and `main` require a pull request with a code-owner approval,
  require the test and security workflows to pass, dismiss approvals when new
  commits are pushed, and block force-pushes and deletion.
- Secret scanning and push protection are enabled.
- Dependabot raises alerts and opens pull requests for both the Python
  dependencies and the GitHub Actions.
- Every action in every workflow is pinned by commit SHA, not by tag.
- Workflows run with a read-only `GITHUB_TOKEN` by default, and no workflow
  uses `pull_request_target`. Workflows from an outside contributor require
  approval before they run.
- Bandit and `pip-audit` run on every push to `develop` and `main`, on every
  pull request against them, and weekly on a schedule.

Found a gap in that list? It is in scope. Report it the same way.
