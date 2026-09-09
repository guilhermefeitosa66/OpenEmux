# Contributing to OpenEmux

OpenEmux is a Linux-native emulation frontend, and it is shaped as much by the
people who report bugs, test releases and ask for the right feature as by the
people who write the code. Everyone who sets a change in motion is credited —
see [CONTRIBUTORS.md](CONTRIBUTORS.md) for how that is recorded.

This file describes the *process*. For how to install the dependencies, run the
app, build the packages or develop on Windows, read the
[Developer Guide](docs/DEVELOPMENT.md); nothing here repeats it.

## Ways to contribute

You do not need to write Python to help.

- **Report a bug.** Use the bug form under
  [New issue](https://github.com/guilhermefeitosa66/OpenEmux/issues/new/choose).
  It asks for the version, the distribution, the package format and the
  start-up log, because those four answers decide whether a report can be
  reproduced or not.
- **Test a release.** Install a fresh release, run through your own library and
  write down what broke. The most valuable reports this project ever received
  were exactly that: one person going through the whole app end to end and
  describing each step.
- **Suggest a feature.** Say what you were trying to do and what stopped you.
  A described problem survives longer than a proposed solution.
- **Translate.** The app ships German, English, Spanish, French, Japanese,
  Brazilian Portuguese, Tamil and Simplified Chinese, in
  `src/openemux/i18n/locales/`. Each locale is a flat Python `dict` keyed by
  string id, with English as the source of truth. Use the translation form to
  claim a language.
- **Write code.** Read the rest of this file first.

Questions about *using* OpenEmux belong in
[Discussions](https://github.com/guilhermefeitosa66/OpenEmux/discussions) or on
[r/OpenEmux](https://www.reddit.com/r/OpenEmux/), not in the issue tracker.

## Before you write code

**Open an issue first, and wait for a reply.** This is not bureaucracy: the
project has a roadmap on a public
[board](https://github.com/users/guilhermefeitosa66/projects/1), and a pull
request that arrives without one may be duplicating work already in flight or
solving a problem in a direction the project has already ruled out. An issue
costs you five minutes; a rejected pull request costs you an evening.

Issues labelled [`good first issue`](https://github.com/guilhermefeitosa66/OpenEmux/labels/good%20first%20issue)
are scoped so that you can finish one without knowing the rest of the codebase.

## The branch model

Two branches are permanent and never deleted:

- **`main`** — released code only. It moves solely through a release pull request.
- **`develop`** — the integration branch, and the repository's default branch.
  All day-to-day work lands here.

Release branches (`release/vX.Y.Z`) are also kept, one per released version.
Everything else is disposable and is deleted as soon as its pull request merges.

So: fork the repository, branch off an up-to-date `develop`, and open your pull
request **against `develop`**. A pull request against `main` will be asked to
retarget. Name the branch for what it does — `feat/…`, `fix/…`, `chore/…`.

Both `develop` and `main` are protected. Nobody commits to them directly, the
maintainer included.

## Commits

Every commit message starts with the issue reference, then follows
[Conventional Commits](https://www.conventionalcommits.org/):

```
[issue-<id>] <type>: <summary>
```

`<type>` is one of `feat`, `fix`, `refactor`, `chore`, `docs`, `test`. Work with
no issue behind it — a release, a small chore — uses `[no-issue]` in the same
slot.

```
[issue-45] feat: choose the libretro core per console
[issue-32] fix: capture gamepad input exclusively while remapping
[no-issue] chore: release 1.7.0
```

One logical change per commit. Write the summary in the imperative, in English:
every project-facing text in this repository is English, whatever language the
conversation around it happened in.

## What a complete pull request contains

**Tests pass.** The suite is `unittest`, it lives in `tests/`, and each
`test_<module>.py` covers the matching module in `src/openemux/core/`:

```bash
make test
```

Continuous integration also runs correctness-only lint (`make lint`), the suite
on Python 3.10 through 3.13, the suite under MSYS2 on Windows, a headless
start-up smoke test, Bandit and `pip-audit`. Coverage has a floor, so a change
that drops the total below it fails the build rather than moving the badge
quietly.

**The regression test book is updated.** `tests/regression/TESTBOOK.md` is the
manual-QA suite, and any pull request that adds, changes or removes
*user-facing behavior* must update it in the same pull request: add scenarios
for new behavior, edit the ones your change affects, retire — never delete —
the ones for behavior you removed. The file's own header carries the rules and
the scenario template. A behavior change with no test-book change is an
incomplete pull request.

**The user interface was actually looked at.** The unit suite cannot build most
GTK widgets, so a change to `src/openemux/ui/` has to be run. `devbox/` exists
for exactly this: a container with an X server of its own, so testing the app
does not take over your desktop.

```bash
make devbox-up && make devbox-app && make devbox-shot OUT=/tmp/shot.png
```

**The description says what changed and why.** Reference the issue in prose —
`Related to #123` — and do not use GitHub's closing keywords (`Closes`,
`Fixes`, `Resolves`). Issues in this repository stay open after the merge so
they can be verified in review; a closing keyword skips that step.

## Code conventions

- **User interface and logic stay apart.** GTK and libadwaita code lives in
  `src/openemux/ui/`, everything else in `src/openemux/core/`. A core module
  must never import `gi`.
- PEP 8 naming: `snake_case` for functions and variables, `PascalCase` for
  classes.
- **No formatter is configured, and lint carries no style rules.** Do not
  reformat code you are not otherwise changing — it buries the actual change in
  a diff nobody can review.
- Console identifiers are the short canonical ones defined in
  `src/openemux/core/systems.py` (`FC`, `SFC`, `GBA`, `MD`, …). Always pass
  user or config input through `resolve_system_id()` first.
- Comments explain *why*, not *what*. The existing ones are the model: most of
  them name the failure that made the line necessary.

## Review

The maintainer reviews every pull request; `.github/CODEOWNERS` assigns every
path, so a code-owner approval is required before anything merges. Expect a
first response within about a week. If it has been longer, a comment on the
pull request is welcome and will not annoy anybody.

Approvals are dismissed when new commits are pushed, so a review that arrives
after you push again will need to be redone. Push your fixes in a batch rather
than one commit at a time.

Merges are squash merges, which means the pull request title becomes the commit
message on `develop`. Give it the same shape as a commit message.

## Credit

If your issue, suggestion, diagnosis, reproduction or proof of concept produced
a change, you get a `Co-authored-by` trailer on the commit and an entry in
[CONTRIBUTORS.md](CONTRIBUTORS.md), whether or not you wrote the code. That
applies to reports that arrive through Reddit or the Diolinux Plus forum too.

## Conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Security

Do not open a public issue for a vulnerability. [SECURITY.md](SECURITY.md)
describes the private channel.

## Licence

OpenEmux is MIT licensed. Contributing means agreeing that your contribution
ships under the same terms.
