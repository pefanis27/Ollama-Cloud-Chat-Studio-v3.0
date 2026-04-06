#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Εγκαταστάτης πακέτων για το Ollama_cloud_chat_Browser.py.

Το script εγκαθιστά τα εξωτερικά Python packages που χρησιμοποιεί η εφαρμογή.
Από έλεγχο του αρχείου, τα βασικά imports είναι από την standard library και
δεν χρειάζονται pip εγκατάσταση. Τα εξωτερικά packages που εμφανίζονται είναι:

- pypdf
- PyMuPDF (module name: fitz)

Το script μπορεί προαιρετικά να κάνει και έλεγχο εγκατάστασης στο τέλος.
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class PackageSpec:
    """Περιγράφει ένα πακέτο που θα εγκατασταθεί μέσω pip."""

    pip_name: str
    import_name: str
    description: str
    required_for_full_features: bool = True


PACKAGE_SPECS: List[PackageSpec] = [
    PackageSpec(
        pip_name="pypdf",
        import_name="pypdf",
        description="Ανάγνωση και επεξεργασία PDF.",
        required_for_full_features=True,
    ),
    PackageSpec(
        pip_name="PyMuPDF",
        import_name="fitz",
        description="Βελτιωμένο PDF polish/export μέσω PyMuPDF.",
        required_for_full_features=True,
    ),
]


def run_command(command: List[str]) -> int:
    """Εκτελεί εντολή και επιστρέφει τον κωδικό εξόδου."""
    print("\n[EXEC]", " ".join(command))
    completed = subprocess.run(command)
    return int(completed.returncode)


def is_module_available(module_name: str) -> bool:
    """Ελέγχει αν ένα module εισάγεται επιτυχώς στο τρέχον περιβάλλον."""
    try:
        importlib.import_module(module_name)
        return True
    except Exception:
        return False


def install_packages(packages: Iterable[PackageSpec], upgrade_pip: bool = False) -> int:
    """Εγκαθιστά τα packages μέσω του τρέχοντος Python interpreter."""
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
    """Επαληθεύει ότι όλα τα modules εισάγονται σωστά."""
    failed = 0
    print("\n[VERIFY] Έλεγχος imports...")
    for pkg in packages:
        ok = is_module_available(pkg.import_name)
        status = "OK" if ok else "FAIL"
        print(f" - {pkg.import_name:<10} ({pkg.pip_name:<10}) : {status}")
        if not ok:
            failed += 1
    return failed


def print_summary() -> None:
    """Εκτυπώνει σύντομη σύνοψη των dependencies."""
    print("\n" + "=" * 72)
    print("ΣΥΝΟΨΗ DEPENDENCIES")
    print("=" * 72)
    print("Η εφαρμογή χρησιμοποιεί κυρίως Python standard library modules.")
    print("Τα εξωτερικά packages που εγκαθίστανται για πλήρη λειτουργικότητα είναι:")
    for pkg in PACKAGE_SPECS:
        print(f" - {pkg.pip_name}  (import: {pkg.import_name})")
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    """Αναλύει τα ορίσματα γραμμής εντολών."""
    parser = argparse.ArgumentParser(
        description="Εγκατάσταση των Python packages για το Ollama_cloud_chat_Browser.py"
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
    return parser.parse_args()


def main() -> int:
    """Κύριο σημείο εκτέλεσης του installer."""
    args = parse_args()
    print_summary()
    print(f"[INFO] Python executable: {sys.executable}")
    print(f"[INFO] Python version   : {sys.version.split()[0]}")

    if args.verify_only:
        verify_failed = verify_packages(PACKAGE_SPECS)
        if verify_failed:
            print(f"\n[RESULT] Λείπουν {verify_failed} package(s).")
            return 1
        print("\n[RESULT] Όλα τα απαραίτητα packages είναι εγκατεστημένα.")
        return 0

    failed = install_packages(PACKAGE_SPECS, upgrade_pip=args.upgrade_pip)
    verify_failed = verify_packages(PACKAGE_SPECS)

    if failed or verify_failed:
        print("\n[RESULT] Η εγκατάσταση ολοκληρώθηκε με προβλήματα.")
        return 1

    print("\n[RESULT] Η εγκατάσταση ολοκληρώθηκε επιτυχώς.")
    print("[TIP] Μπορείς τώρα να τρέξεις το Ollama_cloud_chat_Browser.py με τον ίδιο interpreter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
