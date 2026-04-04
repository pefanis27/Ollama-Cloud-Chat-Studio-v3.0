#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Διαδραστικός οδηγός δημιουργίας εκτελέσιμου με PyInstaller.

Έκδοση v3 με:
- προέλεγχο για ασύμβατα obsolete backport packages (π.χ. pathlib),
- αυτόματο scan του source file για imports/πακέτα,
- αυτόματη προσθήκη hidden imports και collect-all για packages όπως pypdf/PyMuPDF,
- προαιρετική αυτόματη εγκατάσταση ελλειπόντων packages,
- δημιουργία requirements manifest για την εφαρμογή.
"""
from __future__ import annotations

import ast
import importlib
import importlib.metadata as importlib_metadata
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

APP_VERSION = "3.3"
SEP = "=" * 72
SEP2 = "─" * 72
DEFAULT_APP_NAME = "OllamaCloudChatStudio"
DEFAULT_UPX_EXCLUDES = ["_uuid.pyd", "python3.dll"]
DEFAULT_STDLIB_HIDDEN_IMPORTS = [
    "concurrent.futures",
    "concurrent.futures._base",
    "concurrent.futures.thread",
    "concurrent.futures.process",
    "http.server",
    "urllib.request",
    "urllib.error",
    "urllib.parse",
    "xml.etree.ElementTree",
    "email.mime.text",
]

# Πακέτα backport που δεν πρέπει να υπάρχουν σε σύγχρονες εκδόσεις Python,
# επειδή συχνά προκαλούν failure στο PyInstaller.
OBSOLETE_BACKPORTS = {
    "pathlib": (3, 4),
    "typing": (3, 5),
    "enum34": (3, 4),
    "dataclasses": (3, 7),
}

PACKAGE_RULES = {
    "pypdf": {
        "pip": "pypdf",
        "hidden": ["pypdf"],
        "collect": ["pypdf"],
    },
    "fitz": {
        "pip": "PyMuPDF",
        "hidden": ["fitz", "pymupdf"],
        "collect": ["fitz", "pymupdf"],
    },
    "pymupdf": {
        "pip": "PyMuPDF",
        "hidden": ["fitz", "pymupdf"],
        "collect": ["fitz", "pymupdf"],
    },
}


@dataclass
class BuildConfig:
    source: Path
    app_name: str
    one_file: bool
    console: bool
    icon_path: str = ""
    use_upx: bool = False
    upx_excludes: list[str] = field(default_factory=list)
    clean_before_build: bool = True
    open_dist_after_build: bool = False
    run_after_build: bool = False
    extra_hidden_imports: list[str] = field(default_factory=list)
    auto_install_missing: bool = True


@dataclass
class PackagePlan:
    import_names: list[str] = field(default_factory=list)
    pip_packages: list[str] = field(default_factory=list)
    hidden_imports: list[str] = field(default_factory=list)
    collect_all: list[str] = field(default_factory=list)


def step(msg: str) -> None:
    print(f"\n  ▶  {msg}")


def ok(msg: str) -> None:
    print(f"  ✅  {msg}")


def warn(msg: str) -> None:
    print(f"  ⚠   {msg}")


def fail(msg: str, code: int = 1) -> None:
    print(f"\n  ❌  {msg}\n")
    raise SystemExit(code)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"\n  $ {' '.join(str(c) for c in cmd)}\n")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        fail(f"Η εντολή απέτυχε με κωδικό {result.returncode}.")
    return result


def ask_text(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    default_text = "Y/n" if default else "y/N"
    while True:
        value = input(f"{prompt} [{default_text}]: ").strip().lower()
        if not value:
            return default
        if value in {"y", "yes", "ν", "ναι", "nai"}:
            return True
        if value in {"n", "no", "ο", "oxi", "όχι"}:
            return False
        print("  Δώσε y ή n.")


def ask_choice(prompt: str, options: list[tuple[str, str]], default_index: int = 0) -> str:
    print(f"\n{prompt}")
    for idx, (_, label) in enumerate(options, 1):
        marker = " (default)" if idx - 1 == default_index else ""
        print(f"  [{idx}] {label}{marker}")
    while True:
        raw = input("Επιλογή: ").strip()
        if not raw:
            return options[default_index][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print("  Μη έγκυρη επιλογή.")


def parse_csv(raw: str) -> list[str]:
    return [x.strip() for x in raw.split(",") if x.strip()]


def dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def check_python() -> None:
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 9):
        fail(f"Απαιτείται Python 3.9+. Τρέχουσα έκδοση: {major}.{minor}")
    ok(f"Python {major}.{minor}.{sys.version_info.micro}")


def ensure_pyinstaller() -> str:
    try:
        import PyInstaller
        version = PyInstaller.__version__
        ok(f"PyInstaller {version}")
        return version
    except ImportError:
        pass
    step("Εγκατάσταση/αναβάθμιση PyInstaller…")
    run([sys.executable, "-m", "pip", "install", "pyinstaller", "--upgrade"])
    import PyInstaller
        
    importlib.reload(PyInstaller)
    version = PyInstaller.__version__
    ok(f"PyInstaller {version} εγκαταστάθηκε")
    return version


def has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def find_upx() -> str | None:
    return shutil.which("upx")


def find_sources(script_dir: Path) -> list[Path]:
    this_file = Path(__file__).resolve()
    candidates = [
        f
        for f in sorted(script_dir.glob("*.py"), key=lambda p: p.name.lower())
        if f.resolve() != this_file and not f.name.lower().startswith("build_exe")
    ]
    preferred = [f for f in candidates if re.search("ollama", f.name, re.IGNORECASE)]
    return preferred or candidates


def choose_source(script_dir: Path) -> Path:
    candidates = find_sources(script_dir)
    if not candidates:
        fail("Δεν βρέθηκαν .py αρχεία για build στον ίδιο φάκελο.")
    print("\nΔιαθέσιμα αρχεία πηγής:\n")
    for i, c in enumerate(candidates, 1):
        size_kb = c.stat().st_size / 1024
        print(f"  [{i}] {c.name}  ({size_kb:.1f} KB)")
    while True:
        raw = input(f"\nΕπίλεξε source file [1-{len(candidates)}] (default 1): ").strip()
        if not raw:
            return candidates[0].resolve()
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            return candidates[int(raw) - 1].resolve()
        print("  Μη έγκυρη επιλογή.")


def _handle_remove_error(func, path, excinfo) -> None:
    err = excinfo if isinstance(excinfo, BaseException) else excinfo[1]
    path_obj = Path(path)
    if isinstance(err, PermissionError):
        print()
        warn(f"Το αρχείο ή ο φάκελος είναι κλειδωμένος και δεν μπορεί να διαγραφεί: {path_obj}")
        print("     Συνήθως αυτό σημαίνει ότι το παλιό .exe είναι ακόμη ανοιχτό.")
        while True:
            action = input("     Κλείσ' το και πάτησε [R]etry, ή [A]bort για ακύρωση build: ").strip().lower()
            if action in {"", "r", "retry"}:
                try:
                    func(path)
                    return
                except PermissionError:
                    warn("     Παραμένει κλειδωμένο.")
                    continue
                except Exception as retry_exc:
                    fail(f"Αποτυχία διαγραφής του {path_obj}: {retry_exc}")
            if action in {"a", "abort"}:
                fail("Το build ακυρώθηκε επειδή το παλιό εκτελέσιμο είναι ακόμη ανοιχτό.", 2)
            print("     Δώσε R ή A.")
    raise err


def _remove_target(path: Path) -> bool:
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, onexc=_handle_remove_error)
    else:
        path.unlink()
    return True


def clean_previous(script_dir: Path, app_name: str) -> None:
    targets = [script_dir / "build", script_dir / "dist", script_dir / f"{app_name}.spec"]
    cleaned = False
    for target in targets:
        try:
            cleaned = _remove_target(target) or cleaned
        except FileNotFoundError:
            continue
    if cleaned:
        ok("Καθαρίστηκαν προηγούμενα builds")
    else:
        ok("Δεν υπήρχαν προηγούμενα build artifacts")


def get_installed_dist(name: str):
    try:
        return importlib_metadata.distribution(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def detect_obsolete_backports() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    py_now = sys.version_info[:2]
    for package, builtin_since in OBSOLETE_BACKPORTS.items():
        if py_now >= builtin_since:
            dist = get_installed_dist(package)
            if dist is not None:
                found.append((package, dist.version))
    return found


def fix_obsolete_backports_interactively() -> None:
    found = detect_obsolete_backports()
    if not found:
        ok("Δεν βρέθηκαν ασύμβατα obsolete backport packages")
        return

    warn("Βρέθηκαν obsolete backport packages που μπορεί να ρίξουν το PyInstaller:")
    for package, version in found:
        print(f"     - {package} {version}")

    for package, version in found:
        if ask_yes_no(f"Να γίνει uninstall του {package} {version} τώρα;", True):
            run([sys.executable, "-m", "pip", "uninstall", "-y", package])
            ok(f"Απεγκαταστάθηκε: {package}")
        else:
            fail(
                "Το build δεν μπορεί να συνεχίσει με ασφάλεια όσο υπάρχει το ασύμβατο package "
                f"'{package}'. Αφαίρεσέ το και ξανατρέξε το build.",
                2,
            )


def scan_source_imports(source: Path) -> set[str]:
    text = source.read_text(encoding="utf-8", errors="ignore")
    root_imports: set[str] = set()

    try:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_imports.add(node.module.split(".")[0])
    except SyntaxError as exc:
        warn(f"Αποτυχία AST scan στο {source.name}: {exc}. Θα γίνει regex fallback.")

    regex_patterns = {
        "pypdf": r"\b(?:import|from)\s+pypdf\b|\bPdfReader\b|\bPdfWriter\b",
        "fitz": r"\b(?:import|from)\s+fitz\b",
        "pymupdf": r"\b(?:import|from)\s+pymupdf\b",
    }
    for name, pattern in regex_patterns.items():
        if re.search(pattern, text):
            root_imports.add(name)

    return root_imports


def resolve_package_plan(source: Path) -> PackagePlan:
    imports_found = scan_source_imports(source)
    plan = PackagePlan(import_names=sorted(imports_found))

    pip_packages: list[str] = []
    hidden_imports: list[str] = list(DEFAULT_STDLIB_HIDDEN_IMPORTS)
    collect_all: list[str] = []

    for import_name in sorted(imports_found):
        rule = PACKAGE_RULES.get(import_name)
        if not rule:
            continue
        pip_packages.append(rule["pip"])
        hidden_imports.extend(rule["hidden"])
        collect_all.extend(rule["collect"])

    plan.pip_packages = dedupe(pip_packages)
    plan.hidden_imports = dedupe(hidden_imports)
    plan.collect_all = dedupe(collect_all)
    return plan


def install_missing_packages(plan: PackagePlan) -> None:
    missing: list[str] = []
    for pip_name in plan.pip_packages:
        if get_installed_dist(pip_name) is None:
            missing.append(pip_name)

    if not missing:
        ok("Όλα τα απαιτούμενα external packages είναι ήδη εγκατεστημένα")
        return

    warn("Λείπουν τα παρακάτω packages:")
    for pkg in missing:
        print(f"     - {pkg}")

    step("Εγκατάσταση ελλειπόντων packages…")
    run([sys.executable, "-m", "pip", "install", *missing])
    ok("Ολοκληρώθηκε η εγκατάσταση των απαιτούμενων packages")


def collect_hidden_imports(config: BuildConfig, plan: PackagePlan) -> list[str]:
    hidden = list(plan.hidden_imports)
    hidden.extend(config.extra_hidden_imports)
    return dedupe(hidden)


def write_requirements_manifest(script_dir: Path, app_name: str, plan: PackagePlan) -> Path:
    req_path = script_dir / f"{app_name}_requirements.txt"
    lines = ["pyinstaller"]
    lines.extend(plan.pip_packages)
    lines = dedupe(lines)
    req_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return req_path


def build(config: BuildConfig, script_dir: Path, plan: PackagePlan) -> Path:
    hidden_imports = collect_hidden_imports(config, plan)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        f"--name={config.app_name}",
        "--clean",
        "--noconfirm",
    ]
    cmd.append("--onefile" if config.one_file else "--onedir")
    cmd.append("--console" if config.console else "--windowed")

    if config.icon_path:
        cmd += ["--icon", config.icon_path]

    if config.use_upx:
        for item in config.upx_excludes:
            cmd.append(f"--upx-exclude={item}")
    else:
        cmd.append("--noupx")

    for hidden in hidden_imports:
        cmd.append(f"--hidden-import={hidden}")
    for pkg in plan.collect_all:
        cmd.append(f"--collect-all={pkg}")

    cmd.append(str(config.source))

    print(f"\n{SEP2}")
    step("Έναρξη build…")
    print(SEP2)
    run(cmd, cwd=str(script_dir))

    if config.one_file:
        exe = script_dir / "dist" / f"{config.app_name}.exe"
    else:
        exe = script_dir / "dist" / config.app_name / f"{config.app_name}.exe"
    return exe


def print_summary(config: BuildConfig, hidden_imports: Iterable[str], upx_found: str | None, plan: PackagePlan) -> None:
    print(f"\n{SEP}")
    print("  Σύνοψη build")
    print(SEP2)
    print(f"  Πηγή                 : {config.source.name}")
    print(f"  Όνομα εφαρμογής      : {config.app_name}")
    print(f"  Build mode           : {'onefile' if config.one_file else 'onedir'}")
    print(f"  Terminal window      : {'Ναι' if config.console else 'Όχι'}")
    print(f"  Εικονίδιο            : {config.icon_path or 'Κανένα'}")
    print(f"  UPX                  : {'Ναι' if config.use_upx else 'Όχι'}")
    if upx_found:
        print(f"  UPX path             : {upx_found}")
    if config.use_upx:
        print(f"  UPX excludes         : {', '.join(config.upx_excludes) if config.upx_excludes else 'Κανένα'}")
    print(f"  Καθαρισμός build     : {'Ναι' if config.clean_before_build else 'Όχι'}")
    print(f"  External packages    : {', '.join(plan.pip_packages) if plan.pip_packages else 'Κανένα'}")
    print(f"  Hidden imports       : {', '.join(hidden_imports) if hidden_imports else 'Κανένα'}")
    print(f"  Collect-all          : {', '.join(plan.collect_all) if plan.collect_all else 'Κανένα'}")
    print(f"  Run μετά το build    : {'Ναι' if config.run_after_build else 'Όχι'}")
    print(f"  Άνοιγμα dist folder  : {'Ναι' if config.open_dist_after_build else 'Όχι'}")
    print(SEP)


def configure(script_dir: Path) -> tuple[BuildConfig, PackagePlan]:
    step("Εύρεση αρχείου πηγής…")
    source = choose_source(script_dir)
    ok(f"Πηγή: {source.name}")

    step("Ανάλυση imports / packages της εφαρμογής…")
    plan = resolve_package_plan(source)
    ok(
        "Ανιχνεύθηκαν packages: "
        + (", ".join(plan.pip_packages) if plan.pip_packages else "κανένα external package")
    )

    default_app_name = source.stem or DEFAULT_APP_NAME
    app_name = ask_text("Όνομα εφαρμογής / exe", default_app_name)
    mode = ask_choice(
        "Επίλεξε τύπο build:",
        [
            ("onefile", "Ένα μόνο .exe (ευκολότερη διανομή, πιο βαρύ startup)"),
            ("onedir", "Φάκελος dist με exe + αρχεία (πιο σταθερό για apps με αρχεία)"),
        ],
        default_index=1,
    )
    console_mode = ask_choice(
        "Θες terminal window;",
        [("console", "Ναι, να φαίνεται terminal/logs"), ("windowed", "Όχι, καθαρό GUI χωρίς terminal")],
        default_index=0,
    )
    icon_path = ask_text("Διαδρομή εικονιδίου .ico (άφησέ το κενό αν δεν θες)", "")
    if icon_path:
        icon_candidate = Path(icon_path)
        if not icon_candidate.is_absolute():
            icon_candidate = (script_dir / icon_candidate).resolve()
        if not icon_candidate.exists():
            warn(f"Το icon δεν βρέθηκε: {icon_candidate}. Θα αγνοηθεί.")
            icon_path = ""
        else:
            icon_path = str(icon_candidate)

    auto_install_missing = True
    if plan.pip_packages:
        auto_install_missing = ask_yes_no("Αν λείπουν packages, να εγκατασταθούν αυτόματα;", True)

    upx_path = find_upx()
    use_upx = False
    upx_excludes: list[str] = []
    if upx_path:
        use_upx = ask_yes_no("Βρέθηκε UPX. Να χρησιμοποιηθεί συμπίεση UPX;", False)
        if use_upx:
            raw_excludes = ask_text("UPX excludes (comma separated)", ", ".join(DEFAULT_UPX_EXCLUDES))
            upx_excludes = parse_csv(raw_excludes)
    else:
        ok("UPX δεν βρέθηκε — θα χρησιμοποιηθεί --noupx")

    clean_before = ask_yes_no("Να καθαριστούν προηγούμενα build/dist/spec;", True)
    extra_hidden_imports = parse_csv(ask_text("Extra hidden imports (comma separated, προαιρετικό)", ""))
    run_after = ask_yes_no("Να τρέξει το exe μόλις ολοκληρωθεί το build;", False)
    open_dist = ask_yes_no("Να ανοίξει ο φάκελος dist μετά το build;", False)

    config = BuildConfig(
        source=source,
        app_name=app_name,
        one_file=(mode == "onefile"),
        console=(console_mode == "console"),
        icon_path=icon_path,
        use_upx=use_upx,
        upx_excludes=upx_excludes,
        clean_before_build=clean_before,
        open_dist_after_build=open_dist,
        run_after_build=run_after,
        extra_hidden_imports=extra_hidden_imports,
        auto_install_missing=auto_install_missing,
    )
    hidden_imports = collect_hidden_imports(config, plan)
    print_summary(config, hidden_imports, upx_path, plan)
    if not ask_yes_no("Να ξεκινήσει το build με αυτές τις ρυθμίσεις;", True):
        fail("Το build ακυρώθηκε από τον χρήστη.", 0)
    return config, plan


def open_in_explorer(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def print_result(exe: Path, source: Path, req_path: Path) -> None:
    if not exe.exists():
        fail("Το εκτελέσιμο δεν δημιουργήθηκε.\nΈλεγξε τα μηνύματα του PyInstaller παραπάνω.")
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f"\n{SEP}")
    print("  ✅  Build επιτυχές!")
    print(SEP2)
    print(f"  📁  Αρχείο exe       : {exe}")
    print(f"  📦  Μέγεθος          : {size_mb:.1f} MB")
    print(f"  🐍  Πηγή             : {source.name}")
    print(f"  📄  Requirements     : {req_path}")
    print(SEP2)
    print(f"  🚀  Εκτέλεση:")
    print(f"        {exe.name}")
    print(SEP)


def main() -> None:
    print(f"\n{SEP}")
    print(f"  Ollama Cloud Chat Studio v{APP_VERSION} — Interactive Build Wizard")
    print(f"  Python: {sys.executable}")
    print(SEP)

    script_dir = Path(__file__).resolve().parent
    check_python()
    fix_obsolete_backports_interactively()
    step("Έλεγχος PyInstaller…")
    ensure_pyinstaller()
    config, plan = configure(script_dir)

    if config.auto_install_missing and plan.pip_packages:
        install_missing_packages(plan)

    req_path = write_requirements_manifest(script_dir, config.app_name, plan)
    ok(f"Γράφτηκε requirements manifest: {req_path.name}")

    if config.clean_before_build:
        step("Καθαρισμός προηγούμενων builds…")
        clean_previous(script_dir, config.app_name)

    exe = build(config, script_dir, plan)
    print_result(exe, config.source, req_path)

    if config.open_dist_after_build:
        dist_dir = exe.parent if exe.parent.exists() else script_dir / "dist"
        open_in_explorer(dist_dir)

    if config.run_after_build:
        step("Εκτέλεση του exe…")
        subprocess.Popen([str(exe)], cwd=str(exe.parent))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  ⛔  Διακόπηκε από τον χρήστη.\n")
        raise SystemExit(130)
