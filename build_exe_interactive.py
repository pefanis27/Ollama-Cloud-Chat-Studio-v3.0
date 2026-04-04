#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Διαδραστικός οδηγός δημιουργίας εκτελέσιμου με PyInstaller.

Το αρχείο συγκεντρώνει την πλήρη ροή του build wizard: επιλογή αρχείου πηγής, συλλογή ρυθμίσεων από τον χρήστη, καθαρισμό προηγούμενων artifacts, σύνθεση hidden imports και τελική δημιουργία του εκτελέσιμου. Οι νέες σημειώσεις έχουν οργανωθεί σε docstrings ώστε να εξηγούν τον ρόλο κάθε μέρους του script χωρίς να επιβαρύνουν τη λειτουργικότητα."""
from __future__ import annotations
import importlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
APP_VERSION = '3.1'
SEP = '=' * 72
SEP2 = '─' * 72
DEFAULT_APP_NAME = 'OllamaCloudChatStudio'
DEFAULT_UPX_EXCLUDES = ['_uuid.pyd', 'python3.dll']
DEFAULT_STDLIB_HIDDEN_IMPORTS = ['concurrent.futures', 'concurrent.futures._base', 'concurrent.futures.thread', 'concurrent.futures.process', 'http.server', 'urllib.request', 'urllib.error', 'xml.etree.ElementTree', 'email.mime.text']

@dataclass
class BuildConfig:
    """Dataclass που συγκεντρώνει όλες τις ρυθμίσεις του build σε ένα ενιαίο αντικείμενο.

Η ύπαρξη ενιαίας δομής μειώνει την πολυπλοκότητα των κλήσεων και βοηθά να περνά το configuration με καθαρό και προβλέψιμο τρόπο."""
    source: Path
    app_name: str
    one_file: bool
    console: bool
    icon_path: str = ''
    use_upx: bool = False
    upx_excludes: list[str] = field(default_factory=list)
    clean_before_build: bool = True
    include_pypdf: bool = True
    open_dist_after_build: bool = False
    run_after_build: bool = False
    extra_hidden_imports: list[str] = field(default_factory=list)

def step(msg: str) -> None:
    """Υλοποιεί το βήμα «step» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: msg."""
    print(f'\n  ▶  {msg}')

def ok(msg: str) -> None:
    """Υλοποιεί το βήμα «ok» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: msg."""
    print(f'  ✅  {msg}')

def warn(msg: str) -> None:
    """Υλοποιεί το βήμα «warn» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: msg."""
    print(f'  ⚠   {msg}')

def fail(msg: str, code: int=1) -> None:
    """Υλοποιεί το βήμα «fail» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: msg, code."""
    print(f'\n  ❌  {msg}\n')
    raise SystemExit(code)

def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Υλοποιεί το βήμα «run» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: cmd."""
    print(f"\n  $ {' '.join((str(c) for c in cmd))}\n")
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        fail(f'Η εντολή απέτυχε με κωδικό {result.returncode}.')
    return result

def ask_text(prompt: str, default: str='') -> str:
    """Συλλέγει πληροφορία από τον χρήστη για το βήμα «ask_text» με προβλέψιμη συμπεριφορά εισόδου.

Βασικά ορίσματα: prompt, default."""
    suffix = f' [{default}]' if default else ''
    value = input(f'{prompt}{suffix}: ').strip()
    return value if value else default

def ask_yes_no(prompt: str, default: bool=True) -> bool:
    """Συλλέγει πληροφορία από τον χρήστη για το βήμα «ask_yes_no» με προβλέψιμη συμπεριφορά εισόδου.

Βασικά ορίσματα: prompt, default."""
    default_text = 'Y/n' if default else 'y/N'
    while True:
        value = input(f'{prompt} [{default_text}]: ').strip().lower()
        if not value:
            return default
        if value in {'y', 'yes', 'ν', 'ναι', 'nai'}:
            return True
        if value in {'n', 'no', 'ο', 'oxi', 'όχι'}:
            return False
        print('  Δώσε y ή n.')

def ask_choice(prompt: str, options: list[tuple[str, str]], default_index: int=0) -> str:
    """Συλλέγει πληροφορία από τον χρήστη για το βήμα «ask_choice» με προβλέψιμη συμπεριφορά εισόδου.

Βασικά ορίσματα: prompt, options, default_index."""
    print(f'\n{prompt}')
    for idx, (_, label) in enumerate(options, 1):
        marker = ' (default)' if idx - 1 == default_index else ''
        print(f'  [{idx}] {label}{marker}')
    while True:
        raw = input('Επιλογή: ').strip()
        if not raw:
            return options[default_index][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print('  Μη έγκυρη επιλογή.')

def parse_csv(raw: str) -> list[str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «parse_csv» με συνεπή τρόπο.

Βασικά ορίσματα: raw."""
    return [x.strip() for x in raw.split(',') if x.strip()]

def check_python() -> None:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «check_python» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση."""
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 9):
        fail(f'Απαιτείται Python 3.9+. Τρέχουσα έκδοση: {major}.{minor}')
    ok(f'Python {major}.{minor}.{sys.version_info.micro}')

def ensure_pyinstaller() -> str:
    """Υλοποιεί το βήμα «ensure_pyinstaller» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
    try:
        import PyInstaller
        version = PyInstaller.__version__
        ok(f'PyInstaller {version}')
        return version
    except ImportError:
        pass
    step('Εγκατάσταση/αναβάθμιση PyInstaller…')
    run([sys.executable, '-m', 'pip', 'install', 'pyinstaller', '--upgrade'])
    import PyInstaller
    importlib.reload(PyInstaller)
    version = PyInstaller.__version__
    ok(f'PyInstaller {version} εγκαταστάθηκε')
    return version

def has_module(name: str) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «has_module» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: name."""
    try:
        __import__(name)
        return True
    except Exception:
        return False

def find_upx() -> str | None:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «find_upx» με συνεπή τρόπο."""
    return shutil.which('upx')

def find_sources(script_dir: Path) -> list[Path]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «find_sources» με συνεπή τρόπο.

Βασικά ορίσματα: script_dir."""
    this_file = Path(__file__).resolve()
    candidates = [f for f in sorted(script_dir.glob('*.py'), key=lambda p: p.name.lower()) if f.resolve() != this_file and (not f.name.lower().startswith('build_exe'))]
    preferred = [f for f in candidates if re.search('ollama', f.name, re.IGNORECASE)]
    return preferred or candidates

def choose_source(script_dir: Path) -> Path:
    """Λαμβάνει απόφαση για το βήμα «choose_source» εφαρμόζοντας τους κανόνες που χρησιμοποιεί η εφαρμογή.

Βασικά ορίσματα: script_dir."""
    candidates = find_sources(script_dir)
    if not candidates:
        fail('Δεν βρέθηκαν .py αρχεία για build στον ίδιο φάκελο.')
    print('\nΔιαθέσιμα αρχεία πηγής:\n')
    for i, c in enumerate(candidates, 1):
        size_kb = c.stat().st_size / 1024
        print(f'  [{i}] {c.name}  ({size_kb:.1f} KB)')
    while True:
        raw = input(f'\nΕπίλεξε source file [1-{len(candidates)}] (default 1): ').strip()
        if not raw:
            return candidates[0].resolve()
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            return candidates[int(raw) - 1].resolve()
        print('  Μη έγκυρη επιλογή.')

def _handle_remove_error(func, path, excinfo) -> None:
    """Υλοποιεί το βήμα «_handle_remove_error» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: func, path, excinfo."""
    err = excinfo if isinstance(excinfo, BaseException) else excinfo[1]
    path_obj = Path(path)
    if isinstance(err, PermissionError):
        print()
        warn(f'Το αρχείο ή ο φάκελος είναι κλειδωμένος και δεν μπορεί να διαγραφεί: {path_obj}')
        print('     Συνήθως αυτό σημαίνει ότι το παλιό .exe είναι ακόμη ανοιχτό.')
        while True:
            action = input("     Κλείσ' το και πάτησε [R]etry, ή [A]bort για ακύρωση build: ").strip().lower()
            if action in {'', 'r', 'retry'}:
                try:
                    func(path)
                    return
                except PermissionError:
                    warn('     Παραμένει κλειδωμένο.')
                    continue
                except Exception as retry_exc:
                    fail(f'Αποτυχία διαγραφής του {path_obj}: {retry_exc}')
            if action in {'a', 'abort'}:
                fail('Το build ακυρώθηκε επειδή το παλιό εκτελέσιμο είναι ακόμη ανοιχτό.', 2)
            print('     Δώσε R ή A.')
    raise err

def _remove_target(path: Path) -> bool:
    """Υλοποιεί το βήμα «_remove_target» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: path."""
    if not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path, onexc=_handle_remove_error)
    else:
        path.unlink()
    return True

def clean_previous(script_dir: Path, app_name: str) -> None:
    """Κανονικοποιεί ή καθαρίζει δεδομένα στο βήμα «clean_previous» ώστε οι επόμενες φάσεις να λαμβάνουν ασφαλή και συνεπή είσοδο.

Βασικά ορίσματα: script_dir, app_name."""
    targets = [script_dir / 'build', script_dir / 'dist', script_dir / f'{app_name}.spec']
    cleaned = False
    for t in targets:
        try:
            cleaned = _remove_target(t) or cleaned
        except FileNotFoundError:
            continue
    if cleaned:
        ok('Καθαρίστηκαν προηγούμενα builds')
    else:
        ok('Δεν υπήρχαν προηγούμενα build artifacts')

def collect_hidden_imports(config: BuildConfig) -> list[str]:
    """Υλοποιεί το βήμα «collect_hidden_imports» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: config."""
    hidden = list(DEFAULT_STDLIB_HIDDEN_IMPORTS)
    if config.include_pypdf and has_module('pypdf'):
        hidden.append('pypdf')
    hidden.extend(config.extra_hidden_imports)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in hidden:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped

def build(config: BuildConfig, script_dir: Path) -> Path:
    """Υλοποιεί το βήμα «build» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: config, script_dir."""
    hidden_imports = collect_hidden_imports(config)
    cmd = [sys.executable, '-m', 'PyInstaller', f'--name={config.app_name}', '--clean', '--noconfirm']
    cmd.append('--onefile' if config.one_file else '--onedir')
    cmd.append('--console' if config.console else '--windowed')
    if config.icon_path:
        cmd += ['--icon', config.icon_path]
    if config.use_upx:
        for item in config.upx_excludes:
            cmd.append(f'--upx-exclude={item}')
    else:
        cmd.append('--noupx')
    for hi in hidden_imports:
        cmd.append(f'--hidden-import={hi}')
    cmd.append(str(config.source))
    print(f'\n{SEP2}')
    step('Έναρξη build…')
    print(SEP2)
    run(cmd, cwd=str(script_dir))
    if config.one_file:
        exe = script_dir / 'dist' / f'{config.app_name}.exe'
    else:
        exe = script_dir / 'dist' / config.app_name / f'{config.app_name}.exe'
    return exe

def print_summary(config: BuildConfig, hidden_imports: Iterable[str], upx_found: str | None) -> None:
    """Υλοποιεί το βήμα «print_summary» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: config, hidden_imports, upx_found."""
    print(f'\n{SEP}')
    print('  Σύνοψη build')
    print(SEP2)
    print(f'  Πηγή                 : {config.source.name}')
    print(f'  Όνομα εφαρμογής      : {config.app_name}')
    print(f"  Build mode           : {('onefile' if config.one_file else 'onedir')}")
    print(f"  Terminal window      : {('Ναι' if config.console else 'Όχι')}")
    print(f"  Εικονίδιο            : {config.icon_path or 'Κανένα'}")
    print(f"  UPX                  : {('Ναι' if config.use_upx else 'Όχι')}")
    if upx_found:
        print(f'  UPX path             : {upx_found}')
    if config.use_upx:
        print(f"  UPX excludes         : {(', '.join(config.upx_excludes) if config.upx_excludes else 'Κανένα')}")
    print(f"  Καθαρισμός build     : {('Ναι' if config.clean_before_build else 'Όχι')}")
    print(f"  PDF support (pypdf)  : {('Ναι' if config.include_pypdf and has_module('pypdf') else 'Όχι')}")
    print(f"  Hidden imports       : {', '.join(hidden_imports)}")
    print(f"  Run μετά το build    : {('Ναι' if config.run_after_build else 'Όχι')}")
    print(f"  Άνοιγμα dist folder  : {('Ναι' if config.open_dist_after_build else 'Όχι')}")
    print(SEP)

def configure(script_dir: Path) -> BuildConfig:
    """Υλοποιεί το βήμα «configure» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: script_dir."""
    step('Εύρεση αρχείου πηγής…')
    source = choose_source(script_dir)
    ok(f'Πηγή: {source.name}')
    default_app_name = Path(source).stem
    app_name = ask_text('Όνομα εφαρμογής / exe', default_app_name or DEFAULT_APP_NAME)
    mode = ask_choice('Επίλεξε τύπο build:', [('onefile', 'Ένα μόνο .exe (ευκολότερη διανομή, πιο βαρύ startup)'), ('onedir', 'Φάκελος dist με exe + αρχεία (πιο σταθερό για apps με αρχεία)')], default_index=1)
    console_mode = ask_choice('Θες terminal window;', [('console', 'Ναι, να φαίνεται terminal/logs'), ('windowed', 'Όχι, καθαρό GUI χωρίς terminal')], default_index=0)
    icon_path = ask_text('Διαδρομή εικονιδίου .ico (άφησέ το κενό αν δεν θες)', '')
    if icon_path:
        icon_candidate = Path(icon_path)
        if not icon_candidate.is_absolute():
            icon_candidate = (script_dir / icon_candidate).resolve()
        if not icon_candidate.exists():
            warn(f'Το icon δεν βρέθηκε: {icon_candidate}. Θα αγνοηθεί.')
            icon_path = ''
        else:
            icon_path = str(icon_candidate)
    use_pypdf = False
    if has_module('pypdf'):
        use_pypdf = ask_yes_no('Βρέθηκε pypdf. Να συμπεριληφθεί υποστήριξη PDF;', True)
    else:
        warn('Το pypdf δεν είναι εγκατεστημένο. PDF support δεν θα προστεθεί.')
    upx_path = find_upx()
    use_upx = False
    upx_excludes: list[str] = []
    if upx_path:
        use_upx = ask_yes_no('Βρέθηκε UPX. Να χρησιμοποιηθεί συμπίεση UPX;', False)
        if use_upx:
            raw_excludes = ask_text('UPX excludes (comma separated)', ', '.join(DEFAULT_UPX_EXCLUDES))
            upx_excludes = parse_csv(raw_excludes)
    else:
        ok('UPX δεν βρέθηκε — θα χρησιμοποιηθεί --noupx')
    clean_before = ask_yes_no('Να καθαριστούν προηγούμενα build/dist/spec;', True)
    extra_hidden_imports = parse_csv(ask_text('Extra hidden imports (comma separated, προαιρετικό)', ''))
    run_after = ask_yes_no('Να τρέξει το exe μόλις ολοκληρωθεί το build;', False)
    open_dist = ask_yes_no('Να ανοίξει ο φάκελος dist μετά το build;', False)
    config = BuildConfig(source=source, app_name=app_name, one_file=mode == 'onefile', console=console_mode == 'console', icon_path=icon_path, use_upx=use_upx, upx_excludes=upx_excludes, clean_before_build=clean_before, include_pypdf=use_pypdf, open_dist_after_build=open_dist, run_after_build=run_after, extra_hidden_imports=extra_hidden_imports)
    hidden_imports = collect_hidden_imports(config)
    print_summary(config, hidden_imports, upx_path)
    if not ask_yes_no('Να ξεκινήσει το build με αυτές τις ρυθμίσεις;', True):
        fail('Το build ακυρώθηκε από τον χρήστη.', 0)
    return config

def open_in_explorer(path: Path) -> None:
    """Υλοποιεί τη λειτουργική ρουτίνα «open_in_explorer» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: path."""
    if sys.platform.startswith('win'):
        os.startfile(str(path))
    elif sys.platform == 'darwin':
        subprocess.Popen(['open', str(path)])
    else:
        subprocess.Popen(['xdg-open', str(path)])

def print_result(exe: Path, source: Path) -> None:
    """Υλοποιεί το βήμα «print_result» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: exe, source."""
    if not exe.exists():
        fail('Το εκτελέσιμο δεν δημιουργήθηκε.\nΈλεγξε τα μηνύματα του PyInstaller παραπάνω.')
    size_mb = exe.stat().st_size / (1024 * 1024)
    print(f'\n{SEP}')
    print('  ✅  Build επιτυχές!')
    print(SEP2)
    print(f'  📁  Αρχείο  : {exe}')
    print(f'  📦  Μέγεθος : {size_mb:.1f} MB')
    print(f'  🐍  Πηγή    : {source.name}')
    print(SEP2)
    print(f'  🚀  Εκτέλεση:')
    print(f'        {exe.name}')
    print(SEP)

def main() -> None:
    """Σημείο εισόδου της εφαρμογής.

Η συνάρτηση εκτελεί τα βασικά βήματα αρχικοποίησης με σωστή σειρά και ενεργοποιεί τις επιμέρους ρουτίνες που χρειάζονται για να ξεκινήσει το πρόγραμμα."""
    print(f'\n{SEP}')
    print(f'  Ollama Cloud Chat Studio v{APP_VERSION} — Interactive Build Wizard')
    print(f'  Python: {sys.executable}')
    print(SEP)
    script_dir = Path(__file__).resolve().parent
    check_python()
    step('Έλεγχος PyInstaller…')
    ensure_pyinstaller()
    config = configure(script_dir)
    if config.clean_before_build:
        step('Καθαρισμός προηγούμενων builds…')
        clean_previous(script_dir, config.app_name)
    exe = build(config, script_dir)
    print_result(exe, config.source)
    if config.open_dist_after_build:
        dist_dir = exe.parent if exe.parent.exists() else script_dir / 'dist'
        open_in_explorer(dist_dir)
    if config.run_after_build:
        step('Εκτέλεση του exe…')
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n\n  ⛔  Διακόπηκε από τον χρήστη.\n')
        raise SystemExit(130)
