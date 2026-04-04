#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Αυστηρός builder για το Ollama_cloud_chat_Browser.py.

Στόχος:
- GUI executable χωρίς κονσόλα.
- Χωρίς UPX για να μην εμφανίζονται τα warning/error τύπου NotCompressibleException.
- Πιο σωστή ανίχνευση third-party imports.
- Αποκλεισμός γνωστών άσχετων πακέτων που μπορεί να τραβηχτούν από το περιβάλλον build.
- Συμπερίληψη μόνο των optional PDF πακέτων όταν υπάρχουν πράγματι import statements στο source.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Sequence, Set, Tuple


FORCED_EXCLUDES = {
    "IPython",
    "PIL",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "bs4",
    "cv2",
    "fontTools",
    "jupyter",
    "lxml",
    "matplotlib",
    "notebook",
    "numpy",
    "pandas",
    "pygame",
    "qt_material",
    "requests",
    "scipy",
    "sklearn",
    "tensorflow",
    "torch",
    "torchvision",
}

PACKAGE_RULES = {
    "fitz": {
        "hidden": ["fitz"],
        "collect_submodules": ["fitz"],
        "metadata": ["PyMuPDF"],
    },
    "pymupdf": {
        "hidden": ["fitz"],
        "collect_submodules": ["fitz"],
        "metadata": ["PyMuPDF"],
    },
    "pypdf": {
        "hidden": ["pypdf"],
        "collect_submodules": ["pypdf"],
        "metadata": ["pypdf"],
    },
    "pathlib": {
        "hidden": [],
        "collect_submodules": [],
        "metadata": [],
    },
}

STD_LIB_FALLBACK = {
    "__future__",
    "argparse",
    "ast",
    "base64",
    "concurrent",
    "copy",
    "dataclasses",
    "datetime",
    "html",
    "http",
    "json",
    "logging",
    "os",
    "pathlib",
    "queue",
    "re",
    "shlex",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "tempfile",
    "threading",
    "time",
    "typing",
    "urllib",
    "uuid",
    "webbrowser",
    "xml",
}


def eprint(*parts: object) -> None:
    print(*parts, file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Builder για αυστηρό minimal GUI executable.")
    parser.add_argument("--source", default="Ollama_cloud_chat_Browser.py", help="Κύριο .py αρχείο.")
    parser.add_argument("--name", default="", help="Όνομα executable.")
    parser.add_argument("--icon", default="", help="Προαιρετικό .ico αρχείο.")
    parser.add_argument("--onefile", action="store_true", help="Δημιουργία ενός μόνο .exe.")
    parser.add_argument("--keep-spec", action="store_true", help="Να κρατηθεί το .spec.")
    parser.add_argument("--no-clean", action="store_true", help="Να μην διαγραφούν build/dist πριν το build.")
    parser.add_argument("--zip", action="store_true", help="Δημιουργία zip του τελικού build.")
    return parser.parse_args()


def validate_input_paths(source: Path, icon: Path | None) -> None:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε το source αρχείο: {source}")
    if source.suffix.lower() != ".py":
        raise ValueError("Το source πρέπει να είναι αρχείο .py")
    if icon is not None and (not icon.exists() or not icon.is_file()):
        raise FileNotFoundError(f"Δεν βρέθηκε το icon αρχείο: {icon}")


def clean_build_artifacts(project_root: Path, app_name: str) -> None:
    for target in (project_root / "build", project_root / "dist", project_root / f"{app_name}.spec"):
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            try:
                target.unlink()
            except OSError:
                pass


def read_source_text(source: Path) -> str:
    return source.read_text(encoding="utf-8")


def extract_import_roots(source_text: str) -> Set[str]:
    tree = ast.parse(source_text)
    roots: Set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                roots.add(node.module.split(".", 1)[0])

    return roots


def _site_package_dirs() -> List[Path]:
    paths: List[Path] = []
    for raw in list(site.getsitepackages()) + [site.getusersitepackages()]:
        if not raw:
            continue
        try:
            p = Path(raw).resolve()
        except Exception:
            continue
        if p not in paths:
            paths.append(p)
    return paths


def is_stdlib_module(module_name: str) -> bool:
    if module_name in STD_LIB_FALLBACK:
        return True

    try:
        spec = importlib.util.find_spec(module_name)
    except Exception:
        return False

    if spec is None:
        return False

    origin = spec.origin
    if origin in (None, "built-in", "frozen"):
        return True

    try:
        origin_path = Path(origin).resolve()
    except Exception:
        return False

    site_dirs = _site_package_dirs()
    if any(origin_path == site_dir or site_dir in origin_path.parents for site_dir in site_dirs):
        return False

    try:
        stdlib_dir = Path(os.__file__).resolve().parent
        if origin_path == stdlib_dir or stdlib_dir in origin_path.parents:
            return True
    except Exception:
        pass

    return False


def detect_third_party_roots(import_roots: Iterable[str]) -> List[str]:
    return sorted({name for name in import_roots if not is_stdlib_module(name)})


def uninstall_obsolete_pathlib_backport_if_present() -> None:
    found_backport = False
    for base in _site_package_dirs():
        if not base.exists():
            continue
        if (base / "pathlib.py").exists() or any(base.glob("pathlib-*.dist-info")) or any(base.glob("pathlib-*.egg-info")):
            found_backport = True
            break

    if not found_backport:
        return

    print("Βρέθηκε obsolete package 'pathlib' στο site-packages. Γίνεται αφαίρεση...")
    result = subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "pathlib"], text=True)
    if result.returncode != 0:
        raise RuntimeError("Απέτυχε η αφαίρεση του obsolete package 'pathlib'.")


def ensure_package_installed(import_name: str, pip_name: str | None = None) -> None:
    try:
        if importlib.util.find_spec(import_name) is not None:
            return
    except Exception:
        pass

    package_to_install = pip_name or import_name
    print(f"Λείπει το πακέτο '{package_to_install}'. Γίνεται εγκατάσταση...")
    result = subprocess.run([sys.executable, "-m", "pip", "install", package_to_install], text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Απέτυχε η εγκατάσταση του '{package_to_install}'.")


def ensure_pyinstaller_ready() -> None:
    ensure_package_installed("PyInstaller", "pyinstaller")


def gather_pyinstaller_options(import_roots: Sequence[str]) -> Tuple[List[str], List[str]]:
    hiddenimports: List[str] = []
    collect_args: List[str] = []

    for root in sorted(set(import_roots)):
        rule = PACKAGE_RULES.get(root)
        if not rule:
            continue

        for name in rule.get("hidden", []):
            hiddenimports.append(name)

        for name in rule.get("collect_submodules", []):
            collect_args.extend(["--collect-submodules", name])

        for name in rule.get("metadata", []):
            try:
                importlib.metadata.distribution(name)
                collect_args.extend(["--copy-metadata", name])
            except importlib.metadata.PackageNotFoundError:
                pass

    hiddenimports.extend(
        [
            "concurrent.futures",
            "concurrent.futures._base",
            "concurrent.futures.thread",
            "concurrent.futures.process",
        ]
    )

    return sorted(set(hiddenimports)), collect_args


def build_exclude_args(import_roots: Sequence[str]) -> List[str]:
    imported = set(import_roots)
    excludes: List[str] = []
    for name in sorted(FORCED_EXCLUDES):
        if name not in imported:
            excludes.extend(["--exclude-module", name])
    return excludes


def build_pyinstaller_command(
    source: Path,
    app_name: str,
    icon: Path | None,
    onefile: bool,
    hiddenimports: Sequence[str],
    collect_args: Sequence[str],
    exclude_args: Sequence[str],
) -> List[str]:
    cmd: List[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--noupx",
        "--name",
        app_name,
    ]

    cmd.append("--onefile" if onefile else "--onedir")

    if icon is not None:
        cmd.extend(["--icon", str(icon)])

    for mod in hiddenimports:
        cmd.extend(["--hidden-import", mod])

    cmd.extend(collect_args)
    cmd.extend(exclude_args)
    cmd.append(str(source))
    return cmd


def remove_spec_if_needed(project_root: Path, app_name: str, keep_spec: bool) -> None:
    if keep_spec:
        return
    spec_path = project_root / f"{app_name}.spec"
    if spec_path.exists():
        try:
            spec_path.unlink()
        except OSError:
            pass


def zip_output(project_root: Path, app_name: str, onefile: bool) -> Path:
    dist_dir = project_root / "dist"
    target = dist_dir / (f"{app_name}.exe" if onefile else app_name)
    archive_base = dist_dir / f"{app_name}_portable"
    return Path(shutil.make_archive(str(archive_base), "zip", root_dir=str(target.parent), base_dir=target.name))


def print_summary(
    source: Path,
    app_name: str,
    third_party: Sequence[str],
    hiddenimports: Sequence[str],
    onefile: bool,
    exclude_args: Sequence[str],
) -> None:
    excluded_modules = [exclude_args[i + 1] for i, item in enumerate(exclude_args[:-1]) if item == "--exclude-module"]
    print("=" * 78)
    print("Builder για strict minimal executable")
    print("=" * 78)
    print(f"Source          : {source.name}")
    print(f"App name        : {app_name}")
    print(f"Build mode      : {'onefile' if onefile else 'onedir'}")
    print("Console         : disabled (GUI / χωρίς terminal)")
    print("UPX             : disabled")
    print(f"Third-party     : {', '.join(third_party) if third_party else 'κανένα'}")
    print(f"Hidden imports  : {', '.join(hiddenimports) if hiddenimports else 'κανένα'}")
    print(f"Excludes        : {', '.join(excluded_modules) if excluded_modules else 'κανένα'}")
    print("=" * 78)


def main() -> int:
    args = parse_args()

    source = Path(args.source).resolve()
    icon = Path(args.icon).resolve() if args.icon else None
    validate_input_paths(source, icon)

    project_root = source.parent
    os.chdir(project_root)

    app_name = args.name.strip() or source.stem

    if not args.no_clean:
        clean_build_artifacts(project_root, app_name)

    uninstall_obsolete_pathlib_backport_if_present()
    ensure_pyinstaller_ready()

    source_text = read_source_text(source)
    import_roots = extract_import_roots(source_text)
    third_party = detect_third_party_roots(import_roots)
    hiddenimports, collect_args = gather_pyinstaller_options(import_roots)
    exclude_args = build_exclude_args(import_roots)

    print_summary(
        source=source,
        app_name=app_name,
        third_party=third_party,
        hiddenimports=hiddenimports,
        onefile=args.onefile,
        exclude_args=exclude_args,
    )

    cmd = build_pyinstaller_command(
        source=source,
        app_name=app_name,
        icon=icon,
        onefile=args.onefile,
        hiddenimports=hiddenimports,
        collect_args=collect_args,
        exclude_args=exclude_args,
    )

    print("Εκτέλεση:")
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd))

    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"Το PyInstaller απέτυχε με exit code {result.returncode}.")

    remove_spec_if_needed(project_root, app_name, args.keep_spec)

    dist_path = project_root / "dist" / (f"{app_name}.exe" if args.onefile else app_name)
    print(f"\nOK: Το build ολοκληρώθηκε στο: {dist_path}")

    if args.zip:
        archive_path = zip_output(project_root, app_name, args.onefile)
        print(f"ZIP: {archive_path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        eprint(f"\nΣφάλμα: {exc}")
        raise SystemExit(1)
