#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Installer πακέτων για το Ollama Cloud Chat Studio.

Τι κάνει:
- Εντοπίζει αυτόματα το κύριο source αρχείο αν δεν δοθεί ρητά.
- Αναλύει τα imports του source.
- Εγκαθιστά μόνο τα third-party packages που χρησιμοποιεί πραγματικά η εφαρμογή.
- Καλύπτει PDF και DOCX export dependencies.
"""

from __future__ import annotations

import argparse
import ast
import importlib
import importlib.util
import os
import site
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set


@dataclass(frozen=True)
class PackageSpec:
    """Περιγράφει ένα πακέτο που θα εγκατασταθεί μέσω pip."""

    pip_name: str
    import_name: str
    description: str
    required_for_full_features: bool = True


PACKAGE_CATALOG: Dict[str, PackageSpec] = {
    "pypdf": PackageSpec(
        pip_name="pypdf",
        import_name="pypdf",
        description="Ανάγνωση και επεξεργασία PDF.",
    ),
    "fitz": PackageSpec(
        pip_name="PyMuPDF",
        import_name="fitz",
        description="Βελτιωμένο PDF polish/export μέσω PyMuPDF.",
    ),
    "docx": PackageSpec(
        pip_name="python-docx",
        import_name="docx",
        description="Native export σε Microsoft Word .docx χωρίς LibreOffice.",
    ),
    "lxml": PackageSpec(
        pip_name="lxml",
        import_name="lxml",
        description="XML engine που απαιτεί το python-docx για αξιόπιστο DOCX export και .exe bundling.",
    ),
    "bs4": PackageSpec(
        pip_name="beautifulsoup4",
        import_name="bs4",
        description="Ανάλυση HTML fragment για σωστό DOCX export.",
    ),
    "PIL": PackageSpec(
        pip_name="Pillow",
        import_name="PIL",
        description="Μετατροπή/κανονικοποίηση εικόνων πριν την ενσωμάτωση στο DOCX.",
    ),
    "cairosvg": PackageSpec(
        pip_name="CairoSVG",
        import_name="cairosvg",
        description="Προαιρετική μετατροπή SVG σε PNG. Συχνά απαιτεί system Cairo DLL και δεν είναι απαραίτητο για το τρέχον DOCX flow.",
        required_for_full_features=False,
    ),
    "pygments": PackageSpec(
        pip_name="Pygments",
        import_name="pygments",
        description="Έγχρωμο syntax highlighting για code blocks στο DOCX.",
    ),
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
    "io",
    "json",
    "logging",
    "math",
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
    "tokenize",
    "typing",
    "urllib",
    "uuid",
    "webbrowser",
    "xml",
}

SOURCE_CANDIDATE_PATTERNS = [
    "Ollama_cloud_chat_Browser*.py",
    "Ollama_Cloud_Chat_Studio*.py",
]
SOURCE_EXCLUDE_NAMES = {
    "build_ollama_cloud_chat_studio_exe.py",
    "install_ollama_cloud_chat_studio_packages.py",
    "build_ollama_cloud_chat_studio_exe_fixed.py",
    "install_ollama_cloud_chat_studio_packages_fixed.py",
    "build_ollama_cloud_chat_studio_exe_fixed_v2.py",
    "install_ollama_cloud_chat_studio_packages_fixed_v2.py",
    "build_ollama_cloud_chat_studio_exe_fixed_v3.py",
    "install_ollama_cloud_chat_studio_packages_fixed_v3.py",
}


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


def autodetect_source(project_root: Path) -> Optional[Path]:
    candidates: List[Path] = []
    for pattern in SOURCE_CANDIDATE_PATTERNS:
        for path in project_root.glob(pattern):
            if not path.is_file():
                continue
            if path.name in SOURCE_EXCLUDE_NAMES:
                continue
            candidates.append(path.resolve())

    if not candidates:
        return None

    candidates = sorted(
        set(candidates),
        key=lambda p: (
            0 if "docx_export" in p.stem.lower() else 1,
            0 if "browser" in p.stem.lower() else 1,
            -p.stat().st_mtime,
            p.name.lower(),
        ),
    )
    return candidates[0]


def resolve_source_path(source_arg: str) -> Path:
    if source_arg:
        return Path(source_arg).resolve()

    detected = autodetect_source(Path.cwd())
    if detected is None:
        raise FileNotFoundError(
            "Δεν βρέθηκε αυτόματα source αρχείο. Δώσε ρητά --source <αρχείο.py>."
        )
    return detected


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


def detect_required_packages(import_roots: Iterable[str], include_optional_native: bool=False) -> List[PackageSpec]:
    packages: List[PackageSpec] = []
    seen_pip_names: Set[str] = set()
    roots = set(import_roots)

    for root in sorted(roots):
        if is_stdlib_module(root):
            continue
        spec = PACKAGE_CATALOG.get(root)
        if spec is None:
            continue
        if (not include_optional_native) and (not spec.required_for_full_features):
            continue
        if spec.pip_name in seen_pip_names:
            continue
        packages.append(spec)
        seen_pip_names.add(spec.pip_name)

    if "docx" in roots or "lxml" in roots:
        extra_spec = PACKAGE_CATALOG["lxml"]
        if extra_spec.pip_name not in seen_pip_names:
            packages.append(extra_spec)
            seen_pip_names.add(extra_spec.pip_name)

    return packages


def run_command(command: List[str]) -> int:
    print("\n[EXEC]", " ".join(command))
    completed = subprocess.run(command)
    return int(completed.returncode)


def is_module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def install_packages(packages: Iterable[PackageSpec], upgrade_pip: bool = False) -> int:
    if upgrade_pip:
        code = run_command([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
        if code != 0:
            print("[WARNING] Η αναβάθμιση του pip απέτυχε. Συνεχίζω με την εγκατάσταση των πακέτων.")

    failed = 0
    for pkg in packages:
        print(f"\n[INFO] Εγκατάσταση: {pkg.pip_name} -> import {pkg.import_name}")
        print(f"[INFO] Περιγραφή: {pkg.description}")
        code = run_command([sys.executable, "-m", "pip", "install", pkg.pip_name])
        if code != 0:
            failed += 1
            print(f"[ERROR] Αποτυχία εγκατάστασης του πακέτου: {pkg.pip_name}")
        else:
            print(f"[OK] Το πακέτο εγκαταστάθηκε: {pkg.pip_name}")
    return failed


def verify_packages(packages: Iterable[PackageSpec]) -> int:
    failed = 0
    print("\n[VERIFY] Έλεγχος imports...")
    for pkg in packages:
        ok = is_module_available(pkg.import_name)
        status = "OK" if ok else "FAIL"
        print(f" - {pkg.import_name:<12} ({pkg.pip_name:<15}) : {status}")
        if not ok:
            failed += 1
    return failed


def print_summary(source: Path, packages: Iterable[PackageSpec], include_optional_native: bool=False) -> None:
    packages = list(packages)
    print("\n" + "=" * 72)
    print("ΣΥΝΟΨΗ DEPENDENCIES")
    print("=" * 72)
    print(f"Source αρχείο: {source.name}")
    print("Η εφαρμογή χρησιμοποιεί κυρίως Python standard library modules.")
    if not packages:
        print("Δεν εντοπίστηκαν γνωστά third-party packages από το source.")
    else:
        print("Θα εγκατασταθούν τα παρακάτω third-party packages:")
        for pkg in packages:
            optional_note = " [optional/native]" if not pkg.required_for_full_features else ""
            print(f" - {pkg.pip_name:<15} (import: {pkg.import_name:<10}){optional_note} -> {pkg.description}")
    if not include_optional_native:
        print("Σημείωση: optional/native packages όπως CairoSVG παραλείπονται από προεπιλογή για να αποφευχθούν σφάλματα λόγω system DLLs.")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Εγκατάσταση των Python packages για το Ollama Cloud Chat Studio"
    )
    parser.add_argument(
        "--source",
        default="",
        help="Κύριο .py αρχείο. Αν μείνει κενό, γίνεται αυτόματος εντοπισμός.",
    )
    parser.add_argument(
        "--upgrade-pip",
        action="store_true",
        help="Αναβάθμιση του pip πριν από την εγκατάσταση.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Δεν εγκαθιστά τίποτα. Ελέγχει μόνο αν τα packages υπάρχουν ήδη.",
    )
    parser.add_argument(
        "--include-optional-native",
        action="store_true",
        help="Να συμπεριληφθούν και optional/native packages όπως CairoSVG που μπορεί να απαιτούν system DLLs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    source = resolve_source_path(args.source)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"Δεν βρέθηκε το source αρχείο: {source}")

    source_text = read_source_text(source)
    import_roots = extract_import_roots(source_text)
    packages = detect_required_packages(import_roots, include_optional_native=args.include_optional_native)

    print_summary(source, packages, include_optional_native=args.include_optional_native)
    print(f"[INFO] Python executable: {sys.executable}")
    print(f"[INFO] Python version   : {sys.version.split()[0]}")

    if args.verify_only:
        verify_failed = verify_packages(packages)
        if verify_failed:
            print(f"\n[RESULT] Λείπουν {verify_failed} package(s).")
            return 1
        print("\n[RESULT] Όλα τα απαραίτητα packages είναι εγκατεστημένα.")
        return 0

    failed = install_packages(packages, upgrade_pip=args.upgrade_pip)
    verify_failed = verify_packages(packages)

    if failed or verify_failed:
        print("\n[RESULT] Η εγκατάσταση ολοκληρώθηκε με προβλήματα.")
        return 1

    print("\n[RESULT] Η εγκατάσταση ολοκληρώθηκε επιτυχώς.")
    print("[TIP] Μπορείς τώρα να τρέξεις την εφαρμογή με τον ίδιο interpreter ή να χρησιμοποιήσεις τον builder.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
