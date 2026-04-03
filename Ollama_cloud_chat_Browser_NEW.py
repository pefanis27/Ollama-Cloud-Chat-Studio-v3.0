#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ollama Cloud Chat Studio  —  v3.0
===================================
Ιστορικό εκδόσεων:
  v1.x  — Browser UI, streaming, cloud model scraping, file attachments,
           Prism highlighting, drag & drop, dark/light theme, model params,
           tokens/sec, /api/health, model name bug fix (library/ prefix)
  v3.0  — Πλήρως έγχρωμο light theme για κώδικα (Solarized Light base +
           custom vivid token palette), ενοποίηση έκδοσης παντού ως v3.0
"""

from __future__ import annotations

import argparse
import base64
import ast
import copy
import datetime
import html
import json
import logging
import os
import queue as _queue
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Η εφαρμογή χρησιμοποιεί πλέον direct HTTPS κλήσεις στο Ollama Cloud API
# και δεν εξαρτάται από το τοπικό Ollama runtime.


# ─────────────────────────────── Logging ────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────── Constants ───────────────────────────────────

APP_TITLE       = "Ollama Cloud Chat Studio v3.0"
HOST            = "127.0.0.1"
DEFAULT_PORT    = 8765
MODEL_CACHE_SECONDS = 15 * 60  # 15 λεπτά TTL για model cache
BROWSER_SESSION_GRACE_SECONDS = 8.0
BROWSER_SESSION_HEARTBEAT_STALE_SECONDS = 30.0
BROWSER_SESSION_WATCHDOG_POLL_SECONDS = 2.0

# Βάλε εδώ το Ollama Cloud API key σου αν θέλεις να είναι ενσωματωμένο
# μέσα στο ίδιο το .py αρχείο. Αν μείνει κενό, τότε η εφαρμογή θα δοκιμάσει
# να το πάρει από τη μεταβλητή περιβάλλοντος OLLAMA_API_KEY.
EMBEDDED_OLLAMA_API_KEY = ""

BASE_DIR        = Path(__file__).resolve().parent
UPLOADS_DIR        = BASE_DIR / "_chat_uploads"
GENERATED_CODE_DIR = BASE_DIR / "_generated_code_blocks"
APP_CONFIG_FILE    = BASE_DIR / "ollama_cloud_chat_settings.json"

MAX_UPLOAD_BYTES_PER_FILE        = 15 * 1024 * 1024  # 15 MB
MAX_UPLOAD_FILES_PER_MESSAGE     = 8
MAX_TEXT_CHARS_PER_FILE          = 12_000
MAX_TOTAL_TEXT_CHARS_PER_MESSAGE = 30_000
MAX_HISTORY_MESSAGES             = 100
MAX_REQUEST_BODY_BYTES           = int(MAX_UPLOAD_FILES_PER_MESSAGE * MAX_UPLOAD_BYTES_PER_FILE * 1.5)

# Ασφαλείς HTTP headers που προστίθενται σε όλες τις responses.
SECURITY_HEADERS: Dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options":        "SAMEORIGIN",
    "X-XSS-Protection":       "1; mode=block",
    "Referrer-Policy":        "strict-origin-when-cross-origin",
}

DEFAULT_SYSTEM_PROMPT = '''Είσαι principal software engineer, software architect και technical lead με εξειδίκευση στην ανάπτυξη επαγγελματικών εφαρμογών, κυρίως σε Python, αλλά και σε web, desktop, API, automation, data, AI/ML και DevOps όπου χρειάζεται.

Κύριος στόχος:
Για κάθε αίτημα του χρήστη πρέπει να παράγεις λύση επαγγελματικού επιπέδου, σωστά σχεδιασμένη, πλήρη, καθαρή, εκτελέσιμη και άμεσα αξιοποιήσιμη.

Στυλ και ποιότητα που απαιτούνται:
- Να γράφεις σαν έμπειρος senior engineer που παραδίδει production-ready δουλειά.
- Να προτιμάς απλές, στιβαρές και συντηρήσιμες λύσεις αντί για εντυπωσιακές αλλά εύθραυστες λύσεις.
- Να δίνεις έμφαση σε αναγνωσιμότητα, σωστή αρχιτεκτονική, καθαρή ονοματοδοσία, modular σχεδίαση και επαγγελματικό formatting.
- Να αποφεύγεις πρόχειρο, βιαστικό ή “demo-only” κώδικα.
- Να χρησιμοποιείς ασφαλή defaults, λογική διαχείριση σφαλμάτων, validation εισόδων και καθαρό flow εκτέλεσης.
- Ο κώδικας πρέπει να είναι έτοιμος για άμεση δοκιμή και όσο γίνεται κοντά σε πραγματική παραγωγική χρήση.

Υποχρεωτική δομή απάντησης:
1) Περιγραφή Εφαρμογής
2) Πλήρης Κώδικας
3) Προαπαιτούμενα

Απαγορεύεται να αλλάξεις αυτή τη βασική δομή.

[1] Περιγραφή Εφαρμογής
- Ξεκίνα πάντα με ακριβώς αυτόν τον τίτλο: "Περιγραφή Εφαρμογής"
- Γράψε σύντομη αλλά ουσιαστική περιγραφή σε απλό, επαγγελματικό κείμενο.
- Εξήγησε τι κάνει η εφαρμογή, ποιο πρόβλημα λύνει, ποια είναι τα βασικά χαρακτηριστικά της και πώς χρησιμοποιείται.
- Αν η λύση έχει πάνω από ένα αρχείο, να αναφέρεις ρητά και καθαρά τα ονόματα των αρχείων μέσα στην περιγραφή, σε μορφή όπως: (main.py), (api.py), (gui.py).
- Όταν υπάρχουν πολλά scripts Python, να αναφέρεις όλα τα ακριβή .py ονόματα μέσα στην περιγραφή με φυσικό τρόπο.
- Μην γράφεις ψευδοκώδικα σε αυτή την ενότητα.
- Μην παραλείπεις ποτέ αυτή την ενότητα.

[2] Πλήρης Κώδικας
- Συνέχισε πάντα με ακριβώς αυτόν τον τίτλο: "Πλήρης Κώδικας"
- Δώσε πλήρη, σωστό, εκτελέσιμο, επαγγελματικό και ολοκληρωμένο κώδικα.
- Ο κώδικας πρέπει να είναι σε καθαρά markdown code blocks για εύκολο copy.
- Μην δίνεις ποτέ αποσπασματικό κώδικα, placeholders, "...", "συνέχεια", "συμπλήρωσε εδώ" ή ψευδοκώδικα.
- Αν διορθώνεις υπάρχον κώδικα, να επιστρέφεις το πλήρες διορθωμένο αρχείο και όχι μόνο το patch, εκτός αν ο χρήστης ζητήσει ρητά diff.
- Αν η λύση γίνεται σωστά σε ένα αρχείο, προτίμησε ένα πλήρες αρχείο.
- Αν απαιτούνται πολλά αρχεία, δώσε όλα τα απαραίτητα αρχεία και μόνο τα απαραίτητα.
- Κάθε πλήρες αρχείο πρέπει να δίνεται ολόκληρο μέσα σε ένα και μόνο ένα code block.
- Μην σπας το ίδιο αρχείο σε πολλά συνεχόμενα code blocks.
- Για Python να παράγεις όμορφα μορφοποιημένο κώδικα, με σωστή στοίχιση, καθαρή δομή, type hints όπου βοηθούν, ουσιαστικές συναρτήσεις/κλάσεις και λογικά σχόλια.
- Όπου ταιριάζει, να χρησιμοποιείς ελληνικά σχόλια που βοηθούν στην κατανόηση χωρίς να φορτώνουν άσκοπα τον κώδικα.
- Να περιλαμβάνεις όλα τα απαραίτητα imports.
- Να φροντίζεις ο κώδικας να έχει καθαρό entry point, π.χ. main() και if __name__ == "__main__": όπου χρειάζεται.
- Να φροντίζεις για σωστή διαχείριση exceptions, καθαρά μηνύματα λάθους και ασφαλή συμπεριφορά.
- Να χρησιμοποιείς λογικό validation εισόδων και να αποφεύγεις σιωπηλά failures.
- Για GUI, web app, desktop app, API ή εργαλεία γραμμής εντολών, να δίνεις αποτέλεσμα επαγγελματικού επιπέδου με καλή εμπειρία χρήστη.
- Για web ή GUI εφαρμογές, να προτιμάς καθαρό και όμορφο UI με σωστή δομή και πρακτική χρηστικότητα.
- Για αρχεία ρυθμίσεων, environment variables, JSON, YAML, HTML, CSS, JS, SQL, shell ή batch αρχεία, να τα δίνεις επίσης ολοκληρωμένα όταν απαιτούνται.
- Αν το αίτημα αφορά απόδοση, ασφάλεια, συντήρηση ή επεκτασιμότητα, να ενσωματώνεις αυτές τις απαιτήσεις στον κώδικα και όχι μόνο στην περιγραφή.

[3] Προαπαιτούμενα
- Ολοκλήρωσε πάντα με ακριβώς αυτόν τον τίτλο: "Προαπαιτούμενα"
- Δώσε καθαρά και συνοπτικά ό,τι χρειάζεται για να τρέξει η εφαρμογή.
- Συμπερίλαβε βιβλιοθήκες Python, pip εντολές εγκατάστασης, απαιτούμενες εκδόσεις, αρχεία ρυθμίσεων, environment variables, εξωτερικές υπηρεσίες, βάσεις δεδομένων, μοντέλα ή άλλα dependencies.
- Αν δεν απαιτείται κάτι ιδιαίτερο, να το λες καθαρά.
- Όταν χρειάζεται, να δίνεις συγκεκριμένη εντολή εγκατάστασης όπως π.χ. pip install package1 package2.

Επιπλέον κρίσιμοι κανόνες:
- Πάντα να απαντάς κυρίως στα ελληνικά, εκτός αν ο χρήστης ζητήσει άλλη γλώσσα.
- Μην απαντάς μόνο με θεωρία όταν ο χρήστης ζητά εφαρμογή ή κώδικα.
- Μην θυσιάζεις την πληρότητα για συντομία όταν ο χρήστης ζητά ολοκληρωμένη υλοποίηση.
- Να προτιμάς ονόματα αρχείων καθαρά, περιγραφικά και επαγγελματικά.
- Αν υπάρχουν πολλά Python αρχεία, να δίνεις σαφή και πραγματικά filenames, π.χ. (train_and_test_mnist.py), (load_and_test_mnist.py), (app.py), (server.py), (client.py).
- Να αποφεύγεις μπερδεμένα προσωρινά ονόματα, γενικά labels ή ασαφή file naming.
- Να παράγεις κώδικα που να μπορεί να αποθηκευτεί αυτούσιος σε αρχεία και να εκτελεστεί με ελάχιστες προσαρμογές ή χωρίς καμία.
- Ποτέ μη δίνεις ημιτελή ή μη εκτελέσιμη λύση ως τελική απάντηση.
- Όταν έχεις αβεβαιότητα για μία τεχνική επιλογή, να επιλέγεις την πιο σταθερή, συντηρήσιμη και επαγγελματική προσέγγιση.
'''

TEXT_EXTENSIONS: Set[str] = {
    ".txt", ".py", ".md", ".markdown", ".json", ".jsonl", ".csv", ".tsv",
    ".yaml", ".yml", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".jsx",
    ".tsx", ".java", ".c", ".cpp", ".h", ".hpp", ".cs", ".go", ".rs",
    ".php", ".rb", ".swift", ".kt", ".kts", ".sql", ".ini", ".cfg", ".conf",
    ".log", ".bat", ".ps1", ".sh", ".zsh", ".toml", ".tex", ".r", ".m",
}

IMAGE_EXTENSIONS: Set[str] = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff",
}

# Δεκτές επεκτάσεις για το file input (HTML accept attribute)
ACCEPTED_FILE_TYPES = (
    "image/*,"
    ".txt,.py,.md,.markdown,.json,.jsonl,.csv,.tsv,.yaml,.yml,.xml,"
    ".html,.htm,.css,.js,.ts,.jsx,.tsx,.java,.c,.cpp,.h,.hpp,.cs,.go,"
    ".rs,.php,.rb,.swift,.kt,.kts,.sql,.ini,.cfg,.conf,.log,.bat,.ps1,"
    ".sh,.zsh,.toml,.tex,.r,.m,.pdf"
)

OFFICIAL_SEARCH_URL         = "https://ollama.com/search?c=cloud"
OFFICIAL_GENERAL_SEARCH_URL = "https://ollama.com/search"
OFFICIAL_CLOUD_API_TAGS_URL = "https://ollama.com/api/tags"
OLLAMA_SEARCH_API_URL       = "https://ollama.com/api/search"
OLLAMA_LIBRARY_BASE         = "https://ollama.com/library/"
REQUEST_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}

OLLAMA_DIRECT_BASE_URL     = "https://ollama.com"
OLLAMA_DIRECT_API_BASE_URL = f"{OLLAMA_DIRECT_BASE_URL}/api"

# Πιάνει model(:tag)?-cloud — συμπεριλαμβανομένου τυχόν 'library/' prefix που αφαιρείται αργότερα
CLOUD_TAG_RE    = re.compile(r"\b([a-zA-Z0-9._/-]+:(?:[a-zA-Z0-9._-]+-)?cloud)\b")
LIBRARY_LINK_RE = re.compile(r'href="/library/([a-zA-Z0-9._/-]+)"', flags=re.IGNORECASE)
SEARCH_TEXT_FAMILY_RE = re.compile(
    r'>\s*([a-zA-Z0-9._/-]+)\s+[^<]{0,250}?\bcloud\b',
    flags=re.IGNORECASE,
)

CONTEXT_WINDOW_RE = re.compile(
    r"([0-9][0-9.,]*)\s*([KMB])?\s+context\s+window",
    flags=re.IGNORECASE,
)

CLOUD_WORD_RE = re.compile(r"\bcloud\b", flags=re.IGNORECASE)


# ─────────────────────────── Data classes ────────────────────────────────────

@dataclass
class ModelRegistry:
    """Κρατά την τρέχουσα κατάσταση της λίστας cloud μοντέλων."""

    models:              List[str] = field(default_factory=list)
    model_meta:          Dict[str, Dict[str, object]] = field(default_factory=dict)
    source:              str       = "initializing"
    last_refresh_ts:     float     = 0.0
    last_error:          str       = ""
    refresh_in_progress: bool      = False
    recommended_model:   str       = ""
    lock: threading.Lock           = field(default_factory=threading.Lock)

    def as_dict(self) -> Dict[str, object]:
        with self.lock:
            models = list(self.models)
            rec    = self.recommended_model
            model_meta = copy.deepcopy(self.model_meta)
            source = self.source
            last_refresh_ts = self.last_refresh_ts
            last_error = self.last_error
            refresh_in_progress = self.refresh_in_progress

        try:
            models = sorted(models, key=lambda model: score_model(model, model_meta.get(model, {}), "overall"), reverse=True)  # type: ignore[name-defined]
        except Exception:
            pass

        models_with_context = sum(
            1 for model in models
            if isinstance(model_meta.get(model), dict) and model_meta.get(model, {}).get("num_ctx_max")
        )

        return {
            "models":                models,
            "model_meta":            model_meta,
            "models_with_context":   models_with_context,
            "source":                source,
            "last_refresh_ts":       last_refresh_ts,
            "last_error":            last_error,
            "refresh_in_progress":   refresh_in_progress,
            "recommended_model":     rec,
        }


@dataclass
class ChatSession:
    """Αποθηκεύει την κατάσταση της συνομιλίας στον server."""

    messages:     List[Dict]     = field(default_factory=list)
    history:      List[Dict]     = field(default_factory=list)
    upload_paths: Set[str]       = field(default_factory=set)
    lock:         threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        with self.lock:
            self.messages.clear()
            self.history.clear()
            paths_to_delete = list(self.upload_paths)
            self.upload_paths.clear()

        cleanup_targets = [UPLOADS_DIR, GENERATED_CODE_DIR, Path(tempfile.gettempdir()) / "ollama_cloud_chat_exec"]

        # File I/O εκτός lock ώστε να μην μπλοκάρει άλλα threads.
        for item in paths_to_delete:
            try:
                path = Path(item)
                if path.exists() and path.is_file():
                    path.unlink()
            except Exception:
                pass

        for target in cleanup_targets:
            try:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass

        for target in cleanup_targets[:2]:
            try:
                target.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass


@dataclass
class AppConfig:
    """Επιλεγμένες ρυθμίσεις εφαρμογής που αποθηκεύονται σε αρχείο JSON."""

    ollama_api_key: str = ""
    updated_at: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)

    def as_public_dict(self) -> Dict[str, object]:
        with self.lock:
            key = str(self.ollama_api_key or "")
            updated_at = str(self.updated_at or "")
        return {
            "ollama_api_key": key,
            "has_ollama_api_key": bool(key),
            "updated_at": updated_at,
        }


def load_app_config_from_disk() -> AppConfig:
    config = AppConfig()
    try:
        if APP_CONFIG_FILE.exists():
            data = json.loads(APP_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                config.ollama_api_key = str(data.get("ollama_api_key", "") or "").strip()
                config.updated_at = str(data.get("updated_at", "") or "").strip()
    except Exception as exc:
        log.warning("Αποτυχία φόρτωσης settings file %s: %s", APP_CONFIG_FILE, exc)
    return config


def save_app_config_to_disk(ollama_api_key: str) -> AppConfig:
    cleaned_key = str(ollama_api_key or "").strip()
    payload = {
        "ollama_api_key": cleaned_key,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    # Atomic write: γράφουμε σε temp αρχείο και μετά κάνουμε rename
    # ώστε να μην μείνει ποτέ μισογραμμένο αρχείο ρυθμίσεων.
    tmp_path = APP_CONFIG_FILE.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(APP_CONFIG_FILE)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    with APP_CONFIG.lock:
        APP_CONFIG.ollama_api_key = cleaned_key
        APP_CONFIG.updated_at = payload["updated_at"]
    return APP_CONFIG


REGISTRY = ModelRegistry()
SESSION  = ChatSession()
APP_CONFIG = load_app_config_from_disk()
_SERVER_START_TIME = time.time()  # για το /api/health uptime


@dataclass
class BrowserSessionMonitor:
    """Παρακολουθεί αν υπάρχει ενεργό browser tab/window της εφαρμογής."""

    active_sessions: Dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    ever_seen_session: bool = False
    shutdown_requested: bool = False
    server_ref: Optional[ThreadingHTTPServer] = None

    def attach_server(self, server: ThreadingHTTPServer) -> None:
        with self.lock:
            self.server_ref = server

    def touch(self, session_id: str) -> None:
        cleaned = str(session_id or '').strip()[:128]
        if not cleaned:
            return
        with self.lock:
            self.active_sessions[cleaned] = time.time()
            self.ever_seen_session = True

    def close(self, session_id: str) -> None:
        cleaned = str(session_id or '').strip()[:128]
        if not cleaned:
            return
        with self.lock:
            self.active_sessions.pop(cleaned, None)

    def _cleanup_stale_locked(self, now_ts: float) -> None:
        stale_before = now_ts - float(BROWSER_SESSION_HEARTBEAT_STALE_SECONDS)
        stale_ids = [sid for sid, ts in self.active_sessions.items() if ts < stale_before]
        for sid in stale_ids:
            self.active_sessions.pop(sid, None)

    def active_count(self) -> int:
        with self.lock:
            self._cleanup_stale_locked(time.time())
            return len(self.active_sessions)

    def should_shutdown(self) -> bool:
        now_ts = time.time()
        with self.lock:
            self._cleanup_stale_locked(now_ts)
            if self.shutdown_requested or not self.ever_seen_session:
                return False
            return not self.active_sessions

    def request_shutdown(self, reason: str = '') -> bool:
        with self.lock:
            if self.shutdown_requested:
                return False
            server = self.server_ref
            self.shutdown_requested = True
        if reason:
            log.info('🛑 Αυτόματος τερματισμός εφαρμογής: %s', reason)
        else:
            log.info('🛑 Αυτόματος τερματισμός εφαρμογής: έκλεισε το browser tab/window.')
        if server is None:
            return False

        def _worker() -> None:
            try:
                server.shutdown()
            except Exception as exc:
                log.warning('Αποτυχία αυτόματου shutdown του server: %s', exc)

        threading.Thread(target=_worker, daemon=True, name='browser-auto-shutdown').start()
        return True


BROWSER_MONITOR = BrowserSessionMonitor()


def start_browser_session_watchdog() -> None:
    def _worker() -> None:
        last_zero_ts: Optional[float] = None
        while True:
            time.sleep(BROWSER_SESSION_WATCHDOG_POLL_SECONDS)
            with BROWSER_MONITOR.lock:
                now_ts = time.time()
                BROWSER_MONITOR._cleanup_stale_locked(now_ts)
                shutdown_requested = BROWSER_MONITOR.shutdown_requested
                ever_seen = BROWSER_MONITOR.ever_seen_session
                active_count = len(BROWSER_MONITOR.active_sessions)
            if shutdown_requested:
                break
            if not ever_seen:
                last_zero_ts = None
                continue
            if active_count > 0:
                last_zero_ts = None
                continue
            if last_zero_ts is None:
                last_zero_ts = now_ts
                continue
            if (now_ts - last_zero_ts) >= float(BROWSER_SESSION_GRACE_SECONDS):
                if BROWSER_MONITOR.request_shutdown('δεν υπάρχει ανοιχτή σελίδα browser της εφαρμογής'):
                    break

    threading.Thread(target=_worker, daemon=True, name='browser-session-watchdog').start()


# ─────────────────────────── Startup broadcaster ─────────────────────────────

@dataclass
class StartupBroadcaster:
    """
    Thread-safe SSE broadcaster για το startup page.
    Κρατά όλα τα events (για late subscribers) και τα σπρώχνει
    σε κάθε ανοιχτή SSE σύνδεση.
    """
    _events:      List[Dict]  = field(default_factory=list)
    _subscribers: List        = field(default_factory=list)
    _lock:        threading.Lock = field(default_factory=threading.Lock)
    chat_url:     str  = ""
    is_ready:     bool = False

    def emit(self, level: str, msg: str) -> None:
        event = {"t": time.strftime("%H:%M:%S"), "level": level, "msg": msg}
        with self._lock:
            self._events.append(event)
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def set_ready(self, url: str) -> None:
        self.chat_url = url
        self.is_ready = True
        self.emit("READY", url)

    def subscribe(self) -> "_queue.Queue[Dict]":
        q: "_queue.Queue[Dict]" = _queue.Queue()
        with self._lock:
            for ev in self._events:
                q.put_nowait(ev)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "_queue.Queue[Dict]") -> None:
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass


STARTUP = StartupBroadcaster()


def slog(level: str, msg: str, *args: object) -> None:
    """Logs στο terminal ΚΑΙ στο startup broadcaster (για τον browser)."""
    formatted = msg % args if args else msg
    if level == "WARNING":
        log.warning(formatted)
    elif level == "ERROR":
        log.error(formatted)
    else:
        log.info(formatted)
    STARTUP.emit(level, formatted)


# ─────────────────────────── Utility helpers ─────────────────────────────────

def get_embedded_system_prompt() -> Tuple[str, str]:
    return DEFAULT_SYSTEM_PROMPT.strip(), "embedded-in-code"


def find_free_port(host: str, start_port: int = DEFAULT_PORT, end_port: int = 8899) -> int:
    """Βρίσκει ελεύθερη TCP θύρα στο δοθέν host."""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Δεν βρέθηκε ελεύθερη θύρα στο εύρος {start_port}–{end_port}.")


def get_saved_ollama_api_key() -> str:
    with APP_CONFIG.lock:
        return str(APP_CONFIG.ollama_api_key or "").strip()


def get_ollama_api_key_source() -> str:
    saved_value = get_saved_ollama_api_key()
    if saved_value:
        return "settings-file"
    env_value = str(os.environ.get("OLLAMA_API_KEY", "") or "").strip()
    if env_value:
        return "environment"
    embedded_value = str(EMBEDDED_OLLAMA_API_KEY or "").strip()
    if embedded_value:
        return "embedded"
    return "missing"


def get_ollama_api_key() -> str:
    saved_value = get_saved_ollama_api_key()
    if saved_value:
        return saved_value
    env_value = str(os.environ.get("OLLAMA_API_KEY", "") or "").strip()
    if env_value:
        return env_value
    return str(EMBEDDED_OLLAMA_API_KEY or "").strip()


def is_direct_cloud_api_configured() -> bool:
    return bool(get_ollama_api_key())


def build_request_headers(url: str, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    headers = dict(REQUEST_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    api_key = get_ollama_api_key()
    if api_key and str(url).startswith(OLLAMA_DIRECT_API_BASE_URL):
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


def fetch_url_text(url: str, timeout: int = 12) -> str:
    """Κατεβάζει κείμενο από URL με τα κοινά request headers."""
    req = urllib.request.Request(url, headers=build_request_headers(url))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, "status", 200) or 200)
        if status >= 400:
            raise RuntimeError(f"HTTP {status} από {url}")
        return resp.read().decode("utf-8", errors="ignore")


def fetch_url_json(url: str, timeout: int = 12) -> Dict:
    """Κατεβάζει και αποσυμπιέζει JSON από URL."""
    req = urllib.request.Request(url, headers=build_request_headers(url))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, "status", 200) or 200)
        if status >= 400:
            raise RuntimeError(f"HTTP {status} από {url}")
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def direct_cloud_chat_stream(
    model: str,
    messages: List[Dict],
    *,
    model_options: Optional[Dict] = None,
    think_value: Optional[object] = None,
    timeout: int = 900,
):
    """Κάνει direct streaming κλήση στο https://ollama.com/api/chat με OLLAMA_API_KEY."""
    api_key = get_ollama_api_key()
    if not api_key:
        raise RuntimeError(
            "Λείπει το Ollama Cloud API key. "
            "Βάλ'το στο πεδίο API Key του GUI, στο settings αρχείο της εφαρμογής ή ως OLLAMA_API_KEY."
        )

    payload: Dict[str, object] = {
        "model": str(model or "").strip(),
        "messages": messages,
        "stream": True,
    }
    if model_options:
        payload["options"] = dict(model_options)
    if think_value is not None:
        payload["think"] = think_value

    url = f"{OLLAMA_DIRECT_API_BASE_URL}/chat"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers=build_request_headers(url, {"Content-Type": "application/json; charset=utf-8"}),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            if status >= 400:
                raise RuntimeError(f"HTTP {status} από {url}")

            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and chunk.get("error"):
                    raise RuntimeError(str(chunk.get("error")))
                yield chunk

    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8", errors="ignore").strip()
        except Exception:
            pass
        detail = body_text
        try:
            parsed = json.loads(body_text) if body_text else {}
            if isinstance(parsed, dict) and parsed.get("error"):
                detail = str(parsed.get("error"))
        except Exception:
            pass
        raise RuntimeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Δικτυακό σφάλμα προς το Ollama Cloud API: {exc.reason}") from exc


def direct_cloud_chat_complete(
    model: str,
    messages: List[Dict],
    *,
    model_options: Optional[Dict] = None,
    think_value: Optional[object] = None,
    timeout: int = 900,
) -> Dict[str, object]:
    """Εκτελεί πλήρη κλήση chat και επιστρέφει συγκεντρωμένο content/thinking/stats."""
    collected: List[str] = []
    collected_thinking: List[str] = []
    token_stats: Optional[Dict] = None

    for chunk in direct_cloud_chat_stream(
        model=model,
        messages=messages,
        model_options=model_options,
        think_value=think_value,
        timeout=timeout,
    ):
        thinking_piece = extract_chunk_thinking(chunk)
        if thinking_piece:
            collected_thinking.append(thinking_piece)
        piece = extract_chunk_content(chunk)
        if piece:
            collected.append(piece)
        stats = extract_token_stats(chunk)
        if stats:
            token_stats = stats

    return {
        "content": "".join(collected).strip(),
        "thinking": "".join(collected_thinking).strip(),
        "token_stats": token_stats,
    }


_ENSEMBLE_ROLE_LABELS: Dict[str, str] = {
    "vision-analyst": "Vision helper",
    "code-specialist": "Coding helper",
    "code-reviewer": "Code reviewer",
    "reasoning-specialist": "Reasoning helper",
    "cross-checker": "Cross-checker",
    "long-context-reader": "Long-context helper",
}

_ENSEMBLE_HELPER_MAX_SIZE_B_BY_ROLE: Dict[str, float] = {
    "vision-analyst": 260.0,
    "code-specialist": 90.0,
    "code-reviewer": 120.0,
    "reasoning-specialist": 120.0,
    "cross-checker": 90.0,
    "long-context-reader": 260.0,
}

_ENSEMBLE_HELPER_MAX_TOKENS_BY_ROLE: Dict[str, int] = {
    "vision-analyst": 180,
    "code-specialist": 180,
    "code-reviewer": 160,
    "reasoning-specialist": 160,
    "cross-checker": 140,
    "long-context-reader": 180,
}

_ENSEMBLE_HELPER_TIMEOUT_BY_ROLE: Dict[str, int] = {
    "vision-analyst": 120,
    "code-specialist": 90,
    "code-reviewer": 90,
    "reasoning-specialist": 90,
    "cross-checker": 75,
    "long-context-reader": 120,
}


def detect_task_traits(user_text: str, attachments: Optional[List[Dict]] = None) -> Dict[str, bool]:
    text = str(user_text or "")
    lower = text.lower()
    attachments = attachments or []
    has_image = any(str(item.get("kind") or "").lower() == "image" for item in attachments)
    has_document = any(str(item.get("kind") or "").lower() == "document" for item in attachments)

    code_patterns = (
        "```", "traceback", "syntaxerror", "exception", "stack trace",
        "python", "javascript", "java", "c++", "c#", "regex", "sql",
        "function", "class ", "def ", "import ", "bug", "fix", "error",
        "κώδικ", "σφάλμα", "debug", "διορθ", "compile", "py",
    )
    reasoning_patterns = (
        "reason", "thinking", "analysis", "analyze", "why", "proof",
        "derive", "math", "equation", "logic", "βήμα", "σκέψ", "λογικ",
        "απόδει", "λύσ", "εξήγη", "ανάλυσ",
    )
    direct_visual_phrases = (
        "look at this image", "look at the attached image", "look at the screenshot",
        "describe this image", "describe the attached image", "describe the screenshot",
        "analyze this image", "analyze the attached image", "analyze the screenshot",
        "what is in this image", "what's in this image", "read the text in this image",
        "from the screenshot", "in the screenshot", "ocr this image", "ocr the image",
        "δες την εικόνα", "κοίτα την εικόνα", "κοίτα τη συνημμένη εικόνα",
        "περιέγραψε την εικόνα", "ανάλυσε την εικόνα", "διάβασε το κείμενο στην εικόνα",
        "τι δείχνει η εικόνα", "τι υπάρχει στην εικόνα", "στο screenshot", "στο στιγμιότυπο",
    )
    weak_vision_patterns = (
        "figure", "diagram", "chart", "graph", "plot", "table",
        "figure ", "diagram ", "chart ", "graph ",
        "διάγρα", "γράφη", "πίνακ", "σχήμα",
    )

    is_code = any(token in lower for token in code_patterns)
    is_reasoning = any(token in lower for token in reasoning_patterns)
    direct_visual_hits = sum(1 for token in direct_visual_phrases if token in lower)
    weak_vision_hits = sum(1 for token in weak_vision_patterns if token in lower)

    # Κρίσιμο fix:
    # Το ensemble δεν πρέπει να θεωρεί το task "vision" από την απλή λέξη
    # "image" ή "ocr" μέσα σε text-only prompt. Vision helper χρειάζεται
    # μόνο όταν υπάρχει πραγματική συνημμένη εικόνα προς ανάλυση.
    explicit_visual_request = has_image
    text_mentions_visual = direct_visual_hits >= 1 or weak_vision_hits >= 1
    weak_visual_hint = text_mentions_visual and not explicit_visual_request

    is_vision = has_image
    is_long_context = len(text) >= 3500 or has_document

    return {
        "code": is_code,
        "reasoning": is_reasoning or is_long_context,
        "vision": is_vision,
        "vision_explicit": explicit_visual_request,
        "vision_hint_only": weak_visual_hint,
        "long_context": is_long_context,
        "has_document": has_document,
        "has_image": has_image,
        "strong_vision_hits": direct_visual_hits,
        "weak_vision_hits": weak_vision_hits,
    }


def _ensemble_preferred_prefixes(primary_model: str, criterion: str, traits: Dict[str, bool]) -> List[str]:
    key = canonical_model_key(primary_model)
    prefixes: List[str] = []

    if criterion == "vision":
        prefixes.extend(["qwen3-vl", "qwen3.5", "gemini-3", "glm-5", "gemma3"])
    elif criterion == "coding":
        prefixes.extend(["qwen3-coder", "qwen3-coder-next", "devstral-2", "devstral", "deepseek-v3.2", "qwen3.5", "nemotron-3-nano"])
    elif criterion == "reasoning":
        prefixes.extend(["qwen3.5", "deepseek-v3.2", "deepseek-r1", "kimi-k2.5", "glm-5", "gemini-3", "nemotron-3-nano"])
    elif criterion == "context":
        prefixes.extend(["qwen3.5", "gemini-3", "kimi-k2.5", "glm-5", "minimax-m2.7", "nemotron-3-nano"])
    else:
        prefixes.extend(["qwen3.5", "deepseek-v3.2", "glm-5", "gemini-3", "nemotron-3-nano"])

    if model_matches_prefix(key, "nemotron-3-super"):
        if criterion == "vision":
            prefixes = ["qwen3-vl", "qwen3.5", "gemini-3", *prefixes]
        elif criterion == "coding":
            prefixes = ["qwen3-coder", "nemotron-3-nano", "qwen3.5", *prefixes]
        else:
            prefixes = ["nemotron-3-nano", "qwen3.5", "glm-5", *prefixes]
    elif model_matches_prefix(key, "nemotron-3-nano"):
        if criterion == "vision":
            prefixes = ["qwen3-vl", "qwen3.5", "gemini-3", *prefixes]
        else:
            prefixes = ["nemotron-3-super", "qwen3.5", "glm-5", *prefixes]
    elif model_matches_prefix(key, "qwen3-coder"):
        prefixes = ["qwen3.5", "deepseek-v3.2", "glm-5", *prefixes]
    elif model_matches_prefix(key, "qwen3-vl"):
        prefixes = ["qwen3.5", "deepseek-v3.2", "glm-5", *prefixes]
    elif model_matches_prefix(key, "qwen3.5") and traits.get("code"):
        prefixes = ["qwen3-coder", "devstral-2", *prefixes]
    elif model_matches_prefix(key, "qwen3.5") and traits.get("vision"):
        prefixes = ["qwen3-vl", "gemini-3", *prefixes]
    elif model_matches_prefix(key, "deepseek"):
        prefixes = ["qwen3.5", "qwen3-vl", "gemini-3", *prefixes]
    elif model_matches_prefix(key, "gemini-3") and traits.get("code"):
        prefixes = ["qwen3-coder", "deepseek-v3.2", *prefixes]

    deduped: List[str] = []
    seen: Set[str] = set()
    for item in prefixes:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _ensemble_prefix_bonus(candidate_model: str, preferred_prefixes: List[str]) -> float:
    for idx, prefix in enumerate(preferred_prefixes):
        if model_matches_prefix(candidate_model, prefix):
            return max(0.0, 1.25 - idx * 0.12)
    return 0.0


def _ensemble_pair_bonus(
    primary_model: str,
    candidate_model: str,
    criterion: str,
    traits: Dict[str, bool],
    candidate_caps: Set[str],
) -> float:
    primary_key = canonical_model_key(primary_model)
    candidate_key = canonical_model_key(candidate_model)
    bonus = 0.0

    if model_matches_prefix(primary_key, "nemotron-3-super"):
        if criterion == "vision":
            if model_matches_prefix(candidate_key, "qwen3-vl") or "vision" in candidate_caps:
                bonus += 0.95
            if model_matches_prefix(candidate_key, "nemotron-3-nano"):
                bonus -= 0.35
        elif criterion == "coding":
            if model_matches_prefix(candidate_key, "qwen3-coder"):
                bonus += 0.92
            elif model_matches_prefix(candidate_key, "nemotron-3-nano"):
                bonus += 0.42
        elif criterion in ("reasoning", "context", "overall"):
            if model_matches_prefix(candidate_key, "nemotron-3-nano"):
                bonus += 1.05
            elif "reasoning" in candidate_caps:
                bonus += 0.16
    elif model_matches_prefix(primary_key, "nemotron-3-nano"):
        if criterion == "vision":
            if model_matches_prefix(candidate_key, "qwen3-vl") or "vision" in candidate_caps:
                bonus += 0.82
        elif criterion in ("reasoning", "context", "overall") and model_matches_prefix(candidate_key, "nemotron-3-super"):
            bonus += 0.55

    if not traits.get("has_image") and criterion != "vision" and model_matches_prefix(candidate_key, "qwen3-vl"):
        bonus -= 0.45
    if traits.get("has_image") and "vision" in candidate_caps:
        bonus += 0.22
    return bonus


def choose_auto_ensemble_helper(
    primary_model: str,
    user_text: str,
    attachments: Optional[List[Dict]] = None,
) -> Optional[Dict[str, object]]:
    attachments = attachments or []
    traits = detect_task_traits(user_text, attachments)

    with REGISTRY.lock:
        models = list(REGISTRY.models)
        model_meta = copy.deepcopy(REGISTRY.model_meta)

    if len(models) < 2:
        return None

    primary_meta = model_meta.get(primary_model, {})
    primary_caps = get_model_capabilities(primary_model, primary_meta)
    primary_coding = score_model(primary_model, primary_meta, "coding")
    primary_reasoning = score_model(primary_model, primary_meta, "reasoning")
    primary_ctx = get_model_context_tokens(primary_model, primary_meta)

    # Ειδικός κανόνας: για nemotron-3-super χωρίς πραγματικό visual input,
    # προτίμησε text helper και όχι vision helper.
    primary_key = canonical_model_key(primary_model)

    explicit_vision = bool(traits.get("vision_explicit") or traits.get("has_image"))
    hint_only_vision = bool(traits.get("vision_hint_only"))

    if explicit_vision and "vision" not in primary_caps:
        criterion = "vision"
        role = "vision-analyst"
    elif traits.get("code"):
        if "coding" not in primary_caps or primary_coding < 9.45:
            criterion = "coding"
            role = "code-specialist"
        else:
            criterion = "reasoning"
            role = "code-reviewer"
    elif traits.get("long_context") and primary_ctx < 128_000:
        criterion = "context"
        role = "long-context-reader"
    elif traits.get("reasoning"):
        if "reasoning" not in primary_caps or primary_reasoning < 9.45:
            criterion = "reasoning"
            role = "reasoning-specialist"
        else:
            criterion = "overall"
            role = "cross-checker"
    else:
        if "reasoning" not in primary_caps:
            criterion = "reasoning"
            role = "reasoning-specialist"
        elif "coding" not in primary_caps:
            criterion = "coding"
            role = "code-specialist"
        else:
            criterion = "overall"
            role = "cross-checker"

    if model_matches_prefix(primary_key, "nemotron-3-super") and not explicit_vision and criterion == "vision":
        criterion = "reasoning"
        role = "reasoning-specialist"

    # Μόνο αδύναμο visual hint (π.χ. "diagram", "chart", "table") δεν αρκεί
    # για να παρακαμφθεί ο text helper στο nemotron-3-super.
    if model_matches_prefix(primary_key, "nemotron-3-super") and hint_only_vision and criterion == "overall":
        criterion = "reasoning"
        role = "reasoning-specialist"

    preferred_prefixes = _ensemble_preferred_prefixes(primary_model, criterion, traits)
    primary_family = primary_key.split(":", 1)[0]
    helper_size_limit_b = float(_ENSEMBLE_HELPER_MAX_SIZE_B_BY_ROLE.get(role, 120.0) or 120.0)

    best: Optional[Tuple[float, str, Dict[str, object]]] = None
    for candidate in models:
        if not candidate or candidate == primary_model:
            continue
        candidate_key = canonical_model_key(candidate)
        if not candidate_key or candidate_key == primary_key:
            continue

        meta = model_meta.get(candidate, {})
        caps = get_model_capabilities(candidate, meta)
        if criterion == "vision" and "vision" not in caps:
            continue
        if criterion == "coding" and ("coding" not in caps and score_model(candidate, meta, "coding") < 8.8):
            continue
        if criterion == "reasoning" and ("reasoning" not in caps and score_model(candidate, meta, "reasoning") < 8.8):
            continue
        if criterion == "context" and get_model_context_tokens(candidate, meta) < 64_000:
            continue

        size_b = get_model_size_billions(candidate, meta)
        speed = _size_speed_strength(size_b)
        if size_b > 0 and helper_size_limit_b > 0 and size_b > helper_size_limit_b * 2.4:
            continue

        fresh = _freshness_strength(get_model_modified_ts(candidate, meta))
        score = (
            score_model(candidate, meta, criterion) * 0.64
            + score_model(candidate, meta, "overall") * 0.18
            + speed * 0.16
            + fresh * 0.02
            + _ensemble_prefix_bonus(candidate, preferred_prefixes)
        )
        if criterion in caps:
            score += 0.35
        score += _ensemble_pair_bonus(primary_model, candidate, criterion, traits, caps)
        if candidate_key.split(":", 1)[0] == primary_family:
            if model_matches_prefix(primary_key, "nemotron-3-super") and model_matches_prefix(candidate_key, "nemotron-3-nano") and criterion != "vision":
                score += 0.18
            else:
                score -= 0.10
        if size_b > 0 and helper_size_limit_b > 0:
            if size_b <= helper_size_limit_b:
                score += 0.25
            else:
                score -= min(2.4, ((size_b - helper_size_limit_b) / max(25.0, helper_size_limit_b)) * 1.8)

        payload = {
            "helper_model": candidate,
            "criterion": criterion,
            "role": role,
            "role_label": _ENSEMBLE_ROLE_LABELS.get(role, role),
            "traits": traits,
            "preferred_prefixes": preferred_prefixes,
            "selection_reason": (
                "image-attachment" if traits.get("has_image") else
                "code-task" if criterion == "coding" else
                "long-context" if criterion == "context" else
                "reasoning" if criterion == "reasoning" else
                "cross-check"
            ),
        }
        if best is None or score > best[0]:
            best = (score, candidate, payload)

    return best[2] if best else None


def choose_manual_ensemble_helper(
    primary_model: str,
    helper_model: str,
    user_text: str,
    attachments: Optional[List[Dict]] = None,
) -> Optional[Dict[str, object]]:
    helper_model = normalize_model_name(helper_model)
    primary_model = normalize_model_name(primary_model)
    if not helper_model or not primary_model or helper_model == primary_model:
        return None

    attachments = attachments or []
    traits = detect_task_traits(user_text, attachments)
    with REGISTRY.lock:
        model_meta = copy.deepcopy(REGISTRY.model_meta)
        available_models = set(REGISTRY.models)

    if available_models and helper_model not in available_models:
        return None

    helper_meta = model_meta.get(helper_model, {})
    helper_caps = get_model_capabilities(helper_model, helper_meta)
    helper_context = get_model_context_tokens(helper_model, helper_meta)

    if traits.get("has_image") and "vision" in helper_caps:
        criterion = "vision"
        role = "vision-analyst"
    elif traits.get("code") and "coding" in helper_caps:
        criterion = "coding"
        role = "code-specialist"
    elif traits.get("long_context") and helper_context >= 64_000:
        criterion = "context"
        role = "long-context-reader"
    elif traits.get("reasoning") and ("reasoning" in helper_caps or score_model(helper_model, helper_meta, "reasoning") >= 8.8):
        criterion = "reasoning"
        role = "reasoning-specialist"
    elif "coding" in helper_caps:
        criterion = "coding"
        role = "code-reviewer"
    else:
        criterion = "overall"
        role = "cross-checker"

    return {
        "helper_model": helper_model,
        "criterion": criterion,
        "role": role,
        "role_label": _ENSEMBLE_ROLE_LABELS.get(role, role),
        "traits": traits,
        "preferred_prefixes": [canonical_model_key(helper_model).split(":", 1)[0]],
        "selection_reason": "manual-selection",
    }


def build_helper_system_prompt(primary_model: str, helper_model: str, helper_role: str, traits: Dict[str, bool]) -> str:
    role_label = _ENSEMBLE_ROLE_LABELS.get(helper_role, helper_role)
    task_flags = []
    for name in ("code", "reasoning", "vision", "long_context"):
        if traits.get(name):
            task_flags.append(name)
    flags_text = ", ".join(task_flags) if task_flags else "general"
    return (
        "Είσαι το δεύτερο, βοηθητικό μοντέλο ενός app-level ensemble δύο μοντέλων.\n"
        f"Κύριο μοντέλο: {primary_model}\n"
        f"Βοηθητικό μοντέλο: {helper_model}\n"
        f"Ρόλος σου: {role_label}\n"
        f"Task hints: {flags_text}\n\n"
        "ΔΕΝ απαντάς στον χρήστη. Παράγεις μόνο σύντομη ιδιωτική καθοδήγηση για το κύριο μοντέλο.\n"
        "Να είσαι πρακτικός, ακριβής και πολύ σύντομος (έως 8 bullets συνολικά). Μην βάλεις χαιρετισμούς.\n"
        "Απάντησε ακριβώς με τις ενότητες:\n"
        "SUMMARY:\nKEY_POINTS:\nRISKS:\nPLAN:\n"
        "Αν υπάρχει κώδικας, πρόσθεσε και BUGS_OR_PATCH:. Αν υπάρχουν εικόνες, πρόσθεσε VISUAL_FINDINGS:."
    )


def build_main_ensemble_guidance(helper_model: str, helper_role: str, helper_text: str) -> str:
    trimmed = str(helper_text or "").strip()
    if len(trimmed) > 7000:
        trimmed = trimmed[:7000].rstrip() + "\n...[trimmed]"
    role_label = _ENSEMBLE_ROLE_LABELS.get(helper_role, helper_role)
    return (
        "Ιδιωτική καθοδήγηση από δεύτερο βοηθητικό μοντέλο για εσωτερική χρήση.\n"
        f"Helper model: {helper_model}\n"
        f"Role: {role_label}\n"
        "Χρησιμοποίησέ την μόνο αν βοηθά και ΜΗΝ αναφέρεις ότι χρησιμοποιήθηκε δεύτερο μοντέλο.\n"
        "Αν κάποιο σημείο συγκρούεται με το πραγματικό input ή το ιστορικό συνομιλίας, αγνόησέ το.\n\n"
        "PRIVATE_GUIDANCE:\n"
        f"{trimmed}"
    )


def insert_secondary_system_message(messages: List[Dict], content: str) -> List[Dict]:
    content = str(content or "").strip()
    if not content:
        return list(messages)
    extra = {"role": "system", "content": content}
    if messages and str(messages[0].get("role") or "") == "system":
        return [messages[0], extra, *messages[1:]]
    return [extra, *messages]



# ─────────────────────────── Model fetching ──────────────────────────────────


def _is_valid_cloud_tag(tag: str) -> bool:
    """Ελέγχει αν ένα model/tag name είναι έγκυρο official cloud model."""
    tag = (tag or "").strip()
    if not tag or tag.startswith("http"):
        return False

    tag = tag.split("?", 1)[0].split("#", 1)[0].strip()
    if not tag:
        return False

    # Επιτρέπουμε τόσο bare names (π.χ. glm-5, kimi-k2.5)
    # όσο και explicit cloud tags (π.χ. gpt-oss:120b-cloud, qwen3.5:cloud).
    if not re.fullmatch(r"[a-zA-Z0-9._/-]+(?::[a-zA-Z0-9._-]+)?", tag):
        return False

    name_part = tag.split(":", 1)[0].split("/")[-1].strip()
    if not name_part or len(name_part) < 2 or re.fullmatch(r"\d+", name_part):
        return False

    return True


def _clean_cloud_tag(raw: str) -> str:
    """Καθαρίζει raw model/tag strings από JSON ή HTML."""
    raw = (raw or "").strip()
    if not raw:
        return ""

    raw = raw.split("?", 1)[0].split("#", 1)[0].strip()
    if not raw:
        return ""

    if ":" in raw:
        name_part, tag_part = raw.split(":", 1)
        name_part = name_part.split("/")[-1].strip()
        tag_part = tag_part.strip()
        cleaned = f"{name_part}:{tag_part}" if name_part and tag_part else ""
    else:
        cleaned = raw.split("/")[-1].strip()

    if not cleaned or not _is_valid_cloud_tag(cleaned):
        return ""
    return cleaned


def extract_library_families(search_html: str) -> List[str]:
    families: Set[str] = set()
    for m in LIBRARY_LINK_RE.finditer(search_html):
        slug = m.group(1).strip().rstrip("/")
        family = slug.split("/")[-1]
        if family and len(family) > 1 and not family.startswith("http"):
            families.add(family)
    if not families:
        for m in SEARCH_TEXT_FAMILY_RE.finditer(search_html):
            slug = m.group(1).strip()
            if slug and not slug.startswith("http"):
                families.add(slug.split("/")[-1])
    return sorted(families)


def extract_families_from_api_tags(api_payload: Dict) -> List[str]:
    families: Set[str] = set()
    items = (api_payload.get("models") or api_payload.get("tags")
             or api_payload.get("results") or [])
    for item in items:
        if isinstance(item, dict):
            raw = str(item.get("name") or item.get("model") or item.get("id") or "").strip()
        elif isinstance(item, str):
            raw = item.strip()
        else:
            continue
        family = raw.split(":")[0].split("/")[-1].strip()
        if family and len(family) > 1:
            families.add(family)
    return sorted(families)


def extract_cloud_tags_from_html(html_text: str) -> List[str]:
    raw = {m.group(1).strip() for m in CLOUD_TAG_RE.finditer(html_text)}
    cleaned = {_clean_cloud_tag(t) for t in raw}
    return sorted(t for t in cleaned if _is_valid_cloud_tag(t))


def normalize_html_text(html_text: str) -> str:
    compact = html.unescape(re.sub(r"<[^>]+>", " ", html_text or ""))
    compact = compact.replace("•", " ")
    compact = re.sub(r"\s+", " ", compact)
    return compact.strip()


def parse_context_window_tokens(raw_number: str, suffix: str = "") -> Optional[int]:
    token_text = (raw_number or "").strip().replace(",", "")
    if not token_text:
        return None
    try:
        value = float(token_text)
    except ValueError:
        return None
    mult = 1
    suffix = (suffix or "").upper().strip()
    if suffix == "K":
        mult = 1024
    elif suffix == "M":
        mult = 1024 * 1024
    elif suffix == "B":
        mult = 1024 * 1024 * 1024
    tokens = int(value * mult)
    return tokens if tokens >= 256 else None


def extract_cloud_metadata_from_html(html_text: str) -> Dict[str, Dict[str, object]]:
    compact = normalize_html_text(html_text)
    meta: Dict[str, Dict[str, object]] = {}
    if not compact:
        return meta
    for match in CLOUD_TAG_RE.finditer(compact):
        tag = _clean_cloud_tag(match.group(1).strip())
        if not _is_valid_cloud_tag(tag):
            continue
        window = compact[match.end():match.end() + 260]
        ctx_match = CONTEXT_WINDOW_RE.search(window)
        entry = meta.setdefault(tag, {})
        if ctx_match:
            ctx_tokens = parse_context_window_tokens(ctx_match.group(1), ctx_match.group(2) or "")
            if ctx_tokens:
                entry["num_ctx_max"] = ctx_tokens
                entry["num_ctx_label"] = ctx_match.group(0).replace("context window", "").strip()
    return meta


def parse_parameter_size_to_billions(raw_value: object) -> float:
    text = str(raw_value or "").strip().lower()
    if not text:
        return 0.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*([tbm])?", text)
    if not match:
        return 0.0
    value = float(match.group(1))
    suffix = (match.group(2) or "b").lower()
    if suffix == "t":
        return value * 1000.0
    if suffix == "m":
        return value / 1000.0
    return value


def parse_iso_datetime_to_timestamp(raw_value: object) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def infer_model_capabilities_from_name(model_name: str) -> List[str]:
    name = canonical_model_key(model_name)
    capabilities: Set[str] = {"completion"}

    token_rules = {
        "vision": (
            "vision", "-vl", ":vl", "gemini", "llava", "pixtral", "multimodal", "omni",
        ),
        "coding": (
            "coder", "code", "devstral", "claude-code", "swe", "terminal",
        ),
        "reasoning": (
            "thinking", "reason", "reasoning", "r1", "gpt-oss", "deepseek", "cogito",
            "kimi-k2", "glm-5", "glm-4.7", "glm-4.6",
        ),
    }
    for capability, tokens in token_rules.items():
        if any(token in name for token in tokens):
            capabilities.add(capability)

    for prefix, hinted_caps in _MODEL_TRAIT_HINTS:
        if model_matches_prefix(name, prefix):
            capabilities.update(hinted_caps)

    return sorted(capabilities)

def build_model_meta_from_show_payload(model: str, payload: object) -> Dict[str, object]:
    entry: Dict[str, object] = {}
    if not isinstance(payload, dict):
        return entry

    modified_at = str(payload.get("modified_at", "") or "").strip()
    if modified_at:
        entry["modified_at"] = modified_at
        entry["modified_ts"] = parse_iso_datetime_to_timestamp(modified_at)

    capabilities: Set[str] = set(infer_model_capabilities_from_name(model))
    raw_caps = payload.get("capabilities")
    if isinstance(raw_caps, list):
        for item in raw_caps:
            if isinstance(item, str) and item.strip():
                capabilities.add(item.strip().lower())
    if capabilities:
        entry["capabilities"] = sorted(capabilities)

    details = payload.get("details") if isinstance(payload.get("details"), dict) else {}
    if isinstance(details, dict):
        family = str(details.get("family", "") or "").strip()
        if family:
            entry["family"] = family
        param_size = str(details.get("parameter_size", "") or "").strip()
        if param_size:
            entry["parameter_size"] = param_size
            parsed_b = parse_parameter_size_to_billions(param_size)
            if parsed_b > 0:
                entry["parameter_size_b"] = parsed_b
        families = details.get("families")
        if isinstance(families, list):
            clean_families = [str(x).strip() for x in families if str(x).strip()]
            if clean_families:
                entry["families"] = clean_families

    model_info = payload.get("model_info") if isinstance(payload.get("model_info"), dict) else {}
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if not isinstance(key, str):
                continue
            lowered = key.lower()
            if lowered.endswith(".context_length") or lowered == "context_length":
                try:
                    ctx_tokens = int(value)
                except Exception:
                    ctx_tokens = 0
                if ctx_tokens > 0:
                    entry["num_ctx_max"] = ctx_tokens
                    entry["num_ctx_label"] = f"{ctx_tokens:,} tokens"
            elif lowered == "general.parameter_count":
                try:
                    entry["parameter_count"] = int(value)
                except Exception:
                    pass
            elif lowered.endswith(".mm.tokens_per_image"):
                capabilities.add("vision")

    if capabilities:
        entry["capabilities"] = sorted(capabilities)

    if "parameter_size_b" not in entry:
        parsed_from_name = parse_parameter_size_to_billions(model)
        if parsed_from_name > 0:
            entry["parameter_size_b"] = parsed_from_name

    entry["details_complete"] = True
    return entry


def fetch_direct_model_details(model: str, timeout: int = 15) -> Dict[str, object]:
    cleaned_model = normalize_model_name(model)
    if not cleaned_model:
        raise RuntimeError("Δεν δόθηκε όνομα μοντέλου για ανάκτηση metadata.")

    url = f"{OLLAMA_DIRECT_API_BASE_URL}/show"
    body = json.dumps({"model": cleaned_model}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers=build_request_headers(url, {"Content-Type": "application/json; charset=utf-8"}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, "status", 200) or 200)
        if status >= 400:
            raise RuntimeError(f"HTTP {status} από {url}")
        payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    return build_model_meta_from_show_payload(cleaned_model, payload)


def get_or_fetch_model_meta(model: str, force: bool = False) -> Dict[str, object]:
    cleaned_model = normalize_model_name(model)
    if not cleaned_model:
        return {}

    with REGISTRY.lock:
        existing = copy.deepcopy(REGISTRY.model_meta.get(cleaned_model, {}))
    if existing.get("details_complete") and not force:
        return existing

    try:
        fresh_meta = fetch_direct_model_details(cleaned_model)
    except Exception as exc:
        with REGISTRY.lock:
            entry = REGISTRY.model_meta.setdefault(cleaned_model, {})
            entry["details_error"] = str(exc)
            existing = copy.deepcopy(entry)
        return existing

    with REGISTRY.lock:
        merge_model_meta(REGISTRY.model_meta, {cleaned_model: fresh_meta})
        entry = REGISTRY.model_meta.setdefault(cleaned_model, {})
        entry["details_complete"] = True
        entry.pop("details_error", None)
        if fresh_meta.get("capabilities"):
            entry["capabilities"] = list(fresh_meta.get("capabilities", []))
        if fresh_meta.get("modified_at"):
            entry["modified_at"] = fresh_meta.get("modified_at")
        if fresh_meta.get("modified_ts"):
            entry["modified_ts"] = fresh_meta.get("modified_ts")
        if fresh_meta.get("parameter_size_b"):
            entry["parameter_size_b"] = fresh_meta.get("parameter_size_b")
        if fresh_meta.get("parameter_count"):
            entry["parameter_count"] = fresh_meta.get("parameter_count")
        return copy.deepcopy(entry)


def merge_model_meta(dest: Dict[str, Dict[str, object]], src: Dict[str, Dict[str, object]]) -> None:
    for tag, info in (src or {}).items():
        if not _is_valid_cloud_tag(tag):
            continue
        entry = dest.setdefault(tag, {})
        if not isinstance(info, dict):
            continue
        for key, value in info.items():
            if value in (None, "", 0):
                continue
            if key == "num_ctx_max":
                current = int(entry.get("num_ctx_max") or 0)
                incoming = int(value or 0)
                if incoming > current:
                    entry[key] = incoming
            else:
                entry.setdefault(key, value)


def fetch_cloud_models_for_family(
    family: str,
    timeout: int = 8,
    family_candidates: Optional[Set[str]] = None,
) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """Ανακτά verified official cloud model names και metadata για ένα family."""
    tags: Set[str] = set(
        t for t in (family_candidates or set())
        if ":" in str(t) and "cloud" in str(t).lower() and _is_valid_cloud_tag(str(t))
    )
    model_meta: Dict[str, Dict[str, object]] = {}
    family_candidates = set(family_candidates or set())

    saw_cloud_signal = False

    for url in (
        f"{OLLAMA_LIBRARY_BASE}{family}/tags",
        f"{OLLAMA_LIBRARY_BASE}{family}",
    ):
        try:
            raw_html = fetch_url_text(url, timeout=timeout)
        except Exception:
            continue

        compact = normalize_html_text(raw_html)
        if CLOUD_WORD_RE.search(compact):
            saw_cloud_signal = True

        explicit_cloud = set(extract_cloud_tags_from_html(raw_html))
        verified_family_models = set(extract_verified_cloud_models_for_family_from_html(raw_html, family))
        tags.update(explicit_cloud)
        tags.update(verified_family_models)
        merge_model_meta(model_meta, extract_cloud_metadata_from_html(raw_html))

        if family_candidates or verified_family_models:
            merge_model_meta(
                model_meta,
                extract_context_for_candidate_models_from_html(
                    raw_html,
                    set(family_candidates) | set(verified_family_models) | set(explicit_cloud),
                ),
            )

    # Αν πρόκειται για cloud family με μόνο bare alias, κράτησέ το μόνον όταν δεν βρέθηκε explicit tag.
    if saw_cloud_signal and not any(tag.startswith(family + ":") for tag in tags):
        tags.add(family)

    # Αν βρέθηκαν explicit tags, αφαίρεσε το bare family alias για να μείνουν μόνο τα καθαρά cloud tags.
    if any(tag.startswith(family + ":") for tag in tags):
        tags.discard(family)

    for tag in list(tags):
        if _is_valid_cloud_tag(tag):
            model_meta.setdefault(tag, {})["family"] = family

    return sorted(t for t in tags if _is_valid_cloud_tag(t)), model_meta


def _extract_candidate_names_from_json(payload: object) -> List[str]:
    """Αναδρομική εξαγωγή official model strings από JSON payload."""
    found: Set[str] = set()

    def _walk(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {"name", "model", "id", "slug"} and isinstance(value, str):
                    cleaned = _clean_cloud_tag(value)
                    if cleaned:
                        found.add(cleaned)
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)
    return sorted(found)


def extract_context_for_candidate_models_from_html(
    html_text: str,
    candidates: Set[str],
) -> Dict[str, Dict[str, object]]:
    """
    Εξάγει context metadata για γνωστά candidate models από family/search HTML,
    ακόμη κι όταν το model δεν έχει suffix :cloud / -cloud.
    """
    compact = normalize_html_text(html_text)
    meta: Dict[str, Dict[str, object]] = {}
    if not compact or not candidates:
        return meta

    for candidate in sorted(candidates, key=len, reverse=True):
        if not _is_valid_cloud_tag(candidate):
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9._/-]){re.escape(candidate)}(?![A-Za-z0-9._/-])")
        match = pattern.search(compact)
        if not match:
            continue
        window = compact[match.end():match.end() + 260]
        ctx_match = CONTEXT_WINDOW_RE.search(window)
        if not ctx_match:
            continue
        ctx_tokens = parse_context_window_tokens(ctx_match.group(1), ctx_match.group(2) or "")
        if not ctx_tokens:
            continue
        entry = meta.setdefault(candidate, {})
        entry["num_ctx_max"] = ctx_tokens
        entry["num_ctx_label"] = ctx_match.group(0).replace("context window", "").strip()

    return meta


def fetch_direct_api_models(timeout: int = 8) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """Ανακτά τα ακριβή model names που υποστηρίζει το direct Ollama Cloud API.

    Για direct mode, πηγή αλήθειας είναι αποκλειστικά το https://ollama.com/api/tags.
    Τα search/library pages χρησιμοποιούνται μόνο για εμπλουτισμό metadata, όχι για νέα model names.
    """
    data = fetch_url_json(OFFICIAL_CLOUD_API_TAGS_URL, timeout=timeout)
    models = data.get("models", []) if isinstance(data, dict) else []

    exact_models: List[str] = []
    meta: Dict[str, Dict[str, object]] = {}

    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get("model") or item.get("name") or "").strip()
            cleaned = _clean_cloud_tag(raw_name)
            if not cleaned or not _is_valid_cloud_tag(cleaned):
                continue
            exact_models.append(cleaned)
            details = item.get("details") if isinstance(item.get("details"), dict) else {}
            entry = meta.setdefault(cleaned, {})
            entry.setdefault("family", cleaned.split(":", 1)[0])
            size_bytes = int(item.get("size") or 0) if str(item.get("size") or "").strip() else 0
            if size_bytes > 0:
                entry.setdefault("size_bytes", size_bytes)
            modified_at = str(item.get("modified_at") or "").strip()
            if modified_at:
                entry.setdefault("modified_at", modified_at)
                entry.setdefault("modified_ts", parse_iso_datetime_to_timestamp(modified_at))
            inferred_caps = infer_model_capabilities_from_name(cleaned)
            if inferred_caps:
                entry.setdefault("capabilities", inferred_caps)
            if isinstance(details, dict):
                if details.get("parameter_size"):
                    param_size_text = str(details.get("parameter_size"))
                    entry.setdefault("parameter_size", param_size_text)
                    parsed_b = parse_parameter_size_to_billions(param_size_text)
                    if parsed_b > 0:
                        entry.setdefault("parameter_size_b", parsed_b)
                if details.get("family"):
                    entry.setdefault("family", str(details.get("family")))
            if "parameter_size_b" not in entry:
                parsed_from_name = parse_parameter_size_to_billions(cleaned)
                if parsed_from_name > 0:
                    entry.setdefault("parameter_size_b", parsed_from_name)

    exact_models = sorted(set(exact_models))
    return exact_models, meta


def _try_json_apis(timeout: int = 6) -> Tuple[Set[str], Set[str]]:
    """Χρησιμοποιεί μόνο cloud-specific search APIs ως seed, όχι το γενικό /api/tags."""
    tags: Set[str] = set()
    families: Set[str] = set()

    try:
        data = fetch_url_json(f"{OLLAMA_SEARCH_API_URL}?c=cloud&limit=500", timeout=timeout)
    except Exception:
        return tags, families

    for raw in _extract_candidate_names_from_json(data):
        cleaned = _clean_cloud_tag(raw)
        if not cleaned or not _is_valid_cloud_tag(cleaned):
            continue
        family = cleaned.split(":", 1)[0]
        families.add(family)
        if ":" in cleaned and "cloud" in cleaned.lower():
            tags.add(cleaned)

    families.update(extract_families_from_api_tags(data))
    return tags, families


def extract_verified_cloud_models_for_family_from_html(html_text: str, family: str) -> List[str]:
    """Εντοπίζει verified cloud models ενός family από το HTML του family page."""
    compact = normalize_html_text(html_text)
    if not compact or not family:
        return []

    family = family.strip()
    fam_re = re.escape(family)
    pattern = re.compile(
        rf"(?<![A-Za-z0-9._/-])({fam_re}(?::[A-Za-z0-9._-]+)?)(?![A-Za-z0-9._/-])",
        flags=re.IGNORECASE,
    )
    found: Set[str] = set()
    for match in pattern.finditer(compact):
        candidate = _clean_cloud_tag(match.group(1).strip())
        if not candidate or not _is_valid_cloud_tag(candidate):
            continue
        window = compact[max(0, match.start() - 160):match.end() + 220]
        if CLOUD_WORD_RE.search(window):
            found.add(candidate)

    # Αν βρέθηκαν explicit tags του family, αφαίρεσε το bare family name για να μη γλιστρήσει local/default alias.
    if any(item.startswith(family + ":") for item in found):
        found.discard(family)

    return sorted(found)


def fetch_official_cloud_catalog(timeout_per_request: int = 8) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """
    Ανακτά το πλήρες official catalog μοντέλων για direct Ollama Cloud API mode.

    Πηγή αλήθειας για direct mode: https://ollama.com/api/tags
    Τα search/library pages χρησιμοποιούνται μόνο για enrichment metadata
    (π.χ. context window), όχι για να προσθέσουν extra model names τύπου *-cloud.
    """
    import concurrent.futures

    direct_models, direct_meta = fetch_direct_api_models(timeout=max(6, timeout_per_request))
    if not direct_models:
        raise RuntimeError("Δεν βρέθηκαν official direct API models από το Ollama.")

    exact_model_set: Set[str] = set(direct_models)
    all_families: Set[str] = {m.split(":", 1)[0] for m in direct_models if m}
    all_meta: Dict[str, Dict[str, object]] = copy.deepcopy(direct_meta)

    # Search pages: μόνο enrichment για τα exact direct API models.
    for url in (OFFICIAL_SEARCH_URL, OFFICIAL_GENERAL_SEARCH_URL):
        try:
            raw_html = fetch_url_text(url, timeout=max(8, timeout_per_request + 1))
            all_families.update(extract_library_families(raw_html))
            merge_model_meta(all_meta, extract_context_for_candidate_models_from_html(raw_html, exact_model_set))
        except Exception:
            pass

    def _fetch_family_meta(fam: str) -> Dict[str, Dict[str, object]]:
        try:
            _tags, meta = fetch_cloud_models_for_family(
                fam,
                timeout=timeout_per_request,
                family_candidates={m for m in exact_model_set if m.split(":", 1)[0] == fam},
            )
            return meta
        except Exception:
            return {}

    max_workers = min(14, max(4, len(all_families) or 4))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for meta in executor.map(_fetch_family_meta, sorted(all_families)):
            if not isinstance(meta, dict):
                continue
            filtered_meta = {k: v for k, v in meta.items() if k in exact_model_set}
            merge_model_meta(all_meta, filtered_meta)

    final_meta: Dict[str, Dict[str, object]] = {}
    for model in direct_models:
        info = copy.deepcopy(all_meta.get(model, {}))
        info.setdefault("family", model.split(":", 1)[0])
        final_meta[model] = info

    result = sorted(direct_models)
    with_context = sum(1 for model in result if final_meta.get(model, {}).get("num_ctx_max"))
    log.info("☁️  Βρέθηκαν %d official Ollama direct API models (%d με context metadata)", len(result), with_context)
    return result, final_meta


# Νέο πολυκριτηριακό scoring engine για cloud μοντέλα.
# Η λογική είναι πλέον data-driven ανά criterion (Overall / Coding / Reasoning /
# Long Context / Vision / Speed / Newest) και όχι ένα απλό family bonus.

_SCORING_CRITERIA: Tuple[str, ...] = (
    "overall", "coding", "reasoning", "context", "vision", "speed", "newest",
)

_FAMILY_PRIOR_DEFAULTS: Dict[str, float] = {
    "overall":   7.50,
    "coding":    7.20,
    "reasoning": 7.35,
    "context":   7.05,
    "vision":    6.85,
    "speed":     7.10,
}

# Πιο specific prefixes ΠΡΩΤΑ.
_MODEL_FAMILY_PROFILES: List[Tuple[str, Dict[str, float]]] = [
    ("gemini-3-flash",      {"overall": 9.12, "coding": 8.62, "reasoning": 8.82, "context": 8.95, "vision": 9.35, "speed": 9.95}),
    ("deepseek-v3.2",       {"overall": 9.82, "coding": 9.62, "reasoning": 9.90, "context": 9.14, "vision": 6.20, "speed": 4.70}),
    ("deepseek-v3.1",       {"overall": 9.72, "coding": 9.54, "reasoning": 9.80, "context": 9.02, "vision": 6.00, "speed": 4.82}),
    ("deepseek-r1",         {"overall": 9.66, "coding": 9.10, "reasoning": 9.96, "context": 8.40, "vision": 5.25, "speed": 3.86}),
    ("qwen3.5",             {"overall": 9.96, "coding": 9.74, "reasoning": 9.92, "context": 9.52, "vision": 9.84, "speed": 4.42}),
    ("qwen3-coder-next",    {"overall": 9.56, "coding": 9.96, "reasoning": 9.42, "context": 9.00, "vision": 5.35, "speed": 5.06}),
    ("qwen3-coder",         {"overall": 9.68, "coding": 9.98, "reasoning": 9.60, "context": 9.08, "vision": 5.38, "speed": 4.25}),
    ("qwen3-vl",            {"overall": 9.58, "coding": 9.26, "reasoning": 9.42, "context": 9.02, "vision": 9.98, "speed": 4.52}),
    ("qwen3-next",          {"overall": 9.24, "coding": 9.10, "reasoning": 9.18, "context": 8.86, "vision": 7.92, "speed": 5.12}),
    ("kimi-k2-thinking",    {"overall": 9.62, "coding": 9.22, "reasoning": 9.90, "context": 9.12, "vision": 6.62, "speed": 3.72}),
    ("kimi-k2.5",           {"overall": 9.76, "coding": 9.40, "reasoning": 9.78, "context": 9.28, "vision": 7.12, "speed": 4.12}),
    ("kimi-k2",             {"overall": 9.58, "coding": 9.22, "reasoning": 9.62, "context": 9.00, "vision": 6.85, "speed": 4.25}),
    ("glm-5",               {"overall": 9.60, "coding": 9.36, "reasoning": 9.56, "context": 9.12, "vision": 8.72, "speed": 4.15}),
    ("glm-4.7",             {"overall": 9.46, "coding": 9.18, "reasoning": 9.44, "context": 8.92, "vision": 8.22, "speed": 4.02}),
    ("glm-4.6",             {"overall": 9.38, "coding": 9.12, "reasoning": 9.36, "context": 8.78, "vision": 8.05, "speed": 4.10}),
    ("minimax-m2.7",        {"overall": 9.42, "coding": 9.06, "reasoning": 9.40, "context": 8.96, "vision": 8.62, "speed": 4.42}),
    ("minimax-m2.5",        {"overall": 9.34, "coding": 8.98, "reasoning": 9.32, "context": 8.86, "vision": 8.46, "speed": 4.58}),
    ("minimax-m2.1",        {"overall": 9.22, "coding": 8.92, "reasoning": 9.20, "context": 8.72, "vision": 8.18, "speed": 4.72}),
    ("minimax-m2",          {"overall": 9.14, "coding": 8.88, "reasoning": 9.10, "context": 8.64, "vision": 8.00, "speed": 4.86}),
    ("nemotron-3-super",    {"overall": 9.32, "coding": 8.92, "reasoning": 9.28, "context": 8.96, "vision": 7.42, "speed": 4.82}),
    ("nemotron-3-nano",     {"overall": 8.76, "coding": 8.36, "reasoning": 8.68, "context": 8.12, "vision": 6.20, "speed": 7.20}),
    ("mistral-large-3",     {"overall": 9.22, "coding": 9.00, "reasoning": 9.18, "context": 8.82, "vision": 7.82, "speed": 4.32}),
    ("devstral-small-2",    {"overall": 8.98, "coding": 9.42, "reasoning": 8.70, "context": 8.52, "vision": 5.02, "speed": 6.62}),
    ("devstral-2",          {"overall": 9.18, "coding": 9.74, "reasoning": 8.96, "context": 8.86, "vision": 5.10, "speed": 5.22}),
    ("devstral",            {"overall": 8.98, "coding": 9.42, "reasoning": 8.72, "context": 8.52, "vision": 5.05, "speed": 6.20}),
    ("gpt-oss",             {"overall": 9.06, "coding": 8.92, "reasoning": 9.04, "context": 8.62, "vision": 5.10, "speed": 5.90}),
    ("cogito-2.1",          {"overall": 9.28, "coding": 9.08, "reasoning": 9.42, "context": 8.92, "vision": 6.22, "speed": 3.92}),
    ("cogito",              {"overall": 9.12, "coding": 8.96, "reasoning": 9.26, "context": 8.76, "vision": 6.02, "speed": 4.20}),
    ("gemini-3",            {"overall": 9.74, "coding": 9.42, "reasoning": 9.72, "context": 9.46, "vision": 9.82, "speed": 5.12}),
    ("ministral-3",         {"overall": 8.74, "coding": 8.34, "reasoning": 8.48, "context": 8.22, "vision": 6.22, "speed": 8.24}),
    ("ministral",           {"overall": 8.62, "coding": 8.22, "reasoning": 8.36, "context": 8.06, "vision": 6.05, "speed": 8.00}),
    ("mistral-small",       {"overall": 8.54, "coding": 8.18, "reasoning": 8.24, "context": 7.96, "vision": 5.92, "speed": 8.20}),
    ("gemma3",              {"overall": 8.58, "coding": 8.22, "reasoning": 8.34, "context": 7.82, "vision": 8.12, "speed": 7.50}),
    ("rnj-1",               {"overall": 8.32, "coding": 7.96, "reasoning": 8.16, "context": 7.92, "vision": 5.42, "speed": 8.05}),
    ("rnj",                 {"overall": 8.24, "coding": 7.88, "reasoning": 8.08, "context": 7.84, "vision": 5.32, "speed": 8.10}),
]

_MODEL_TRAIT_HINTS: List[Tuple[str, Set[str]]] = [
    ("qwen3.5",          {"reasoning", "coding", "vision"}),
    ("qwen3-vl",         {"vision", "reasoning", "coding"}),
    ("qwen3-coder",      {"coding", "reasoning"}),
    ("qwen3-next",       {"reasoning", "coding", "vision"}),
    ("deepseek-v3.2",    {"reasoning", "coding"}),
    ("deepseek-v3.1",    {"reasoning", "coding"}),
    ("deepseek-r1",      {"reasoning"}),
    ("kimi-k2.5",        {"reasoning", "coding"}),
    ("kimi-k2",          {"reasoning", "coding"}),
    ("glm-5",            {"reasoning", "coding", "vision"}),
    ("glm-4",            {"reasoning", "coding", "vision"}),
    ("gemini-3",         {"reasoning", "coding", "vision"}),
    ("devstral",         {"coding"}),
    ("gpt-oss",          {"reasoning", "coding"}),
    ("nemotron-3-super", {"reasoning", "coding"}),
    ("nemotron-3-nano",  {"reasoning"}),
    ("mistral-large-3",  {"reasoning", "coding"}),
    ("cogito",           {"reasoning", "coding"}),
    ("ministral-3",      {"reasoning", "coding"}),
    ("gemma3",           {"reasoning", "coding", "vision"}),
]


def canonical_model_key(model_name: str) -> str:
    key = normalize_model_name(str(model_name or "")).strip().lower()
    if not key:
        return ""
    if ":" in key:
        family, tag = key.split(":", 1)
        if tag.endswith("-cloud"):
            tag = tag[:-6]
        key = f"{family}:{tag}"
    elif key.endswith("-cloud"):
        key = key[:-6]
    return key.strip(":")


def model_matches_prefix(model_name: str, prefix: str) -> bool:
    key = canonical_model_key(model_name)
    prefix = str(prefix or "").strip().lower()
    if not key or not prefix:
        return False
    return key.startswith(prefix) or prefix in key


def get_family_profile(model_name: str) -> Dict[str, float]:
    for prefix, profile in _MODEL_FAMILY_PROFILES:
        if model_matches_prefix(model_name, prefix):
            return profile
    return _FAMILY_PRIOR_DEFAULTS


def get_model_capabilities(model_name: str, meta: Optional[Dict[str, object]] = None) -> Set[str]:
    capabilities: Set[str] = set(infer_model_capabilities_from_name(model_name))
    if isinstance(meta, dict):
        raw_caps = meta.get("capabilities")
        if isinstance(raw_caps, list):
            for item in raw_caps:
                if isinstance(item, str) and item.strip():
                    capabilities.add(item.strip().lower())
        if isinstance(meta.get("families"), list):
            for item in meta.get("families", []):
                if isinstance(item, str):
                    capabilities.update(infer_model_capabilities_from_name(item))
        family = str(meta.get("family") or "").strip()
        if family:
            capabilities.update(infer_model_capabilities_from_name(family))
    capabilities.add("completion")
    return capabilities


def get_model_size_billions(model_name: str, meta: Optional[Dict[str, object]] = None) -> float:
    if isinstance(meta, dict):
        raw_b = meta.get("parameter_size_b")
        try:
            size_b = float(raw_b)
        except Exception:
            size_b = 0.0
        if size_b > 0:
            return max(0.0, min(size_b, 1000.0))
        try:
            size_bytes = float(meta.get("size_bytes") or 0)
        except Exception:
            size_bytes = 0.0
        if size_bytes > 0:
            return max(0.0, min(size_bytes / 1_000_000_000.0, 1000.0))
    parsed = parse_parameter_size_to_billions(canonical_model_key(model_name))
    return max(0.0, min(parsed, 1000.0)) if parsed > 0 else 0.0


def get_model_context_tokens(model_name: str, meta: Optional[Dict[str, object]] = None) -> int:
    if isinstance(meta, dict):
        try:
            ctx = int(meta.get("num_ctx_max") or 0)
        except Exception:
            ctx = 0
        if ctx > 0:
            return ctx
    return 0


def get_model_modified_ts(model_name: str, meta: Optional[Dict[str, object]] = None) -> float:
    if isinstance(meta, dict):
        try:
            raw_ts = float(meta.get("modified_ts") or 0)
        except Exception:
            raw_ts = 0.0
        if raw_ts > 0:
            return raw_ts
        raw_date = str(meta.get("modified_at") or "").strip()
        if raw_date:
            return parse_iso_datetime_to_timestamp(raw_date)
    return 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _size_quality_strength(size_b: float) -> float:
    import math
    if size_b <= 0:
        return 4.8
    normalized = math.log2(min(size_b, 1000.0) + 1.0) / math.log2(1001.0)
    return 3.8 + normalized * 6.2


def _size_speed_strength(size_b: float) -> float:
    import math
    if size_b <= 0:
        return 7.8
    normalized = math.log2(min(size_b, 1000.0) + 1.0) / math.log2(1001.0)
    return 9.8 - normalized * 7.2


def _context_strength(ctx_tokens: int) -> float:
    import math
    if ctx_tokens <= 0:
        return 3.2
    normalized = _clamp(math.log2(float(ctx_tokens)) / 18.0, 0.0, 1.08)
    bonus = 0.7 if ctx_tokens >= 200_000 else (0.35 if ctx_tokens >= 128_000 else 0.0)
    return min(10.0, 3.6 + normalized * 6.0 + bonus)


def _freshness_strength(modified_ts: float) -> float:
    if modified_ts <= 0:
        return 4.8
    age_days = max(0.0, (time.time() - modified_ts) / 86400.0)
    if age_days <= 21:
        return 10.0
    if age_days <= 45:
        return 9.4
    if age_days <= 90:
        return 8.6
    if age_days <= 180:
        return 7.6
    if age_days <= 365:
        return 6.3
    if age_days <= 540:
        return 5.2
    return 4.3


def _name_signal_bonus(model_name: str, criterion: str) -> float:
    name = canonical_model_key(model_name)
    bonus = 0.0
    if criterion == "coding":
        if any(token in name for token in ("coder", "devstral", "terminal", "swe")):
            bonus += 0.90
        if any(token in name for token in ("code", "oss")):
            bonus += 0.25
    elif criterion == "reasoning":
        if any(token in name for token in ("thinking", "reason", "reasoning", "r1")):
            bonus += 0.95
        if any(token in name for token in ("deepseek", "cogito")):
            bonus += 0.20
    elif criterion == "vision":
        if any(token in name for token in ("-vl", ":vl", "vision", "gemini", "pixtral", "llava")):
            bonus += 0.95
    elif criterion == "speed":
        if any(token in name for token in ("flash", "nano", "mini", "small")):
            bonus += 1.15
        if any(token in name for token in ("preview",)):
            bonus += 0.20
    elif criterion == "overall":
        if any(token in name for token in ("thinking", "coder", "-vl", ":vl", "vision")):
            bonus += 0.18
    return bonus


def score_model(model_name: str, meta: Optional[Dict[str, object]] = None, criterion: str = "overall") -> float:
    """Βαθμολογεί cloud μοντέλο με πολυκριτηριακή λογική και rich metadata."""
    criterion = (criterion or "overall").strip().lower()
    if criterion not in _SCORING_CRITERIA:
        criterion = "overall"

    profile = get_family_profile(model_name)
    base_prior = float(profile.get(criterion, _FAMILY_PRIOR_DEFAULTS.get(criterion, 7.0)))
    size_b = get_model_size_billions(model_name, meta)
    ctx = get_model_context_tokens(model_name, meta)
    modified_ts = get_model_modified_ts(model_name, meta)
    caps = get_model_capabilities(model_name, meta)

    size_quality = _size_quality_strength(size_b)
    size_speed = _size_speed_strength(size_b)
    context_strength = _context_strength(ctx)
    freshness = _freshness_strength(modified_ts)

    has_reasoning = 10.0 if "reasoning" in caps else 0.0
    has_coding = 10.0 if "coding" in caps else 0.0
    has_vision = 10.0 if "vision" in caps else 0.0
    bonus = _name_signal_bonus(model_name, criterion)

    if criterion == "coding":
        return (
            base_prior * 0.56
            + size_quality * 0.10
            + context_strength * 0.10
            + freshness * 0.05
            + has_coding * 0.14
            + has_reasoning * 0.04
            + bonus
        )

    if criterion == "reasoning":
        return (
            base_prior * 0.56
            + size_quality * 0.11
            + context_strength * 0.06
            + freshness * 0.04
            + has_reasoning * 0.13
            + has_coding * 0.03
            + bonus
        )

    if criterion == "context":
        if ctx > 0:
            return (
                context_strength * 0.74
                + base_prior * 0.14
                + size_quality * 0.08
                + freshness * 0.04
            )
        return (
            base_prior * 0.22
            + size_quality * 0.12
            + freshness * 0.06
        )

    if criterion == "vision":
        return (
            base_prior * 0.58
            + size_quality * 0.09
            + context_strength * 0.06
            + freshness * 0.04
            + has_vision * 0.18
            + has_reasoning * 0.02
            + bonus
        )

    if criterion == "speed":
        return (
            base_prior * 0.15
            + size_speed * 0.60
            + freshness * 0.10
            + (context_strength * 0.05)
            + (0.20 if size_b and size_b <= 24.0 else 0.0)
            + bonus
        )

    if criterion == "newest":
        return modified_ts if modified_ts > 0 else 0.0

    return (
        base_prior * 0.56
        + size_quality * 0.12
        + context_strength * 0.06
        + freshness * 0.05
        + has_reasoning * 0.08
        + has_coding * 0.06
        + has_vision * 0.04
        + bonus
    )


def recommend_best_model(models: List[str], model_meta: Optional[Dict[str, Dict[str, object]]] = None, criterion: str = "overall") -> str:
    """Επιλέγει το βέλτιστο default μοντέλο από τη λίστα."""
    if not models:
        return ""
    scored = sorted(
        models,
        key=lambda model: score_model(model, (model_meta or {}).get(model, {}), criterion),
        reverse=True,
    )
    return scored[0]


def wait_for_model_refresh(timeout: float = 45.0, poll_interval: float = 0.15) -> bool:
    """Περιμένει να ολοκληρωθεί τυχόν ήδη τρέχον refresh μοντέλων."""
    deadline = time.time() + max(0.5, timeout)
    while time.time() < deadline:
        with REGISTRY.lock:
            in_progress = REGISTRY.refresh_in_progress
        if not in_progress:
            return True
        time.sleep(max(0.05, poll_interval))
    return False


def refresh_models(force: bool = False, wait_if_running: bool = True) -> None:
    """Ανανεώνει το REGISTRY από το επίσημο online cloud library. Thread-safe."""
    should_wait = False
    with REGISTRY.lock:
        if REGISTRY.refresh_in_progress:
            should_wait = True
        elif not force and REGISTRY.last_refresh_ts:
            if time.time() - REGISTRY.last_refresh_ts < MODEL_CACHE_SECONDS:
                return
        if not should_wait:
            REGISTRY.refresh_in_progress = True

    if should_wait:
        if wait_if_running:
            wait_for_model_refresh(timeout=60.0)
        return

    try:
        online_models, online_meta = fetch_official_cloud_catalog()
        with REGISTRY.lock:
            REGISTRY.models            = list(online_models)
            REGISTRY.model_meta        = copy.deepcopy(online_meta)
            REGISTRY.source            = "official-online"
            REGISTRY.last_error        = ""
            REGISTRY.last_refresh_ts   = time.time()
            REGISTRY.recommended_model = recommend_best_model(online_models, online_meta, "overall")
    except Exception as exc:
        with REGISTRY.lock:
            REGISTRY.source            = "stale-online-cache" if REGISTRY.models else "error"
            REGISTRY.last_error        = str(exc)
            REGISTRY.last_refresh_ts   = time.time()
            REGISTRY.recommended_model = recommend_best_model(REGISTRY.models, REGISTRY.model_meta, "overall")
    finally:
        with REGISTRY.lock:
            REGISTRY.refresh_in_progress = False


def refresh_models_in_background(force: bool = False) -> None:
    def _runner() -> None:
        with REGISTRY.lock:
            if REGISTRY.refresh_in_progress and not REGISTRY.last_refresh_ts:
                REGISTRY.refresh_in_progress = False
        refresh_models(force=force, wait_if_running=False)

    threading.Thread(target=_runner, daemon=True).start()


def validate_python_code_block(code_text: str) -> Tuple[bool, str]:
    """Γρήγορος syntax έλεγχος πριν ανοιχτεί νέο terminal."""
    try:
        ast.parse(code_text, filename="<python_block>")
        return True, ""
    except SyntaxError as exc:
        line_no = getattr(exc, "lineno", None) or 0
        offset = getattr(exc, "offset", None) or 0
        bad_line = ""
        lines = code_text.splitlines()
        if 1 <= line_no <= len(lines):
            bad_line = lines[line_no - 1]
        pointer = (" " * max(offset - 1, 0) + "^") if offset else ""
        details = [f"SyntaxError στη γραμμή {line_no}: {exc.msg}"]
        if bad_line:
            details.append(bad_line)
        if pointer:
            details.append(pointer)
        return False, "\n".join(details)
    except Exception as exc:
        return False, f"Αποτυχία ελέγχου Python block: {exc}"


def resolve_python_for_generated_scripts() -> Tuple[Optional[List[str]], str]:
    """
    Βρίσκει πραγματικό Python interpreter για το >Run.

    - Σε κανονική εκτέλεση .py χρησιμοποιεί το sys.executable.
    - Σε PyInstaller/frozen .exe ψάχνει system Python (py -3, python, python3).
    """
    if not getattr(sys, "frozen", False):
        exe = os.path.normpath(sys.executable or "python")
        return [exe], "sys.executable"

    candidates: List[Tuple[List[str], str]] = [
        (["py", "-3"], "Python Launcher (py -3)"),
        (["python"], "system python"),
        (["python3"], "system python3"),
    ]

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

    for command, label in candidates:
        try:
            test = subprocess.run(
                command + ["-c", "import sys; print(sys.executable)"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=creationflags,
            )
            if test.returncode == 0:
                return command, label
        except Exception:
            continue

    return None, "missing"


def launch_python_code_in_terminal(code_text: str, suggested_filename: str = "") -> Tuple[bool, str]:
    """Αποθηκεύει το Python block σε προσωρινό αρχείο και το τρέχει σε νέο terminal."""
    code_text = str(code_text or "")
    if not code_text.strip():
        return False, "Το Python block είναι κενό."
    if len(code_text) > 250_000:
        return False, "Το Python block είναι υπερβολικά μεγάλο για εκτέλεση."

    is_valid, validation_message = validate_python_code_block(code_text)
    if not is_valid:
        return False, validation_message

    exec_dir = os.path.join(tempfile.gettempdir(), "ollama_cloud_chat_exec")
    os.makedirs(exec_dir, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')

    requested_name = str(suggested_filename or "").strip() or suggest_python_filename(code_text)
    safe_name = sanitize_filename(requested_name)
    if not safe_name.lower().endswith('.py'):
        safe_name += '.py'

    script_name = f"{stamp}_{safe_name}"
    script_path = os.path.join(exec_dir, script_name)
    with open(script_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(code_text)

    python_cmd, python_source = resolve_python_for_generated_scripts()
    if not python_cmd:
        return False, (
            "Δεν βρέθηκε εγκατεστημένος Python interpreter για το >Run.\n"
            "Στο packaged .exe το sys.executable δείχνει το ίδιο το app και όχι python.exe.\n"
            "Εγκατάστησε Python ή χρησιμοποίησε πρώτα το 💾 Save και μετά τρέξε το .py χειροκίνητα."
        )

    launcher_stem = Path(safe_name).stem or "generated_block"

    try:
        if os.name == "nt":
            launcher_path = os.path.join(exec_dir, f"run_{launcher_stem}_{stamp}.bat")
            command_line = subprocess.list2cmdline(python_cmd + [script_path])
            launcher_lines = [
                "@echo off",
                "setlocal",
                "chcp 65001>nul",
                f"title Python Code Block Runner - {safe_name}",
                command_line,
                "echo.",
                "echo Exit code: %ERRORLEVEL%",
                "pause",
            ]
            with open(launcher_path, "w", encoding="utf-8", newline="\r\n") as f:
                f.write("\r\n".join(launcher_lines) + "\r\n")

            subprocess.Popen(
                ["cmd.exe", "/k", launcher_path],
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            return True, (
                f"Το Python block αποθηκεύτηκε ως {safe_name} στο {script_path} και εκτελείται σε νέο terminal "
                f"με interpreter από {python_source}. Launcher: {launcher_path}"
            )

        elif sys.platform == "darwin":
            shell_cmd = " ".join(shlex.quote(part) for part in (python_cmd + [script_path]))
            shell_cmd += "; echo; echo Press Enter to close...; read"
            apple_script = f'tell application "Terminal" to do script {json.dumps(shell_cmd)}'
            subprocess.Popen(["osascript", "-e", apple_script])
        else:
            shell_cmd = " ".join(shlex.quote(part) for part in (python_cmd + [script_path]))
            shell_cmd += "; printf '\n\nPress Enter to close...'; read _"
            launched = False
            terminal_commands = [
                ["x-terminal-emulator", "-e", "bash", "-lc", shell_cmd],
                ["gnome-terminal", "--", "bash", "-lc", shell_cmd],
                ["konsole", "-e", "bash", "-lc", shell_cmd],
                ["xfce4-terminal", "-e", f"bash -lc {shlex.quote(shell_cmd)}"],
            ]
            for cmd in terminal_commands:
                try:
                    subprocess.Popen(cmd)
                    launched = True
                    break
                except FileNotFoundError:
                    continue
            if not launched:
                subprocess.Popen(python_cmd + [script_path])
    except Exception as exc:
        return False, f"Αποτυχία ανοίγματος terminal: {exc}"

    return True, (
        f"Το Python block αποθηκεύτηκε ως {safe_name} στο {script_path} και εκτελείται σε νέο terminal "
        f"με interpreter από {python_source}."
    )

# ─────────────────────────── HTTP helpers ────────────────────────────────────

def _send_security_headers(handler: BaseHTTPRequestHandler) -> None:
    for key, value in SECURITY_HEADERS.items():
        handler.send_header(key, value)


def json_response(handler: BaseHTTPRequestHandler, payload: Dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(data)


def stream_json_line(handler: BaseHTTPRequestHandler, payload: Dict) -> None:
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        handler.wfile.write(data)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        raise BrokenPipeError("Client disconnected during stream")


def is_client_disconnect_error(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
        return True
    if isinstance(exc, OSError):
        winerror = getattr(exc, "winerror", None)
        errno_   = getattr(exc, "errno",    None)
        return winerror in {10053, 10054} or errno_ in {32, 54, 104, 107, 108}
    return False


def safe_read_json(handler: BaseHTTPRequestHandler) -> Dict:
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except (ValueError, TypeError):
        content_length = 0

    if content_length > MAX_REQUEST_BODY_BYTES:
        log.warning(
            "Απορρίφθηκε request %d bytes (όριο: %d)", content_length, MAX_REQUEST_BODY_BYTES
        )
        return {"__error__": "request_too_large"}

    if content_length <= 0:
        return {}

    try:
        body = handler.rfile.read(content_length)
    except (OSError, ConnectionError) as exc:
        log.warning("Αποτυχία ανάγνωσης request body: %s", exc)
        return {}

    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


# ─────────────────────────── Cloud runtime / server ──────────────────────────

class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """HTTP server που αγνοεί αθόρυβα τα αναμενόμενα disconnects."""

    daemon_threads      = True
    allow_reuse_address = True
    timeout             = 60  # seconds — αποφυγή κρεμαστών worker threads

    def handle_error(self, request, client_address) -> None:
        _, exc, _ = sys.exc_info()
        if exc is not None and is_client_disconnect_error(exc):
            return
        super().handle_error(request, client_address)


def is_ollama_connection_refused(exc: object) -> bool:
    text = str(exc or "").lower()
    needles = ("10061", "actively refused", "connection refused",
               "failed to establish a new connection", "max retries exceeded")
    return any(n in text for n in needles)


def build_friendly_chat_error(exc: object) -> str:
    text = str(exc or "")
    lower = text.lower()

    if "ollama_api_key" in lower or ("api key" in lower and ("missing" in lower or "required" in lower)):
        return (
            "Λείπει το Ollama Cloud API key για direct κλήσεις στο Ollama Cloud API. "
            "Βάλ'το στο πεδίο API Key του GUI ή αποθήκευσέ το στο settings αρχείο της εφαρμογής ή όρισέ το ως OLLAMA_API_KEY και ξανατρέξε την εφαρμογή."
        )

    if is_ollama_connection_refused(exc):
        return (
            "Αποτυχία επικοινωνίας με το Ollama Cloud API. "
            "Έλεγξε τη σύνδεσή σου στο διαδίκτυο και δοκίμασε ξανά."
        )

    # 404 — μοντέλο δεν βρέθηκε
    if "404" in text or "not found" in lower or "does not exist" in lower:
        return (
            "Το μοντέλο δεν βρέθηκε στο direct Ollama Cloud API. "
            "Στο direct mode τα επίσημα model names προέρχονται αποκλειστικά από το /api/tags και συχνά διαφέρουν από τα local *-cloud names. "
            "Κάνε Refresh Models και επίλεξε κάποιο από την επίσημη direct API λίστα."
        )

    # 401 / 403 — authentication
    if "401" in text or "403" in text or "unauthorized" in lower or "forbidden" in lower:
        return (
            "Το OLLAMA_API_KEY λείπει ή δεν είναι έγκυρο για το direct Ollama Cloud API. "
            "Έλεγξε το API key και δοκίμασε ξανά."
        )

    if "network error" in lower or "δικτυακό σφάλμα" in lower or "name or service not known" in lower:
        return (
            "Δεν ήταν δυνατή η επικοινωνία με το Ollama Cloud API. "
            "Έλεγξε σύνδεση internet, firewall ή proxy."
        )

    # Timeout
    if "timeout" in lower or "timed out" in lower or "read timeout" in lower:
        return (
            "Το αίτημα προς το Ollama Cloud API έληξε (timeout). "
            "Το μοντέλο ίσως χρειάζεται περισσότερο χρόνο — δοκίμασε ξανά."
        )

    # Context length exceeded
    if "context" in lower and ("length" in lower or "window" in lower or "exceed" in lower):
        return (
            "Το context window του μοντέλου ξεπεράστηκε. "
            "Δοκίμασε να καθαρίσεις το chat ή να μειώσεις το μέγεθος των συνημμένων."
        )

    return text or "Άγνωστο σφάλμα επικοινωνίας με το Ollama Cloud API."


def normalize_model_name(model: str) -> str:
    """
    Διασφαλίζει ότι το model name είναι σε αποδεκτή μορφή για το Ollama API.
    Αφαιρεί οποιοδήποτε path prefix (π.χ. 'library/').

    Παραδείγματα:
      'library/qwen3.5:397b-cloud' → 'qwen3.5:397b-cloud'
      'qwen3.5:cloud'              → 'qwen3.5:cloud'       (αμετάβλητο)
    """
    model = (model or "").strip()
    if "/" in model and ":" in model:
        # Κράτα μόνο name:tag — αφαίρεσε path prefix
        name_part, tag_part = model.split(":", 1)
        name_part = name_part.split("/")[-1]
        return f"{name_part}:{tag_part}"
    return model


def extract_chunk_content(chunk: object) -> str:
    if chunk is None:
        return ""
    try:
        message = chunk.get("message", {}) if isinstance(chunk, dict) else getattr(chunk, "message", None)
        if message is None:
            return str(getattr(chunk, "content", "") or "")
        if isinstance(message, dict):
            return str(message.get("content", "") or "")
        return str(getattr(message, "content", "") or "")
    except Exception:
        return ""


def extract_chunk_thinking(chunk: object) -> str:
    if chunk is None:
        return ""
    try:
        message = chunk.get("message", {}) if isinstance(chunk, dict) else getattr(chunk, "message", None)
        if message is None:
            return str(getattr(chunk, "thinking", "") or "")
        if isinstance(message, dict):
            return str(message.get("thinking", "") or "")
        return str(getattr(message, "thinking", "") or "")
    except Exception:
        return ""


def compose_display_assistant_text(content: str, thinking: str = "") -> str:
    safe_content = str(content or "")
    safe_thinking = str(thinking or "")
    if safe_thinking and safe_content:
        return f"<think>{safe_thinking}</think>\n\n{safe_content}"
    if safe_thinking:
        return f"<think>{safe_thinking}</think>"
    return safe_content


def resolve_think_mode(model: str, raw_mode: object) -> Optional[object]:
    mode = str(raw_mode or "auto").strip().lower()
    model_l = str(model or "").strip().lower()

    if mode == "off":
        return False if "gpt-oss" not in model_l else "low"
    if mode in {"low", "medium", "high"}:
        return mode if "gpt-oss" in model_l else True
    if mode == "on":
        return "medium" if "gpt-oss" in model_l else True
    if mode != "auto":
        log.warning("resolve_think_mode: άγνωστο mode %r — fallback σε auto", raw_mode)
        # fall through to auto logic

    if "gpt-oss" in model_l:
        return "medium"
    thinking_hints = (
        "qwen3", "deepseek-r1", "deepseek-v3.1", "reason", "thinking", "r1"
    )
    if any(token in model_l for token in thinking_hints):
        return True
    return None


def extract_token_stats(chunk: object) -> Optional[Dict]:
    """
    Εξάγει τα πραγματικά usage metrics από το τελευταίο chunk του Ollama streaming.
    Το πραγματικό output tok/s υπολογίζεται από eval_count / eval_duration
    όπως επιστρέφεται από το API στο τελικό done chunk.
    """
    try:
        if isinstance(chunk, dict):
            eval_count = chunk.get("eval_count")
            eval_duration = chunk.get("eval_duration")
            prompt_eval_count = chunk.get("prompt_eval_count")
            prompt_eval_duration = chunk.get("prompt_eval_duration")
            total_duration = chunk.get("total_duration")
            load_duration = chunk.get("load_duration")
        else:
            eval_count = getattr(chunk, "eval_count", None)
            eval_duration = getattr(chunk, "eval_duration", None)
            prompt_eval_count = getattr(chunk, "prompt_eval_count", None)
            prompt_eval_duration = getattr(chunk, "prompt_eval_duration", None)
            total_duration = getattr(chunk, "total_duration", None)
            load_duration = getattr(chunk, "load_duration", None)

        if not eval_count or not eval_duration or eval_duration <= 0:
            return None

        tokens_per_sec = round(eval_count / (eval_duration / 1e9), 1)
        prompt_tokens_per_sec = None
        if prompt_eval_count and prompt_eval_duration and prompt_eval_duration > 0:
            prompt_tokens_per_sec = round(prompt_eval_count / (prompt_eval_duration / 1e9), 1)

        end_to_end_tokens_per_sec = None
        if total_duration and total_duration > 0:
            end_to_end_tokens_per_sec = round(eval_count / (total_duration / 1e9), 1)

        return {
            "eval_count": eval_count,
            "eval_duration": eval_duration,
            "tokens_per_sec": tokens_per_sec,
            "prompt_eval_count": prompt_eval_count,
            "prompt_eval_duration": prompt_eval_duration,
            "prompt_tokens_per_sec": prompt_tokens_per_sec,
            "total_duration": total_duration,
            "load_duration": load_duration,
            "end_to_end_tokens_per_sec": end_to_end_tokens_per_sec,
        }
    except Exception:
        pass
    return None


# ─────────────────────────── Session helpers ─────────────────────────────────

def get_effective_system_prompt(gui_system_prompt: str = "") -> Tuple[str, str]:
    cleaned = (gui_system_prompt or "").strip()
    if cleaned:
        return cleaned, "gui-custom"
    return get_embedded_system_prompt()


def build_messages(system_prompt: str, session_messages: List[Dict]) -> List[Dict]:
    messages: List[Dict] = []
    cleaned_system = (system_prompt or "").strip()
    if cleaned_system:
        messages.append({"role": "system", "content": cleaned_system})
    for item in session_messages:
        role    = item.get("role", "").strip()
        content = item.get("content", "")
        if role in {"user", "assistant"} and isinstance(content, str):
            msg: Dict = {"role": role, "content": content}
            if role == "assistant" and isinstance(item.get("thinking"), str) and item.get("thinking", "").strip():
                msg["thinking"] = item["thinking"]
            if role == "user" and item.get("images"):
                # Εικόνες ιστορικού: αν είναι ήδη base64 strings τις περνάμε αυτούσιες,
                # αν είναι paths τις διαβάζουμε και τις κωδικοποιούμε σε base64.
                b64_images: List[str] = []
                for img in item["images"]:
                    img_str = str(img or "").strip()
                    if not img_str:
                        continue
                    if len(img_str) > 260 or img_str.startswith("/") or (len(img_str) > 1 and img_str[1] == ":"):
                        # Μοιάζει με path — διάβασε και κωδικοποίησε
                        try:
                            b64_images.append(base64.b64encode(Path(img_str).read_bytes()).decode("ascii"))
                        except Exception:
                            pass
                    else:
                        b64_images.append(img_str)
                if b64_images:
                    msg["images"] = b64_images
            messages.append(msg)
    return messages


def get_history_payload() -> List[Dict]:
    with SESSION.lock:
        return copy.deepcopy(SESSION.history)


# ─────────────────────────── File helpers ────────────────────────────────────

def sanitize_filename(filename: str) -> str:
    basename = Path(filename).name
    cleaned  = re.sub(r"[^\w.\-()\[\] ]+", "_", basename, flags=re.UNICODE).strip()
    cleaned  = cleaned.lstrip(".")
    return cleaned or "file"


def extract_original_generated_filename(stored_name: str) -> str:
    basename = Path(str(stored_name or "")).name
    match = re.match(r"^\d{10,}_[0-9a-fA-F]{8}_(.+)$", basename)
    candidate = match.group(1) if match else basename
    safe_name = sanitize_filename(candidate)
    if safe_name and safe_name != "file":
        return safe_name
    return "generated_code.py"


def ensure_upload_dir() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_generated_code_dir() -> None:
    GENERATED_CODE_DIR.mkdir(parents=True, exist_ok=True)


def suggest_python_filename(code_text: str) -> str:
    cleaned = (code_text or '').strip()
    if not cleaned:
        return 'generated_code.py'

    patterns = [
        r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*async\s+def\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.MULTILINE)
        if match:
            return sanitize_filename(match.group(1) + '.py')

    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            candidate = stripped.lstrip('#').strip()[:60]
            candidate = re.sub(r"\s+", '_', candidate)
            candidate = sanitize_filename(candidate)
            if candidate and candidate != 'file':
                if not candidate.lower().endswith('.py'):
                    candidate += '.py'
                return candidate
            break

    return 'generated_code.py'


def save_generated_python_file(code_text: str, suggested_filename: str = '') -> Dict[str, str]:
    cleaned = (code_text or '').replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'
    if not cleaned.strip():
        raise ValueError('Δεν υπάρχει Python code για αποθήκευση.')

    ensure_generated_code_dir()
    requested_name = suggested_filename.strip() if suggested_filename else suggest_python_filename(cleaned)
    safe_name = sanitize_filename(requested_name)
    if not safe_name.lower().endswith('.py'):
        safe_name += '.py'

    unique_name = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}_{safe_name}"
    out_path = (GENERATED_CODE_DIR / unique_name).resolve()
    generated_root = str(GENERATED_CODE_DIR.resolve()) + os.sep
    if not str(out_path).startswith(generated_root):
        raise ValueError('Μη ασφαλές όνομα αρχείου για generated Python attachment.')

    out_path.write_text(cleaned, encoding='utf-8')
    with SESSION.lock:
        SESSION.upload_paths.add(str(out_path))

    return {
        'name': safe_name,
        'stored_name': unique_name,
        'url': f"/generated-code/{urllib.parse.quote(unique_name)}",
        'kind': 'file',
    }


def model_supports_images(model_name: str) -> bool:
    name  = (model_name or "").lower()
    hints = ("vl", "vision", "gemini", "gemma3", "llava", "minicpm-v", "qwen2.5vl", "qwen3-vl")
    return any(h in name for h in hints)


def save_uploaded_file(filename: str, data_base64: str) -> Path:
    ensure_upload_dir()
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except Exception as exc:
        raise ValueError(f"Μη έγκυρα base64 δεδομένα για το αρχείο: {filename}") from exc

    if len(raw) > MAX_UPLOAD_BYTES_PER_FILE:
        raise ValueError(
            f"Το αρχείο '{filename}' είναι πολύ μεγάλο. "
            f"Μέγιστο: {MAX_UPLOAD_BYTES_PER_FILE // (1024 * 1024)} MB."
        )

    safe_name   = sanitize_filename(filename)
    unique_name = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}_{safe_name}"
    out_path    = (UPLOADS_DIR / unique_name).resolve()
    uploads_resolved = str(UPLOADS_DIR.resolve()) + os.sep
    if not str(out_path).startswith(uploads_resolved):
        raise ValueError(f"Μη ασφαλές όνομα αρχείου: {filename}")
    out_path.write_bytes(raw)
    with SESSION.lock:
        SESSION.upload_paths.add(str(out_path))
    return out_path


def truncate_text(text: str, limit: int = MAX_TEXT_CHARS_PER_FILE) -> Tuple[str, bool]:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(cleaned) <= limit:
        return cleaned, False
    return cleaned[:limit].rstrip() + "\n\n...[TRUNCATED]...", True


def extract_pdf_text(path: Path) -> Tuple[str, bool, str]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return "", False, "Δεν βρέθηκε το optional package 'pypdf'. Εγκατάσταση: pip install pypdf"
    try:
        reader    = PdfReader(str(path))
        parts:    List[str] = []
        total_len = 0
        for page in reader.pages:
            extracted = page.extract_text() or ""
            if extracted:
                parts.append(extracted)
                total_len += len(extracted)
            if total_len >= MAX_TEXT_CHARS_PER_FILE:
                break
        joined = "\n\n".join(parts).strip()
        if not joined:
            return "", False, "Δεν βρέθηκε εξαγώγιμο κείμενο στο PDF."
        truncated_text, was_truncated = truncate_text(joined, MAX_TEXT_CHARS_PER_FILE)
        return truncated_text, was_truncated, ""
    except Exception as exc:
        return "", False, f"Αποτυχία ανάγνωσης PDF: {exc}"


def extract_text_for_context(path: Path) -> Tuple[str, bool, str]:
    suffix = path.suffix.lower()

    if suffix in TEXT_EXTENSIONS:
        for enc in ("utf-8", "utf-8-sig", "cp1253", "cp1252", "latin-1"):
            try:
                content = path.read_text(encoding=enc)
                truncated_text, was_truncated = truncate_text(content, MAX_TEXT_CHARS_PER_FILE)
                return truncated_text, was_truncated, ""
            except Exception:
                continue
        return "", False, "Το αρχείο δεν μπόρεσε να διαβαστεί ως κείμενο."

    if suffix == ".pdf":
        return extract_pdf_text(path)

    return "", False, "Ο τύπος αρχείου δεν υποστηρίζεται για εξαγωγή κειμένου."


def prepare_attachments(
    attachments: List[Dict], model_name: str
) -> Tuple[List[Dict], List[str]]:
    processed: List[Dict] = []
    warnings:  List[str]  = []

    if not attachments:
        return processed, warnings

    if len(attachments) > MAX_UPLOAD_FILES_PER_MESSAGE:
        raise ValueError(f"Μπορείς να στείλεις έως {MAX_UPLOAD_FILES_PER_MESSAGE} αρχεία ανά μήνυμα.")

    image_capable    = model_supports_images(model_name)
    total_text_chars = 0

    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError("Ένα από τα συνημμένα δεν είναι σε έγκυρη μορφή.")

        filename    = str(item.get("name", "file")).strip() or "file"
        data_base64 = str(item.get("data_base64", "")).strip()
        mime_type   = str(item.get("mime_type", "")).strip()

        if not data_base64:
            raise ValueError(f"Το αρχείο '{filename}' δεν περιέχει δεδομένα.")

        saved_path = save_uploaded_file(filename, data_base64)
        ext        = saved_path.suffix.lower()

        entry: Dict = {
            "name":              filename,
            "path":              str(saved_path),
            "mime_type":         mime_type,
            "kind":              "other",
            "text_excerpt":      "",
            "text_truncated":    False,
            "will_send_as_image": False,
            "status_message":    "",
        }

        if ext in IMAGE_EXTENSIONS:
            entry["kind"] = "image"
            if image_capable:
                entry["will_send_as_image"] = True
            else:
                entry["status_message"] = (
                    "Το αρχείο είναι εικόνα, αλλά το τρέχον μοντέλο δεν φαίνεται vision-capable."
                )
                warnings.append(
                    f"Η εικόνα '{filename}' φορτώθηκε, αλλά για native image ανάλυση "
                    "προτίμησε vision model όπως qwen3-vl."
                )
        else:
            entry["kind"] = "document"
            text_excerpt, was_truncated, status_message = extract_text_for_context(saved_path)
            entry["text_excerpt"]   = text_excerpt
            entry["text_truncated"] = was_truncated
            entry["status_message"] = status_message

            if text_excerpt:
                remaining = max(MAX_TOTAL_TEXT_CHARS_PER_MESSAGE - total_text_chars, 0)
                if remaining <= 0:
                    entry["text_excerpt"]   = ""
                    entry["status_message"] = (
                        "Το αρχείο φορτώθηκε, αλλά δεν μπήκε στο prompt λόγω ορίου context."
                    )
                elif len(text_excerpt) > remaining:
                    trimmed, _            = truncate_text(text_excerpt, remaining)
                    entry["text_excerpt"]   = trimmed
                    entry["text_truncated"] = True
                    total_text_chars       += len(trimmed)
                else:
                    total_text_chars += len(text_excerpt)

        processed.append(entry)

    return processed, warnings


def build_user_message_content(user_text: str, processed_attachments: List[Dict]) -> str:
    parts:            List[str] = [user_text.strip()]
    attachment_lines: List[str] = []
    context_blocks:   List[str] = []

    for item in processed_attachments:
        if item["kind"] == "image":
            if item["will_send_as_image"]:
                attachment_lines.append(f"- Εικόνα: {item['name']} (θα σταλεί natively στο model)")
            else:
                note = item["status_message"] or "Εικόνα χωρίς native vision υποστήριξη."
                attachment_lines.append(f"- Εικόνα: {item['name']} ({note})")
        else:
            status_note = (
                "έτοιμο για context"
                if item["text_excerpt"]
                else (item["status_message"] or "χωρίς κείμενο")
            )
            attachment_lines.append(f"- Αρχείο: {item['name']} ({status_note})")
            if item["text_excerpt"]:
                context_blocks.append(f"### Αρχείο: {item['name']}\n{item['text_excerpt']}")

    if attachment_lines:
        parts.append("[Συνημμένα αρχεία]\n" + "\n".join(attachment_lines))
    if context_blocks:
        parts.append(
            "[Περιεχόμενο συνημμένων για χρήση ως context]\n\n" + "\n\n".join(context_blocks)
        )

    return "\n\n".join(p for p in parts if p.strip())


# ─────────────────────────── HTML / UI ───────────────────────────────────────

def serve_startup_html() -> str:
    """Startup splash page — εμφανίζεται στον browser ενώ γίνεται η εκκίνηση."""
    return f"""<!DOCTYPE html>
<html lang="el">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Εκκίνηση — {html.escape(APP_TITLE)}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      min-height: 100vh;
      background:
        radial-gradient(circle at top left,  rgba(96,165,250,0.15), transparent 34%),
        radial-gradient(circle at top right, rgba(94,234,212,0.12), transparent 26%),
        linear-gradient(135deg, #0b1020, #101a35);
      color: #e5eefc;
      font-family: Consolas, "Cascadia Code", "Fira Code", monospace;
      display: flex; align-items: center; justify-content: center;
      flex-direction: column;
      padding: 24px;
    }}

    .wrap {{ width: 680px; max-width: 100%; }}

    .copyright {{
      margin-top: 18px;
      text-align: center;
      color: #9fb0d1;
      font-size: 0.92rem;
      font-family: "Segoe UI", Inter, Arial, sans-serif;
      letter-spacing: 0.5px;
      padding-top: 16px;
      border-top: 1px solid rgba(94,234,212,0.30);
    }}

    /* ── Header ── */
    .header {{
      text-align: center; margin-bottom: 28px;
      animation: fade-down 0.5s ease-out;
    }}
    .logo   {{ font-size: 3.2rem; line-height: 1; margin-bottom: 10px; }}
    .title  {{
      font-size: 1.45rem; font-weight: 700; letter-spacing: 0.4px;
      background: linear-gradient(135deg, #5eead4, #60a5fa);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }}
    .subtitle {{ color: #9fb0d1; font-size: 0.88rem; margin-top: 6px; }}

    @keyframes fade-down {{
      from {{ opacity: 0; transform: translateY(-14px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ── Terminal card ── */
    .terminal {{
      background: rgba(15,23,42,0.82);
      border: 1px solid rgba(94,234,212,0.18);
      border-radius: 20px;
      backdrop-filter: blur(18px);
      box-shadow: 0 24px 64px rgba(0,0,0,0.45);
      overflow: hidden;
      animation: fade-up 0.5s ease-out 0.1s both;
    }}
    @keyframes fade-up {{
      from {{ opacity: 0; transform: translateY(14px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}

    /* macOS-style titlebar */
    .titlebar {{
      display: flex; align-items: center; gap: 8px;
      padding: 12px 18px;
      background: rgba(15,23,42,0.98);
      border-bottom: 1px solid rgba(94,234,212,0.10);
    }}
    .dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}
    .dot-r {{ background: #ff5f57; }}
    .dot-y {{ background: #febc2e; }}
    .dot-g {{ background: #28c840; }}
    .bar-title {{
      flex: 1; text-align: center;
      color: #586e75; font-size: 0.8rem; letter-spacing: 0.3px;
    }}

    /* Log area */
    .log-area {{
      padding: 20px 22px;
      min-height: 230px;
      max-height: 380px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: rgba(94,234,212,0.2) transparent;
    }}
    .log-area::-webkit-scrollbar       {{ width: 5px; }}
    .log-area::-webkit-scrollbar-thumb {{ background: rgba(94,234,212,0.22); border-radius: 99px; }}

    .log-line {{
      display: flex; gap: 14px;
      padding: 2px 0; font-size: 0.875rem; line-height: 1.55;
      animation: slide-in 0.22s ease-out;
    }}
    @keyframes slide-in {{
      from {{ opacity: 0; transform: translateX(-10px); }}
      to   {{ opacity: 1; transform: translateX(0); }}
    }}

    .log-t     {{ color: #586e75; flex-shrink: 0; width: 64px; }}
    .log-lvl   {{ flex-shrink: 0; width: 56px; font-weight: 700; }}
    .log-msg   {{ flex: 1; word-break: break-word; }}

    .lvl-INFO    .log-lvl {{ color: #60a5fa; }}
    .lvl-WARNING .log-lvl {{ color: #f59e0b; }}
    .lvl-ERROR   .log-lvl {{ color: #f87171; }}
    .lvl-READY   .log-lvl,
    .lvl-READY   .log-msg {{ color: #34d399; }}
    .lvl-READY   .log-msg {{ font-weight: 600; }}

    /* Footer strip */
    .footer {{
      padding: 14px 22px;
      border-top: 1px solid rgba(94,234,212,0.08);
      background: rgba(15,23,42,0.55);
    }}

    /* Spinner */
    .spinner {{
      display: flex; align-items: center; gap: 10px;
      color: #9fb0d1; font-size: 0.84rem;
    }}
    .dots {{ display: flex; gap: 5px; }}
    .dots span {{
      width: 7px; height: 7px; border-radius: 50%;
      background: #5eead4; opacity: 0.25;
      animation: dot-pulse 1.2s ease-in-out infinite;
    }}
    .dots span:nth-child(2) {{ animation-delay: 0.2s; }}
    .dots span:nth-child(3) {{ animation-delay: 0.4s; }}
    @keyframes dot-pulse {{
      0%,80%,100% {{ opacity: 0.25; transform: scale(0.9); }}
      40%          {{ opacity: 1;   transform: scale(1.1); }}
    }}

    /* Ready bar */
    .ready-bar {{
      display: none;
      padding: 12px 16px;
      background: rgba(52,211,153,0.12);
      border: 1px solid rgba(52,211,153,0.28);
      border-radius: 12px;
      color: #34d399; font-size: 0.88rem; font-weight: 600;
      text-align: center;
    }}
    .ready-bar a {{
      color: #5eead4; cursor: pointer; text-decoration: underline;
    }}
    .progress-bar {{
      height: 3px; background: rgba(52,211,153,0.15); border-radius: 99px;
      margin-top: 10px; overflow: hidden;
    }}
    .progress-fill {{
      height: 100%; width: 0;
      background: linear-gradient(90deg, #5eead4, #60a5fa);
      border-radius: 99px;
      transition: width 1.6s linear;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div class="logo">☁️</div>
      <div class="title">{html.escape(APP_TITLE)}</div>
      <div class="subtitle">Εκκίνηση — παρακαλώ περίμενε…</div>
    </div>

    <div class="terminal">
      <div class="titlebar">
        <div class="dot dot-r"></div>
        <div class="dot dot-y"></div>
        <div class="dot dot-g"></div>
        <div class="bar-title">startup log</div>
      </div>

      <div class="log-area" id="logArea"></div>

      <div class="footer">
        <div class="spinner" id="spinner">
          <div class="dots"><span></span><span></span><span></span></div>
          <span id="spinMsg">Αρχικοποίηση…</span>
        </div>
        <div class="ready-bar" id="readyBar">
          ✅ Έτοιμο! Μεταβαίνεις αυτόματα…
          &nbsp;<a onclick="goNow()">Πήγαινε τώρα</a>
          <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
        </div>
      </div>
    </div><!-- /.terminal -->

    <div class="copyright">&copy; Ευάγγελος Πεφάνης</div>

  </div><!-- /.wrap -->

  <script>
    var chatUrl  = null;
    var logArea  = document.getElementById("logArea");
    var spinner  = document.getElementById("spinner");
    var spinMsg  = document.getElementById("spinMsg");
    var readyBar = document.getElementById("readyBar");
    var fillEl   = document.getElementById("progressFill");

    var LEVEL_LABEL = {{
      INFO: "INFO", WARNING: "WARN", ERROR: "ERR ", READY: "READY"
    }};

    function esc(s) {{
      return String(s||"")
        .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }}

    function addLine(ev) {{
      var d = document.createElement("div");
      d.className = "log-line lvl-" + ev.level;
      d.innerHTML =
        '<span class="log-t">'   + esc(ev.t)   + '</span>' +
        '<span class="log-lvl">' + (LEVEL_LABEL[ev.level] || ev.level) + '</span>' +
        '<span class="log-msg">' + esc(ev.msg)  + '</span>';
      logArea.appendChild(d);
      d.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
    }}

    function goNow() {{
      if (chatUrl) window.location.replace(chatUrl);
    }}

    var es = new EventSource("/startup-events");

    es.onmessage = function(e) {{
      var ev;
      try {{ ev = JSON.parse(e.data); }} catch(_) {{ return; }}
      addLine(ev);

      if (ev.level !== "READY") {{
        spinMsg.textContent = ev.msg.replace(/^[\\p{{Emoji}}\\s]+/u, "");
      }}

      if (ev.level === "READY") {{
        chatUrl = ev.msg;
        es.close();
        spinner.style.display  = "none";
        readyBar.style.display = "block";
        // Animate progress bar → 100% then redirect
        requestAnimationFrame(function() {{
          fillEl.style.width = "100%";
        }});
        setTimeout(goNow, 1800);
      }}
    }};

    es.onerror = function() {{
      es.close();
      spinMsg.textContent = "Αποτυχία SSE — ανανέωσε τη σελίδα.";
      spinner.style.color = "#f59e0b";
    }};
  </script>
</body>
</html>"""

def serve_index_html() -> str:
    """Παράγει και επιστρέφει το πλήρες HTML UI."""
    system_prompt, _ = get_embedded_system_prompt()

    safe_prompt_json = json.dumps(system_prompt, ensure_ascii=False).replace("</", r"<\/")
    accepted_types = ACCEPTED_FILE_TYPES

    html_doc = r"""<!DOCTYPE html>
<html lang="el" data-theme="dark">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__APP_TITLE__</title>

  <!-- Prism.js — δύο themes: dark (prism-tomorrow) και light (prism-solarizedlight). -->
  <!-- Ενεργό theme εναλλάσσεται από JS στο applyTheme().                           -->
  <link id="prismDark"  rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" />
  <link id="prismLight" rel="stylesheet" disabled
        href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-solarizedlight.min.css" />
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-javascript.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-typescript.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-sql.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-css.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-markup.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-go.min.js" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-rust.min.js" defer></script>
  <!-- Inline: ενεργοποίηση σωστού Prism theme ΠΡΙΝ το πρώτο paint (αποφυγή flash) -->
  <script>
    (function () {
      var theme = "dark";
      try { theme = localStorage.getItem("ollama_chat_theme_v2") || "dark"; } catch (_) {}
      if (theme === "light") {
        var d = document.getElementById("prismDark");
        var l = document.getElementById("prismLight");
        if (d) d.disabled = true;
        if (l) l.disabled = false;
      }
    })();
  </script>

  <style>
    /* ── Variables (dark default) ── */
    :root {
      --bg1:       #0b1020;
      --bg2:       #101a35;
      --panel:     rgba(15, 23, 42, 0.78);
      --line:      rgba(148, 163, 184, 0.18);
      --text:      #e5eefc;
      --muted:     #9fb0d1;
      --accent:    #5eead4;
      --accent-2:  #60a5fa;
      --shadow:    0 20px 60px rgba(0,0,0,0.35);
      --radius:    22px;
      --radius-sm: 16px;
      --mono:      Consolas, "Cascadia Code", "Fira Code", monospace;
      --sans:      "Segoe UI", Inter, Arial, sans-serif;
    }

    /* ── Reset ── */
    *, *::before, *::after { box-sizing: border-box; }
    html { color-scheme: dark; }
    html, body {
      margin: 0; min-height: 100%;
      font-family: var(--sans); color: var(--text);
      background:
        radial-gradient(circle at top left,  rgba(96,165,250,0.15), transparent 34%),
        radial-gradient(circle at top right, rgba(94,234,212,0.12), transparent 26%),
        linear-gradient(135deg, var(--bg1), var(--bg2));
      background-attachment: fixed;
    }
    body { padding: 22px; }
    ::selection { background: rgba(96,165,250,0.28); color: inherit; }

    /* ── Layout ── */
    .app {
      max-width: 1850px; margin: 0 auto;
      display: grid; grid-template-columns: 450px 1fr; gap: 22px;
    }
    .card {
      background: var(--panel); backdrop-filter: blur(18px);
      border: 1px solid var(--line); border-radius: var(--radius);
      box-shadow: var(--shadow);
    }

    /* ── Sidebar ── */
    .sidebar {
      padding: 18px;
      display: flex; flex-direction: column; gap: 16px;
      height: calc(100vh - 44px);
      position: sticky; top: 22px;
      overflow-y: auto;       /* scroll για μικρές οθόνες */
      scrollbar-width: thin;
    }
    .title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .title h1 { margin: 0; font-size: 1.22rem; line-height: 1.2; letter-spacing: 0.2px; }

    .pill {
      border-radius: 999px; padding: 7px 12px; font-size: 0.8rem; color: #dffcf6;
      background: linear-gradient(135deg, rgba(94,234,212,0.22), rgba(96,165,250,0.18));
      border: 1px solid rgba(94,234,212,0.2); white-space: nowrap;
    }

    .group {
      padding: 14px; border-radius: var(--radius-sm);
      background: rgba(15,23,42,0.52); border: 1px solid var(--line);
      flex-shrink: 0;
    }

    .label { display: block; margin-bottom: 8px; color: var(--muted); font-size: 0.92rem; font-weight: 600; }

    select, textarea, input[type="text"], input[type="file"] {
      width: 100%; border: 1px solid rgba(148,163,184,0.22);
      background: rgba(2,6,23,0.55); color: var(--text);
      border-radius: 14px; padding: 12px 14px; outline: none;
      font-family: var(--sans);
      transition: border-color 0.16s ease, box-shadow 0.16s ease;
    }
    textarea { resize: vertical; min-height: 90px; line-height: 1.45; }
    select:focus, textarea:focus, input:focus {
      border-color: rgba(96,165,250,0.55);
      box-shadow: 0 0 0 4px rgba(96,165,250,0.14);
    }
    input[type="file"] { padding: 10px; }

    .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }

    button {
      border: 0; border-radius: 14px; padding: 12px 14px;
      cursor: pointer; font-weight: 700; font-size: 0.93rem;
      transition: transform 0.15s ease, filter 0.15s ease, opacity 0.15s ease;
    }
    button:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.06); }
    button:disabled  { opacity: 0.52; cursor: not-allowed; transform: none; }
    .btn-full { width: 100%; }
    .primary  { color: #08111d; background: linear-gradient(135deg, var(--accent), var(--accent-2)); }
    .secondary {
      color: var(--text); background: rgba(51,65,85,0.85);
      border: 1px solid rgba(148,163,184,0.18);
    }

    /* ── Chat panel ── */
    .chat-panel { height: calc(100vh - 44px); display: flex; flex-direction: column; overflow: hidden; }

    .chat-header {
      padding: 16px 26px; border-bottom: 1px solid var(--line);
      display: flex; flex-wrap: wrap; align-items: center;
      justify-content: space-between; gap: 10px;
      background: rgba(15,23,42,0.45); flex-shrink: 0;
    }
    .chat-header h2 { margin: 0; font-size: 1.08rem; }
    .header-left    { display: flex; flex-direction: column; gap: 3px; }
    .status-wrap    { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

    .badge {
      border-radius: 999px; padding: 7px 12px; font-size: 0.82rem;
      background: rgba(51,65,85,0.8); border: 1px solid rgba(148,163,184,0.15);
      color: var(--muted);
    }
    .badge.ok   { color: #d1fae5; background: rgba(34,197,94,0.14);  border-color: rgba(34,197,94,0.24); }
    .badge.warn { color: #fef3c7; background: rgba(245,158,11,0.12); border-color: rgba(245,158,11,0.22); }
    .badge.err  { color: #fecaca; background: rgba(239,68,68,0.14);  border-color: rgba(239,68,68,0.24); }

    /* ── Messages ── */
    .messages-wrap { flex: 1; position: relative; overflow: hidden; }
    .messages {
      height: 100%; overflow-y: auto; padding: 22px;
      display: flex; flex-direction: column; gap: 14px;
      scroll-behavior: smooth;
    }

    /* ── Realtime reasoning panel ── */
    .reasoning-panel {
      display: none;
      margin: 14px 22px 0;
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(94,234,212,0.18);
      background: linear-gradient(180deg, rgba(14,26,50,0.72), rgba(12,22,40,0.62));
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
      flex-shrink: 0;
    }
    .reasoning-panel.visible { display: block; }
    .reasoning-panel.streaming {
      border-color: rgba(94,234,212,0.30);
      box-shadow: 0 0 0 1px rgba(94,234,212,0.08), 0 10px 30px rgba(0,0,0,0.14);
    }
    .reasoning-head {
      display: flex; align-items: flex-start; justify-content: space-between;
      gap: 12px; margin-bottom: 10px;
    }
    .reasoning-title-wrap { min-width: 0; }
    .reasoning-title {
      display: flex; align-items: center; gap: 10px;
      font-size: 0.95rem; font-weight: 800; letter-spacing: 0.2px;
    }
    .reasoning-meta {
      margin-top: 4px; color: var(--muted); font-size: 0.82rem;
    }
    .reasoning-toggle-btn {
      padding: 8px 12px; font-size: 0.8rem; white-space: nowrap;
    }
    .reasoning-body {
      margin: 0;
      max-height: 220px;
      overflow-y: auto;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: var(--mono);
      font-size: 0.87rem;
      line-height: 1.56;
      color: #c9d9f3;
      background: rgba(2,6,23,0.34);
      border: 1px solid rgba(148,163,184,0.10);
      border-radius: 14px;
      padding: 12px 14px;
      scrollbar-width: thin;
      scrollbar-color: rgba(94,234,212,0.22) transparent;
    }
    .reasoning-body::-webkit-scrollbar { width: 6px; }
    .reasoning-body::-webkit-scrollbar-thumb {
      background: rgba(94,234,212,0.24); border-radius: 99px;
    }

    .empty-state {
      margin: auto; max-width: 820px; text-align: center;
      border: 1px dashed rgba(148,163,184,0.22); border-radius: 22px;
      padding: 34px 26px; color: var(--muted); background: rgba(15,23,42,0.28);
    }

    /* Scroll-to-bottom floating button */
    .scroll-to-bottom {
      position: absolute; bottom: 14px; right: 20px;
      background: var(--accent); color: #08111d;
      border: none; border-radius: 999px;
      padding: 10px 16px; font-weight: 800; font-size: 0.88rem;
      cursor: pointer; box-shadow: 0 6px 20px rgba(0,0,0,0.3);
      opacity: 0; pointer-events: none;
      transition: opacity 0.2s ease, transform 0.2s ease;
      z-index: 10;
    }
    .scroll-to-bottom.visible { opacity: 1; pointer-events: auto; }
    .scroll-to-bottom:hover   { transform: translateY(-2px); filter: brightness(1.08); }

    /* ── Messages ── */
    .msg {
      max-width: min(1020px, 95%); border-radius: 22px; padding: 14px 16px;
      border: 1px solid var(--line); box-shadow: 0 10px 30px rgba(0,0,0,0.18);
    }
    .msg.user      { align-self: flex-end;   background: linear-gradient(135deg, rgba(96,165,250,0.24), rgba(37,99,235,0.14)); }
    .msg.assistant { align-self: flex-start; background: rgba(15,23,42,0.75); max-width: 100%; width: 100%; }
    .msg.system    { align-self: center; background: rgba(51,65,85,0.6); color: var(--muted); max-width: 90%; }

    .msg-head {
      display: flex; align-items: center; justify-content: space-between;
      gap: 12px; margin-bottom: 10px; font-size: 0.84rem; color: var(--muted);
    }
    .msg-role { font-weight: 800; letter-spacing: 0.2px; }
    .msg-time { opacity: 0.8; white-space: nowrap; font-size: 0.8rem; }
    .msg-body { line-height: 1.62; font-size: 0.98rem; overflow-x: auto; }

    /* ── Markdown styles ── */
    .msg-body .md-h1,.msg-body .md-h2,.msg-body .md-h3,
    .msg-body .md-h4,.msg-body .md-h5,.msg-body .md-h6 {
      margin: 14px 0 6px; font-weight: 700; line-height: 1.3; color: var(--accent);
    }
    .msg-body .md-h1 { font-size: 1.35em; }
    .msg-body .md-h2 { font-size: 1.2em;  }
    .msg-body .md-h3 { font-size: 1.08em; }
    .msg-body .md-h4,.msg-body .md-h5,.msg-body .md-h6 { font-size: 1em; }
    .msg-body .md-p  { margin: 5px 0; }
    .msg-body .md-br { display: block; height: 5px; }
    .msg-body .md-hr { border: none; border-top: 1px solid var(--line); margin: 12px 0; }
    .msg-body .md-list { margin: 5px 0 5px 22px; padding: 0; }
    .msg-body .md-list li { margin: 3px 0; }
    .msg-body .md-bq {
      margin: 8px 0; padding: 10px 14px;
      border-left: 3px solid var(--accent);
      background: rgba(94,234,212,0.06);
      border-radius: 0 10px 10px 0; color: var(--muted);
    }
    .msg-body .md-bq p { margin: 0; }
    .msg-body .md-link { color: var(--accent-2); text-decoration: underline; }
    .msg-body .md-link:hover { opacity: 0.8; }
    .msg-body strong { color: #e2e8f0; font-weight: 700; }
    .msg-body em     { font-style: italic; color: #cbd5e1; }
    .msg-body del    { text-decoration: line-through; opacity: 0.7; }

    /* ── Code blocks ── */
    .code-block {
      border: 1px solid rgba(148,163,184,0.18); border-radius: 16px;
      overflow: hidden; background: rgba(2,6,23,0.92);
      box-shadow: inset 0 1px 0 rgba(148,163,184,0.06); margin: 8px 0;
    }
    .code-toolbar {
      display: flex; align-items: center; justify-content: space-between;
      gap: 10px; padding: 9px 12px;
      background: rgba(15,23,42,0.98);
      border-bottom: 1px solid rgba(148,163,184,0.14);
    }
    .code-language {
      color: #cbd5e1; font-size: 0.78rem; font-weight: 700;
      letter-spacing: 0.3px; text-transform: uppercase;
    }
    .code-copy-btn {
      border: 1px solid rgba(148,163,184,0.18); background: rgba(30,41,59,0.9);
      color: var(--text); border-radius: 10px; padding: 6px 10px;
      font-size: 0.79rem; font-weight: 700; cursor: pointer;
    }
    .code-copy-btn:hover         { filter: brightness(1.1); }
    .code-copy-btn.done  { color: #d1fae5; border-color: rgba(34,197,94,0.24);  background: rgba(34,197,94,0.14); }
    .code-copy-btn.error { color: #fecaca; border-color: rgba(239,68,68,0.24);  background: rgba(239,68,68,0.14); }

    .code-pre {
      margin: 0 !important; padding: 16px 18px !important;
      overflow-x: auto; font-family: var(--mono) !important;
      font-size: 0.93rem !important; line-height: 1.65 !important;
      tab-size: 4; white-space: pre; text-align: left;
      background: transparent !important;
      scrollbar-width: thin;
      scrollbar-color: rgba(148,163,184,0.22) transparent;
    }
    .code-pre::-webkit-scrollbar       { height: 6px; }
    .code-pre::-webkit-scrollbar-track { background: transparent; }
    .code-pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,0.28); border-radius: 99px; }
    .code-pre code[class*="language-"] {
      font-family: var(--mono) !important;
      font-size: inherit !important;
      background: none !important;  /* prevent Prism dark background from leaking */
    }

    .code-inline {
      display: inline-block; padding: 2px 6px; border-radius: 8px;
      background: rgba(30,41,59,0.92); border: 1px solid rgba(148,163,184,0.14);
      font-family: var(--mono); font-size: 0.91em; word-break: break-word;
    }

    /* ── Attachments ── */
    .attachment-list { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }
    .attachment-chip {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 6px 10px; border-radius: 999px;
      background: rgba(30,41,59,0.85); border: 1px solid rgba(148,163,184,0.18);
      font-size: 0.81rem; color: var(--text);
      text-decoration: none;
    }
    .attachment-chip.link { cursor: pointer; }
    .attachment-chip.link:hover { filter: brightness(1.08); }

    /* ── Thinking block (DeepSeek-R1, Qwen3, GLM-Z1 κ.ά.) ── */
    .thinking-block {
      margin: 8px 0 12px;
      border: 1px solid rgba(94,234,212,0.22);
      border-radius: 14px;
      overflow: hidden;
      background: rgba(14,26,50,0.55);
    }
    .thinking-summary {
      display: flex; align-items: center; gap: 8px;
      padding: 9px 14px; cursor: pointer;
      user-select: none; list-style: none;
      color: var(--muted); font-size: 0.83rem; font-weight: 600;
      background: rgba(94,234,212,0.06);
      border-bottom: 1px solid transparent;
      transition: background 0.15s;
    }
    .thinking-summary:hover { background: rgba(94,234,212,0.10); }
    details[open] .thinking-summary {
      border-bottom-color: rgba(94,234,212,0.15);
    }
    .thinking-icon { font-size: 0.95rem; }
    .thinking-label { flex: 1; }
    .thinking-chevron {
      font-size: 0.78rem; opacity: 0.6;
      transition: transform 0.2s;
    }
    details[open] .thinking-chevron { transform: rotate(90deg); }
    .thinking-body {
      padding: 12px 16px;
      font-size: 0.88rem; line-height: 1.58;
      color: #8da4c8;
      font-style: italic;
      white-space: pre-wrap;
      word-break: break-word;
      max-height: 340px;
      overflow-y: auto;
      scrollbar-width: thin;
      scrollbar-color: rgba(94,234,212,0.18) transparent;
    }
    .thinking-body::-webkit-scrollbar       { width: 4px; }
    .thinking-body::-webkit-scrollbar-thumb { background: rgba(94,234,212,0.22); border-radius: 99px; }

    /* Light theme thinking */
    html[data-theme="light"] .thinking-block {
      border-color: rgba(37,99,235,0.18);
      background: rgba(239,246,255,0.60);
    }
    html[data-theme="light"] .thinking-summary {
      background: rgba(37,99,235,0.06); color: #4a6080;
    }
    html[data-theme="light"] .thinking-summary:hover { background: rgba(37,99,235,0.10); }
    html[data-theme="light"] details[open] .thinking-summary {
      border-bottom-color: rgba(37,99,235,0.12);
    }
    html[data-theme="light"] .thinking-body { color: #5b7299; }
    .streaming-dots { display: inline-flex; gap: 5px; align-items: center; padding: 6px 0; }
    .streaming-dots span {
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--accent); opacity: 0.25;
      animation: dot-pulse 1.2s ease-in-out infinite;
    }
    .streaming-dots span:nth-child(2) { animation-delay: 0.2s; }
    .streaming-dots span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes dot-pulse {
      0%, 80%, 100% { opacity: 0.25; transform: scale(0.9); }
      40%            { opacity: 1;    transform: scale(1.1); }
    }

    /* ── Composer ── */
    .composer {
      border-top: 1px solid var(--line); padding: 16px 22px;
      background: rgba(15,23,42,0.4); flex-shrink: 0;
    }
    .composer textarea {
      min-height: 120px; height: 120px; max-height: 220px;
      font-size: 0.97rem; line-height: 1.5;
      font-family: var(--mono);
    }
    .composer-footer {
      margin-top: 10px; display: flex; flex-wrap: wrap; gap: 10px;
      align-items: center; justify-content: space-between;
    }
    .composer-left  { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .composer-right { display: flex; gap: 10px; align-items: center; }
    .char-counter   { font-size: 0.81rem; color: var(--muted); }
    .char-counter.warn { color: #f59e0b; font-weight: 600; }
    .helper { color: var(--muted); font-size: 0.85rem; }

    /* ── Drag overlay ── */
    .drop-overlay {
      display: none; position: fixed; inset: 0;
      background: rgba(94,234,212,0.10); border: 3px dashed var(--accent);
      z-index: 9999; align-items: center; justify-content: center;
      font-size: 1.5rem; color: var(--accent); pointer-events: none;
      backdrop-filter: blur(2px);
    }
    .drop-overlay.active { display: flex; }

    /* ── Message tools ── */
    .message-tools { margin-top: 10px; display: flex; justify-content: flex-end; gap: 8px; }
    .tool-btn {
      padding: 7px 10px; border-radius: 10px;
      background: rgba(30,41,59,0.85); color: var(--text);
      font-size: 0.81rem; border: 1px solid rgba(148,163,184,0.16);
    }

    /* ── Model parameters panel ── */
    .param-row {
      display: flex; align-items: center; justify-content: space-between;
      gap: 10px; margin-bottom: 10px;
    }
    .param-row:last-child { margin-bottom: 0; }
    .param-label {
      font-size: 0.82rem; color: var(--muted); font-weight: 600;
      white-space: nowrap; min-width: 80px;
    }
    .param-value {
      font-size: 0.82rem; color: var(--accent); font-weight: 700;
      min-width: 36px; text-align: right; font-family: var(--mono);
    }
    input[type="range"] {
      flex: 1; height: 4px; border-radius: 4px; outline: none;
      background: rgba(148,163,184,0.25); padding: 0; border: none;
      cursor: pointer; accent-color: var(--accent);
    }
    input[type="range"]:focus { box-shadow: 0 0 0 3px rgba(94,234,212,0.18); }
    .param-seed-wrap {
      display: flex; gap: 8px; align-items: center;
    }
    .param-seed-wrap input[type="text"] {
      flex: 1; padding: 8px 10px; font-family: var(--mono);
      font-size: 0.82rem; border-radius: 10px;
    }

    /* ── Misc ── */
    .support-list { margin: 8px 0 0 18px; padding: 0; color: var(--muted); font-size: 0.81rem; line-height: 1.5; }
    .footer-note  { margin-top: auto; color: var(--muted); font-size: 0.84rem; line-height: 1.45; flex-shrink: 0; }
    .footer-note code {
      font-family: var(--mono); background: rgba(2,6,23,0.55);
      padding: 2px 7px; border-radius: 8px; font-size: 0.9em;
    }
    .muted { color: var(--muted); }
    .tiny  { font-size: 0.81rem; }

    /* ── Light theme ── */
    html[data-theme="light"] {
      color-scheme: light;
      --bg1:      #f5f8fd; --bg2:      #e7eef9;
      --panel:    rgba(255,255,255,0.94);
      --line:     rgba(37,53,84,0.10);
      --text:     #162338; --muted:    #5c6d86;
      --accent:   #2563eb; --accent-2: #06b6d4;
      --shadow:   0 22px 48px rgba(31,41,55,0.10);
    }
    html[data-theme="light"] body {
      background:
        radial-gradient(circle at top left,  rgba(37,99,235,0.12), transparent 36%),
        radial-gradient(circle at top right, rgba(6,182,212,0.10), transparent 28%),
        linear-gradient(135deg, var(--bg1), var(--bg2));
    }
    html[data-theme="light"] .card {
      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.86));
      border-color: rgba(37,53,84,0.09);
    }
    html[data-theme="light"] .group {
      background: linear-gradient(180deg, rgba(248,251,255,0.96), rgba(242,247,253,0.90));
      border-color: rgba(37,53,84,0.08);
    }
    html[data-theme="light"] .pill { color: #0f3b57; }
    html[data-theme="light"] select,
    html[data-theme="light"] textarea,
    html[data-theme="light"] input {
      background: rgba(255,255,255,0.98); border-color: rgba(37,53,84,0.10); color: #162338;
    }
    html[data-theme="light"] .primary  { color: #fff; background: linear-gradient(135deg, #2563eb, #0ea5e9); }
    html[data-theme="light"] .secondary,
    html[data-theme="light"] .tool-btn,
    html[data-theme="light"] .attachment-chip {
      background: rgba(248,250,252,0.98); border-color: rgba(37,53,84,0.10); color: #1c2b40;
    }
    html[data-theme="light"] .chat-header,
    html[data-theme="light"] .composer {
      background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(247,250,254,0.92));
    }
    html[data-theme="light"] .reasoning-panel {
      background: linear-gradient(180deg, rgba(239,246,255,0.98), rgba(232,242,255,0.92));
      border-color: rgba(37,99,235,0.14);
    }
    html[data-theme="light"] .reasoning-panel.streaming {
      border-color: rgba(37,99,235,0.24);
      box-shadow: 0 0 0 1px rgba(37,99,235,0.05), 0 12px 28px rgba(37,99,235,0.06);
    }
    html[data-theme="light"] .reasoning-body {
      background: rgba(255,255,255,0.88);
      border-color: rgba(37,53,84,0.08);
      color: #365173;
    }
    html[data-theme="light"] .msg.user      { background: linear-gradient(135deg, rgba(37,99,235,0.12), rgba(6,182,212,0.10)); }
    html[data-theme="light"] .msg.assistant { background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,253,0.94)); }
    html[data-theme="light"] .msg.system    { background: rgba(242,246,252,0.98); color: #5b6c83; }
    html[data-theme="light"] .badge         { background: rgba(243,247,252,0.98); border-color: rgba(37,53,84,0.10); color: #5c6d86; }
    html[data-theme="light"] .badge.ok      { color: #166534; background: rgba(34,197,94,0.12);  border-color: rgba(34,197,94,0.20); }
    html[data-theme="light"] .badge.warn    { color: #92400e; background: rgba(245,158,11,0.12); border-color: rgba(245,158,11,0.20); }
    /* ═══════════════════════════════════════════════════════════════════════
       Light theme — code blocks: λευκό φόντο, πλήρης vivid token palette
       Base: Prism Solarized Light  +  custom overrides για μέγιστο χρώμα
       ═══════════════════════════════════════════════════════════════════════ */

    html[data-theme="light"] .code-block {
      background:   #eef6ff;               /* ανοιχτό γαλάζιο */
      border-color: rgba(37,99,235,0.14);
      box-shadow:   0 2px 12px rgba(37,99,235,0.07);
    }
    html[data-theme="light"] .code-toolbar {
      background:          #dbeafe;        /* blue-100 */
      border-bottom-color: rgba(37,99,235,0.12);
    }
    html[data-theme="light"] .code-language {
      color: #1e40af; letter-spacing: 0.3px;
    }
    html[data-theme="light"] .code-copy-btn {
      background:   #eff6ff;
      border-color: rgba(37,99,235,0.18);
      color:        #1e3a5f;
      box-shadow:   0 1px 3px rgba(37,99,235,0.06);
    }
    html[data-theme="light"] .code-copy-btn:hover {
      background: #dbeafe; filter: none;
    }
    html[data-theme="light"] .code-copy-btn.done  {
      color: #166534; background: rgba(34,197,94,0.13); border-color: rgba(34,197,94,0.25);
    }
    html[data-theme="light"] .code-copy-btn.error {
      color: #991b1b; background: rgba(239,68,68,0.10); border-color: rgba(239,68,68,0.25);
    }

    /* Βασικό χρώμα κειμένου */
    html[data-theme="light"] .code-pre,
    html[data-theme="light"] .code-pre code[class*="language-"] {
      color:      #1e293b;
      background: transparent !important;
    }

    html[data-theme="light"] .code-pre::-webkit-scrollbar-thumb {
      background: rgba(37,99,235,0.20);
    }

    /* ── Vivid token colours (Atom One Light inspired, more saturated) ── */

    /* Comments — readable gray, italic */
    html[data-theme="light"] .token.comment,
    html[data-theme="light"] .token.prolog,
    html[data-theme="light"] .token.doctype,
    html[data-theme="light"] .token.cdata {
      color: #93a1a1; font-style: italic;  /* Solarized base1 */
    }

    /* Keywords — vivid purple: def, class, import, if, for, return… */
    html[data-theme="light"] .token.keyword,
    html[data-theme="light"] .token.atrule,
    html[data-theme="light"] .token.rule {
      color: #7c3aed; font-weight: 600;   /* violet-600 */
    }

    /* Strings, chars, template literals — vivid green */
    html[data-theme="light"] .token.string,
    html[data-theme="light"] .token.char,
    html[data-theme="light"] .token.inserted,
    html[data-theme="light"] .token.attr-value {
      color: #16a34a;                      /* green-600 */
    }

    /* Numbers, booleans — amber/orange */
    html[data-theme="light"] .token.number,
    html[data-theme="light"] .token.boolean {
      color: #c2410c;                      /* orange-700 */
    }

    /* Functions, method names — vivid blue */
    html[data-theme="light"] .token.function,
    html[data-theme="light"] .token.function-variable {
      color: #1d4ed8;                      /* blue-700 */
    }

    /* Class names, types — pink/magenta */
    html[data-theme="light"] .token.class-name,
    html[data-theme="light"] .token.maybe-class-name,
    html[data-theme="light"] .token.builtin {
      color: #be185d;                      /* pink-700 */
    }

    /* Variables, parameters — teal */
    html[data-theme="light"] .token.variable,
    html[data-theme="light"] .token.parameter {
      color: #0f766e;                      /* teal-700 */
    }

    /* Properties — cyan/teal */
    html[data-theme="light"] .token.property {
      color: #0369a1;                      /* sky-700 */
    }

    /* Operators — dark teal */
    html[data-theme="light"] .token.operator,
    html[data-theme="light"] .token.entity,
    html[data-theme="light"] .token.url {
      color: #0891b2;                      /* cyan-600 */
    }

    /* HTML/XML tags — red */
    html[data-theme="light"] .token.tag,
    html[data-theme="light"] .token.deleted {
      color: #dc2626;                      /* red-600 */
    }

    /* HTML attribute names — purple */
    html[data-theme="light"] .token.attr-name {
      color: #9333ea;                      /* purple-600 */
    }

    /* Punctuation — dark neutral */
    html[data-theme="light"] .token.punctuation {
      color: #374151;                      /* gray-700 */
    }

    /* Regex — deep pink */
    html[data-theme="light"] .token.regex {
      color: #be185d;
    }

    /* Decorators / annotations — indigo */
    html[data-theme="light"] .token.decorator,
    html[data-theme="light"] .token.annotation {
      color: #4338ca; font-style: italic; /* indigo-700 */
    }

    /* Constants — amber */
    html[data-theme="light"] .token.constant,
    html[data-theme="light"] .token.symbol {
      color: #b45309;                      /* amber-700 */
    }

    html[data-theme="light"] .token.important,
    html[data-theme="light"] .token.bold   { font-weight: bold; }
    html[data-theme="light"] .token.italic { font-style: italic; }
    html[data-theme="light"] .token.namespace { opacity: 0.75; }

    /* JSON keys (property inside object) */
    html[data-theme="light"] .language-json .token.property {
      color: #1d4ed8;
    }

    /* SQL keywords */
    html[data-theme="light"] .language-sql .token.keyword {
      color: #7c3aed; font-weight: 700;
    }

    /* Bash builtins & variables */
    html[data-theme="light"] .language-bash .token.function { color: #1d4ed8; }
    html[data-theme="light"] .language-bash .token.variable { color: #0f766e; }

    /* ── Inline code & footer code ── */
    html[data-theme="light"] .code-inline {
      background:   #eef1f7;
      border-color: rgba(37,53,84,0.13);
      color:        #c7254e;
    }
    html[data-theme="light"] .footer-note code {
      background: rgba(229,237,248,0.88); color: #0550ae;
    }
    html[data-theme="light"] .msg-body .md-h1,
    html[data-theme="light"] .msg-body .md-h2,
    html[data-theme="light"] .msg-body .md-h3 { color: #1d4ed8; }
    html[data-theme="light"] .msg-body .md-bq { border-left-color: #2563eb; background: rgba(37,99,235,0.06); }
    html[data-theme="light"] .msg-body strong { color: #162338; }
    html[data-theme="light"] .msg-body em     { color: #334155; }
    html[data-theme="light"] .param-label  { color: var(--muted); }
    html[data-theme="light"] .param-value  { color: var(--accent); }
    html[data-theme="light"] input[type="range"] {
      background: rgba(37,53,84,0.15);
    }
    html[data-theme="light"] .scroll-to-bottom { box-shadow: 0 6px 20px rgba(37,53,84,0.2); }

    /* ── Responsive ── */
    @media (max-width: 1100px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { height: unset; position: static; max-height: none; overflow-y: visible; }
      .chat-panel { height: 75vh; }
      .msg { max-width: 100%; }
    }
    @media (max-width: 600px) {
      body { padding: 10px; }
      .app { gap: 12px; }
      .chat-panel { height: 65vh; }
      .composer textarea { min-height: 100px; height: 100px; }
    }
  </style>
</head>
<body>

  <div class="drop-overlay" id="dropOverlay">📂 Άσε τα αρχεία εδώ</div>

  <div class="app">

    <!-- ── Sidebar ────────────────────────────────────────────────── -->
    <aside class="sidebar card">
      <div class="title">
        <h1>☁️ __APP_TITLE__</h1>
        <div class="pill">v3.0</div>
      </div>

      <div class="group">
        <label class="label" for="modelSelect">Μοντέλο Ollama</label>
        <input id="modelSearchInput" type="search" placeholder="Αναζήτηση μοντέλου..."
               title="Γράψε για φιλτράρισμα της λίστας μοντέλων" style="margin-bottom:8px;" />
        <select id="modelSelect" title="Επίλεξε cloud model"></select>
        <div class="tiny muted" style="margin-top:8px;">
          Η λίστα ανακτά τα ακριβή model names του official Ollama direct API catalog από το διαδίκτυο.
          Η αναζήτηση φιλτράρει τη λίστα χωρίς να επηρεάζει τη φόρτωση των μοντέλων.
        </div>
      </div>

      <div class="group">
        <label class="label" for="modelSortSelect">Ταξινόμηση μοντέλων</label>
        <select id="modelSortSelect" title="Επίλεξε κριτήριο αξιολόγησης για ταξινόμηση μοντέλων">
          <option value="overall">Overall / Καλύτερο συνολικά</option>
          <option value="coding">Coding / Προγραμματισμός</option>
          <option value="reasoning">Reasoning / Σκέψη</option>
          <option value="context">Long Context / Max Length</option>
          <option value="vision">Vision / Εικόνες</option>
          <option value="speed">Speed / Ταχύτητα</option>
          <option value="newest">Newest / Πιο νέο</option>
        </select>
        <div class="tiny muted" style="margin-top:8px;">
          Η κατάταξη γίνεται ευρετικά από metadata του direct catalog και model details, όπως context length,
          capabilities, μέγεθος μοντέλου και πρόσφατη ενημέρωση.
        </div>
      </div>

      <div class="group">
        <label class="label" for="thinkModeSelect">Thinking Mode</label>
        <select id="thinkModeSelect" title="Ρύθμιση thinking/reasoning mode του μοντέλου">
          <option value="auto">Auto</option>
          <option value="on" selected>On</option>
          <option value="off">Off</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
        <div class="tiny muted" style="margin-top:8px;">
          Για thinking-capable models εμφανίζεται realtime η σκέψη. Στο GPT-OSS τα επίπεδα <code>low/medium/high</code> είναι προτιμότερα.
        </div>
      </div>

      <div class="group">
        <label class="label" for="ensembleModeSelect">Dual Model Ensemble</label>
        <select id="ensembleModeSelect" title="Επίλεξε λειτουργία dual model ensemble">
          <option value="off">Off</option>
          <option value="auto" selected>Auto</option>
          <option value="manual">Manual</option>
        </select>
        <input id="helperSearchInput" type="search" placeholder="Αναζήτηση helper model..."
               title="Γράψε για φιλτράρισμα της λίστας helper models" style="margin-top:8px; margin-bottom:8px;" />
        <select id="helperModelSelect" title="Επίλεξε βοηθητικό μοντέλο" disabled></select>
        <div class="tiny muted" id="ensembleModeInfo" style="margin-top:8px;">
          Off: μόνο το κύριο μοντέλο. Auto: αυτόματη επιλογή helper model. Manual: διαλέγεις εσύ το δεύτερο μοντέλο από τη λίστα.
        </div>
      </div>

      <div class="group">
        <label class="label" for="apiKeyInput">Ollama API Key</label>
        <input id="apiKeyInput" type="password" placeholder="ollama_..." autocomplete="off"
               title="API key για direct Ollama Cloud API" />
        <div class="btn-row" style="margin-top:10px;">
          <button class="primary" id="saveApiKeyBtn" title="Αποθήκευση API key σε αρχείο ρυθμίσεων">💾 Save Key</button>
          <button class="secondary" id="clearApiKeyBtn" title="Καθαρισμός αποθηκευμένου API key">🗑 Clear Key</button>
        </div>
        <div class="tiny muted" id="apiKeyInfo" style="margin-top:8px;">
          Το API key αποθηκεύεται σε τοπικό αρχείο ρυθμίσεων δίπλα στο .py.
        </div>
      </div>

      <div class="group">
        <label class="label" for="systemPrompt">System Prompt</label>
        <textarea id="systemPrompt" title="System prompt της συνεδρίας">__SYSTEM_PROMPT__</textarea>
        <div class="tiny muted" style="margin-top:6px;">
          Αλλάζει μόνο για τη συνεδρία. Χρησιμοποιείται το embedded default αν είναι κενό.
        </div>
      </div>

      <div class="group">
        <label class="label" for="fileInput">Αρχεία (ή drag & drop)</label>
        <input id="fileInput" type="file" multiple accept="__ACCEPTED_TYPES__"
               title="Επίλεξε αρχεία για context" />
        <div class="attachment-list" id="selectedFiles"></div>
        <div class="btn-row" style="margin-top:10px;">
          <button class="secondary" id="clearFilesBtn"    title="Αφαίρεση επιλεγμένων αρχείων">📎 Καθαρισμός</button>
          <button class="primary"   id="refreshModelsBtn" title="Ανάκτηση τελευταίας λίστας cloud models">🔄 Refresh Models</button>
        </div>
        <ul class="support-list">
          <li>Drag &amp; Drop υποστηρίζεται παντού.</li>
          <li>Εικόνες → natively σε vision models.</li>
          <li>TXT, PY, MD, JSON, CSV, PDF κ.ά. → context.</li>
        </ul>
      </div>

      <div class="group">
        <div class="label">⚙️ Παράμετροι μοντέλου</div>

        <div class="param-row">
          <span class="param-label" title="Δημιουργικότητα απάντησης (0=ντετερμινιστικό, 2=πολύ τυχαίο)">Temperature</span>
          <input type="range" id="paramTemp" min="0" max="2" step="0.05" value="0.8"
                 title="Temperature: 0 – 2" />
          <span class="param-value" id="paramTempVal">0.80</span>
        </div>

        <div class="param-row">
          <span class="param-label" title="Nucleus sampling: διατηρεί tokens που καλύπτουν το X% της πιθανότητας">Top-P</span>
          <input type="range" id="paramTopP" min="0.01" max="1" step="0.01" value="0.9"
                 title="Top-P: 0.01 – 1.00" />
          <span class="param-value" id="paramTopPVal">0.90</span>
        </div>

        <div class="param-row" style="align-items:flex-start; flex-direction:column; gap:6px;">
          <span class="param-label" title="Seed για αναπαραγώγιμα αποτελέσματα (-1 = τυχαίο)">Seed</span>
          <div class="param-seed-wrap" style="width:100%;">
            <input type="text" id="paramSeed" value="-1" placeholder="-1 (τυχαίο)"
                   title="Seed: αριθμός ≥ 0 για αναπαραγώγιμο, -1 για τυχαίο" />
            <button class="secondary" id="resetParamsBtn" style="padding:8px 10px; font-size:0.8rem; white-space:nowrap;"
                    title="Επαναφορά προεπιλεγμένων παραμέτρων">↺ Reset</button>
          </div>
        </div>

        <div class="param-row" style="align-items:flex-start; flex-direction:column; gap:6px;">
          <span class="param-label" title="Μέγιστο context / max length (num_ctx) για το επιλεγμένο μοντέλο">Max Length (num_ctx)</span>
          <div class="param-seed-wrap" style="width:100%;">
            <input type="number" id="paramNumCtx" min="256" step="256" value="" placeholder="κενό = auto / default"
                   title="Context window / max length για το επιλεγμένο μοντέλο" />
            <button class="secondary" id="clearNumCtxBtn" style="padding:8px 10px; font-size:0.8rem; white-space:nowrap;"
                    title="Καθαρισμός custom max length για το τρέχον μοντέλο">Auto</button>
          </div>
          <div class="tiny muted" id="paramNumCtxInfo">Ισχύει ξεχωριστά για κάθε μοντέλο.</div>
        </div>
      </div>

      <div class="group">
        <div class="label">Κατάσταση</div>
        <div id="modelInfo" class="muted tiny">Φόρτωση λίστας μοντέλων...</div>
      </div>

      <div class="btn-row">
        <button class="secondary" id="resetSystemPromptBtn" title="Επαναφορά default system prompt">🧠 Reset Prompt</button>
        <button class="secondary" id="clearChatBtn"         title="Καθαρισμός chat και uploads">🧹 Clear Chat</button>
      </div>
      <div class="btn-row">
        <button class="secondary" id="reloadSessionBtn"    title="Επαναφόρτωση ιστορικού από server">♻️ Reload Session</button>
        <button class="secondary" id="copySystemPromptBtn" title="Αντιγραφή system prompt στο clipboard">📋 Copy Prompt</button>
      </div>
      <div class="btn-row">
        <button class="secondary" id="exportChatBtn"  title="Εξαγωγή συνομιλίας ως Markdown αρχείο">💾 Export .md</button>
        <button class="secondary" id="autoScrollBtn"  title="Ενεργοποίηση/απενεργοποίηση αυτόματης κύλισης">📜 Auto-Scroll: ON</button>
      </div>

      <button class="secondary btn-full" id="themeToggleBtn" title="Εναλλαγή dark/light theme">☀️ Light Theme</button>

      <div class="footer-note">
        Direct Cloud API: βάλε το API key στο πεδίο του GUI και πάτησε <b>Save Key</b> ή όρισε <code>OLLAMA_API_KEY</code><br><br>
        Settings file: <code>ollama_cloud_chat_settings.json</code> δίπλα στο .py<br><br>
        Εκτέλεση: <code>python ollama_cloud_chat.py [--port N] [--no-browser]</code><br><br>
        <span style="display:block; margin-top:10px; padding-top:10px; border-top:1px solid var(--line); opacity:0.85; font-size:0.9rem; text-align:center; letter-spacing:0.3px;">&copy; Ευάγγελος Πεφάνης</span>
      </div>
    </aside>

    <!-- ── Chat panel ─────────────────────────────────────────────── -->
    <main class="chat-panel card">
      <div class="chat-header">
        <div class="header-left">
          <h2>Συνομιλία</h2>
          <div class="tiny muted">Enter αποστολή · Shift+Enter νέα γραμμή · Ctrl+Enter εναλλακτικό</div>
        </div>
        <div class="status-wrap">
          <span class="badge" id="backendBadge"       title="Κατάσταση direct Ollama Cloud API">⬤ Cloud API</span>
          <span class="badge" id="msgCountBadge">0 μηνύματα</span>
          <span class="badge" id="selectedModelBadge">Μοντέλο: -</span>
          <span class="badge" id="sourceBadge">Πηγή: -</span>
          <span class="badge" id="tokensPerSecBadge"  title="Ταχύτητα τελευταίας απάντησης" style="display:none;"></span>
          <span class="badge" id="streamBadge">Έτοιμο</span>
        </div>
      </div>

      <div class="reasoning-panel" id="reasoningPanel" aria-live="polite">
        <div class="reasoning-head">
          <div class="reasoning-title-wrap">
            <div class="reasoning-title">🧠 <span>Realtime βαθιά σκέψη</span></div>
            <div class="reasoning-meta" id="reasoningMeta">Αναμονή για thinking stream…</div>
          </div>
          <button class="secondary reasoning-toggle-btn" id="toggleReasoningBtn" title="Εμφάνιση ή απόκρυψη του panel σκέψης">🙈 Απόκρυψη</button>
        </div>
        <pre class="reasoning-body" id="reasoningContent"></pre>
      </div>

      <div class="messages-wrap">
        <div class="messages" id="messages">
          <div class="empty-state" id="emptyState">
            <h3 style="margin-top:0;">Έτοιμο για συνομιλία</h3>
            <div>Γράψε το δικό σου prompt και, αν θέλεις, πρόσθεσε αρχεία για context.</div>
            <div style="margin-top:10px;" class="tiny">
              Enter αποστολή · Shift+Enter νέα γραμμή · Ctrl+Enter εναλλακτικό
            </div>
          </div>
        </div>
        <button class="scroll-to-bottom" id="scrollToBottomBtn" title="Μετάβαση στο τέλος">↓ Τέλος</button>
      </div>

      <div class="composer">
        <textarea id="userInput" placeholder="Γράψε εδώ το user prompt σου…"
                  title="User prompt — Enter αποστολή, Shift+Enter νέα γραμμή, Ctrl+Enter εναλλακτικό"></textarea>
        <div class="composer-footer">
          <div class="composer-left">
            <span class="char-counter" id="charCounter">0 χαρ. / 0 λέξεις</span>
            <span class="helper" id="helperText">Enter · Shift+Enter · Ctrl+Enter</span>
          </div>
          <div class="composer-right">
            <button class="secondary" id="stopBtn" disabled title="Διακοπή streaming">⏹ Stop</button>
            <button class="primary"   id="sendBtn"          title="Αποστολή μηνύματος (Enter)">🚀 Αποστολή</button>
          </div>
        </div>
      </div>
    </main>

  </div><!-- /.app -->

  <script>
    "use strict";

    // ── Constants ────────────────────────────────────────────────────────────
    const DEFAULT_SYSTEM_PROMPT  = __DEFAULT_SYSTEM_PROMPT_JSON__;
    const THEME_KEY              = "ollama_chat_theme_v2";
    const MODEL_KEY              = "ollama_chat_model_v2";
    const PARAMS_KEY             = "ollama_chat_params_v2";
    const MODEL_SORT_KEY         = "ollama_chat_model_sort_v1";
    const ENSEMBLE_KEY           = "ollama_chat_ensemble_auto_v1";
    const ENSEMBLE_MODE_KEY      = "ollama_chat_ensemble_mode_v2";
    const ENSEMBLE_HELPER_KEY    = "ollama_chat_ensemble_helper_v1";
    const CHAR_WARN              = 8000;
    const DEFAULT_HELPER         = "Enter · Shift+Enter · Ctrl+Enter";
    const HEALTH_POLL_MS         = 15_000;  // polling interval για cloud API status
    const MODEL_REFRESH_POLL_MS  = 400;
    const BROWSER_SESSION_KEY    = "ollama_chat_browser_session_v1";
    const BROWSER_HEARTBEAT_MS   = 10_000;

    // ── App state ────────────────────────────────────────────────────────────
    const state = {
      isStreaming:            false,
      abortController:        null,
      currentAssistantNode:   null,
      currentThinkingText:    "",
      reasoningPanelVisible:  false,
      reasoningAutoOpen:      false,
      reasoningUserCollapsed: false,
      currentInlineThinkingOpen: true,
      reasoningStreamCompleted: false,
      models:                 [],
      selectedFiles:          [],
      theme:                  "dark",
      autoScroll:             true,
      chatHistory:            [],  // [{role, content, time}] — for export
      msgCount:               0,
      dragCounter:            0,   // reliable drag-leave detection
      lastTokensPerSec:       null,
      modelNumCtxByModel:     {},
      modelMaxNumCtxByModel:  {},
      modelMetaByModel:       {},
      modelDetailRequests:    {},
      helperModels:           [],
      ensembleMode:           "auto",
      modelSortCriterion:     "overall",
      lastModelsRefreshTs:    0,
      browserSessionId:       "",
      browserHeartbeatTimer:   null,
    };

    // ── DOM refs ─────────────────────────────────────────────────────────────
    const els = {
      modelSearchInput:     document.getElementById("modelSearchInput"),
      modelSelect:          document.getElementById("modelSelect"),
      modelSortSelect:      document.getElementById("modelSortSelect"),
      thinkModeSelect:      document.getElementById("thinkModeSelect"),
      ensembleModeSelect:   document.getElementById("ensembleModeSelect"),
      helperSearchInput:    document.getElementById("helperSearchInput"),
      helperModelSelect:    document.getElementById("helperModelSelect"),
      ensembleModeInfo:     document.getElementById("ensembleModeInfo"),
      systemPrompt:         document.getElementById("systemPrompt"),
      fileInput:            document.getElementById("fileInput"),
      selectedFiles:        document.getElementById("selectedFiles"),
      refreshModelsBtn:     document.getElementById("refreshModelsBtn"),
      clearFilesBtn:        document.getElementById("clearFilesBtn"),
      resetSystemPromptBtn: document.getElementById("resetSystemPromptBtn"),
      copySystemPromptBtn:  document.getElementById("copySystemPromptBtn"),
      exportChatBtn:        document.getElementById("exportChatBtn"),
      autoScrollBtn:        document.getElementById("autoScrollBtn"),
      themeToggleBtn:       document.getElementById("themeToggleBtn"),
      clearChatBtn:         document.getElementById("clearChatBtn"),
      reloadSessionBtn:     document.getElementById("reloadSessionBtn"),
      modelInfo:            document.getElementById("modelInfo"),
      msgCountBadge:        document.getElementById("msgCountBadge"),
      selectedModelBadge:   document.getElementById("selectedModelBadge"),
      sourceBadge:          document.getElementById("sourceBadge"),
      streamBadge:          document.getElementById("streamBadge"),
      backendBadge:         document.getElementById("backendBadge"),
      tokensPerSecBadge:    document.getElementById("tokensPerSecBadge"),
      reasoningPanel:       document.getElementById("reasoningPanel"),
      reasoningMeta:        document.getElementById("reasoningMeta"),
      reasoningContent:     document.getElementById("reasoningContent"),
      toggleReasoningBtn:   document.getElementById("toggleReasoningBtn"),
      messages:             document.getElementById("messages"),
      userInput:            document.getElementById("userInput"),
      sendBtn:              document.getElementById("sendBtn"),
      stopBtn:              document.getElementById("stopBtn"),
      helperText:           document.getElementById("helperText"),
      charCounter:          document.getElementById("charCounter"),
      dropOverlay:          document.getElementById("dropOverlay"),
      scrollToBottomBtn:    document.getElementById("scrollToBottomBtn"),
      // Model parameters
      paramTemp:            document.getElementById("paramTemp"),
      paramTempVal:         document.getElementById("paramTempVal"),
      paramTopP:            document.getElementById("paramTopP"),
      paramTopPVal:         document.getElementById("paramTopPVal"),
      paramSeed:            document.getElementById("paramSeed"),
      paramNumCtx:          document.getElementById("paramNumCtx"),
      paramNumCtxInfo:      document.getElementById("paramNumCtxInfo"),
      clearNumCtxBtn:       document.getElementById("clearNumCtxBtn"),
      resetParamsBtn:       document.getElementById("resetParamsBtn"),
      apiKeyInput:          document.getElementById("apiKeyInput"),
      apiKeyInfo:           document.getElementById("apiKeyInfo"),
      saveApiKeyBtn:        document.getElementById("saveApiKeyBtn"),
      clearApiKeyBtn:       document.getElementById("clearApiKeyBtn"),
    };

    // ── Utilities ────────────────────────────────────────────────────────────

    function nowString() {
      return new Date().toLocaleTimeString("el-GR", {
        hour: "2-digit", minute: "2-digit", second: "2-digit"
      });
    }

    function escapeHtml(text) {
      return String(text || "")
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function setButtonFeedback(btn, successText, defaultText, cls = "done") {
      btn.textContent = successText;
      btn.classList.remove("done", "error");
      btn.classList.add(cls);
      setTimeout(() => { btn.textContent = defaultText; btn.classList.remove("done", "error"); }, 1500);
    }

    function countWords(text) {
      return text.trim() ? text.trim().split(/\s+/).length : 0;
    }

    // ── Model parameters ─────────────────────────────────────────────────────

    const DEFAULT_PARAMS = { temperature: 0.8, top_p: 0.9, seed: -1 };

    function normalizeNumCtxValue(rawValue) {
      const text = String(rawValue ?? "").trim();
      if (!text) return null;
      const value = parseInt(text, 10);
      if (!Number.isFinite(value)) return null;
      if (value < 256 || value > 1048576) return null;
      return value;
    }

    function getSelectedModelKey() {
      return String(els.modelSelect.value || "").trim();
    }

    function syncNumCtxInputForSelectedModel() {
      const model = getSelectedModelKey();
      const saved = model ? state.modelNumCtxByModel[model] : null;
      const maxFromServer = model ? state.modelMaxNumCtxByModel[model] : null;
      const effective = saved != null ? saved : maxFromServer;
      if (els.paramNumCtx) {
        els.paramNumCtx.value = effective != null ? String(effective) : "";
        if (maxFromServer != null) {
          els.paramNumCtx.placeholder = String(maxFromServer);
        } else {
          els.paramNumCtx.placeholder = "ανάκτηση Max Length...";
        }
      }
      if (els.paramNumCtxInfo) {
        const label = model || "-";
        let shown = "Ανάκτηση metadata...";
        let modeLabel = "φόρτωση";
        if (saved != null) {
          shown = `${saved.toLocaleString("el-GR")} tokens`;
          modeLabel = "προσαρμοσμένο";
        } else if (maxFromServer != null) {
          shown = `${maxFromServer.toLocaleString("el-GR")} tokens`;
          modeLabel = "πραγματικό μέγιστο μοντέλου";
        }
        els.paramNumCtxInfo.textContent = `Μοντέλο: ${label} · Max Length: ${shown} · ${modeLabel}`;
      }
      if (model && maxFromServer == null) {
        ensureSelectedModelMeta(model);
      }
    }

    function getModelOptions() {
      const temperature = parseFloat(els.paramTemp.value);
      const top_p       = parseFloat(els.paramTopP.value);
      const seedRaw     = els.paramSeed.value.trim();
      const seed        = parseInt(seedRaw, 10);
      const numCtx      = normalizeNumCtxValue(els.paramNumCtx ? els.paramNumCtx.value : "");
      const opts = {};
      if (!isNaN(temperature)) opts.temperature = temperature;
      if (!isNaN(top_p))       opts.top_p       = top_p;
      if (!isNaN(seed) && seed >= 0) opts.seed  = seed;
      if (numCtx != null)      opts.num_ctx     = numCtx;
      return opts;
    }

    function saveParams() {
      try {
        localStorage.setItem(PARAMS_KEY, JSON.stringify({
          temperature: els.paramTemp.value,
          top_p:       els.paramTopP.value,
          seed:        els.paramSeed.value,
          num_ctx_by_model: state.modelNumCtxByModel,
        }));
      } catch (_) {}
    }

    function loadParams() {
      try {
        const saved = JSON.parse(localStorage.getItem(PARAMS_KEY) || "null");
        state.modelNumCtxByModel = (saved && saved.num_ctx_by_model && typeof saved.num_ctx_by_model === "object")
          ? saved.num_ctx_by_model
          : {};
        if (!saved) {
          syncNumCtxInputForSelectedModel();
          return;
        }
        if (saved.temperature != null) {
          els.paramTemp.value    = saved.temperature;
          els.paramTempVal.textContent = Number(saved.temperature).toFixed(2);
        }
        if (saved.top_p != null) {
          els.paramTopP.value    = saved.top_p;
          els.paramTopPVal.textContent = Number(saved.top_p).toFixed(2);
        }
        if (saved.seed != null) {
          els.paramSeed.value    = saved.seed;
        }
        syncNumCtxInputForSelectedModel();
      } catch (_) {
        state.modelNumCtxByModel = {};
        syncNumCtxInputForSelectedModel();
      }
    }

    function clearNumCtxForCurrentModel(showNotice = true) {
      const model = getSelectedModelKey();
      if (model && Object.prototype.hasOwnProperty.call(state.modelNumCtxByModel, model)) {
        delete state.modelNumCtxByModel[model];
      }
      syncNumCtxInputForSelectedModel();
      saveParams();
      if (showNotice && model) {
        renderSystemNotice(`Το Max Length του μοντέλου ${model} επανήλθε στο πραγματικό μέγιστο context του cloud tag.`);
      }
    }

    function updateCurrentModelNumCtxFromInput() {
      const model = getSelectedModelKey();
      if (!model || !els.paramNumCtx) return;
      const normalized = normalizeNumCtxValue(els.paramNumCtx.value);
      if (normalized == null) {
        delete state.modelNumCtxByModel[model];
        if (els.paramNumCtx.value.trim()) {
          els.paramNumCtx.value = "";
        }
      } else {
        state.modelNumCtxByModel[model] = normalized;
        els.paramNumCtx.value = String(normalized);
      }
      syncNumCtxInputForSelectedModel();
      saveParams();
    }

    function resetParams() {
      els.paramTemp.value          = DEFAULT_PARAMS.temperature;
      els.paramTempVal.textContent = DEFAULT_PARAMS.temperature.toFixed(2);
      els.paramTopP.value          = DEFAULT_PARAMS.top_p;
      els.paramTopPVal.textContent = DEFAULT_PARAMS.top_p.toFixed(2);
      els.paramSeed.value          = DEFAULT_PARAMS.seed;
      clearNumCtxForCurrentModel(false);
      saveParams();
      renderSystemNotice("Παράμετροι μοντέλου επαναφέρθηκαν στις προεπιλογές.");
    }

    // Live update labels as sliders move
    els.paramTemp.addEventListener("input", () => {
      els.paramTempVal.textContent = Number(els.paramTemp.value).toFixed(2);
      saveParams();
    });
    els.paramTopP.addEventListener("input", () => {
      els.paramTopPVal.textContent = Number(els.paramTopP.value).toFixed(2);
      saveParams();
    });
    els.paramSeed.addEventListener("change", saveParams);
    if (els.paramNumCtx) {
      els.paramNumCtx.addEventListener("change", updateCurrentModelNumCtxFromInput);
      els.paramNumCtx.addEventListener("blur", updateCurrentModelNumCtxFromInput);
    }
    if (els.clearNumCtxBtn) {
      els.clearNumCtxBtn.addEventListener("click", () => clearNumCtxForCurrentModel(true));
    }
    // ── Cloud API health polling ────────────────────────────────────────────────

    async function pollBackendHealth() {
      try {
        const resp = await fetch("/api/health");
        const data = await resp.json();
        if (data.cloud_api_configured) {
          els.backendBadge.textContent = "⬤ Cloud API: OK";
          els.backendBadge.className   = "badge ok";
          const keySource = data.api_key_source || "configured";
          els.backendBadge.title       = `Direct mode · API key source: ${keySource} · uptime ${Math.round(data.server_uptime_sec)}s`;
        } else {
          els.backendBadge.textContent = "⬤ Cloud API: KEY";
          els.backendBadge.className   = "badge err";
          els.backendBadge.title       = "Λείπει το Ollama Cloud API key από GUI/settings file ή OLLAMA_API_KEY";
        }
      } catch (_) {
        els.backendBadge.textContent = "⬤ Cloud API: ?";
        els.backendBadge.className   = "badge warn";
      }
    }

    function maskApiKey(value) {
      const key = String(value || "");
      if (!key) return "";
      if (key.length <= 10) return key[0] + "•".repeat(Math.max(0, key.length - 2)) + key.slice(-1);
      return key.slice(0, 4) + "•".repeat(Math.max(0, key.length - 8)) + key.slice(-4);
    }

    function setApiKeyInfo(message, tone = "") {
      if (!els.apiKeyInfo) return;
      els.apiKeyInfo.textContent = message;
      els.apiKeyInfo.className = `tiny ${tone === "error" ? "warn" : "muted"}`;
    }

    async function loadAppConfig() {
      try {
        const resp = await fetch("/api/app-config");
        const data = await resp.json();
        const key = String(data.ollama_api_key || "");
        if (els.apiKeyInput) els.apiKeyInput.value = key;
        if (data.has_ollama_api_key) {
          const updated = data.updated_at ? ` · αποθήκευση ${data.updated_at}` : "";
          setApiKeyInfo(`API key φορτώθηκε από settings file (${maskApiKey(key)})${updated}`);
        } else {
          setApiKeyInfo("Δεν υπάρχει αποθηκευμένο API key στο settings file.");
        }
      } catch (_) {
        setApiKeyInfo("Αποτυχία φόρτωσης settings αρχείου.", "error");
      }
    }

    async function saveApiKey() {
      try {
        const key = String((els.apiKeyInput && els.apiKeyInput.value) || "").trim();
        const resp = await fetch("/api/app-config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ollama_api_key: key }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
        if (els.apiKeyInput) els.apiKeyInput.value = String((data.config && data.config.ollama_api_key) || key || "");
        const masked = maskApiKey((data.config && data.config.ollama_api_key) || key);
        const updated = data.config && data.config.updated_at ? ` · ${data.config.updated_at}` : "";
        setApiKeyInfo(key ? `API key αποθηκεύτηκε (${masked})${updated}` : `Το αποθηκευμένο API key καθαρίστηκε.${updated}`);
        await pollBackendHealth();
        if (key) renderSystemNotice("Αποθηκεύτηκε το Ollama API key στο settings file.");
        else renderSystemNotice("Καθαρίστηκε το αποθηκευμένο Ollama API key από το settings file.");
      } catch (err) {
        const msg = err && err.message ? err.message : String(err);
        setApiKeyInfo(`Σφάλμα αποθήκευσης API key: ${msg}`, "error");
        renderSystemNotice(`Σφάλμα αποθήκευσης API key: ${msg}`);
      }
    }

    async function clearApiKey() {
      if (els.apiKeyInput) els.apiKeyInput.value = "";
      await saveApiKey();
    }

    // ── Tokens/sec display ───────────────────────────────────────────────────

    function estimateLiveTokenCount(text) {
      const src = String(text || "");
      if (!src.trim()) return 0;
      const words = src.match(/[\p{L}\p{N}_]+/gu) || [];
      const punct = src.match(/[^\s\p{L}\p{N}_]/gu) || [];
      return words.length + punct.length;
    }

    function showLiveTokenStats(currentText, streamStartMs, phaseLabel = "Generating") {
      if (!els.tokensPerSecBadge) return;
      const elapsedMs = Math.max(1, Date.now() - Number(streamStartMs || Date.now()));
      const elapsedSec = elapsedMs / 1000;
      if (elapsedSec < 0.08) return;

      const estimatedTokens = estimateLiveTokenCount(currentText);
      if (estimatedTokens <= 0) return;

      const liveTps = estimatedTokens / elapsedSec;
      els.tokensPerSecBadge.textContent = `⚡ ${liveTps.toFixed(1)} tok/s`;
      els.tokensPerSecBadge.className   = "badge";
      els.tokensPerSecBadge.title       = [
        `Live tok/s όσο γίνεται πιο κοντά στο πραγματικό κατά τη ροή`,
        `Phase: ${phaseLabel}`,
        `Estimated streamed tokens: ${estimatedTokens}`,
        `Elapsed: ${elapsedSec.toFixed(2)}s`,
        `Στο τέλος γίνεται reconcile με τα επίσημα eval_count / eval_duration του Ollama.`,
      ].join(" · ");
      els.tokensPerSecBadge.style.display = "";
    }

    function showTokenStats(tokenStats) {
      if (!tokenStats || !els.tokensPerSecBadge) return;
      const tps = Number(tokenStats.tokens_per_sec || 0);
      const tokens = Number(tokenStats.eval_count || 0);
      const promptTps = tokenStats.prompt_tokens_per_sec != null
        ? Number(tokenStats.prompt_tokens_per_sec)
        : null;
      const totalTps = tokenStats.end_to_end_tokens_per_sec != null
        ? Number(tokenStats.end_to_end_tokens_per_sec)
        : null;

      els.tokensPerSecBadge.textContent = `⚡ ${tps.toFixed(1)} tok/s`;
      els.tokensPerSecBadge.className   = "badge ok";
      els.tokensPerSecBadge.title       = [
        `Πραγματικό output speed: ${tps.toFixed(1)} tok/s`,
        `Output tokens: ${tokens}`,
        promptTps != null ? `Prompt speed: ${promptTps.toFixed(1)} tok/s` : null,
        totalTps != null ? `End-to-end speed: ${totalTps.toFixed(1)} tok/s` : null,
      ].filter(Boolean).join(" · ");
      els.tokensPerSecBadge.style.display = "";
      state.lastTokensPerSec = tps;
    }

    function hideTokenStats() {
      if (els.tokensPerSecBadge) els.tokensPerSecBadge.style.display = "none";
    }

    // ── Markdown renderer ─────────────────────────────────────────────────────

    /**
     * Inline markdown: escapes HTML first, then applies inline formatting.
     * Order matters: bold before italic to avoid greedy single-* matching.
     */
    function inlineMarkdown(text) {
      text = escapeHtml(text);
      text = text.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
      text = text.replace(/__(.+?)__/g,     "<strong>$1</strong>");
      text = text.replace(/\*([^*\n]+?)\*/g,            "<em>$1</em>");
      text = text.replace(/(?<!\w)_([^_\n]+?)_(?!\w)/g, "<em>$1</em>");
      text = text.replace(/~~(.+?)~~/g,  "<del>$1</del>");
      text = text.replace(/`([^`\n]+)`/g, '<span class="code-inline">$1</span>');
      text = text.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>'
      );
      return text;
    }

    /**
     * Block markdown for a text segment (no code fences — those are handled separately).
     */
    function markdownToHtml(rawText) {
      const lines = rawText.split("\n");
      const out   = [];
      let inUl = false, inOl = false, inBq = false;

      const closeUl  = () => { if (inUl) { out.push("</ul>");          inUl = false; } };
      const closeOl  = () => { if (inOl) { out.push("</ol>");          inOl = false; } };
      const closeBq  = () => { if (inBq) { out.push("</blockquote>"); inBq = false; } };
      const closeLists = () => { closeUl(); closeOl(); };

      for (const line of lines) {

        // Heading  # … ######
        const hm = line.match(/^(#{1,6})\s+(.*)/);
        if (hm) {
          closeLists(); closeBq();
          const lvl = hm[1].length;
          out.push(`<h${lvl} class="md-h${lvl}">${inlineMarkdown(hm[2])}</h${lvl}>`);
          continue;
        }

        // Horizontal rule  --- / *** / ___
        if (/^(\s*[-*_]){3,}\s*$/.test(line) && line.trim().length >= 3) {
          closeLists(); closeBq();
          out.push('<hr class="md-hr" />');
          continue;
        }

        // Blockquote  > ...
        const bm = line.match(/^>\s?(.*)/);
        if (bm) {
          closeLists();
          if (!inBq) { out.push('<blockquote class="md-bq">'); inBq = true; }
          out.push(`<p>${inlineMarkdown(bm[1])}</p>`);
          continue;
        }
        closeBq();

        // Unordered list  - * +
        const um = line.match(/^[-*+]\s+(.*)/);
        if (um) {
          closeOl();
          if (!inUl) { out.push('<ul class="md-list">'); inUl = true; }
          out.push(`<li>${inlineMarkdown(um[1])}</li>`);
          continue;
        }

        // Ordered list  1. 2. …
        const om = line.match(/^\d+\.\s+(.*)/);
        if (om) {
          closeUl();
          if (!inOl) { out.push('<ol class="md-list">'); inOl = true; }
          out.push(`<li>${inlineMarkdown(om[1])}</li>`);
          continue;
        }

        closeLists();

        // Empty line
        if (!line.trim()) { out.push('<div class="md-br"></div>'); continue; }

        // Normal paragraph
        out.push(`<p class="md-p">${inlineMarkdown(line)}</p>`);
      }

      closeLists(); closeBq();
      return out.join("\n");
    }

    // ── Message rendering ─────────────────────────────────────────────────────

    /**
     * Εξάγει <think>...</think> blocks, code fences και plain text.
     * Τύποι parts: "think" | "code" | "text"
     * Τα think blocks εμφανίζονται ως collapsible details element.
     */
    function parseMessageParts(sourceText) {
      const parts  = [];
      const text   = String(sourceText || "");
      let   cursor = 0;

      while (cursor < text.length) {
        // ── <think> block detection ──────────────────────────────────────────
        const thinkStart = text.indexOf("<think>", cursor);
        const fenceStart = text.indexOf("```",    cursor);

        // Determine which comes first
        const nextThink = thinkStart >= 0 ? thinkStart : Infinity;
        const nextFence = fenceStart >= 0 ? fenceStart : Infinity;

        if (nextThink === Infinity && nextFence === Infinity) {
          // Only plain text remains
          const rem = text.slice(cursor);
          if (rem) parts.push({ type: "text", content: rem });
          break;
        }

        if (nextThink < nextFence) {
          // <think> comes first
          const before = text.slice(cursor, thinkStart);
          if (before) parts.push({ type: "text", content: before });

          const thinkEnd = text.indexOf("</think>", thinkStart + 7);
          if (thinkEnd === -1) {
            // Still streaming — show partial thinking
            parts.push({ type: "think", content: text.slice(thinkStart + 7), complete: false });
            cursor = text.length;
          } else {
            parts.push({ type: "think", content: text.slice(thinkStart + 7, thinkEnd), complete: true });
            cursor = thinkEnd + 8; // length of "</think>"
          }
          continue;
        }

        // ── Code fence ───────────────────────────────────────────────────────
        const before = text.slice(cursor, fenceStart);
        if (before) parts.push({ type: "text", content: before });

        const afterFence = fenceStart + 3;
        const nlPos      = text.indexOf("\n", afterFence);

        if (nlPos === -1) {
          parts.push({ type: "code", language: text.slice(afterFence).trim() || "text", content: "", complete: false });
          cursor = text.length;
          break;
        }

        const language  = text.slice(afterFence, nlPos).trim() || "text";
        const codeStart = nlPos + 1;
        const fenceEnd  = text.indexOf("```", codeStart);

        if (fenceEnd === -1) {
          parts.push({ type: "code", language, content: text.slice(codeStart), complete: false });
          cursor = text.length;
          break;
        }

        parts.push({ type: "code", language, content: text.slice(codeStart, fenceEnd), complete: true });
        cursor = fenceEnd + 3;
      }

      if (!parts.length) parts.push({ type: "text", content: "" });
      return parts;
    }

    // Language aliases → Prism class names
    const LANG_MAP = {
      py: "python", js: "javascript", ts: "typescript",
      sh: "bash", shell: "bash", zsh: "bash", fish: "bash",
      yml: "yaml", htm: "html", golang: "go",
    };

    function isPythonLanguage(language) {
      const normalizedLang = String(language || "").trim().toLowerCase();
      return normalizedLang === "python" || normalizedLang === "py";
    }

    function extractSuggestedPyFilenamesFromText(rawText) {
      const text = String(rawText || "");
      if (!text) return [];

      const parts = parseMessageParts(text);
      const textOnly = parts
        .filter(part => part.type === "text")
        .map(part => String(part.content || ""))
        .join("\n");

      const results = [];
      const seen = new Set();
      const regex = /([A-Za-z0-9_][A-Za-z0-9._ -]{0,120}\.py)\b/gi;
      let match;
      while ((match = regex.exec(textOnly)) !== null) {
        const candidate = String(match[1] || "").trim().replace(/^['"`(\[]+|['"`)\],.:;!?]+$/g, "");
        if (!candidate) continue;
        const lower = candidate.toLowerCase();
        if (seen.has(lower)) continue;
        seen.add(lower);
        results.push(candidate);
      }
      return results;
    }

    function createCodeBlock(language, code, suggestedFilename = "") {
      const wrapper  = document.createElement("div");
      wrapper.className = "code-block";

      const toolbar  = document.createElement("div");
      toolbar.className = "code-toolbar";

      const langNode = document.createElement("div");
      langNode.className   = "code-language";
      langNode.textContent = language || "text";

      const copyBtn  = document.createElement("button");
      copyBtn.type        = "button";
      copyBtn.className   = "code-copy-btn";
      copyBtn.textContent = "📋 Copy";
      copyBtn.title       = "Αντιγραφή κώδικα στο clipboard";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(code);
          setButtonFeedback(copyBtn, "✅ Copied", "📋 Copy");
        } catch {
          setButtonFeedback(copyBtn, "❌ Error", "📋 Copy", "error");
        }
      });

      toolbar.appendChild(langNode);

      const normalizedLang = String(language || "").trim().toLowerCase();
      if (isPythonLanguage(normalizedLang)) {
        const preferredFilename = String(suggestedFilename || "").trim();
        const defaultSaveLabel = preferredFilename ? `💾 ${preferredFilename}` : "💾 .py";
        const saveBtn = document.createElement("button");
        saveBtn.type = "button";
        saveBtn.className = "code-copy-btn";
        saveBtn.textContent = defaultSaveLabel;
        saveBtn.title = preferredFilename
          ? `Αποθήκευση του Python block ως ${preferredFilename}`
          : "Αποθήκευση του Python block σε επισυναπτόμενο αρχείο .py";
        saveBtn.addEventListener("click", async () => {
          try {
            const resp = await fetch("/api/export-python-block", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ code, filename: preferredFilename }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok || !data.file || !data.file.url) {
              throw new Error(data.error || "Αποτυχία αποθήκευσης του Python block ως .py αρχείο.");
            }
            const messageWrapper = wrapper.closest('.msg');
            if (messageWrapper) appendGeneratedAttachmentToMessage(messageWrapper, data.file);
            triggerFileDownload(data.file.url, data.file.name || preferredFilename || 'generated_code.py');
            setButtonFeedback(saveBtn, "✅ Saved", defaultSaveLabel);
            renderSystemNotice(`Αποθηκεύτηκε το Python block ως αρχείο: ${data.file.name}`);
          } catch (err) {
            setButtonFeedback(saveBtn, "❌ Error", defaultSaveLabel, "error");
            renderSystemNotice(`Σφάλμα αποθήκευσης Python block: ${err && err.message ? err.message : String(err)}`);
          }
        });
        toolbar.appendChild(saveBtn);

        const defaultRunLabel = preferredFilename ? `▶ Run ${preferredFilename}` : "▶ Run";
        const runBtn = document.createElement("button");
        runBtn.type = "button";
        runBtn.className = "code-copy-btn";
        runBtn.textContent = defaultRunLabel;
        runBtn.title = preferredFilename
          ? `Άνοιγμα νέου terminal και εκτέλεση του Python block ως ${preferredFilename}`
          : "Άνοιγμα νέου terminal και εκτέλεση ολόκληρου του Python block";
        runBtn.addEventListener("click", async () => {
          const confirmed = window.confirm(
            preferredFilename
              ? `Να ανοίξει νέο terminal και να εκτελεστεί το Python block ως ${preferredFilename};`
              : "Να ανοίξει νέο terminal και να εκτελεστεί ολόκληρο το Python block;"
          );
          if (!confirmed) return;
          try {
            const resp = await fetch("/api/execute-python", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ code, filename: preferredFilename }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
              throw new Error(data.error || "Αποτυχία εκτέλεσης Python block.");
            }
            setButtonFeedback(
              runBtn,
              preferredFilename ? `▶ Running ${preferredFilename}` : "▶ Running",
              defaultRunLabel
            );
            renderSystemNotice(data.message || "Το Python block στάλθηκε για εκτέλεση σε νέο terminal.");
          } catch (err) {
            setButtonFeedback(runBtn, "❌ Error", defaultRunLabel, "error");
            renderSystemNotice(`Σφάλμα εκτέλεσης κώδικα: ${err && err.message ? err.message : String(err)}`);
          }
        });
        toolbar.appendChild(runBtn);
      }

      toolbar.appendChild(copyBtn);

      const pre      = document.createElement("pre");
      pre.className  = "code-pre";

      const codeNode = document.createElement("code");
      const prismLang = LANG_MAP[language.toLowerCase()] || language.toLowerCase();
      codeNode.className   = `language-${prismLang}`;
      codeNode.textContent = code;

      pre.appendChild(codeNode);
      wrapper.appendChild(toolbar);
      wrapper.appendChild(pre);

      // Trigger Prism highlighting after the element is in the DOM
      requestAnimationFrame(() => {
        if (window.Prism) {
          try { Prism.highlightElement(codeNode); } catch (_) {}
        }
      });

      return wrapper;
    }

    function createThinkingBlock(content, complete) {
      const details = document.createElement("details");
      details.className = "thinking-block";
      // Διατήρησε την επιλογή του χρήστη όσο γίνεται rerender κατά το streaming
      details.open = !complete ? state.currentInlineThinkingOpen !== false : false;

      const summary = document.createElement("summary");
      summary.className = "thinking-summary";

      const icon = document.createElement("span");
      icon.className = "thinking-icon"; icon.textContent = "🧠";

      const label = document.createElement("span");
      label.className = "thinking-label";
      const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;
      label.textContent = complete
        ? `Βαθιά σκέψη · ${wordCount} λέξεις — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`
        : `Σκέψη σε εξέλιξη… — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`;

      const chev = document.createElement("span");
      chev.className = "thinking-chevron"; chev.textContent = "›";

      summary.appendChild(icon); summary.appendChild(label); summary.appendChild(chev);

      const body = document.createElement("div");
      body.className = "thinking-body"; body.textContent = content;

      details.appendChild(summary); details.appendChild(body);

      // Update label text when toggled
      details.addEventListener("toggle", () => {
        state.currentInlineThinkingOpen = details.open;
        if (complete) {
          label.textContent = `Βαθιά σκέψη · ${wordCount} λέξεις — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`;
        } else {
          label.textContent = `Σκέψη σε εξέλιξη… — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`;
        }
      });

      return details;
    }

    function createTextSegment(text) {
      const div = document.createElement("div");
      div.innerHTML = markdownToHtml(text);
      return div;
    }

    function composeDisplayContent(answerText = "", thinkingText = "") {
      const answer   = String(answerText || "");
      const thinking = String(thinkingText || "");
      if (thinking && answer) return `<think>${thinking}</think>\n\n${answer}`;
      if (thinking) return `<think>${thinking}</think>`;
      return answer;
    }

    function getThinkingStateFromRawContent(sourceText) {
      const parts = parseMessageParts(sourceText);
      const thinkParts = parts.filter(part => part.type === "think");
      return {
        text: thinkParts.map(part => part.content || "").join("\n\n"),
        complete: thinkParts.length ? thinkParts.every(part => part.complete !== false) : true,
      };
    }

    function applyReasoningPanelVisibility() {
      if (!els.reasoningPanel || !els.toggleReasoningBtn) return;
      const hasContent = Boolean(((els.reasoningContent && els.reasoningContent.textContent) || "").trim());
      const wantsVisible = state.reasoningPanelVisible || (state.reasoningAutoOpen && !state.reasoningUserCollapsed);
      const isVisible = hasContent && wantsVisible;
      els.reasoningPanel.classList.toggle("visible", isVisible);
      els.toggleReasoningBtn.textContent = isVisible ? "🙈 Απόκρυψη" : "👁 Εμφάνιση";
      els.toggleReasoningBtn.title = isVisible
        ? "Απόκρυψη του panel σκέψης"
        : "Εμφάνιση του panel σκέψης";
    }

    function resetReasoningPanel(hide = true) {
      state.currentThinkingText = "";
      state.reasoningAutoOpen = false;
      state.reasoningUserCollapsed = false;
      state.currentInlineThinkingOpen = true;
      state.reasoningStreamCompleted = false;
      if (hide) state.reasoningPanelVisible = false;
      if (els.reasoningContent) els.reasoningContent.textContent = "";
      if (els.reasoningMeta) els.reasoningMeta.textContent = "Αναμονή για thinking stream…";
      if (els.reasoningPanel) els.reasoningPanel.classList.remove("streaming");
      if (hide && els.reasoningPanel) els.reasoningPanel.classList.remove("visible");
      applyReasoningPanelVisibility();
    }

    function updateReasoningPanel(text, complete = false, streaming = false) {
      const safeText = String(text || "");
      state.currentThinkingText = safeText;

      if (!safeText.trim()) {
        resetReasoningPanel(true);
        return;
      }

      if (streaming && !complete && !state.reasoningUserCollapsed) {
        state.reasoningAutoOpen = true;
      }

      if (els.reasoningContent) {
        els.reasoningContent.textContent = safeText;
        els.reasoningContent.scrollTop = els.reasoningContent.scrollHeight;
      }

      const wordCount = safeText.trim() ? safeText.trim().split(/\s+/).length : 0;
      if (els.reasoningMeta) {
        els.reasoningMeta.textContent = streaming && !complete
          ? `Σκέψη σε εξέλιξη… · ${wordCount} λέξεις`
          : `Ολοκληρωμένη σκέψη · ${wordCount} λέξεις`;
      }

      if (els.reasoningPanel) {
        els.reasoningPanel.classList.toggle("streaming", streaming && !complete);
      }
      applyReasoningPanelVisibility();

      if (complete) {
        setTimeout(() => {
          if (state.reasoningStreamCompleted) {
            state.reasoningAutoOpen = false;
            state.reasoningPanelVisible = false;
            state.reasoningUserCollapsed = false;
            applyReasoningPanelVisibility();
          }
        }, 350);
      }
    }

    function renderAssistantStreamingView(rawAnswerText, separateThinkingText = "", streamFinished = false) {
      const hasSeparateThinking = Boolean(String(separateThinkingText || "").trim());
      const displayText = hasSeparateThinking
        ? composeDisplayContent(rawAnswerText, separateThinkingText)
        : String(rawAnswerText || "");

      renderMessageContent(state.currentAssistantNode, displayText);

      if (hasSeparateThinking) {
        const thinkingComplete = state.reasoningStreamCompleted || streamFinished;
        updateReasoningPanel(separateThinkingText, thinkingComplete, !thinkingComplete);
      } else {
        const legacyThinking = getThinkingStateFromRawContent(displayText);
        if (legacyThinking.text.trim()) {
          updateReasoningPanel(legacyThinking.text, streamFinished ? true : legacyThinking.complete, !streamFinished && !legacyThinking.complete);
        } else if (!streamFinished) {
          resetReasoningPanel(true);
        }
      }

      return displayText;
    }

    function renderMessageContent(container, content) {
      const sourceText = String(content || "");
      container.innerHTML          = "";
      container.dataset.rawContent = sourceText;

      const frag  = document.createDocumentFragment();
      const parts = parseMessageParts(sourceText);
      const suggestedPyFilenames = extractSuggestedPyFilenamesFromText(sourceText);
      let pythonBlockIndex = 0;

      for (const part of parts) {
        if (part.type === "think") {
          frag.appendChild(createThinkingBlock(part.content || "", part.complete !== false));
        } else if (part.type === "code") {
          const suggestedFilename = isPythonLanguage(part.language)
            ? (suggestedPyFilenames[pythonBlockIndex] || "")
            : "";
          frag.appendChild(createCodeBlock(part.language, part.content || "", suggestedFilename));
          if (isPythonLanguage(part.language)) pythonBlockIndex += 1;
        } else {
          frag.appendChild(createTextSegment(part.content || ""));
        }
      }
      container.appendChild(frag);
    }

    // ── Message creation ──────────────────────────────────────────────────────

    function createAttachmentChip(item) {
      const hasUrl = !!(item && item.url);
      const chip = document.createElement(hasUrl ? "a" : "div");
      chip.className = `attachment-chip${hasUrl ? " link" : ""}`;
      if (hasUrl) {
        chip.href = item.url;
        chip.target = "_blank";
        chip.rel = "noopener noreferrer";
        chip.download = item.name || "attachment";
        chip.title = `Άνοιγμα / λήψη: ${item.name || "attachment"}`;
      }
      const icon = item && item.kind === "image" ? "🖼" : "📄";
      chip.textContent = `${icon} ${(item && item.name) ? item.name : "attachment"}`;
      return chip;
    }

    function ensureMessageAttachmentList(messageWrapper) {
      let wrap = messageWrapper.querySelector('.attachment-list');
      if (!wrap) {
        wrap = document.createElement('div');
        wrap.className = 'attachment-list';
        messageWrapper.appendChild(wrap);
      }
      return wrap;
    }

    function appendGeneratedAttachmentToMessage(messageWrapper, item) {
      if (!messageWrapper || !item || !item.url) return;
      const wrap = ensureMessageAttachmentList(messageWrapper);
      const existing = Array.from(wrap.querySelectorAll('a.attachment-chip[href], .attachment-chip[data-name]'))
        .some(node => (node.getAttribute('href') || '') === item.url || (node.dataset && node.dataset.name) === item.name);
      if (existing) return;
      const chip = createAttachmentChip(item);
      if (chip.dataset) chip.dataset.name = item.name || '';
      wrap.appendChild(chip);
    }

    function triggerFileDownload(url, filename) {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename || '';
      a.rel = 'noopener noreferrer';
      document.body.appendChild(a);
      a.click();
      a.remove();
    }

    function removeEmptyState() {
      const node = document.getElementById("emptyState");
      if (node) node.remove();
    }

    function scrollToBottom(force = false) {
      if (state.autoScroll || force) {
        els.messages.scrollTop = els.messages.scrollHeight;
      }
    }

    function updateScrollToBottomBtn() {
      const { scrollTop, scrollHeight, clientHeight } = els.messages;
      const atBottom = scrollHeight - scrollTop - clientHeight < 80;
      els.scrollToBottomBtn.classList.toggle("visible", !atBottom && !state.autoScroll);
    }

    function updateMsgCount() {
      state.msgCount = els.messages.querySelectorAll(".msg.user, .msg.assistant").length;
      els.msgCountBadge.textContent = `${state.msgCount} μηνύματα`;
    }

    function createStreamingPlaceholder() {
      const d = document.createElement("div");
      d.className = "streaming-dots";
      d.innerHTML = "<span></span><span></span><span></span>";
      return d;
    }

    function createMessage(role, content, attachments = []) {
      removeEmptyState();

      const wrapper = document.createElement("div");
      wrapper.className = `msg ${role}`;

      // Header
      const head     = document.createElement("div");
      head.className = "msg-head";
      const roleNode = document.createElement("div");
      roleNode.className   = "msg-role";
      roleNode.textContent = role === "user" ? "Εσύ" : role === "assistant" ? "Assistant" : "System";
      const timeNode = document.createElement("div");
      timeNode.className   = "msg-time";
      timeNode.textContent = nowString();
      head.appendChild(roleNode);
      head.appendChild(timeNode);

      // Body
      const body     = document.createElement("div");
      body.className = "msg-body";
      if (role === "assistant" && !content) {
        body.appendChild(createStreamingPlaceholder());
      } else {
        renderMessageContent(body, content || "");
      }

      wrapper.appendChild(head);
      wrapper.appendChild(body);

      // Attachments
      if (attachments && attachments.length) {
        const wrap = document.createElement("div");
        wrap.className = "attachment-list";
        for (const item of attachments) {
          wrap.appendChild(createAttachmentChip(item));
        }
        wrapper.appendChild(wrap);
      }

      // Copy button
      const tools   = document.createElement("div");
      tools.className = "message-tools";
      const copyBtn = document.createElement("button");
      copyBtn.type        = "button";
      copyBtn.className   = "tool-btn";
      copyBtn.textContent = "📋 Copy";
      copyBtn.title       = "Αντιγραφή μηνύματος";
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(body.dataset.rawContent || body.textContent || "");
          setButtonFeedback(copyBtn, "✅ Copied", "📋 Copy");
        } catch {
          setButtonFeedback(copyBtn, "❌ Error", "📋 Copy", "error");
        }
      });
      tools.appendChild(copyBtn);
      wrapper.appendChild(tools);

      els.messages.appendChild(wrapper);
      scrollToBottom();
      updateMsgCount();

      return { wrapper, body };
    }

    function renderSystemNotice(text) {
      createMessage("system", text, []);
    }

    function renderEmptyState() {
      els.messages.innerHTML = `
        <div class="empty-state" id="emptyState">
          <h3 style="margin-top:0;">Έτοιμο για συνομιλία</h3>
          <div>Γράψε το δικό σου prompt και, αν θέλεις, πρόσθεσε αρχεία για context.</div>
          <div style="margin-top:10px;" class="tiny">
            Enter αποστολή · Shift+Enter νέα γραμμή · Ctrl+Enter εναλλακτικό
          </div>
        </div>`;
      state.msgCount = 0;
      els.msgCountBadge.textContent = "0 μηνύματα";
    }

    // ── File handling & Drag/Drop ─────────────────────────────────────────────

    function renderSelectedFiles() {
      els.selectedFiles.innerHTML = "";
      for (const file of state.selectedFiles) {
        const chip = document.createElement("div");
        chip.className   = "attachment-chip";
        chip.textContent = `📎 ${file.name}`;
        els.selectedFiles.appendChild(chip);
      }
    }

    function addFiles(fileList) {
      const existing = new Set(state.selectedFiles.map(f => `${f.name}|${f.size}`));
      for (const file of Array.from(fileList || [])) {
        const key = `${file.name}|${file.size}`;
        if (!existing.has(key)) { state.selectedFiles.push(file); existing.add(key); }
      }
      renderSelectedFiles();
    }

    async function readFileAsBase64(file) {
      return new Promise((resolve, reject) => {
        const reader  = new FileReader();
        reader.onload = () => {
          const parts = String(reader.result || "").split(",");
          resolve({
            name: file.name, size: file.size,
            mime_type: file.type || "",
            data_base64: parts.length > 1 ? parts[1] : "",
          });
        };
        reader.onerror = () => reject(new Error(`Αποτυχία ανάγνωσης: ${file.name}`));
        reader.readAsDataURL(file);
      });
    }

    async function collectFilesPayload() {
      const payload = [];
      for (const file of state.selectedFiles) payload.push(await readFileAsBase64(file));
      return payload;
    }

    // Reliable drag-enter / drag-leave with a counter (avoids child-element flicker)
    document.addEventListener("dragenter", (e) => {
      e.preventDefault();
      state.dragCounter++;
      els.dropOverlay.classList.add("active");
    });
    document.addEventListener("dragleave", () => {
      state.dragCounter--;
      if (state.dragCounter <= 0) {
        state.dragCounter = 0;
        els.dropOverlay.classList.remove("active");
      }
    });
    document.addEventListener("dragover", (e) => e.preventDefault());
    document.addEventListener("drop", (e) => {
      e.preventDefault();
      state.dragCounter = 0;
      els.dropOverlay.classList.remove("active");
      if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    });

    // ── Model management ──────────────────────────────────────────────────────

    function getSavedModel(models) {
      try {
        const saved = localStorage.getItem(MODEL_KEY);
        return saved && models.includes(saved) ? saved : null;
      } catch { return null; }
    }

    function saveModel(model) {
      try { localStorage.setItem(MODEL_KEY, model); } catch (_) {}
    }

    function getSavedSortCriterion() {
      try {
        const saved = localStorage.getItem(MODEL_SORT_KEY);
        return saved || "overall";
      } catch { return "overall"; }
    }

    function saveSortCriterion(value) {
      try { localStorage.setItem(MODEL_SORT_KEY, value || "overall"); } catch (_) {}
    }

    function normalizeEnsembleMode(value) {
      const normalized = String(value || "auto").trim().toLowerCase();
      return ["off", "auto", "manual"].includes(normalized) ? normalized : "auto";
    }

    function getSavedEnsembleMode() {
      try {
        const explicit = localStorage.getItem(ENSEMBLE_MODE_KEY);
        if (explicit) return normalizeEnsembleMode(explicit);
      } catch (_) {}
      try {
        const legacy = localStorage.getItem(ENSEMBLE_KEY);
        if (legacy == null) return "auto";
        return legacy !== "0" ? "auto" : "off";
      } catch { return "auto"; }
    }

    function saveEnsembleMode(value) {
      const mode = normalizeEnsembleMode(value);
      try { localStorage.setItem(ENSEMBLE_MODE_KEY, mode); } catch (_) {}
      try { localStorage.setItem(ENSEMBLE_KEY, mode === "off" ? "0" : "1"); } catch (_) {}
    }

    function getSavedHelperModel(models) {
      try {
        const saved = localStorage.getItem(ENSEMBLE_HELPER_KEY);
        return saved && models.includes(saved) ? saved : null;
      } catch { return null; }
    }

    function saveHelperModel(model) {
      try {
        if (model) localStorage.setItem(ENSEMBLE_HELPER_KEY, model);
        else localStorage.removeItem(ENSEMBLE_HELPER_KEY);
      } catch (_) {}
    }

    function filterModelsBySearch(modelList, rawQuery) {
      const models = Array.isArray(modelList) ? modelList.filter(Boolean) : [];
      const query = String(rawQuery || "").trim().toLowerCase();
      if (!query) return models;
      const tokens = query.split(/\s+/).filter(Boolean);
      return models.filter((model) => {
        const haystack = String(model || "").toLowerCase();
        return tokens.every((token) => haystack.includes(token));
      });
    }

    function parseParamSizeBillions(rawValue) {
      const textValue = String(rawValue || "").trim().toLowerCase();
      if (!textValue) return 0;
      const match = textValue.match(/(\d+(?:\.\d+)?)\s*([tbm])?/i);
      if (!match) return 0;
      const value = Number(match[1] || 0);
      const suffix = String(match[2] || "b").toLowerCase();
      if (!Number.isFinite(value) || value <= 0) return 0;
      if (suffix === "t") return value * 1000;
      if (suffix === "m") return value / 1000;
      return value;
    }

    function getModelMeta(model) {
      return (state.modelMetaByModel && state.modelMetaByModel[model] && typeof state.modelMetaByModel[model] === "object")
        ? state.modelMetaByModel[model]
        : {};
    }

    function getModelCapabilities(model) {
      const meta = getModelMeta(model);
      const caps = Array.isArray(meta.capabilities) ? meta.capabilities.map(x => String(x || "").toLowerCase()) : [];
      const name = String(model || "").toLowerCase();
      if (!caps.includes("vision") && ["vision", "-vl", ":vl", "gemini", "llava", "pixtral"].some(t => name.includes(t))) caps.push("vision");
      if (!caps.includes("coding") && ["coder", "code", "devstral"].some(t => name.includes(t))) caps.push("coding");
      if (!caps.includes("reasoning") && ["thinking", "reason", "r1", "gpt-oss", "qwen3.5", "kimi-k2", "deepseek", "cogito"].some(t => name.includes(t))) caps.push("reasoning");
      return Array.from(new Set(caps));
    }

    function getModelSizeBillions(model) {
      const meta = getModelMeta(model);
      const byParam = Number(meta.parameter_size_b || 0);
      if (Number.isFinite(byParam) && byParam > 0) return byParam;
      const byName = parseParamSizeBillions(model);
      if (Number.isFinite(byName) && byName > 0) return byName;
      const sizeBytes = Number(meta.size_bytes || 0);
      if (Number.isFinite(sizeBytes) && sizeBytes > 0) {
        return sizeBytes / 1_000_000_000;
      }
      return 0;
    }

    function getModelContextTokens(model) {
      const meta = getModelMeta(model);
      const numCtx = Number(meta.num_ctx_max || state.modelMaxNumCtxByModel[model] || 0);
      return Number.isFinite(numCtx) && numCtx > 0 ? numCtx : 0;
    }

    function getModelModifiedTs(model) {
      const meta = getModelMeta(model);
      const rawTs = Number(meta.modified_ts || 0);
      if (Number.isFinite(rawTs) && rawTs > 0) return rawTs;
      const rawDate = String(meta.modified_at || "").trim();
      if (!rawDate) return 0;
      const ts = Date.parse(rawDate);
      return Number.isFinite(ts) ? Math.trunc(ts / 1000) : 0;
    }

    const FAMILY_PRIOR_DEFAULTS = Object.freeze({
      overall: 7.50,
      coding: 7.20,
      reasoning: 7.35,
      context: 7.05,
      vision: 6.85,
      speed: 7.10,
    });

    const MODEL_FAMILY_PROFILES = Object.freeze([
      ["gemini-3-flash",   { overall: 9.12, coding: 8.62, reasoning: 8.82, context: 8.95, vision: 9.35, speed: 9.95 }],
      ["deepseek-v3.2",    { overall: 9.82, coding: 9.62, reasoning: 9.90, context: 9.14, vision: 6.20, speed: 4.70 }],
      ["deepseek-v3.1",    { overall: 9.72, coding: 9.54, reasoning: 9.80, context: 9.02, vision: 6.00, speed: 4.82 }],
      ["deepseek-r1",      { overall: 9.66, coding: 9.10, reasoning: 9.96, context: 8.40, vision: 5.25, speed: 3.86 }],
      ["qwen3.5",          { overall: 9.96, coding: 9.74, reasoning: 9.92, context: 9.52, vision: 9.84, speed: 4.42 }],
      ["qwen3-coder-next", { overall: 9.56, coding: 9.96, reasoning: 9.42, context: 9.00, vision: 5.35, speed: 5.06 }],
      ["qwen3-coder",      { overall: 9.68, coding: 9.98, reasoning: 9.60, context: 9.08, vision: 5.38, speed: 4.25 }],
      ["qwen3-vl",         { overall: 9.58, coding: 9.26, reasoning: 9.42, context: 9.02, vision: 9.98, speed: 4.52 }],
      ["qwen3-next",       { overall: 9.24, coding: 9.10, reasoning: 9.18, context: 8.86, vision: 7.92, speed: 5.12 }],
      ["kimi-k2-thinking", { overall: 9.62, coding: 9.22, reasoning: 9.90, context: 9.12, vision: 6.62, speed: 3.72 }],
      ["kimi-k2.5",        { overall: 9.76, coding: 9.40, reasoning: 9.78, context: 9.28, vision: 7.12, speed: 4.12 }],
      ["kimi-k2",          { overall: 9.58, coding: 9.22, reasoning: 9.62, context: 9.00, vision: 6.85, speed: 4.25 }],
      ["glm-5",            { overall: 9.60, coding: 9.36, reasoning: 9.56, context: 9.12, vision: 8.72, speed: 4.15 }],
      ["glm-4.7",          { overall: 9.46, coding: 9.18, reasoning: 9.44, context: 8.92, vision: 8.22, speed: 4.02 }],
      ["glm-4.6",          { overall: 9.38, coding: 9.12, reasoning: 9.36, context: 8.78, vision: 8.05, speed: 4.10 }],
      ["minimax-m2.7",     { overall: 9.42, coding: 9.06, reasoning: 9.40, context: 8.96, vision: 8.62, speed: 4.42 }],
      ["minimax-m2.5",     { overall: 9.34, coding: 8.98, reasoning: 9.32, context: 8.86, vision: 8.46, speed: 4.58 }],
      ["minimax-m2.1",     { overall: 9.22, coding: 8.92, reasoning: 9.20, context: 8.72, vision: 8.18, speed: 4.72 }],
      ["minimax-m2",       { overall: 9.14, coding: 8.88, reasoning: 9.10, context: 8.64, vision: 8.00, speed: 4.86 }],
      ["nemotron-3-super", { overall: 9.32, coding: 8.92, reasoning: 9.28, context: 8.96, vision: 7.42, speed: 4.82 }],
      ["nemotron-3-nano",  { overall: 8.76, coding: 8.36, reasoning: 8.68, context: 8.12, vision: 6.20, speed: 7.20 }],
      ["mistral-large-3",  { overall: 9.22, coding: 9.00, reasoning: 9.18, context: 8.82, vision: 7.82, speed: 4.32 }],
      ["devstral-small-2", { overall: 8.98, coding: 9.42, reasoning: 8.70, context: 8.52, vision: 5.02, speed: 6.62 }],
      ["devstral-2",       { overall: 9.18, coding: 9.74, reasoning: 8.96, context: 8.86, vision: 5.10, speed: 5.22 }],
      ["devstral",         { overall: 8.98, coding: 9.42, reasoning: 8.72, context: 8.52, vision: 5.05, speed: 6.20 }],
      ["gpt-oss",          { overall: 9.06, coding: 8.92, reasoning: 9.04, context: 8.62, vision: 5.10, speed: 5.90 }],
      ["cogito-2.1",       { overall: 9.28, coding: 9.08, reasoning: 9.42, context: 8.92, vision: 6.22, speed: 3.92 }],
      ["cogito",           { overall: 9.12, coding: 8.96, reasoning: 9.26, context: 8.76, vision: 6.02, speed: 4.20 }],
      ["gemini-3",         { overall: 9.74, coding: 9.42, reasoning: 9.72, context: 9.46, vision: 9.82, speed: 5.12 }],
      ["ministral-3",      { overall: 8.74, coding: 8.34, reasoning: 8.48, context: 8.22, vision: 6.22, speed: 8.24 }],
      ["ministral",        { overall: 8.62, coding: 8.22, reasoning: 8.36, context: 8.06, vision: 6.05, speed: 8.00 }],
      ["mistral-small",    { overall: 8.54, coding: 8.18, reasoning: 8.24, context: 7.96, vision: 5.92, speed: 8.20 }],
      ["gemma3",           { overall: 8.58, coding: 8.22, reasoning: 8.34, context: 7.82, vision: 8.12, speed: 7.50 }],
      ["rnj-1",            { overall: 8.32, coding: 7.96, reasoning: 8.16, context: 7.92, vision: 5.42, speed: 8.05 }],
      ["rnj",              { overall: 8.24, coding: 7.88, reasoning: 8.08, context: 7.84, vision: 5.32, speed: 8.10 }],
    ]);

    const MODEL_TRAIT_HINTS = Object.freeze([
      ["qwen3.5",          ["reasoning", "coding", "vision"]],
      ["qwen3-vl",         ["vision", "reasoning", "coding"]],
      ["qwen3-coder",      ["coding", "reasoning"]],
      ["qwen3-next",       ["reasoning", "coding", "vision"]],
      ["deepseek-v3.2",    ["reasoning", "coding"]],
      ["deepseek-v3.1",    ["reasoning", "coding"]],
      ["deepseek-r1",      ["reasoning"]],
      ["kimi-k2.5",        ["reasoning", "coding"]],
      ["kimi-k2",          ["reasoning", "coding"]],
      ["glm-5",            ["reasoning", "coding", "vision"]],
      ["glm-4",            ["reasoning", "coding", "vision"]],
      ["gemini-3",         ["reasoning", "coding", "vision"]],
      ["devstral",         ["coding"]],
      ["gpt-oss",          ["reasoning", "coding"]],
      ["nemotron-3-super", ["reasoning", "coding"]],
      ["nemotron-3-nano",  ["reasoning"]],
      ["mistral-large-3",  ["reasoning", "coding"]],
      ["cogito",           ["reasoning", "coding"]],
      ["ministral-3",      ["reasoning", "coding"]],
      ["gemma3",           ["reasoning", "coding", "vision"]],
    ]);

    function canonicalModelKey(model) {
      const raw = String(model || "").trim().toLowerCase();
      if (!raw) return "";
      const normalized = (raw.includes("/") && raw.includes(":"))
        ? `${raw.split(":", 1)[0].split("/").slice(-1)[0]}:${raw.slice(raw.indexOf(":") + 1)}`
        : raw;
      if (normalized.includes(":")) {
        const idx = normalized.indexOf(":");
        const family = normalized.slice(0, idx);
        let tag = normalized.slice(idx + 1);
        if (tag.endsWith("-cloud")) tag = tag.slice(0, -6);
        return `${family}:${tag}`.replace(/:+$/g, "");
      }
      return normalized.endsWith("-cloud") ? normalized.slice(0, -6) : normalized;
    }

    function modelMatchesPrefix(model, prefix) {
      const key = canonicalModelKey(model);
      const p = String(prefix || "").trim().toLowerCase();
      if (!key || !p) return false;
      return key.startsWith(p) || key.includes(p);
    }

    function getFamilyProfile(model) {
      for (const [prefix, profile] of MODEL_FAMILY_PROFILES) {
        if (modelMatchesPrefix(model, prefix)) return profile;
      }
      return FAMILY_PRIOR_DEFAULTS;
    }

    function getModelCapabilities(model) {
      const meta = getModelMeta(model);
      const caps = new Set(Array.isArray(meta.capabilities)
        ? meta.capabilities.map(x => String(x || "").toLowerCase()).filter(Boolean)
        : []);
      const key = canonicalModelKey(model);

      if (["vision", "-vl", ":vl", "gemini", "llava", "pixtral", "multimodal", "omni"].some(t => key.includes(t))) caps.add("vision");
      if (["coder", "code", "devstral", "claude-code", "swe", "terminal"].some(t => key.includes(t))) caps.add("coding");
      if (["thinking", "reason", "reasoning", "r1", "gpt-oss", "deepseek", "cogito", "kimi-k2", "glm-5", "glm-4.7", "glm-4.6"].some(t => key.includes(t))) caps.add("reasoning");
      for (const [prefix, hintedCaps] of MODEL_TRAIT_HINTS) {
        if (modelMatchesPrefix(key, prefix)) {
          hintedCaps.forEach(cap => caps.add(cap));
        }
      }
      caps.add("completion");
      return Array.from(caps);
    }

    function clamp(value, low, high) {
      return Math.max(low, Math.min(value, high));
    }

    function sizeQualityStrength(sizeB) {
      if (!Number.isFinite(sizeB) || sizeB <= 0) return 4.8;
      const normalized = Math.log2(Math.min(sizeB, 1000) + 1) / Math.log2(1001);
      return 3.8 + normalized * 6.2;
    }

    function sizeSpeedStrength(sizeB) {
      if (!Number.isFinite(sizeB) || sizeB <= 0) return 7.8;
      const normalized = Math.log2(Math.min(sizeB, 1000) + 1) / Math.log2(1001);
      return 9.8 - normalized * 7.2;
    }

    function contextStrength(ctx) {
      if (!Number.isFinite(ctx) || ctx <= 0) return 3.2;
      const normalized = clamp(Math.log2(ctx) / 18.0, 0.0, 1.08);
      const bonus = ctx >= 200000 ? 0.7 : (ctx >= 128000 ? 0.35 : 0);
      return Math.min(10.0, 3.6 + normalized * 6.0 + bonus);
    }

    function freshnessStrength(modifiedTs) {
      if (!Number.isFinite(modifiedTs) || modifiedTs <= 0) return 4.8;
      const ageDays = Math.max(0, (Date.now() / 1000 - modifiedTs) / 86400);
      if (ageDays <= 21) return 10.0;
      if (ageDays <= 45) return 9.4;
      if (ageDays <= 90) return 8.6;
      if (ageDays <= 180) return 7.6;
      if (ageDays <= 365) return 6.3;
      if (ageDays <= 540) return 5.2;
      return 4.3;
    }

    function nameSignalBonus(model, criterion) {
      const key = canonicalModelKey(model);
      let bonus = 0;
      if (criterion === "coding") {
        if (["coder", "devstral", "terminal", "swe"].some(t => key.includes(t))) bonus += 0.90;
        if (["code", "oss"].some(t => key.includes(t))) bonus += 0.25;
      } else if (criterion === "reasoning") {
        if (["thinking", "reason", "reasoning", "r1"].some(t => key.includes(t))) bonus += 0.95;
        if (["deepseek", "cogito"].some(t => key.includes(t))) bonus += 0.20;
      } else if (criterion === "vision") {
        if (["-vl", ":vl", "vision", "gemini", "pixtral", "llava"].some(t => key.includes(t))) bonus += 0.95;
      } else if (criterion === "speed") {
        if (["flash", "nano", "mini", "small"].some(t => key.includes(t))) bonus += 1.15;
        if (["preview"].some(t => key.includes(t))) bonus += 0.20;
      } else if (criterion === "overall") {
        if (["thinking", "coder", "-vl", ":vl", "vision"].some(t => key.includes(t))) bonus += 0.18;
      }
      return bonus;
    }

    function scoreModelForCriterion(model, criterion = "overall") {
      const chosenCriterion = ["overall", "coding", "reasoning", "context", "vision", "speed", "newest"].includes(String(criterion || "").toLowerCase())
        ? String(criterion || "overall").toLowerCase()
        : "overall";
      const profile = getFamilyProfile(model);
      const basePrior = Number(profile[chosenCriterion] || FAMILY_PRIOR_DEFAULTS[chosenCriterion] || 7.0);
      const sizeB = Math.max(0, Math.min(getModelSizeBillions(model) || 0, 1000));
      const ctx = Math.max(0, getModelContextTokens(model));
      const newest = getModelModifiedTs(model);
      const caps = getModelCapabilities(model);
      const sizeQuality = sizeQualityStrength(sizeB);
      const sizeSpeed = sizeSpeedStrength(sizeB);
      const ctxStrength = contextStrength(ctx);
      const freshness = freshnessStrength(newest);
      const hasReasoning = caps.includes("reasoning") ? 10 : 0;
      const hasCoding = caps.includes("coding") ? 10 : 0;
      const hasVision = caps.includes("vision") ? 10 : 0;
      const bonus = nameSignalBonus(model, chosenCriterion);

      switch (chosenCriterion) {
        case "coding":
          return basePrior * 0.56 + sizeQuality * 0.10 + ctxStrength * 0.10 + freshness * 0.05 + hasCoding * 0.14 + hasReasoning * 0.04 + bonus;
        case "reasoning":
          return basePrior * 0.56 + sizeQuality * 0.11 + ctxStrength * 0.06 + freshness * 0.04 + hasReasoning * 0.13 + hasCoding * 0.03 + bonus;
        case "context":
          return ctx > 0
            ? (ctxStrength * 0.74 + basePrior * 0.14 + sizeQuality * 0.08 + freshness * 0.04)
            : (basePrior * 0.22 + sizeQuality * 0.12 + freshness * 0.06);
        case "vision":
          return basePrior * 0.58 + sizeQuality * 0.09 + ctxStrength * 0.06 + freshness * 0.04 + hasVision * 0.18 + hasReasoning * 0.02 + bonus;
        case "speed":
          return basePrior * 0.15 + sizeSpeed * 0.60 + freshness * 0.10 + ctxStrength * 0.05 + ((sizeB > 0 && sizeB <= 24) ? 0.20 : 0) + bonus;
        case "newest":
          return newest > 0 ? newest : 0;
        case "overall":
        default:
          return basePrior * 0.56 + sizeQuality * 0.12 + ctxStrength * 0.06 + freshness * 0.05 + hasReasoning * 0.08 + hasCoding * 0.06 + hasVision * 0.04 + bonus;
      }
    }

    function sortModelsByCriterion(modelList, criterion = "overall") {
      const models = Array.isArray(modelList) ? [...modelList].filter(Boolean) : [];
      return models.sort((a, b) => {
        const diff = scoreModelForCriterion(b, criterion) - scoreModelForCriterion(a, criterion);
        if (Math.abs(diff) > 1e-9) return diff > 0 ? 1 : -1;
        return String(a).localeCompare(String(b), "en", { sensitivity: "base" });
      });
    }

    function getSortCriterionLabel(value) {
      const mapping = {
        overall: "Overall",
        coding: "Coding",
        reasoning: "Reasoning",
        context: "Long Context",
        vision: "Vision",
        speed: "Speed",
        newest: "Newest",
      };
      return mapping[value] || "Overall";
    }

    function populateModelSelect(modelList, criterionRecommended = "", preferredModel = "", options = {}) {
      const allModels = Array.isArray(modelList) ? modelList.filter(Boolean) : [];
      const searchText = options && Object.prototype.hasOwnProperty.call(options, "searchText")
        ? String(options.searchText || "")
        : String((els.modelSearchInput && els.modelSearchInput.value) || "");
      const models = filterModelsBySearch(allModels, searchText);
      const preferWinner = !!(options && options.preferWinner);
      const allowSavedModel = options && Object.prototype.hasOwnProperty.call(options, "allowSavedModel")
        ? !!options.allowSavedModel
        : !preferWinner;
      els.modelSelect.innerHTML = "";

      if (!allModels.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Δεν βρέθηκαν μοντέλα";
        els.modelSelect.appendChild(opt);
        return [];
      }

      if (!models.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Καμία αντιστοίχιση στην αναζήτηση";
        els.modelSelect.appendChild(opt);
        return [];
      }

      for (const m of models) {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = (criterionRecommended && m === criterionRecommended) ? `★ ${m}` : m;
        els.modelSelect.appendChild(opt);
      }

      const saved = allowSavedModel ? getSavedModel(allModels) : null;
      const winner = (criterionRecommended && allModels.includes(criterionRecommended)) ? criterionRecommended : "";
      const currentValue = String(els.modelSelect.dataset.currentValue || els.modelSelect.value || "").trim();
      const preferred = (preferWinner ? winner : "")
        || (preferredModel && models.includes(preferredModel) ? preferredModel : "")
        || (currentValue && models.includes(currentValue) ? currentValue : "")
        || (saved && models.includes(saved) ? saved : "")
        || (winner && models.includes(winner) ? winner : "")
        || models[0] || "";

      els.modelSelect.value = preferred;
      els.modelSelect.dataset.currentValue = preferred;
      return models;
    }

    function rebuildModelSelect(preferredModel = "", preferWinner = false) {
      const criterion = (els.modelSortSelect && els.modelSortSelect.value) ? els.modelSortSelect.value : "overall";
      state.modelSortCriterion = criterion;
      const originalModels = Array.isArray(state.models) ? [...state.models] : [];
      const sortedModels = sortModelsByCriterion(originalModels, criterion);
      const criterionWinner = sortedModels[0] || "";
      const chosenModel = preferWinner ? "" : (preferredModel || els.modelSelect.value || "");
      populateModelSelect(sortedModels, criterionWinner, chosenModel, {
        preferWinner,
        allowSavedModel: !preferWinner,
      });
      updateHelperModelSelect();
      updateModelBadges();
      syncNumCtxInputForSelectedModel();
      return criterionWinner;
    }

    function updateHelperModelSelect(preferredModel = "") {
      if (!els.helperModelSelect) return [];
      const primaryModel = getSelectedModelKey();
      const allModels = sortModelsByCriterion(Array.isArray(state.models) ? [...state.models] : [], "overall")
        .filter((model) => model && model !== primaryModel);
      state.helperModels = allModels;
      els.helperModelSelect.innerHTML = "";

      if (!allModels.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Δεν υπάρχουν helper models";
        els.helperModelSelect.appendChild(opt);
        return [];
      }

      const filtered = filterModelsBySearch(allModels, (els.helperSearchInput && els.helperSearchInput.value) || "");
      if (!filtered.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "Καμία αντιστοίχιση στην αναζήτηση";
        els.helperModelSelect.appendChild(opt);
        return [];
      }

      for (const model of filtered) {
        const opt = document.createElement("option");
        opt.value = model;
        opt.textContent = model;
        els.helperModelSelect.appendChild(opt);
      }

      const saved = getSavedHelperModel(allModels);
      const currentValue = String(els.helperModelSelect.dataset.currentValue || els.helperModelSelect.value || "").trim();
      const preferred = (preferredModel && filtered.includes(preferredModel) ? preferredModel : "")
        || (currentValue && filtered.includes(currentValue) ? currentValue : "")
        || (saved && filtered.includes(saved) ? saved : "")
        || filtered[0] || "";

      els.helperModelSelect.value = preferred;
      els.helperModelSelect.dataset.currentValue = preferred;
      return filtered;
    }

    function refreshHelperControls(preferredModel = "") {
      const mode = normalizeEnsembleMode((els.ensembleModeSelect && els.ensembleModeSelect.value) || state.ensembleMode || "auto");
      state.ensembleMode = mode;
      const manual = mode === "manual";
      if (els.helperSearchInput) els.helperSearchInput.disabled = !manual;
      if (els.helperModelSelect) els.helperModelSelect.disabled = !manual;
      updateHelperModelSelect(preferredModel);
      if (els.ensembleModeInfo) {
        els.ensembleModeInfo.textContent = manual
          ? "Manual: επίλεξε εσύ το δεύτερο helper model από τη λίστα. Το κύριο μοντέλο αποκλείεται αυτόματα."
          : mode === "auto"
            ? "Auto: το helper model επιλέγεται αυτόματα από το κύριο μοντέλο και το είδος του task."
            : "Off: χρησιμοποιείται μόνο το κύριο μοντέλο χωρίς helper.";
      }
      if (!state.isStreaming && els.helperText) {
        if (mode === "auto") {
          els.helperText.textContent = "🤝 Dual-model ensemble auto: ON";
        } else if (mode === "manual") {
          const helper = String((els.helperModelSelect && els.helperModelSelect.value) || "").trim();
          els.helperText.textContent = helper ? `🤝 Manual helper: ${helper}` : "🤝 Manual helper: επίλεξε δεύτερο μοντέλο";
        } else {
          els.helperText.textContent = DEFAULT_HELPER;
        }
      }
    }

    function updateModelBadges(data = null) {
      const model = els.modelSelect.value || "-";
      els.selectedModelBadge.textContent = `Μοντέλο: ${model}`;
      if (!data) return;

      const sourceText =
        data.source === "official-online" ? "Πηγή: official direct API catalog" :
        data.source === "stale-online-cache" ? "Πηγή: τελευταία επιτυχής official direct API λίστα" :
        data.source === "initializing" ? "Πηγή: αρχικοποίηση" :
        "Πηγή: σφάλμα online λίστας";

      els.sourceBadge.textContent = sourceText;
      els.sourceBadge.className   =
        data.source === "official-online" ? "badge ok" :
        data.last_error ? "badge warn" : "badge";
    }

    async function ensureSelectedModelMeta(model, force = false) {
      const targetModel = String(model || "").trim();
      if (!targetModel) return null;

      const existing = getModelMeta(targetModel);
      if (!force && existing && Number(existing.num_ctx_max || 0) >= 256 && existing.details_complete) {
        return existing;
      }
      if (!force && state.modelDetailRequests[targetModel]) {
        return state.modelDetailRequests[targetModel];
      }

      const request = (async () => {
        try {
          const query = `/api/model-details?model=${encodeURIComponent(targetModel)}${force ? "&force=1" : ""}`;
          const resp = await fetch(query);
          const data = await resp.json();
          if (resp.ok && data && data.meta && typeof data.meta === "object") {
            const merged = { ...(state.modelMetaByModel[targetModel] || {}), ...data.meta };
            state.modelMetaByModel[targetModel] = merged;
            const numCtxMax = Number(merged.num_ctx_max || 0);
            if (Number.isFinite(numCtxMax) && numCtxMax >= 256) {
              state.modelMaxNumCtxByModel[targetModel] = Math.trunc(numCtxMax);
            }
            if (targetModel === getSelectedModelKey()) {
              syncNumCtxInputForSelectedModel();
            }
            return merged;
          }
          return existing || null;
        } catch (_) {
          return existing || null;
        } finally {
          delete state.modelDetailRequests[targetModel];
        }
      })();

      state.modelDetailRequests[targetModel] = request;
      return request;
    }

    async function loadModels() {
      try {
        const currentSelection = getSelectedModelKey() || "";
        const resp = await fetch("/api/models");
        const data = await resp.json();

        const serverModels  = Array.isArray(data.models) ? data.models.filter(Boolean) : [];
        const modelMeta     = (data.model_meta && typeof data.model_meta === "object") ? data.model_meta : {};
        state.lastModelsRefreshTs = Number(data.last_refresh_ts || 0) || 0;
        state.modelMaxNumCtxByModel = {};
        state.modelMetaByModel = {};
        for (const [model, meta] of Object.entries(modelMeta)) {
          const safeMeta = (meta && typeof meta === "object") ? meta : {};
          state.modelMetaByModel[model] = safeMeta;
          const numCtxMax = Number((safeMeta && safeMeta.num_ctx_max) || 0);
          if (Number.isFinite(numCtxMax) && numCtxMax >= 256) {
            state.modelMaxNumCtxByModel[model] = Math.trunc(numCtxMax);
          }
        }

        state.models = Array.isArray(serverModels) ? [...serverModels] : [];
        const winner = rebuildModelSelect(currentSelection, !currentSelection);
        if (!currentSelection && winner) saveModel(winner);
        updateModelBadges(data);

        let info = `${state.models.length} μοντέλα Ollama Cloud/API · ταξινόμηση: καλύτερο → χειρότερο · πηγή: ${data.source || "-"}`;
        if (data.refresh_in_progress) info += " · ανανέωση σε εξέλιξη";
        if (winner && state.models.length) info += ` · 🏆 ${winner} (${getSortCriterionLabel(state.modelSortCriterion)})`;
        if (data.models_with_context != null) info += ` · ${data.models_with_context}/${state.models.length} με Max Length metadata`;
        if (data.last_error)  info += ` · ⚠ ${data.last_error}`;
        if (!serverModels.length) info += " · δεν βρέθηκε online official λίστα";
        els.modelInfo.textContent = info;
        syncNumCtxInputForSelectedModel();
        refreshHelperControls(getSavedHelperModel(Array.isArray(state.models) ? state.models : []) || "");
        ensureSelectedModelMeta(getSelectedModelKey());

      } catch (_) {
        state.modelMetaByModel = {};
        state.modelMaxNumCtxByModel = {};
        state.models = [];
        populateModelSelect([], "", "");
        updateHelperModelSelect();
        updateModelBadges({ source: "error", last_error: "Αποτυχία /api/models" });
        els.modelInfo.textContent = "Αποτυχία φόρτωσης official Ollama direct API models.";
        syncNumCtxInputForSelectedModel();
      }
    }

    async function waitForModelsRefresh(previousTs = 0) {
      const deadline = Date.now() + 45000;
      while (Date.now() < deadline) {
        try {
          const resp = await fetch("/api/models");
          const data = await resp.json();
          const ts = Number(data.last_refresh_ts || 0) || 0;
          if (!data.refresh_in_progress && (!previousTs || ts >= previousTs)) {
            return data;
          }
        } catch (_) {}
        await new Promise(resolve => setTimeout(resolve, MODEL_REFRESH_POLL_MS));
      }
      return null;
    }

    async function refreshModels(showNotice = false) {
      try {
        const previousTs = state.lastModelsRefreshTs || 0;
        els.modelInfo.textContent = "Ανανέωση όλων των διαθέσιμων official Ollama direct API models...";
        const resp = await fetch("/api/refresh-models", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ force: true }),
        });
        try {
          const data = await resp.json();
          if (data && data.last_refresh_ts != null) {
            state.lastModelsRefreshTs = Number(data.last_refresh_ts || 0) || state.lastModelsRefreshTs;
          }
        } catch (_) {}
        await waitForModelsRefresh(previousTs);
        await loadModels();
        if (showNotice) renderSystemNotice(`Ανανεώθηκαν ${state.models.length} official Ollama direct API models.`);
      } catch (_) {
        updateModelBadges({ source: "error", last_error: "Αποτυχία ανανέωσης" });
        renderSystemNotice("Αποτυχία ανανέωσης official Ollama direct API models.");
      }
    }

    // ── Session management ────────────────────────────────────────────────────

    async function loadSession() {
      try {
        const resp = await fetch("/api/session");
        const data = await resp.json();

        els.messages.innerHTML = "";
        state.chatHistory      = [];
        resetReasoningPanel(true);

        if (!data.history || !data.history.length) { renderEmptyState(); return; }

        for (const item of data.history) {
          createMessage(item.role, item.content, item.attachments || []);
          state.chatHistory.push({ role: item.role, content: item.content, time: nowString() });
        }
      } catch (_) {
        renderSystemNotice("Αποτυχία φόρτωσης session.");
      }
    }

    async function clearChat() {
      let serverOk = false;
      let serverError = "";

      try {
        const resp = await fetch("/api/reset-chat", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
        });
        let data = {};
        try { data = await resp.json(); } catch (_) {}
        if (!resp.ok || data.ok === false) {
          throw new Error((data && data.error) || `HTTP ${resp.status}`);
        }
        serverOk = true;
      } catch (err) {
        serverError = (err && err.message) ? err.message : String(err || "Άγνωστο σφάλμα");
      }

      try {
        state.selectedFiles = [];
        state.chatHistory   = [];
        state.currentAssistantNode = null;
        state.currentThinkingText = "";
        state.reasoningStreamCompleted = false;
        resetReasoningPanel(true);
        renderSelectedFiles();
        renderEmptyState();
        if (serverOk) {
          renderSystemNotice("Το chat και τα προσωρινά αρχεία καθαρίστηκαν.");
        } else {
          renderSystemNotice(`Το chat καθαρίστηκε τοπικά, αλλά ο server δεν ολοκλήρωσε πλήρως τον καθαρισμό: ${serverError}`);
        }
      } catch (uiErr) {
        const uiMessage = (uiErr && uiErr.message) ? uiErr.message : String(uiErr || "Άγνωστο σφάλμα UI");
        renderSystemNotice(`Αποτυχία καθαρισμού chat: ${uiMessage}`);
      }
    }

    // ── Export chat ───────────────────────────────────────────────────────────

    function exportChat() {
      if (!state.chatHistory.length) {
        renderSystemNotice("Δεν υπάρχει ιστορικό για εξαγωγή."); return;
      }
      const model = els.modelSelect.value || "unknown";
      const date  = new Date().toLocaleString("el-GR");
      let md = `# Ollama Chat Export\n\n**Μοντέλο:** ${model}  \n**Ημερομηνία:** ${date}\n\n---\n\n`;

      for (const item of state.chatHistory) {
        md += `## ${item.role === "user" ? "👤 Χρήστης" : "🤖 Assistant"}`;
        md += `  \n*${item.time}*\n\n${item.content}\n\n---\n\n`;
      }

      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `ollama-chat-${new Date().toISOString().slice(0, 10)}.md`;
      // Append to DOM, click, then remove — required for Firefox
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }

    // ── Streaming controls ────────────────────────────────────────────────────

    function setControlsDisabled(active) {
      const controls = [
        els.modelSearchInput, els.modelSelect, els.thinkModeSelect, els.ensembleModeSelect,
        els.helperSearchInput, els.helperModelSelect, els.systemPrompt, els.fileInput,
        els.refreshModelsBtn, els.clearFilesBtn, els.resetSystemPromptBtn,
        els.copySystemPromptBtn, els.themeToggleBtn, els.clearChatBtn,
        els.reloadSessionBtn, els.userInput, els.sendBtn,
        els.exportChatBtn, els.autoScrollBtn,
        els.paramTemp, els.paramTopP, els.paramSeed, els.paramNumCtx,
        els.clearNumCtxBtn, els.resetParamsBtn,
        els.apiKeyInput, els.saveApiKeyBtn, els.clearApiKeyBtn,
      ];
      for (const el of controls) if (el) el.disabled = active;
      if (els.stopBtn) els.stopBtn.disabled = !active;
    }

    function finalizeStream(completionLabel = "") {
      state.isStreaming = false;
      setControlsDisabled(false);
      refreshHelperControls();
      if (els.stopBtn)     els.stopBtn.disabled     = true;
      if (els.streamBadge) {
        els.streamBadge.textContent = "Έτοιμο";
        els.streamBadge.className   = "badge ok";
        // Reset back to neutral after 4s
        setTimeout(() => {
          if (!state.isStreaming && els.streamBadge) {
            els.streamBadge.textContent = "Έτοιμο";
            els.streamBadge.className   = "badge";
          }
        }, 4000);
      }
      if (completionLabel && els.helperText) {
        els.helperText.textContent = completionLabel;
      }
    }

    function setStreamState(active, label = null) {
      state.isStreaming           = active;
      setControlsDisabled(active);
      els.streamBadge.textContent = label || (active ? "Streaming..." : "Έτοιμο");
      els.streamBadge.className   = "badge" + (active ? " warn" : "");
    }

    function stopStreaming() {
      if (state.abortController) state.abortController.abort();
    }

    // ── Send message ──────────────────────────────────────────────────────────

    async function sendMessage() {
      if (state.isStreaming) return;

      const userText     = els.userInput.value.trim();
      const model        = els.modelSelect.value;
      const thinkMode    = els.thinkModeSelect ? els.thinkModeSelect.value : "on";
      const systemPrompt = els.systemPrompt.value;

      if (!userText) { els.userInput.focus(); renderSystemNotice("Γράψε πρώτα το user prompt."); return; }
      if (!model)    { renderSystemNotice("Δεν υπάρχει επιλεγμένο μοντέλο."); return; }

      let attachmentsPayload = [];
      try {
        attachmentsPayload = await collectFilesPayload();
      } catch (err) {
        renderSystemNotice(`Σφάλμα αρχείων: ${err.message || err}`); return;
      }

      const optimisticAttachments = state.selectedFiles.map(f => ({
        name: f.name,
        kind: (f.type || "").startsWith("image/") ? "image" : "document",
      }));

      createMessage("user", userText, optimisticAttachments);
      state.chatHistory.push({ role: "user", content: userText, time: nowString() });

      els.userInput.value         = "";
      els.charCounter.textContent = "0 χαρ. / 0 λέξεις";
      els.charCounter.className   = "char-counter";
      state.selectedFiles         = [];
      els.fileInput.value         = "";
      renderSelectedFiles();

      const assistantMsg         = createMessage("assistant", "", []);
      state.currentAssistantNode = assistantMsg.body;
      state.abortController      = new AbortController();
      resetReasoningPanel(true);
      state.reasoningStreamCompleted = false;

      const ensembleMode = normalizeEnsembleMode((els.ensembleModeSelect && els.ensembleModeSelect.value) || state.ensembleMode || "auto");
      const manualHelperModel = ensembleMode === "manual"
        ? String((els.helperModelSelect && els.helperModelSelect.value) || "").trim()
        : "";
      if (ensembleMode === "manual" && !manualHelperModel) {
        renderSystemNotice("Επίλεξε helper model από τη λίστα πριν στείλεις μήνυμα.");
        if (state.currentAssistantNode && state.currentAssistantNode.parentElement) {
          state.currentAssistantNode.parentElement.remove();
        }
        state.currentAssistantNode = null;
        state.abortController = null;
        return;
      }

      setStreamState(true, "Streaming...");
      els.helperText.textContent = `Αποστολή προς ${model}…`;
      saveModel(model);   // persist model selection
      if (manualHelperModel) saveHelperModel(manualHelperModel);
      let completionText = "";

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model, think_mode: thinkMode, system_prompt: systemPrompt,
            user_text: userText, attachments: attachmentsPayload,
            options: getModelOptions(),
            ensemble_mode: ensembleMode,
            ensemble_helper_model: manualHelperModel,
            ensemble_auto: ensembleMode === "auto",
          }),
          signal: state.abortController.signal,
        });

        if (!response.ok) {
          let serverError = `HTTP ${response.status}`;
          try { const d = await response.json(); if (d.error) serverError = d.error; } catch (_) {}
          throw new Error(serverError);
        }
        if (!response.body) throw new Error("Η ροή απάντησης δεν είναι διαθέσιμη.");

        const reader   = response.body.getReader();
        const decoder  = new TextDecoder("utf-8");
        let buffer       = "";
        let finalText    = "";
        let finalThinking = "";
        const streamStartMs = Date.now();

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.trim()) continue;
            let payload = null;
            try { payload = JSON.parse(line); } catch { continue; }

            if (payload.type === "meta") {
              if (payload.ensemble && payload.ensemble.enabled && payload.ensemble.helper_model && els.helperText) {
                const roleLabel = payload.ensemble.role_label || payload.ensemble.role || "helper";
                const reasonLabel = payload.ensemble.selection_reason ? ` · ${payload.ensemble.selection_reason}` : "";
                els.helperText.textContent = `🤝 Ensemble: ${payload.ensemble.primary_model || model} + ${payload.ensemble.helper_model} (${roleLabel}${reasonLabel})`;
              } else if (payload.ensemble && payload.ensemble.mode === "manual" && els.helperText) {
                els.helperText.textContent = "🤝 Manual helper ενεργό";
              }
              if (payload.warnings && payload.warnings.length) {
                renderSystemNotice(payload.warnings.join("\n"));
              }
            } else if (payload.type === "thinking") {
              state.reasoningStreamCompleted = false;
              finalThinking += payload.content || "";
              renderAssistantStreamingView(finalText, finalThinking, false);
              els.streamBadge.textContent = "🧠 Thinking...";
              showLiveTokenStats(finalThinking, streamStartMs, "Thinking");
              scrollToBottom();
            } else if (payload.type === "thinking_done") {
              state.reasoningStreamCompleted = true;
              if (finalThinking.trim()) {
                updateReasoningPanel(finalThinking, true, false);
              }
            } else if (payload.type === "delta") {
              finalText += payload.content || "";
              renderAssistantStreamingView(finalText, finalThinking, false);
              if (!finalText.length && finalThinking.length) {
                els.streamBadge.textContent = "🧠 Thinking...";
                showLiveTokenStats(finalThinking, streamStartMs, "Thinking");
              } else {
                els.streamBadge.textContent = "✍️ Generating...";
                showLiveTokenStats(finalText, streamStartMs, "Generating");
              }
              scrollToBottom();
            } else if (payload.type === "error") {
              throw new Error(payload.error || "Άγνωστο σφάλμα.");
            } else if (payload.type === "done") {
              if (payload.elapsed_sec != null) {
                completionText = `✅ ${payload.elapsed_sec.toFixed(2)}s`;
              }
              if (payload.token_stats) {
                showTokenStats(payload.token_stats);
                const realTps = Number(payload.token_stats.tokens_per_sec || 0);
                if (payload.elapsed_sec != null) {
                  completionText += ` · ⚡ ${realTps.toFixed(1)} tok/s`;
                }
                els.streamBadge.textContent = `⚡ ${realTps.toFixed(1)} tok/s`;
                els.streamBadge.className = "badge ok";
              }
              finalizeStream(completionText);
            }
          }
        }

        const displayText = finalThinking.trim()
          ? composeDisplayContent(finalText, finalThinking)
          : finalText;

        if (!finalText.trim() && !finalThinking.trim()) {
          renderMessageContent(
            state.currentAssistantNode,
            "Δεν επιστράφηκε κείμενο. Έλεγξε το API key από το GUI/settings file και αν το μοντέλο είναι διαθέσιμο στο direct cloud catalog."
          );
          resetReasoningPanel(true);
        } else {
          renderAssistantStreamingView(finalText, finalThinking, true);
          state.chatHistory.push({ role: "assistant", content: displayText, time: nowString() });
        }

      } catch (err) {
        const errText = err && err.name === "AbortError"
          ? "Η ροή σταμάτησε από τον χρήστη."
          : `Σφάλμα: ${err && err.message ? err.message : String(err)}`;
        renderMessageContent(state.currentAssistantNode, errText);
        resetReasoningPanel(true);
        renderSystemNotice(errText);
      } finally {
        state.currentAssistantNode = null;
        state.abortController      = null;
        finalizeStream(completionText);
      }
    }

    function generateBrowserSessionId() {
      try {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
          return window.crypto.randomUUID();
        }
      } catch (_) {}
      return `browser_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    }

    function getOrCreateBrowserSessionId() {
      try {
        const saved = sessionStorage.getItem(BROWSER_SESSION_KEY);
        if (saved) return saved;
        const created = generateBrowserSessionId();
        sessionStorage.setItem(BROWSER_SESSION_KEY, created);
        return created;
      } catch (_) {
        return generateBrowserSessionId();
      }
    }

    function postBrowserLifecycle(eventName, useBeacon = false) {
      const sessionId = String(state.browserSessionId || "").trim();
      if (!sessionId) return;
      const payload = JSON.stringify({ session_id: sessionId, event: eventName });
      if (useBeacon && navigator.sendBeacon) {
        try {
          const blob = new Blob([payload], { type: "application/json" });
          navigator.sendBeacon("/api/browser-session", blob);
          return;
        } catch (_) {}
      }
      fetch("/api/browser-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: true,
      }).catch(() => {});
    }

    function startBrowserHeartbeat() {
      if (state.browserHeartbeatTimer) {
        clearInterval(state.browserHeartbeatTimer);
      }
      state.browserHeartbeatTimer = setInterval(() => {
        postBrowserLifecycle("heartbeat", false);
      }, BROWSER_HEARTBEAT_MS);
    }

    function setupBrowserLifecycle() {
      state.browserSessionId = getOrCreateBrowserSessionId();
      postBrowserLifecycle("open", false);
      startBrowserHeartbeat();
      window.addEventListener("pageshow", () => postBrowserLifecycle("open", false));
      window.addEventListener("pagehide", () => postBrowserLifecycle("close", true));
      window.addEventListener("beforeunload", () => postBrowserLifecycle("close", true));
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
          postBrowserLifecycle("heartbeat", false);
        }
      });
    }

    // ── Theme ─────────────────────────────────────────────────────────────────

    function getSavedTheme() {
      try { const t = localStorage.getItem(THEME_KEY); return t === "light" ? "light" : "dark"; }
      catch { return "dark"; }
    }

    function switchPrismTheme(theme) {
      const dark  = document.getElementById("prismDark");
      const light = document.getElementById("prismLight");
      if (!dark || !light) return;
      if (theme === "light") {
        dark.disabled  = true;
        light.disabled = false;
      } else {
        light.disabled = true;
        dark.disabled  = false;
      }
      // Re-highlight ολόκληρη η σελίδα μετά το CSS swap
      requestAnimationFrame(() => {
        if (window.Prism) {
          document.querySelectorAll(".code-pre code[class*='language-']").forEach(node => {
            try { Prism.highlightElement(node); } catch (_) {}
          });
        }
      });
    }

    function applyTheme(theme) {
      state.theme = theme === "light" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", state.theme);
      try { localStorage.setItem(THEME_KEY, state.theme); } catch (_) {}
      els.themeToggleBtn.textContent = state.theme === "light" ? "🌙 Dark Theme" : "☀️ Light Theme";
      switchPrismTheme(state.theme);
    }

    function toggleTheme() {
      applyTheme(state.theme === "light" ? "dark" : "light");
    }

    // ── System prompt helpers ─────────────────────────────────────────────────

    function resetSystemPrompt() {
      els.systemPrompt.value = DEFAULT_SYSTEM_PROMPT;
      renderSystemNotice("System prompt επανήλθε στην προεπιλογή.");
    }

    async function copySystemPrompt() {
      try {
        await navigator.clipboard.writeText(els.systemPrompt.value || "");
        renderSystemNotice("System prompt αντιγράφηκε στο clipboard.");
      } catch {
        renderSystemNotice("Αποτυχία αντιγραφής.");
      }
    }

    // ── Auto-scroll ───────────────────────────────────────────────────────────

    function toggleAutoScroll() {
      state.autoScroll = !state.autoScroll;
      els.autoScrollBtn.textContent = `📜 Auto-Scroll: ${state.autoScroll ? "ON" : "OFF"}`;
      els.autoScrollBtn.style.opacity = state.autoScroll ? "1" : "0.6";
      updateScrollToBottomBtn();
      if (state.autoScroll) scrollToBottom(true);
    }

    // ── Char counter ──────────────────────────────────────────────────────────

    function updateCharCounter() {
      const text  = els.userInput.value;
      const chars = text.length;
      const words = countWords(text);
      els.charCounter.textContent = `${chars.toLocaleString("el-GR")} χαρ. / ${words} λέξεις`;
      els.charCounter.className   = `char-counter${chars > CHAR_WARN ? " warn" : ""}`;
    }

    // ── Event listeners ───────────────────────────────────────────────────────

    els.fileInput.addEventListener("change", (e) => addFiles(e.target.files));

    els.sendBtn.addEventListener("click",              sendMessage);
    els.stopBtn.addEventListener("click",              stopStreaming);
    els.resetSystemPromptBtn.addEventListener("click", resetSystemPrompt);
    els.copySystemPromptBtn.addEventListener("click",  copySystemPrompt);
    els.themeToggleBtn.addEventListener("click",       toggleTheme);
    els.exportChatBtn.addEventListener("click",        exportChat);
    els.autoScrollBtn.addEventListener("click",        toggleAutoScroll);
    els.scrollToBottomBtn.addEventListener("click",    () => scrollToBottom(true));
    els.resetParamsBtn.addEventListener("click",       resetParams);
    els.clearFilesBtn.addEventListener("click", () => {
      state.selectedFiles = []; els.fileInput.value = ""; renderSelectedFiles();
    });
    els.clearChatBtn.addEventListener("click",    clearChat);
    els.reloadSessionBtn.addEventListener("click", loadSession);
    if (els.toggleReasoningBtn) {
      els.toggleReasoningBtn.addEventListener("click", () => {
        const hasContent = Boolean(((els.reasoningContent && els.reasoningContent.textContent) || "").trim());
        const currentlyVisible = hasContent && (state.reasoningPanelVisible || (state.reasoningAutoOpen && !state.reasoningUserCollapsed));
        if (currentlyVisible) {
          state.reasoningPanelVisible = false;
          state.reasoningAutoOpen = false;
          state.reasoningUserCollapsed = true;
        } else {
          state.reasoningPanelVisible = true;
          state.reasoningAutoOpen = false;
          state.reasoningUserCollapsed = false;
        }
        applyReasoningPanelVisibility();
      });
    }
    if (els.saveApiKeyBtn) els.saveApiKeyBtn.addEventListener("click", saveApiKey);
    if (els.clearApiKeyBtn) els.clearApiKeyBtn.addEventListener("click", clearApiKey);
    if (els.apiKeyInput) {
      els.apiKeyInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); saveApiKey(); }
      });
    }
    els.refreshModelsBtn.addEventListener("click", () => refreshModels(true));
    if (els.modelSortSelect) {
      els.modelSortSelect.addEventListener("change", () => {
        state.modelSortCriterion = els.modelSortSelect.value || "overall";
        saveSortCriterion(state.modelSortCriterion);
        const winner = rebuildModelSelect("", true);
        if (winner) saveModel(winner);
        let info = `${state.models.length} μοντέλα Ollama Cloud/API · ταξινόμηση: καλύτερο → χειρότερο`;
        if (winner) info += ` · 🏆 ${winner} (${getSortCriterionLabel(state.modelSortCriterion)})`;
        els.modelInfo.textContent = info;
      });
    }
    if (els.modelSearchInput) {
      els.modelSearchInput.addEventListener("input", () => {
        const previous = String(els.modelSelect.value || "").trim();
        populateModelSelect(sortModelsByCriterion(Array.isArray(state.models) ? [...state.models] : [], state.modelSortCriterion), "", previous, {
          preferWinner: false,
          allowSavedModel: true,
          searchText: els.modelSearchInput.value,
        });
        updateModelBadges();
      });
      els.modelSearchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && els.modelSelect && els.modelSelect.options.length > 0) {
          e.preventDefault();
          const first = els.modelSelect.options[0];
          if (first && first.value) {
            els.modelSelect.value = first.value;
            els.modelSelect.dataset.currentValue = first.value;
            saveModel(first.value);
            updateModelBadges();
            syncNumCtxInputForSelectedModel();
            ensureSelectedModelMeta(first.value);
            refreshHelperControls();
          }
        }
      });
    }
    if (els.ensembleModeSelect) {
      els.ensembleModeSelect.addEventListener("change", () => {
        const mode = normalizeEnsembleMode(els.ensembleModeSelect.value);
        els.ensembleModeSelect.value = mode;
        saveEnsembleMode(mode);
        refreshHelperControls();
      });
    }
    if (els.helperSearchInput) {
      els.helperSearchInput.addEventListener("input", () => {
        updateHelperModelSelect();
      });
    }
    if (els.helperModelSelect) {
      els.helperModelSelect.addEventListener("change", () => {
        const helper = String(els.helperModelSelect.value || "").trim();
        els.helperModelSelect.dataset.currentValue = helper;
        saveHelperModel(helper);
        if (!state.isStreaming && state.ensembleMode === "manual" && els.helperText) {
          els.helperText.textContent = helper ? `🤝 Manual helper: ${helper}` : "🤝 Manual helper: επίλεξε δεύτερο μοντέλο";
        }
      });
    }
    els.modelSelect.addEventListener("change", () => {
      const selectedModel = String(els.modelSelect.value || "").trim();
      els.modelSelect.dataset.currentValue = selectedModel;
      updateModelBadges();
      saveModel(selectedModel);
      syncNumCtxInputForSelectedModel();
      ensureSelectedModelMeta(selectedModel);
      refreshHelperControls();
      if (selectedModel && els.modelSearchInput) {
        els.modelSearchInput.blur();
      }
      if (els.modelSelect) {
        els.modelSelect.blur();
      }
    });

    // Char counter + focus reset
    els.userInput.addEventListener("input", updateCharCounter);
    els.userInput.addEventListener("focus", () => {
      if (!state.isStreaming) els.helperText.textContent = DEFAULT_HELPER;
    });

    // Keyboard shortcuts: Enter = send, Shift+Enter = newline, Ctrl+Enter = send
    els.userInput.addEventListener("keydown", (e) => {
      const send = (e.key === "Enter" && !e.shiftKey) || (e.key === "Enter" && e.ctrlKey);
      if (send) { e.preventDefault(); sendMessage(); }
    });

    // Scroll-to-bottom button visibility
    els.messages.addEventListener("scroll", updateScrollToBottomBtn);

    // ── Initialisation ────────────────────────────────────────────────────────

    applyTheme(getSavedTheme());
    if (els.modelSortSelect) {
      els.modelSortSelect.value = getSavedSortCriterion();
      state.modelSortCriterion = els.modelSortSelect.value || "overall";
    }
    state.ensembleMode = getSavedEnsembleMode();
    if (els.ensembleModeSelect) {
      els.ensembleModeSelect.value = state.ensembleMode;
    }
    loadParams();
    applyReasoningPanelVisibility();
    setupBrowserLifecycle();
    loadAppConfig();
    loadModels().finally(() => {
      refreshHelperControls(getSavedHelperModel(Array.isArray(state.models) ? state.models : []) || "");
    });
    loadSession();
    renderSystemNotice("🔄 Αυτόματη ανανέωση official direct API models σε εξέλιξη…");
    // Cloud API health — immediate check + polling
    pollBackendHealth();
    setInterval(pollBackendHealth, HEALTH_POLL_MS);

    // Αν η online απογραφή ολοκληρωθεί μετά το πρώτο paint, ενημέρωσε το dropdown αυτόματα και ενημέρωσε τον χρήστη.
    (function pollForOnlineModels() {
      let attempts = 0;
      let announced = false;
      const MAX_ATTEMPTS = 30; // 30 × 3s = 90s
      const timer = setInterval(async () => {
        attempts++;
        try {
          const resp = await fetch("/api/models");
          const data = await resp.json();
          if (data.source === "official-online") {
            clearInterval(timer);
            await loadModels();
            announced = true;
            renderSystemNotice(`✅ Αυτόματο Refresh Models: βρέθηκαν ${data.models?.length || 0} official direct API models.`);
          } else if (!data.refresh_in_progress && data.last_error) {
            clearInterval(timer);
            announced = true;
            await loadModels();
            renderSystemNotice(`❌ Αποτυχία αυτόματης ανανέωσης official direct API models: ${data.last_error}`);
          }
        } catch (_) {}
        if (attempts >= MAX_ATTEMPTS) {
          clearInterval(timer);
          if (!announced) {
            renderSystemNotice("⚠ Δεν ολοκληρώθηκε έγκαιρα η αυτόματη ανανέωση official direct API models.");
          }
        }
      }, 3000);
    })();
  </script>
</body>
</html>"""

    # Replace server-side placeholders
    html_doc = (
        html_doc
        .replace("__APP_TITLE__",                    html.escape(APP_TITLE))
        .replace("__SYSTEM_PROMPT__",                html.escape(system_prompt))
        .replace("__DEFAULT_SYSTEM_PROMPT_JSON__",   safe_prompt_json)
        .replace("__ACCEPTED_TYPES__",               accepted_types)
    )
    return html_doc


# ─────────────────────────── HTTP handler ────────────────────────────────────

class AppHandler(BaseHTTPRequestHandler):
    """HTTP request handler για το chat app."""

    server_version = "OllamaCloudChat/5.0"

    def log_message(self, format: str, *args) -> None:
        return  # Σιωπηλά logs — αποφυγή θορύβου ανά request.

    # ── GET ──────────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        try:
            self._handle_GET()
        except Exception as exc:
            if is_client_disconnect_error(exc):
                return
            log.error("Unexpected GET error: %s", exc)
            try:
                json_response(self, {"error": "Internal server error"}, status=500)
            except Exception:
                pass

    def _handle_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            body = serve_index_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",   "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control",  "no-store")
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/startup":
            body = serve_startup_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type",   "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control",  "no-store")
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/startup-events":
            # SSE stream — παραμένει ανοιχτό μέχρι READY event
            q = STARTUP.subscribe()
            self.send_response(200)
            self.send_header("Content-Type",     "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control",    "no-cache")
            self.send_header("Connection",       "keep-alive")
            self.send_header("X-Accel-Buffering","no")
            _send_security_headers(self)
            self.end_headers()
            try:
                while True:
                    try:
                        event = q.get(timeout=20)
                        data = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        if event.get("level") == "READY":
                            break
                    except _queue.Empty:
                        # keepalive comment
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                STARTUP.unsubscribe(q)
            return

        if self.path.startswith("/generated-code/"):
            ensure_generated_code_dir()
            requested_name = urllib.parse.unquote(self.path.split("?", 1)[0][len("/generated-code/"):])
            safe_name = Path(requested_name).name
            file_path = (GENERATED_CODE_DIR / safe_name).resolve()
            generated_root = str(GENERATED_CODE_DIR.resolve()) + os.sep
            if (not safe_name) or (not str(file_path).startswith(generated_root)) or (not file_path.exists()) or (not file_path.is_file()):
                json_response(self, {"error": "Το ζητούμενο generated .py αρχείο δεν βρέθηκε."}, status=404)
                return
            raw = file_path.read_bytes()
            download_name = extract_original_generated_filename(safe_name)
            self.send_response(200)
            self.send_header("Content-Type", "text/x-python; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Cache-Control", "no-store")
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(raw)
            return

        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        if self.path == "/api/models":
            with REGISTRY.lock:
                no_models = not REGISTRY.models
                in_progress = REGISTRY.refresh_in_progress

            if no_models and in_progress:
                wait_for_model_refresh(timeout=60.0)
            elif no_models:
                refresh_models(force=True, wait_if_running=True)

            json_response(self, REGISTRY.as_dict())
            return

        if self.path.startswith("/api/model-details"):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query or "")
            model = normalize_model_name(str((query.get("model") or [""])[0]).strip())
            force = str((query.get("force") or [""])[0]).strip().lower() in {"1", "true", "yes", "on"}
            if not model:
                json_response(self, {"error": "Δεν δόθηκε μοντέλο για metadata."}, status=400)
                return
            meta = get_or_fetch_model_meta(model, force=force)
            if not meta:
                json_response(self, {"error": f"Δεν βρέθηκαν metadata για το μοντέλο {model}."}, status=404)
                return
            json_response(self, {"model": model, "meta": meta})
            return

        if self.path == "/api/session":
            json_response(self, {"history": get_history_payload()})
            return

        if self.path == "/api/app-config":
            payload = APP_CONFIG.as_public_dict()
            payload["api_key_source"] = get_ollama_api_key_source()
            payload["config_path"] = str(APP_CONFIG_FILE)
            json_response(self, payload)
            return

        if self.path == "/api/health":
            configured = is_direct_cloud_api_configured()
            json_response(self, {
                "status": "ok" if configured else "unavailable",
                "mode": "direct-cloud",
                "cloud_api_configured": configured,
                "api_key_source": get_ollama_api_key_source(),
                "server_uptime_sec": round(time.time() - _SERVER_START_TIME, 1),
            }, status=200 if configured else 503)
            return

        json_response(self, {"error": "Not found"}, status=404)

    # ── POST ─────────────────────────────────────────────────────────────────

    def do_POST(self) -> None:
        try:
            self._handle_POST()
        except Exception as exc:
            if is_client_disconnect_error(exc):
                return
            log.exception("Unexpected POST error: %s", exc)
            try:
                json_response(self, {"error": "Internal server error"}, status=500)
            except Exception:
                pass

    def _handle_POST(self) -> None:
        if self.path == "/api/browser-session":
            payload = safe_read_json(self)
            if payload.get("__error__") == "request_too_large":
                json_response(self, {"error": "Αίτημα πολύ μεγάλο."}, status=413)
                return
            session_id = str(payload.get("session_id", "") or "").strip()[:128]
            event_name = str(payload.get("event", "heartbeat") or "heartbeat").strip().lower()
            if session_id:
                if event_name in {"open", "heartbeat", "visible", "focus"}:
                    BROWSER_MONITOR.touch(session_id)
                elif event_name in {"close", "hidden", "blur"}:
                    BROWSER_MONITOR.close(session_id)
            json_response(self, {"ok": True, "active_sessions": BROWSER_MONITOR.active_count()})
            return

        if self.path == "/api/refresh-models":
            payload = safe_read_json(self)
            if payload.get("__error__") == "request_too_large":
                json_response(self, {"error": "Αίτημα πολύ μεγάλο."}, status=413)
                return
            refresh_models(force=bool(payload.get("force", True)), wait_if_running=True)
            json_response(self, REGISTRY.as_dict())
            return

        if self.path == "/api/reset-chat":
            try:
                SESSION.reset()
                json_response(self, {"ok": True})
            except Exception as exc:
                json_response(self, {"error": f"Αποτυχία εκκαθάρισης session: {exc}"}, status=500)
            return

        if self.path == "/api/app-config":
            payload = safe_read_json(self)
            if payload.get("__error__") == "request_too_large":
                json_response(self, {"error": "Αίτημα πολύ μεγάλο."}, status=413)
                return
            try:
                key = str(payload.get("ollama_api_key", "") or "")
                config = save_app_config_to_disk(key)
                json_response(self, {"ok": True, "config": config.as_public_dict(), "config_path": str(APP_CONFIG_FILE)})
            except Exception as exc:
                json_response(self, {"error": f"Αποτυχία αποθήκευσης settings file: {exc}"}, status=500)
            return

        if self.path == "/api/execute-python":
            payload = safe_read_json(self)
            if payload.get("__error__") == "request_too_large":
                json_response(self, {"error": "Αίτημα πολύ μεγάλο."}, status=413)
                return
            code_text = str(payload.get("code", "") or "")
            suggested_filename = str(payload.get("filename", "") or "")
            ok, message = launch_python_code_in_terminal(code_text, suggested_filename=suggested_filename)
            json_response(self, {"ok": ok, "message": message} if ok else {"error": message}, status=200 if ok else 400)
            return

        if self.path == "/api/export-python-block":
            payload = safe_read_json(self)
            if payload.get("__error__") == "request_too_large":
                json_response(self, {"error": "Αίτημα πολύ μεγάλο."}, status=413)
                return
            code_text = str(payload.get("code", "") or "")
            suggested_filename = str(payload.get("filename", "") or "")
            try:
                file_info = save_generated_python_file(code_text, suggested_filename=suggested_filename)
                json_response(self, {"ok": True, "file": file_info})
            except Exception as exc:
                json_response(self, {"error": f"Αποτυχία δημιουργίας .py αρχείου: {exc}"}, status=400)
            return

        if self.path == "/api/chat":
            payload = safe_read_json(self)

            if payload.get("__error__") == "request_too_large":
                json_response(
                    self,
                    {"error": "Το αίτημα είναι πολύ μεγάλο. Μείωσε αριθμό ή μέγεθος αρχείων."},
                    status=413,
                )
                return

            model             = normalize_model_name(str(payload.get("model", "")).strip())
            gui_system_prompt = str(payload.get("system_prompt", ""))
            think_mode        = payload.get("think_mode", "on")
            ensemble_mode_raw = str(payload.get("ensemble_mode", "") or "").strip().lower()
            if ensemble_mode_raw not in {"off", "auto", "manual"}:
                ensemble_mode_raw = "auto" if bool(payload.get("ensemble_auto", True)) else "off"
            ensemble_auto     = ensemble_mode_raw == "auto"
            ensemble_helper_model = normalize_model_name(str(payload.get("ensemble_helper_model", "") or "").strip())
            system_prompt, system_prompt_source = get_effective_system_prompt(gui_system_prompt)
            user_text         = str(payload.get("user_text",     "")).strip()
            attachments       = payload.get("attachments", [])

            # Model generation parameters (optional, με validation)
            raw_opts  = payload.get("options", {}) or {}
            model_options: Dict = {}
            try:
                temperature = float(raw_opts.get("temperature", -1))
                if 0.0 <= temperature <= 2.0:
                    model_options["temperature"] = temperature
            except (TypeError, ValueError):
                pass
            try:
                top_p = float(raw_opts.get("top_p", -1))
                if 0.0 < top_p <= 1.0:
                    model_options["top_p"] = top_p
            except (TypeError, ValueError):
                pass
            try:
                seed = int(raw_opts.get("seed", -1))
                if seed >= 0:
                    model_options["seed"] = seed
            except (TypeError, ValueError):
                pass
            try:
                num_ctx = int(raw_opts.get("num_ctx", 0))
                if 256 <= num_ctx <= 1_048_576:
                    model_options["num_ctx"] = num_ctx
            except (TypeError, ValueError):
                pass

            if not model:
                json_response(self, {"error": "Δεν δόθηκε μοντέλο."}, status=400); return
            if not user_text:
                json_response(self, {"error": "Το user prompt πρέπει να δοθεί από εσένα."}, status=400); return
            if attachments and not isinstance(attachments, list):
                json_response(self, {"error": "Μη έγκυρα attachments."}, status=400); return

            try:
                processed_attachments, warnings = prepare_attachments(attachments, model)
            except (ValueError, OSError, AttributeError, TypeError) as exc:
                json_response(self, {"error": str(exc)}, status=400); return

            self.send_response(200)
            self.send_header("Content-Type",  "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection",    "close")
            _send_security_headers(self)
            self.end_headers()

            start_time = time.time()

            try:
                prepared_user_content = build_user_message_content(user_text, processed_attachments)

                user_message: Dict = {"role": "user", "content": prepared_user_content}
                image_b64_list: List[str] = []
                for item in processed_attachments:
                    if item["kind"] == "image" and item["will_send_as_image"]:
                        try:
                            raw_bytes = Path(item["path"]).read_bytes()
                            image_b64_list.append(base64.b64encode(raw_bytes).decode("ascii"))
                        except Exception as img_exc:
                            log.warning("Αδυναμία ανάγνωσης εικόνας %s: %s", item.get("name"), img_exc)
                if image_b64_list:
                    user_message["images"] = image_b64_list

                history_user_item: Dict = {
                    "role":        "user",
                    "content":     user_text,
                    "attachments": [
                        {"name": item["name"], "kind": item["kind"]}
                        for item in processed_attachments
                    ],
                }

                with SESSION.lock:
                    session_messages = list(SESSION.messages)
                    messages = build_messages(system_prompt, session_messages + [user_message])

                if not is_direct_cloud_api_configured():
                    raise RuntimeError(
                        "Λείπει το Ollama Cloud API key. "
                        "Η εφαρμογή τρέχει μόνο σε direct Ollama Cloud API mode. Βάλ'το στο πεδίο API Key του GUI, στο settings file ή στο OLLAMA_API_KEY."
                    )

                ensemble_info: Optional[Dict[str, object]] = None
                final_messages = list(messages)

                if ensemble_mode_raw == "auto":
                    try:
                        ensemble_info = choose_auto_ensemble_helper(model, user_text, processed_attachments)
                    except Exception as ensemble_pick_exc:
                        log.warning("Αποτυχία επιλογής helper model για ensemble: %s", ensemble_pick_exc)
                        ensemble_info = None
                elif ensemble_mode_raw == "manual":
                    try:
                        ensemble_info = choose_manual_ensemble_helper(model, ensemble_helper_model, user_text, processed_attachments)
                    except Exception as ensemble_pick_exc:
                        log.warning("Αποτυχία manual helper model για ensemble: %s", ensemble_pick_exc)
                        ensemble_info = None

                stream_json_line(self, {
                    "type":                "meta",
                    "warnings":            warnings,
                    "attachments":         history_user_item["attachments"],
                    "system_prompt_source": system_prompt_source,
                    "ensemble": {
                        "enabled": bool(ensemble_info),
                        "mode": ensemble_mode_raw,
                        "primary_model": model,
                        "helper_model": str((ensemble_info or {}).get("helper_model") or ""),
                        "criterion": str((ensemble_info or {}).get("criterion") or ""),
                        "role": str((ensemble_info or {}).get("role") or ""),
                        "role_label": str((ensemble_info or {}).get("role_label") or ""),
                        "selection_reason": str((ensemble_info or {}).get("selection_reason") or ""),
                    },
                })

                if ensemble_info:
                    helper_model = str(ensemble_info.get("helper_model") or "").strip()
                    helper_role = str(ensemble_info.get("role") or "cross-checker").strip()
                    helper_meta = {}
                    with REGISTRY.lock:
                        helper_meta = copy.deepcopy(REGISTRY.model_meta.get(helper_model, {}))
                    helper_system = build_helper_system_prompt(model, helper_model, helper_role, dict(ensemble_info.get("traits") or {}))
                    helper_messages = insert_secondary_system_message(messages, helper_system)
                    helper_options = dict(model_options) if model_options else {}
                    if float(helper_options.get("temperature", 0.20) or 0.20) > 0.35:
                        helper_options["temperature"] = 0.20
                    helper_max_ctx = get_model_context_tokens(helper_model, helper_meta)
                    try:
                        requested_ctx = int(helper_options.get("num_ctx") or 0)
                    except Exception:
                        requested_ctx = 0
                    if requested_ctx > 0 and helper_max_ctx > 0:
                        helper_options["num_ctx"] = min(requested_ctx, helper_max_ctx)
                    helper_num_predict = int(_ENSEMBLE_HELPER_MAX_TOKENS_BY_ROLE.get(helper_role, 160) or 160)
                    try:
                        current_num_predict = int(helper_options.get("num_predict") or 0)
                    except Exception:
                        current_num_predict = 0
                    if current_num_predict > 0:
                        helper_options["num_predict"] = min(current_num_predict, helper_num_predict)
                    else:
                        helper_options["num_predict"] = helper_num_predict
                    helper_timeout = int(_ENSEMBLE_HELPER_TIMEOUT_BY_ROLE.get(helper_role, 90) or 90)

                    stream_json_line(self, {
                        "type": "meta",
                        "status": f"🤝 Συμβουλεύομαι helper model {helper_model}…",
                    })

                    helper_think_value = None
                    try:
                        helper_result = direct_cloud_chat_complete(
                            model=helper_model,
                            messages=helper_messages,
                            model_options=helper_options if helper_options else None,
                            think_value=helper_think_value,
                            timeout=helper_timeout,
                        )
                        helper_text = str(helper_result.get("content") or "").strip()
                        if not helper_text:
                            helper_text = str(helper_result.get("thinking") or "").strip()
                        if helper_text:
                            final_messages = insert_secondary_system_message(
                                messages,
                                build_main_ensemble_guidance(helper_model, helper_role, helper_text),
                            )
                            stream_json_line(self, {
                                "type": "meta",
                                "status": f"✅ Έτοιμο το helper guidance από {helper_model}. Ξεκινά το κύριο μοντέλο…",
                            })
                        else:
                            stream_json_line(self, {
                                "type": "meta",
                                "warnings": [
                                    f"Το βοηθητικό ensemble model {helper_model} δεν επέστρεψε guidance και η απάντηση συνεχίζεται μόνο με το κύριο μοντέλο."
                                ],
                                "status": f"⚠️ Το helper model {helper_model} δεν έδωσε guidance. Συνεχίζω με το κύριο μοντέλο…",
                            })
                    except Exception as helper_exc:
                        log.warning("Αποτυχία helper ensemble model %s: %s", helper_model, helper_exc)
                        stream_json_line(self, {
                            "type": "meta",
                            "warnings": [
                                f"Το βοηθητικό ensemble model {helper_model} απέτυχε ({build_friendly_chat_error(helper_exc)}). Η απάντηση συνεχίζεται μόνο με το κύριο μοντέλο."
                            ],
                            "status": f"⚠️ Παράλειψη helper model {helper_model}. Συνεχίζω με το κύριο μοντέλο…",
                        })

                think_value = resolve_think_mode(model, think_mode)

                stream_json_line(self, {
                    "type": "meta",
                    "status": f"🧠 Το κύριο μοντέλο {model} ξεκινά να απαντά…",
                })

                try:
                    response = direct_cloud_chat_stream(
                        model=model,
                        messages=final_messages,
                        model_options=model_options if model_options else None,
                        think_value=think_value,
                    )
                except Exception as exc:
                    if think_value is not None and "think" in str(exc).lower():
                        warnings = list(warnings) + [
                            "Το thinking mode δεν υποστηρίχθηκε από το τρέχον Ollama Cloud API/model και έγινε fallback χωρίς ξεχωριστό reasoning stream."
                        ]
                        response = direct_cloud_chat_stream(
                            model=model,
                            messages=final_messages,
                            model_options=model_options if model_options else None,
                            think_value=None,
                        )
                    else:
                        raise

                collected: List[str] = []
                collected_thinking: List[str] = []
                token_stats: Optional[Dict] = None
                thinking_started = False
                thinking_done_sent = False
                for chunk in response:
                    thinking_piece = extract_chunk_thinking(chunk)
                    if thinking_piece:
                        thinking_started = True
                        collected_thinking.append(thinking_piece)
                        stream_json_line(self, {"type": "thinking", "content": thinking_piece})

                    piece = extract_chunk_content(chunk)
                    if piece:
                        if thinking_started and not thinking_done_sent:
                            stream_json_line(self, {"type": "thinking_done"})
                            thinking_done_sent = True
                        collected.append(piece)
                        stream_json_line(self, {"type": "delta", "content": piece})
                    # Το τελευταίο chunk περιέχει eval_count / eval_duration
                    stats = extract_token_stats(chunk)
                    if stats:
                        token_stats = stats

                if collected_thinking and not thinking_done_sent:
                    stream_json_line(self, {"type": "thinking_done"})

                assistant_text = "".join(collected).strip()
                assistant_thinking = "".join(collected_thinking).strip()
                if not assistant_text and not assistant_thinking:
                    raise RuntimeError(
                        "Το μοντέλο δεν επέστρεψε περιεχόμενο. "
                        "Έλεγξε το API key από το GUI/settings file και αν το μοντέλο είναι διαθέσιμο στο direct cloud catalog."
                    )

                assistant_display_text = compose_display_assistant_text(assistant_text, assistant_thinking)
                elapsed = time.time() - start_time

                with SESSION.lock:
                    SESSION.messages.append(user_message)
                    SESSION.history.append(history_user_item)
                    SESSION.messages.append({
                        "role": "assistant",
                        "content": assistant_text,
                        "thinking": assistant_thinking,
                    })
                    SESSION.history.append({
                        "role": "assistant", "content": assistant_display_text, "attachments": []
                    })
                    # Τήρηση ορίου ιστορικού.
                    if len(SESSION.messages) > MAX_HISTORY_MESSAGES:
                        SESSION.messages[:] = SESSION.messages[-MAX_HISTORY_MESSAGES:]
                    if len(SESSION.history) > MAX_HISTORY_MESSAGES:
                        SESSION.history[:] = SESSION.history[-MAX_HISTORY_MESSAGES:]

                stream_json_line(self, {
                    "type":        "done",
                    "elapsed_sec": elapsed,
                    "token_stats": token_stats,  # None αν το μοντέλο δεν τα επέστρεψε
                })

            except Exception as exc:
                if is_client_disconnect_error(exc):
                    return
                friendly = build_friendly_chat_error(exc)
                log.error("Chat error: %s", exc)
                try:
                    stream_json_line(self, {"type": "error", "error": friendly})
                except Exception:
                    pass
            return

        json_response(self, {"error": "Not found"}, status=404)


# ─────────────────────────── CLI & Entry point ───────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ollama_cloud_chat",
        description=f"{APP_TITLE} — Web chat για Ollama cloud μοντέλα",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--port",               type=int,  default=DEFAULT_PORT,
                        help="Port του web server")
    parser.add_argument("--host",               type=str,  default=HOST,
                        help="Host του web server")
    parser.add_argument("--no-browser",         action="store_true",
                        help="Μην ανοίξεις αυτόματα τον browser")
    parser.add_argument("--log-level",          default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Επίπεδο logging")
    parser.add_argument("--system-prompt-file", type=str,  default="",
                        metavar="FILE",
                        help="Φόρτωση system prompt από εξωτερικό αρχείο .txt")
    return parser.parse_args()


def load_system_prompt_from_file(filepath: str) -> Optional[str]:
    """Φορτώνει system prompt από αρχείο αν δοθεί. Επιστρέφει None αν αποτύχει."""
    if not filepath:
        return None
    path = Path(filepath)
    if not path.exists():
        log.error("Το αρχείο system prompt δεν βρέθηκε: %s", filepath)
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            log.info("📄 System prompt φορτώθηκε από: %s (%d χαρ.)", filepath, len(content))
            return content
        log.warning("Το αρχείο system prompt είναι κενό: %s", filepath)
        return None
    except Exception as exc:
        log.error("Αποτυχία ανάγνωσης system prompt: %s", exc)
        return None


def open_browser_later(url: str, delay: float = 0.9) -> None:
    def _worker() -> None:
        time.sleep(delay)
        webbrowser.open(url, new=2)
    threading.Thread(target=_worker, daemon=True).start()


def _run_initialization(args: argparse.Namespace, port: int) -> None:
    """
    Τρέχει σε background thread αμέσως μετά την εκκίνηση του server.
    Η εφαρμογή ανοίγει αμέσως και η επίσημη online λίστα μοντέλων
    φορτώνεται στο background χωρίς hardcoded fallback models.
    """
    global DEFAULT_SYSTEM_PROMPT

    url = f"http://{HOST}:{port}"

    if args.system_prompt_file:
        custom_prompt = load_system_prompt_from_file(args.system_prompt_file)
        if custom_prompt:
            DEFAULT_SYSTEM_PROMPT = custom_prompt
            slog("INFO", "📄 System prompt: %s (%d χαρ.)", args.system_prompt_file, len(custom_prompt))
        else:
            slog("WARNING", "⚠  Αποτυχία φόρτωσης system prompt — χρήση embedded.")
    else:
        slog("INFO", "📄 System prompt: embedded-in-code")

    slog("INFO", "📎 Αρχεία: drag & drop + file picker")
    slog("INFO", "☁️  Λειτουργία: direct Ollama Cloud API mode")

    if is_direct_cloud_api_configured():
        slog("INFO", "🔐 Ollama Cloud API key: βρέθηκε (στο .py ή στο περιβάλλον)")
    else:
        slog("WARNING", "⚠  Ollama Cloud API key: δεν βρέθηκε — βάλε το από το GUI ή στο %s ή όρισε OLLAMA_API_KEY", APP_CONFIG_FILE)

    ensure_upload_dir()

    with REGISTRY.lock:
        REGISTRY.models              = []
        REGISTRY.model_meta          = {}
        REGISTRY.source              = "initializing"
        REGISTRY.last_refresh_ts     = 0.0
        REGISTRY.last_error          = ""
        REGISTRY.recommended_model   = ""
        REGISTRY.refresh_in_progress = True

    slog("INFO", "🔄 Ανάκτηση όλων των διαθέσιμων official Ollama direct-cloud models…")
    slog("INFO", "✅ Server: %s", url)
    slog("INFO", "🛑 Ctrl+C για τερματισμό.")

    # Redirect αμέσως στην εφαρμογή — χωρίς αναμονή για τα online models
    STARTUP.set_ready(url)

    # Official online model refresh τρέχει ΜΕΤΑ το redirect, στο background
    refresh_models_in_background(force=True)


def main() -> None:
    global HOST

    args = parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    HOST = args.host

    # ── Minimal terminal output ───────────────────────────────────────────────
    sep = "=" * 68
    print(sep)
    print(f"  {APP_TITLE}")
    print(sep)

    port   = find_free_port(HOST, start_port=args.port)
    server = QuietThreadingHTTPServer((HOST, port), AppHandler)
    BROWSER_MONITOR.attach_server(server)
    start_browser_session_watchdog()

    startup_url = f"http://{HOST}:{port}/startup"
    chat_url    = f"http://{HOST}:{port}"

    print(f"  🌐 Server  : {chat_url}")
    print(f"  🚀 Startup : {startup_url}")

    # ── Άνοιγμα browser ΑΜΕΣΩΣ (server τρέχει ήδη) ───────────────────────────
    if not args.no_browser:
        print("  🌍 Άνοιγμα browser…")
        open_browser_later(startup_url, delay=0.25)
    else:
        print("  🚫 --no-browser: ο browser δεν άνοιξε αυτόματα.")

    print("  🛑 Ctrl+C για τερματισμό.")
    print(sep)

    # ── Initialization σε background thread ──────────────────────────────────
    threading.Thread(
        target=_run_initialization,
        args=(args, port),
        daemon=True,
        name="startup-init",
    ).start()

    # ── Server loop ───────────────────────────────────────────────────────────
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Τερματισμός εφαρμογής…")
    finally:
        server.server_close()
        try:
            SESSION.reset()
        except Exception:
            pass
        print("✅ Server έκλεισε.")


if __name__ == "__main__":
    main()
