"""The AUR's release recipes and the generator that fills them in (issue #991).

`openemux`, `openemux-bin` and `openemux-appimage` follow the published
release; `make aur-release TAG=vX.Y.Z` builds, install-tests and swap-tests
them in the Arch image, and the `AUR` workflow pushes them. What these guard is
what an Arch user only finds out on their own machine:

* every AUR package replaces every other one (they all provide and conflict
  with `openemux`), so pacman can swap between them;
* every download comes from this repository's release on GitHub and is pinned
  to a checksum -- the release's own SHA256SUMS where it covers the file;
* the dependencies stay in step with the release package's;
* the generator writes exactly those values and refuses a release it cannot
  pin, and publishing refuses to run without the AUR key.
"""

import hashlib
import importlib.util
import io
import re
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from tests.test_aur_package import _array, _names, _read

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_PACKAGES = ("openemux", "openemux-bin", "openemux-appimage")
DOWNLOAD = "https://github.com/guilhermefeitosa66/OpenEmux/releases/download/v$pkgver/"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "aur_release", REPO_ROOT / "packaging/aur/release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = _load_generator()

PKG_SUM = "a" * 64
APPIMAGE_SUM = "b" * 64
ARCHIVE = b"the tag archive"
SUMS = (
    f"{PKG_SUM}  openemux-1.24.0-1-x86_64.pkg.tar.zst\n"
    f"{APPIMAGE_SUM} *OpenEmux-1.24.0-x86_64.AppImage\n"
    "\n"
    f"{'c' * 64}  openemux_1.24.0_amd64.deb\n"
)


def _fake_fetch(sums=SUMS):
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith("/SHA256SUMS"):
            return sums.encode("utf-8")
        return ARCHIVE

    fetch.calls = calls
    return fetch


class ReleaseRecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipes = {
            name: _read(f"packaging/aur/{name}/PKGBUILD") for name in RELEASE_PACKAGES
        }

    def test_each_recipe_is_its_package_and_a_template(self):
        for name, pkgbuild in self.recipes.items():
            with self.subTest(package=name):
                self.assertRegex(pkgbuild, rf"(?m)^pkgname={re.escape(name)}$")
                # Placeholders the generator replaces, one of each.
                self.assertEqual(re.findall(r"(?m)^pkgver=.*$", pkgbuild), ["pkgver=0.0.0"])
                self.assertEqual(re.findall(r"(?m)^pkgrel=.*$", pkgbuild), ["pkgrel=1"])
                self.assertEqual(
                    re.findall(r"(?m)^sha256sums=.*$", pkgbuild), ["sha256sums=('SKIP')"]
                )

    def test_every_aur_package_replaces_every_other(self):
        # pacman matches `conflicts` against provisions too, so each non-base
        # package conflicting with `openemux` covers the other three.
        for name in ("openemux-bin", "openemux-appimage"):
            with self.subTest(package=name):
                pkgbuild = self.recipes[name]
                self.assertRegex(pkgbuild, r"(?m)^_pkgname=openemux$")
                self.assertRegex(pkgbuild, r'(?m)^provides=\("\$_pkgname"\)$')
                self.assertRegex(pkgbuild, r'(?m)^conflicts=\("\$_pkgname"\)$')
        git = _read("packaging/aur/openemux-git/PKGBUILD")
        self.assertRegex(git, r'(?m)^conflicts=\("\$_pkgname"\)$')
        self.assertNotRegex(self.recipes["openemux"], r"(?m)^(provides|conflicts)=")

    def test_downloads_come_only_from_this_repositorys_release(self):
        sources = {
            name: re.search(r'(?m)^source=\("([^"]*)"\)$', pkgbuild).group(1)
            for name, pkgbuild in self.recipes.items()
        }
        self.assertEqual(
            sources["openemux"],
            "$pkgname-$pkgver.tar.gz::https://github.com/guilhermefeitosa66/OpenEmux/"
            "archive/refs/tags/v$pkgver.tar.gz",
        )
        self.assertEqual(
            sources["openemux-bin"],
            "$_pkgname-$pkgver-$_srcrel-x86_64.pkg.tar.zst::" + DOWNLOAD
            + "$_pkgname-$pkgver-$_srcrel-x86_64.pkg.tar.zst",
        )
        self.assertEqual(sources["openemux-appimage"], "$_appimage::" + DOWNLOAD + "$_appimage")
        self.assertRegex(
            self.recipes["openemux-appimage"],
            r'(?m)^_appimage="OpenEmux-\$pkgver-x86_64\.AppImage"$',
        )

    def test_the_prebuilt_files_are_not_unpacked_by_makepkg(self):
        self.assertIn('noextract=("$_pkgname-$pkgver-$_srcrel-x86_64.pkg.tar.zst")',
                      self.recipes["openemux-bin"])
        self.assertIn('noextract=("$_appimage")', self.recipes["openemux-appimage"])

    def test_architectures(self):
        # Built from source with the distribution's emulator: any. The release
        # ships its Arch package and AppImage for x86_64 only.
        self.assertRegex(self.recipes["openemux"], r"(?m)^arch=\('any'\)$")
        self.assertRegex(self.recipes["openemux-bin"], r"(?m)^arch=\('x86_64'\)$")
        self.assertRegex(self.recipes["openemux-appimage"], r"(?m)^arch=\('x86_64'\)$")

    def test_dependencies_are_in_step_with_the_release_package(self):
        release_pkg = _read("packaging/arch/PKGBUILD")
        theirs = set(_names(_array(release_pkg, "depends")))
        self.assertTrue(theirs)
        source = set(_names(_array(self.recipes["openemux"], "depends")))
        self.assertEqual(source - {"retroarch"}, theirs)
        self.assertIn("retroarch", source)
        binary = set(_names(_array(self.recipes["openemux-bin"], "depends")))
        self.assertEqual(binary, theirs)
        self.assertEqual(
            _names(_array(self.recipes["openemux-bin"], "optdepends")),
            [
                "python-segno: QR code of the address in Share Nearby",
                "retroarch: use the distribution RetroArch instead of the bundled one",
            ],
        )
        # The AppImage carries its own stack; the runtime mounts it via FUSE 2,
        # and the icon it installs lives in the hicolor hierarchy (namcap).
        self.assertEqual(_names(_array(self.recipes["openemux-appimage"], "depends")),
                         ["fuse2", "hicolor-icon-theme"])

    def test_the_source_build_uses_the_shared_install_layout(self):
        pkgbuild = self.recipes["openemux"]
        self.assertIn('cd "$srcdir/OpenEmux-$pkgver"', pkgbuild)
        self.assertIn('DESTDIR="$pkgdir" ROOT_DIR="$PWD" sh packaging/common/stage_tree.sh',
                      pkgbuild)

    def test_the_bin_package_drops_the_release_packages_metadata(self):
        pkgbuild = self.recipes["openemux-bin"]
        for dotfile in (".PKGINFO", ".BUILDINFO", ".MTREE"):
            self.assertIn(f"--exclude '{dotfile}'", pkgbuild)
        self.assertIn(
            'mv "$pkgdir/usr/share/licenses/$_pkgname" "$pkgdir/usr/share/licenses/$pkgname"',
            pkgbuild,
        )
        self.assertIn('if [ -d "$pkgdir/usr/share/doc" ]; then\n'
                      '    rmdir --ignore-fail-on-non-empty "$pkgdir/usr/share/doc"', pkgbuild)

    def test_the_appimage_package_integrates_with_the_desktop(self):
        pkgbuild = self.recipes["openemux-appimage"]
        self.assertIn('"$pkgdir/opt/$pkgname/OpenEmux.AppImage"', pkgbuild)
        self.assertIn('ln -s "/opt/$pkgname/OpenEmux.AppImage" "$pkgdir/usr/bin/$_pkgname"',
                      pkgbuild)
        self.assertIn("s|^Exec=.*|Exec=/usr/bin/openemux|", pkgbuild)
        for path in ("usr/share/applications/$_appid.desktop",
                     "usr/share/icons/hicolor/512x512/apps/$_appid.png",
                     "usr/share/metainfo/$_appid.metainfo.xml",
                     "usr/lib/openemux/LICENSE", "usr/lib/openemux/copyright"):
            self.assertIn(path, pkgbuild)
        self.assertIn('--appimage-extract "$path"', pkgbuild)

    def test_nothing_shipped_is_stripped(self):
        for name in ("openemux-bin", "openemux-appimage"):
            with self.subTest(package=name):
                self.assertRegex(self.recipes[name], r"(?m)^options=\('!strip' '!debug'\)$")

    def test_licences_land_where_arch_keeps_them(self):
        for name in ("openemux", "openemux-appimage"):
            with self.subTest(package=name):
                self.assertIn('/usr/share/licenses/$pkgname/LICENSE"', self.recipes[name])
                self.assertIn('/usr/share/licenses/$pkgname/copyright"', self.recipes[name])


class TagTests(unittest.TestCase):
    def test_a_release_tag_gives_its_version(self):
        self.assertEqual(release.tag_to_version("v1.24.0"), "1.24.0")

    def test_anything_else_is_refused(self):
        for tag in ("1.24.0", "v1.24", "v1.24.0-rc1", "beta-1.24.1", "v1.24.0; rm -rf /"):
            with self.subTest(tag=tag), self.assertRaises(release.ReleaseError):
                release.tag_to_version(tag)


class Sha256SumsTests(unittest.TestCase):
    def test_text_and_binary_lines_and_blank_lines(self):
        self.assertEqual(
            release.parse_sha256sums(SUMS),
            {
                "openemux-1.24.0-1-x86_64.pkg.tar.zst": PKG_SUM,
                "OpenEmux-1.24.0-x86_64.AppImage": APPIMAGE_SUM,
                "openemux_1.24.0_amd64.deb": "c" * 64,
            },
        )

    def test_a_malformed_line_is_an_error(self):
        with self.assertRaisesRegex(release.ReleaseError, "line 2 is malformed"):
            release.parse_sha256sums(f"{PKG_SUM}  a.deb\nnot a checksum\n")


class ReleaseAssetTests(unittest.TestCase):
    def test_the_package_and_the_appimage(self):
        assets = release.release_assets("1.24.0", release.parse_sha256sums(SUMS))
        self.assertEqual(assets["pkg"], ("openemux-1.24.0-1-x86_64.pkg.tar.zst", PKG_SUM, "1"))
        self.assertEqual(assets["appimage"], ("OpenEmux-1.24.0-x86_64.AppImage", APPIMAGE_SUM))

    def test_the_package_release_number_is_read_off_its_name(self):
        sums = {"openemux-1.24.0-3-x86_64.pkg.tar.zst": PKG_SUM,
                "OpenEmux-1.24.0-x86_64.AppImage": APPIMAGE_SUM}
        self.assertEqual(release.release_assets("1.24.0", sums)["pkg"][2], "3")

    def test_no_arch_package_is_an_error(self):
        with self.assertRaisesRegex(release.ReleaseError, "found 0"):
            release.release_assets("1.24.0", {"OpenEmux-1.24.0-x86_64.AppImage": APPIMAGE_SUM})

    def test_two_arch_packages_are_an_error(self):
        sums = {"openemux-1.24.0-1-x86_64.pkg.tar.zst": PKG_SUM,
                "openemux-1.24.0-2-x86_64.pkg.tar.zst": PKG_SUM}
        with self.assertRaisesRegex(release.ReleaseError, "found 2"):
            release.release_assets("1.24.0", sums)

    def test_another_versions_package_does_not_count(self):
        sums = {"openemux-1.23.0-1-x86_64.pkg.tar.zst": PKG_SUM,
                "OpenEmux-1.24.0-x86_64.AppImage": APPIMAGE_SUM}
        with self.assertRaisesRegex(release.ReleaseError, "found 0"):
            release.release_assets("1.24.0", sums)

    def test_no_appimage_is_an_error(self):
        with self.assertRaisesRegex(release.ReleaseError, "AppImage is not in"):
            release.release_assets("1.24.0", {"openemux-1.24.0-1-x86_64.pkg.tar.zst": PKG_SUM})


class RenderTests(unittest.TestCase):
    def test_each_named_line_is_rewritten(self):
        text = "pkgver=0.0.0\npkgrel=1\n# pkgver=in a comment\n"
        self.assertEqual(
            release.render(text, "x", {"pkgver": "1.2.3", "pkgrel": "2"}),
            "pkgver=1.2.3\npkgrel=2\n# pkgver=in a comment\n",
        )

    def test_a_missing_line_is_an_error(self):
        with self.assertRaisesRegex(release.ReleaseError, "x: expected exactly one 'pkgrel='"):
            release.render("pkgver=0.0.0\n", "x", {"pkgrel": "1"})

    def test_a_repeated_line_is_an_error(self):
        with self.assertRaisesRegex(release.ReleaseError, "exactly one 'pkgver='"):
            release.render("pkgver=0.0.0\npkgver=0.0.0\n", "x", {"pkgver": "1"})

    def test_backslashes_in_a_value_are_written_as_they_are(self):
        self.assertEqual(release.render("a=0\n", "x", {"a": r"\1"}), "a=\\1\n")


class FetchTests(unittest.TestCase):
    def test_returns_the_body(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"body"
        with mock.patch.object(release.urllib.request, "urlopen", return_value=response) as urlopen:
            self.assertEqual(release.fetch("https://example.invalid/x"), b"body")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.invalid/x")
        self.assertEqual(request.get_header("User-agent"), "openemux-aur-release")
        self.assertEqual(urlopen.call_args.kwargs, {"timeout": release.TIMEOUT})

    def test_a_failed_download_names_the_url(self):
        for error in (urllib.error.HTTPError("u", 404, "Not Found", {}, None),
                      urllib.error.URLError("no route"), TimeoutError("slow")):
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(release.urllib.request, "urlopen", side_effect=error), \
                    self.assertRaisesRegex(release.ReleaseError,
                                           r"could not download https://example\.invalid/x"):
                release.fetch("https://example.invalid/x")


class GenerateTests(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.out)

    def test_writes_the_three_recipes_with_the_release_values(self):
        fetch = _fake_fetch()
        written = release.generate("v1.24.0", self.out, pkgrel=2, fetch=fetch)
        self.assertEqual(written, [self.out / p / "PKGBUILD" for p in RELEASE_PACKAGES])
        self.assertEqual(fetch.calls, [
            "https://github.com/guilhermefeitosa66/OpenEmux/releases/download/v1.24.0/SHA256SUMS",
            "https://github.com/guilhermefeitosa66/OpenEmux/archive/refs/tags/v1.24.0.tar.gz",
        ])
        recipes = {p: (self.out / p / "PKGBUILD").read_text() for p in RELEASE_PACKAGES}
        for name, text in recipes.items():
            with self.subTest(package=name):
                self.assertRegex(text, r"(?m)^pkgver=1\.24\.0$")
                self.assertRegex(text, r"(?m)^pkgrel=2$")
                self.assertNotIn("'SKIP'", text)
        self.assertRegex(recipes["openemux"],
                         rf"(?m)^sha256sums=\('{hashlib.sha256(ARCHIVE).hexdigest()}'\)$")
        self.assertRegex(recipes["openemux-bin"], rf"(?m)^sha256sums=\('{PKG_SUM}'\)$")
        self.assertRegex(recipes["openemux-bin"], r"(?m)^_srcrel=1$")
        self.assertRegex(recipes["openemux-appimage"], rf"(?m)^sha256sums=\('{APPIMAGE_SUM}'\)$")
        # Everything but those lines is the tracked template, untouched.
        template = _read("packaging/aur/openemux-appimage/PKGBUILD")
        changed = set(template.splitlines()) ^ set(recipes["openemux-appimage"].splitlines())
        self.assertEqual(
            {line.split("=")[0] for line in changed}, {"pkgver", "pkgrel", "sha256sums"}
        )

    def test_a_bad_tag_downloads_nothing(self):
        fetch = _fake_fetch()
        with self.assertRaises(release.ReleaseError):
            release.generate("1.24.0", self.out, fetch=fetch)
        self.assertEqual(fetch.calls, [])

    def test_pkgrel_starts_at_one(self):
        fetch = _fake_fetch()
        with self.assertRaisesRegex(release.ReleaseError, "pkgrel must be 1 or more"):
            release.generate("v1.24.0", self.out, pkgrel=0, fetch=fetch)
        self.assertEqual(fetch.calls, [])

    def test_a_release_missing_an_asset_writes_nothing(self):
        fetch = _fake_fetch(sums=f"{PKG_SUM}  openemux-1.24.0-1-x86_64.pkg.tar.zst\n")
        with self.assertRaises(release.ReleaseError):
            release.generate("v1.24.0", self.out, fetch=fetch)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_template_whose_placeholder_moved_is_refused(self):
        recipes = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, recipes)
        for name in RELEASE_PACKAGES:
            (recipes / name).mkdir()
            (recipes / name / "PKGBUILD").write_text("pkgver=0.0.0\n")
        with self.assertRaisesRegex(release.ReleaseError, "openemux: expected exactly one"):
            release.generate("v1.24.0", self.out, fetch=_fake_fetch(), recipes=recipes)


class MainTests(unittest.TestCase):
    def test_prints_what_it_wrote(self):
        with tempfile.TemporaryDirectory() as out:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = release.main(["v1.24.0", "--out", out, "--pkgrel", "3"],
                                    fetch=_fake_fetch())
            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue().split(),
                             [str(Path(out) / p / "PKGBUILD") for p in RELEASE_PACKAGES])
            self.assertIn("pkgrel=3", (Path(out) / "openemux" / "PKGBUILD").read_text())

    def test_an_error_is_one_line_and_exit_1(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = release.main(["1.24", "--out", "unused"], fetch=_fake_fetch())
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(),
                         "error: '1.24' is not a release tag (expected vX.Y.Z)\n")


class ReleaseScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = _read("packaging/aur/release.sh")

    def test_publish_without_the_key_fails_before_building(self):
        refusal = self.script.index("FAIL: AUR_SSH_PRIVATE_KEY is not set")
        self.assertLess(refusal, self.script.index("python3 packaging/aur/release.py"))
        self.assertIn('[ "$MODE" = publish ] && [ -z "$AUR_KEY" ]', self.script)

    def test_the_key_leaves_the_environment_before_anything_runs(self):
        unset = self.script.index("unset AUR_SSH_PRIVATE_KEY")
        self.assertLess(unset, self.script.index("python3 packaging/aur/release.py"))
        self.assertEqual(self.script.count("AUR_SSH_PRIVATE_KEY:-"), 1)

    def test_the_modes(self):
        self.assertIn("  check|dry-run|publish) ;;", self.script)
        self.assertIn('MODE="${AUR_MODE:-check}"', self.script)

    def test_every_package_is_built_checked_and_swapped(self):
        self.assertIn("PACKAGES=(openemux openemux-bin openemux-appimage)", self.script)
        self.assertIn("makepkg --printsrcinfo > .SRCINFO", self.script)
        self.assertIn("namcap", self.script)
        # A missing icon-theme dependency is a namcap error: it blocks the run.
        self.assertIn("'Dependency hicolor-icon-theme detected and not included'", self.script)
        self.assertIn('pacman -U --noconfirm --ask=4 "${PKG_PATH[$pkg]}"', self.script)
        for swap in ("swap_to openemux-bin openemux", "swap_to openemux-appimage openemux-bin",
                     "swap_to openemux openemux-appimage"):
            self.assertIn(swap, self.script)
        self.assertIn("pacman -Rns --noconfirm openemux", self.script)

    def test_a_dry_run_is_anonymous_and_pushes_nothing(self):
        self.assertIn('git clone -q "https://aur.archlinux.org/${pkg}.git"', self.script)
        push = self.script.index("push -q origin HEAD:master")
        guard = self.script.rindex('if [ "$MODE" = publish ]; then', 0, push)
        self.assertLess(guard, push)
        self.assertIn("DRY RUN: nothing was pushed to the AUR", self.script)

    def test_the_aur_host_key_is_pinned(self):
        self.assertIn("StrictHostKeyChecking=yes", self.script)
        self.assertIn("aur.archlinux.org ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEuBKrPzbawxA/"
                      "k2g6NcyV5jmqwJ2s+zpgZGZ7tpLIcN", self.script)

    def test_the_output_is_never_in_dist(self):
        self.assertRegex(self.script, r"(?m)^OUT=build/aur/release$")
        self.assertNotIn("dist/", self.script)


class WiringTests(unittest.TestCase):
    def test_the_dispatcher_runs_the_release_script_in_the_arch_image(self):
        dispatcher = _read("packaging/build.sh")
        self.assertIn("appimage|deb|rpm|arch|flatpak|windows|aur|aur-release)", dispatcher)
        self.assertIn('[ "$TARGET" = "aur-release" ] && IMAGE_TARGET=arch', dispatcher)
        self.assertIn("SCRIPT=packaging/aur/release.sh", dispatcher)
        # By name, so its value never lands on docker's command line, and only
        # into a publish; refused before the image is built when missing.
        self.assertIn("DOCKER_ARGS+=(-e AUR_TAG -e AUR_MODE -e AUR_PKGREL)", dispatcher)
        self.assertIn('if [ "$AUR_MODE" = "publish" ]; then\n    DOCKER_ARGS+=(-e AUR_SSH_PRIVATE_KEY)',
                      dispatcher)
        refusal = dispatcher.index("FAIL: AUR_SSH_PRIVATE_KEY is not set")
        self.assertLess(refusal, dispatcher.index('docker build "${PLATFORM_ARGS[@]}"'))

    def test_make_targets(self):
        makefile = _read("Makefile")
        self.assertIn("AUR_TAG='$(TAG)' AUR_MODE=check", makefile)
        self.assertIn("AUR_MODE=$(if $(filter 1,$(DRY_RUN)),dry-run,publish)", makefile)
        packages = re.search(r"(?m)^packages: (.*)$", makefile).group(1)
        self.assertNotIn("aur", packages)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.text = _read(".github/workflows/aur.yml")
        self.data = yaml.safe_load(self.text)

    def test_dispatched_with_a_tag_and_a_dry_run_by_default(self):
        inputs = self.data[True]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(self.data[True]), {"workflow_dispatch"})
        self.assertTrue(inputs["tag"]["required"])
        self.assertEqual(inputs["dry_run"]["type"], "boolean")
        self.assertIs(inputs["dry_run"]["default"], True)

    def test_read_only_and_the_secret_only_in_the_environment(self):
        self.assertEqual(self.data["permissions"], {"contents": "read"})
        step = self.data["jobs"]["aur"]["steps"][-1]
        self.assertEqual(step["env"]["AUR_SSH_PRIVATE_KEY"], "${{ secrets.AUR_SSH_PRIVATE_KEY }}")
        self.assertEqual(step["env"]["TAG"], "${{ inputs.tag }}")
        self.assertNotIn("${{", step["run"])
        self.assertIn('make aur-publish TAG="$TAG" DRY_RUN="$DRY_RUN"', step["run"])
        self.assertIn("^v[0-9]+\\.[0-9]+\\.[0-9]+$", step["run"])
        checkout = self.data["jobs"]["aur"]["steps"][0]
        self.assertIs(checkout["with"]["persist-credentials"], False)


class DocumentationTests(unittest.TestCase):
    def test_the_release_process_dispatches_the_workflow(self):
        claude = _read("CLAUDE.md")
        self.assertIn("gh workflow run aur.yml", claude)
        self.assertIn("AUR_SSH_PRIVATE_KEY", claude)

    def test_the_packaging_readme_lists_the_four_packages(self):
        readme = _read("packaging/README.md")
        for name in ("openemux-git", "openemux-bin", "openemux-appimage", "make aur-release"):
            self.assertIn(name, readme)


if __name__ == "__main__":
    unittest.main()
