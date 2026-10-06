<!--
Base this on `develop`, not `main`. `main` only ever moves through a release PR.
Give the PR title the shape of a commit message: [issue-<id>] <type>: <summary>
-->

## What this changes

<!-- What the change does and, more importantly, why. If it fixes a bug, say
     what the broken behavior was, so the diff can be read against it. -->

## Related issue

<!-- Reference it in prose: "Related to #123".

     Do NOT write "Closes #123", "Fixes #123" or "Resolves #123". Issues in
     this repository stay open after the merge so the change can be verified in
     review; a closing keyword skips that step. -->

Related to #

## How it was verified

<!-- What you actually ran or looked at. "CI is green" is not this section:
     the suite cannot build most GTK widgets, so a UI change has to have been
     seen running. `make devbox-app` starts it on its own X server without
     taking over your desktop. Screenshots are welcome — before and after
     if the change is visual. -->

## Checklist

- [ ] Targets `develop`.
- [ ] Commits follow `[issue-<id>] <type>: <summary>`.
- [ ] `make test` and `make lint` pass locally.
- [ ] `tests/regression/TESTBOOK.md` is updated, or this PR changes no user-facing behavior.
- [ ] Documentation is updated, or none was affected.
- [ ] The person who reported or suggested this has a `Co-authored-by` trailer and an entry in `CONTRIBUTORS.md`, or this came from nobody but me.
