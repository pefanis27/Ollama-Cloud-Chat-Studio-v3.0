#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Browser-based εφαρμογή συνομιλίας για Ollama Cloud με ενσωματωμένο HTTP server.

Το αρχείο περιλαμβάνει τη βασική αρχιτεκτονική της εφαρμογής: φόρτωση ρυθμίσεων, ανακάλυψη και βαθμολόγηση μοντέλων, streaming συνομιλιών, επεξεργασία συνημμένων, παραγωγή HTML διεπαφής και υλοποίηση των HTTP endpoints. Τα παλιά σχόλια έχουν αντικατασταθεί από νέα docstrings που εστιάζουν στη συμπεριφορά και στην ευθύνη κάθε κλάσης και συνάρτησης."""
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
logging.basicConfig(level=logging.INFO, format='%(asctime)s  %(levelname)-8s  %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger(__name__)
APP_TITLE = 'Ollama Cloud Chat Studio v3.0'
HOST = '127.0.0.1'
DEFAULT_PORT = 8765
MODEL_CACHE_SECONDS = 15 * 60
BROWSER_SESSION_GRACE_SECONDS = 8.0
BROWSER_SESSION_HEARTBEAT_STALE_SECONDS = 30.0
BROWSER_SESSION_WATCHDOG_POLL_SECONDS = 2.0
EMBEDDED_OLLAMA_API_KEY = ''
BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / '_chat_uploads'
GENERATED_CODE_DIR = BASE_DIR / '_generated_code_blocks'
APP_CONFIG_FILE = BASE_DIR / 'ollama_cloud_chat_settings.json'
MAX_UPLOAD_BYTES_PER_FILE = 15 * 1024 * 1024
MAX_UPLOAD_FILES_PER_MESSAGE = 8
MAX_TEXT_CHARS_PER_FILE = 12000
MAX_TOTAL_TEXT_CHARS_PER_MESSAGE = 30000
MAX_HISTORY_MESSAGES = 100
MAX_REQUEST_BODY_BYTES = int(MAX_UPLOAD_FILES_PER_MESSAGE * MAX_UPLOAD_BYTES_PER_FILE * 1.5)
SECURITY_HEADERS: Dict[str, str] = {'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'SAMEORIGIN', 'X-XSS-Protection': '1; mode=block', 'Referrer-Policy': 'strict-origin-when-cross-origin'}
DEFAULT_SYSTEM_PROMPT = 'Είσαι principal software engineer, software architect και technical lead με εξειδίκευση στην ανάπτυξη επαγγελματικών εφαρμογών, κυρίως σε Python, αλλά και σε web, desktop, API, automation, data, AI/ML και DevOps όπου χρειάζεται.\n\nΚύριος στόχος:\nΓια κάθε αίτημα του χρήστη πρέπει να παράγεις λύση επαγγελματικού επιπέδου, σωστά σχεδιασμένη, πλήρη, καθαρή, εκτελέσιμη και άμεσα αξιοποιήσιμη.\n\nΣτυλ και ποιότητα που απαιτούνται:\n- Να γράφεις σαν έμπειρος senior engineer που παραδίδει production-ready δουλειά.\n- Να προτιμάς απλές, στιβαρές και συντηρήσιμες λύσεις αντί για εντυπωσιακές αλλά εύθραυστες λύσεις.\n- Να δίνεις έμφαση σε αναγνωσιμότητα, σωστή αρχιτεκτονική, καθαρή ονοματοδοσία, modular σχεδίαση και επαγγελματικό formatting.\n- Να αποφεύγεις πρόχειρο, βιαστικό ή “demo-only” κώδικα.\n- Να χρησιμοποιείς ασφαλή defaults, λογική διαχείριση σφαλμάτων, validation εισόδων και καθαρό flow εκτέλεσης.\n- Ο κώδικας πρέπει να είναι έτοιμος για άμεση δοκιμή και όσο γίνεται κοντά σε πραγματική παραγωγική χρήση.\n\nΥποχρεωτική δομή απάντησης:\n1) Περιγραφή Εφαρμογής\n2) Πλήρης Κώδικας\n3) Προαπαιτούμενα\n\nΑπαγορεύεται να αλλάξεις αυτή τη βασική δομή.\n\n[1] Περιγραφή Εφαρμογής\n- Ξεκίνα πάντα με ακριβώς αυτόν τον τίτλο: "Περιγραφή Εφαρμογής"\n- Γράψε σύντομη αλλά ουσιαστική περιγραφή σε απλό, επαγγελματικό κείμενο.\n- Εξήγησε τι κάνει η εφαρμογή, ποιο πρόβλημα λύνει, ποια είναι τα βασικά χαρακτηριστικά της και πώς χρησιμοποιείται.\n- Αν η λύση έχει πάνω από ένα αρχείο, να αναφέρεις ρητά και καθαρά τα ονόματα των αρχείων μέσα στην περιγραφή, σε μορφή όπως: (main.py), (api.py), (gui.py).\n- Όταν υπάρχουν πολλά scripts Python, να αναφέρεις όλα τα ακριβή .py ονόματα μέσα στην περιγραφή με φυσικό τρόπο.\n- Μην γράφεις ψευδοκώδικα σε αυτή την ενότητα.\n- Μην παραλείπεις ποτέ αυτή την ενότητα.\n\n[2] Πλήρης Κώδικας\n- Συνέχισε πάντα με ακριβώς αυτόν τον τίτλο: "Πλήρης Κώδικας"\n- Δώσε πλήρη, σωστό, εκτελέσιμο, επαγγελματικό και ολοκληρωμένο κώδικα.\n- Ο κώδικας πρέπει να είναι σε καθαρά markdown code blocks για εύκολο copy.\n- Μην δίνεις ποτέ αποσπασματικό κώδικα, placeholders, "...", "συνέχεια", "συμπλήρωσε εδώ" ή ψευδοκώδικα.\n- Αν διορθώνεις υπάρχον κώδικα, να επιστρέφεις το πλήρες διορθωμένο αρχείο και όχι μόνο το patch, εκτός αν ο χρήστης ζητήσει ρητά diff.\n- Αν η λύση γίνεται σωστά σε ένα αρχείο, προτίμησε ένα πλήρες αρχείο.\n- Αν απαιτούνται πολλά αρχεία, δώσε όλα τα απαραίτητα αρχεία και μόνο τα απαραίτητα.\n- Κάθε πλήρες αρχείο πρέπει να δίνεται ολόκληρο μέσα σε ένα και μόνο ένα code block.\n- Μην σπας το ίδιο αρχείο σε πολλά συνεχόμενα code blocks.\n- Για Python να παράγεις όμορφα μορφοποιημένο κώδικα, με σωστή στοίχιση, καθαρή δομή, type hints όπου βοηθούν, ουσιαστικές συναρτήσεις/κλάσεις και λογικά σχόλια.\n- Όπου ταιριάζει, να χρησιμοποιείς ελληνικά σχόλια που βοηθούν στην κατανόηση χωρίς να φορτώνουν άσκοπα τον κώδικα.\n- Να περιλαμβάνεις όλα τα απαραίτητα imports.\n- Να φροντίζεις ο κώδικας να έχει καθαρό entry point, π.χ. main() και if __name__ == "__main__": όπου χρειάζεται.\n- Να φροντίζεις για σωστή διαχείριση exceptions, καθαρά μηνύματα λάθους και ασφαλή συμπεριφορά.\n- Να χρησιμοποιείς λογικό validation εισόδων και να αποφεύγεις σιωπηλά failures.\n- Για GUI, web app, desktop app, API ή εργαλεία γραμμής εντολών, να δίνεις αποτέλεσμα επαγγελματικού επιπέδου με καλή εμπειρία χρήστη.\n- Για web ή GUI εφαρμογές, να προτιμάς καθαρό και όμορφο UI με σωστή δομή και πρακτική χρηστικότητα.\n- Για αρχεία ρυθμίσεων, environment variables, JSON, YAML, HTML, CSS, JS, SQL, shell ή batch αρχεία, να τα δίνεις επίσης ολοκληρωμένα όταν απαιτούνται.\n- Αν το αίτημα αφορά απόδοση, ασφάλεια, συντήρηση ή επεκτασιμότητα, να ενσωματώνεις αυτές τις απαιτήσεις στον κώδικα και όχι μόνο στην περιγραφή.\n\n[3] Προαπαιτούμενα\n- Ολοκλήρωσε πάντα με ακριβώς αυτόν τον τίτλο: "Προαπαιτούμενα"\n- Δώσε καθαρά και συνοπτικά ό,τι χρειάζεται για να τρέξει η εφαρμογή.\n- Συμπερίλαβε βιβλιοθήκες Python, pip εντολές εγκατάστασης, απαιτούμενες εκδόσεις, αρχεία ρυθμίσεων, environment variables, εξωτερικές υπηρεσίες, βάσεις δεδομένων, μοντέλα ή άλλα dependencies.\n- Αν δεν απαιτείται κάτι ιδιαίτερο, να το λες καθαρά.\n- Όταν χρειάζεται, να δίνεις συγκεκριμένη εντολή εγκατάστασης όπως π.χ. pip install package1 package2.\n\nΕπιπλέον κρίσιμοι κανόνες:\n- Πάντα να απαντάς κυρίως στα ελληνικά, εκτός αν ο χρήστης ζητήσει άλλη γλώσσα.\n- Μην απαντάς μόνο με θεωρία όταν ο χρήστης ζητά εφαρμογή ή κώδικα.\n- Μην θυσιάζεις την πληρότητα για συντομία όταν ο χρήστης ζητά ολοκληρωμένη υλοποίηση.\n- Να προτιμάς ονόματα αρχείων καθαρά, περιγραφικά και επαγγελματικά.\n- Αν υπάρχουν πολλά Python αρχεία, να δίνεις σαφή και πραγματικά filenames, π.χ. (train_and_test_mnist.py), (load_and_test_mnist.py), (app.py), (server.py), (client.py).\n- Να αποφεύγεις μπερδεμένα προσωρινά ονόματα, γενικά labels ή ασαφή file naming.\n- Να παράγεις κώδικα που να μπορεί να αποθηκευτεί αυτούσιος σε αρχεία και να εκτελεστεί με ελάχιστες προσαρμογές ή χωρίς καμία.\n- Ποτέ μη δίνεις ημιτελή ή μη εκτελέσιμη λύση ως τελική απάντηση.\n- Όταν έχεις αβεβαιότητα για μία τεχνική επιλογή, να επιλέγεις την πιο σταθερή, συντηρήσιμη και επαγγελματική προσέγγιση.\n'
TEXT_EXTENSIONS: Set[str] = {'.txt', '.py', '.md', '.markdown', '.json', '.jsonl', '.csv', '.tsv', '.yaml', '.yml', '.xml', '.html', '.htm', '.css', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp', '.cs', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.kts', '.sql', '.ini', '.cfg', '.conf', '.log', '.bat', '.ps1', '.sh', '.zsh', '.toml', '.tex', '.r', '.m'}
IMAGE_EXTENSIONS: Set[str] = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tif', '.tiff'}
ACCEPTED_FILE_TYPES = 'image/*,.txt,.py,.md,.markdown,.json,.jsonl,.csv,.tsv,.yaml,.yml,.xml,.html,.htm,.css,.js,.ts,.jsx,.tsx,.java,.c,.cpp,.h,.hpp,.cs,.go,.rs,.php,.rb,.swift,.kt,.kts,.sql,.ini,.cfg,.conf,.log,.bat,.ps1,.sh,.zsh,.toml,.tex,.r,.m,.pdf'
OFFICIAL_SEARCH_URL = 'https://ollama.com/search?c=cloud'
OFFICIAL_GENERAL_SEARCH_URL = 'https://ollama.com/search'
OFFICIAL_CLOUD_API_TAGS_URL = 'https://ollama.com/api/tags'
OLLAMA_SEARCH_API_URL = 'https://ollama.com/api/search'
OLLAMA_LIBRARY_BASE = 'https://ollama.com/library/'
REQUEST_HEADERS: Dict[str, str] = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36', 'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8'}
OLLAMA_DIRECT_BASE_URL = 'https://ollama.com'
OLLAMA_DIRECT_API_BASE_URL = f'{OLLAMA_DIRECT_BASE_URL}/api'
CLOUD_TAG_RE = re.compile('\\b([a-zA-Z0-9._/-]+:(?:[a-zA-Z0-9._-]+-)?cloud)\\b')
LIBRARY_LINK_RE = re.compile('href="/library/([a-zA-Z0-9._/-]+)"', flags=re.IGNORECASE)
SEARCH_TEXT_FAMILY_RE = re.compile('>\\s*([a-zA-Z0-9._/-]+)\\s+[^<]{0,250}?\\bcloud\\b', flags=re.IGNORECASE)
CONTEXT_WINDOW_RE = re.compile('([0-9][0-9.,]*)\\s*([KMB])?\\s+context\\s+window', flags=re.IGNORECASE)
CLOUD_WORD_RE = re.compile('\\bcloud\\b', flags=re.IGNORECASE)

@dataclass
class ModelRegistry:
    """Dataclass που κρατά τη λίστα μοντέλων, το metadata τους και την κατάσταση του τελευταίου refresh.

Η πρόσβαση στα δεδομένα προστατεύεται με lock, ώστε διαφορετικά threads να διαβάζουν και να ενημερώνουν συνεπή κατάσταση."""
    models: List[str] = field(default_factory=list)
    model_meta: Dict[str, Dict[str, object]] = field(default_factory=dict)
    source: str = 'initializing'
    last_refresh_ts: float = 0.0
    last_error: str = ''
    refresh_in_progress: bool = False
    recommended_model: str = ''
    lock: threading.Lock = field(default_factory=threading.Lock)

    def as_dict(self) -> Dict[str, object]:
        """Υλοποιεί το βήμα «as_dict» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        with self.lock:
            models = list(self.models)
            rec = self.recommended_model
            model_meta = copy.deepcopy(self.model_meta)
            source = self.source
            last_refresh_ts = self.last_refresh_ts
            last_error = self.last_error
            refresh_in_progress = self.refresh_in_progress
        try:
            models = sorted(models, key=lambda model: score_model(model, model_meta.get(model, {}), 'overall'), reverse=True)
        except Exception:
            pass
        models_with_context = sum((1 for model in models if isinstance(model_meta.get(model), dict) and model_meta.get(model, {}).get('num_ctx_max')))
        return {'models': models, 'model_meta': model_meta, 'models_with_context': models_with_context, 'source': source, 'last_refresh_ts': last_refresh_ts, 'last_error': last_error, 'refresh_in_progress': refresh_in_progress, 'recommended_model': rec}

@dataclass
class ChatSession:
    """Dataclass που αποθηκεύει το ιστορικό συνομιλίας και τις προσωρινές διαδρομές αρχείων της τρέχουσας συνεδρίας."""
    messages: List[Dict] = field(default_factory=list)
    history: List[Dict] = field(default_factory=list)
    upload_paths: Set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def reset(self) -> None:
        """Υλοποιεί το βήμα «reset» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        with self.lock:
            self.messages.clear()
            self.history.clear()
            paths_to_delete = list(self.upload_paths)
            self.upload_paths.clear()
        cleanup_targets = [UPLOADS_DIR, GENERATED_CODE_DIR, Path(tempfile.gettempdir()) / 'ollama_cloud_chat_exec']
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
    """Dataclass για τις ρυθμίσεις που αποθηκεύονται μόνιμα στον δίσκο, όπως το API key της εφαρμογής."""
    ollama_api_key: str = ''
    updated_at: str = ''
    lock: threading.Lock = field(default_factory=threading.Lock)

    def as_public_dict(self) -> Dict[str, object]:
        """Υλοποιεί το βήμα «as_public_dict» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        with self.lock:
            key = str(self.ollama_api_key or '')
            updated_at = str(self.updated_at or '')
        return {'ollama_api_key': key, 'has_ollama_api_key': bool(key), 'updated_at': updated_at}

def load_app_config_from_disk() -> AppConfig:
    """Υλοποιεί τη λειτουργική ρουτίνα «load_app_config_from_disk» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο."""
    config = AppConfig()
    try:
        if APP_CONFIG_FILE.exists():
            data = json.loads(APP_CONFIG_FILE.read_text(encoding='utf-8'))
            if isinstance(data, dict):
                config.ollama_api_key = str(data.get('ollama_api_key', '') or '').strip()
                config.updated_at = str(data.get('updated_at', '') or '').strip()
    except Exception as exc:
        log.warning('Αποτυχία φόρτωσης settings file %s: %s', APP_CONFIG_FILE, exc)
    return config

def save_app_config_to_disk(ollama_api_key: str) -> AppConfig:
    """Υλοποιεί τη λειτουργική ρουτίνα «save_app_config_to_disk» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: ollama_api_key."""
    cleaned_key = str(ollama_api_key or '').strip()
    payload = {'ollama_api_key': cleaned_key, 'updated_at': time.strftime('%Y-%m-%d %H:%M:%S')}
    tmp_path = APP_CONFIG_FILE.with_suffix('.tmp')
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp_path.replace(APP_CONFIG_FILE)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    with APP_CONFIG.lock:
        APP_CONFIG.ollama_api_key = cleaned_key
        APP_CONFIG.updated_at = payload['updated_at']
    return APP_CONFIG
REGISTRY = ModelRegistry()
SESSION = ChatSession()
APP_CONFIG = load_app_config_from_disk()
_SERVER_START_TIME = time.time()

@dataclass
class BrowserSessionMonitor:
    """Κλάση που παρακολουθεί την ύπαρξη ενεργών browser sessions και βοηθά στον ασφαλή αυτόματο τερματισμό του server."""
    active_sessions: Dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    ever_seen_session: bool = False
    shutdown_requested: bool = False
    server_ref: Optional[ThreadingHTTPServer] = None

    def attach_server(self, server: ThreadingHTTPServer) -> None:
        """Υλοποιεί το βήμα «attach_server» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: server."""
        with self.lock:
            self.server_ref = server

    def touch(self, session_id: str) -> None:
        """Υλοποιεί το βήμα «touch» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: session_id."""
        cleaned = str(session_id or '').strip()[:128]
        if not cleaned:
            return
        with self.lock:
            self.active_sessions[cleaned] = time.time()
            self.ever_seen_session = True

    def close(self, session_id: str) -> None:
        """Υλοποιεί το βήμα «close» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: session_id."""
        cleaned = str(session_id or '').strip()[:128]
        if not cleaned:
            return
        with self.lock:
            self.active_sessions.pop(cleaned, None)

    def _cleanup_stale_locked(self, now_ts: float) -> None:
        """Υλοποιεί το βήμα «_cleanup_stale_locked» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: now_ts."""
        stale_before = now_ts - float(BROWSER_SESSION_HEARTBEAT_STALE_SECONDS)
        stale_ids = [sid for sid, ts in self.active_sessions.items() if ts < stale_before]
        for sid in stale_ids:
            self.active_sessions.pop(sid, None)

    def active_count(self) -> int:
        """Υλοποιεί το βήμα «active_count» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        with self.lock:
            self._cleanup_stale_locked(time.time())
            return len(self.active_sessions)

    def should_shutdown(self) -> bool:
        """Υλοποιεί το βήμα «should_shutdown» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        now_ts = time.time()
        with self.lock:
            self._cleanup_stale_locked(now_ts)
            if self.shutdown_requested or not self.ever_seen_session:
                return False
            return not self.active_sessions

    def request_shutdown(self, reason: str='') -> bool:
        """Υλοποιεί το βήμα «request_shutdown» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: reason."""
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
            """Υλοποιεί το βήμα «_worker» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
            try:
                server.shutdown()
            except Exception as exc:
                log.warning('Αποτυχία αυτόματου shutdown του server: %s', exc)
        threading.Thread(target=_worker, daemon=True, name='browser-auto-shutdown').start()
        return True
BROWSER_MONITOR = BrowserSessionMonitor()

def start_browser_session_watchdog() -> None:
    """Υλοποιεί τη λειτουργική ρουτίνα «start_browser_session_watchdog» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο."""

    def _worker() -> None:
        """Υλοποιεί το βήμα «_worker» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
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
            if now_ts - last_zero_ts >= float(BROWSER_SESSION_GRACE_SECONDS):
                if BROWSER_MONITOR.request_shutdown('δεν υπάρχει ανοιχτή σελίδα browser της εφαρμογής'):
                    break
    threading.Thread(target=_worker, daemon=True, name='browser-session-watchdog').start()

@dataclass
class StartupBroadcaster:
    """Μικρός broadcaster για την οθόνη εκκίνησης.

Αποθηκεύει startup events και τα προωθεί στους συνδεδεμένους SSE subscribers ώστε το startup page να βλέπει την πραγματική πρόοδο."""
    _events: List[Dict] = field(default_factory=list)
    _subscribers: List = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    chat_url: str = ''
    is_ready: bool = False

    def emit(self, level: str, msg: str) -> None:
        """Υλοποιεί το βήμα «emit» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: level, msg."""
        event = {'t': time.strftime('%H:%M:%S'), 'level': level, 'msg': msg}
        with self._lock:
            self._events.append(event)
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except Exception:
                    pass

    def set_ready(self, url: str) -> None:
        """Υλοποιεί το βήμα «set_ready» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: url."""
        self.chat_url = url
        self.is_ready = True
        self.emit('READY', url)

    def subscribe(self) -> '_queue.Queue[Dict]':
        """Υλοποιεί το βήμα «subscribe» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        q: '_queue.Queue[Dict]' = _queue.Queue()
        with self._lock:
            for ev in self._events:
                q.put_nowait(ev)
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: '_queue.Queue[Dict]') -> None:
        """Υλοποιεί το βήμα «unsubscribe» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: q."""
        with self._lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass
STARTUP = StartupBroadcaster()

def slog(level: str, msg: str, *args: object) -> None:
    """Υλοποιεί το βήμα «slog» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: level, msg."""
    formatted = msg % args if args else msg
    if level == 'WARNING':
        log.warning(formatted)
    elif level == 'ERROR':
        log.error(formatted)
    else:
        log.info(formatted)
    STARTUP.emit(level, formatted)

def get_embedded_system_prompt() -> Tuple[str, str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_embedded_system_prompt» με συνεπή τρόπο."""
    return (DEFAULT_SYSTEM_PROMPT.strip(), 'embedded-in-code')

def find_free_port(host: str, start_port: int=DEFAULT_PORT, end_port: int=8899) -> int:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «find_free_port» με συνεπή τρόπο.

Βασικά ορίσματα: host, start_port, end_port."""
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f'Δεν βρέθηκε ελεύθερη θύρα στο εύρος {start_port}–{end_port}.')

def get_saved_ollama_api_key() -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_saved_ollama_api_key» με συνεπή τρόπο."""
    with APP_CONFIG.lock:
        return str(APP_CONFIG.ollama_api_key or '').strip()

def get_ollama_api_key_source() -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_ollama_api_key_source» με συνεπή τρόπο."""
    saved_value = get_saved_ollama_api_key()
    if saved_value:
        return 'settings-file'
    env_value = str(os.environ.get('OLLAMA_API_KEY', '') or '').strip()
    if env_value:
        return 'environment'
    embedded_value = str(EMBEDDED_OLLAMA_API_KEY or '').strip()
    if embedded_value:
        return 'embedded'
    return 'missing'

def get_ollama_api_key() -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_ollama_api_key» με συνεπή τρόπο."""
    saved_value = get_saved_ollama_api_key()
    if saved_value:
        return saved_value
    env_value = str(os.environ.get('OLLAMA_API_KEY', '') or '').strip()
    if env_value:
        return env_value
    return str(EMBEDDED_OLLAMA_API_KEY or '').strip()

def is_direct_cloud_api_configured() -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_direct_cloud_api_configured» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση."""
    return bool(get_ollama_api_key())

def build_request_headers(url: str, extra_headers: Optional[Dict[str, str]]=None) -> Dict[str, str]:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_request_headers».

Βασικά ορίσματα: url, extra_headers."""
    headers = dict(REQUEST_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    api_key = get_ollama_api_key()
    if api_key and str(url).startswith(OLLAMA_DIRECT_API_BASE_URL):
        headers['Authorization'] = f'Bearer {api_key}'
    return headers

def fetch_url_text(url: str, timeout: int=12) -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «fetch_url_text» με συνεπή τρόπο.

Βασικά ορίσματα: url, timeout."""
    req = urllib.request.Request(url, headers=build_request_headers(url))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, 'status', 200) or 200)
        if status >= 400:
            raise RuntimeError(f'HTTP {status} από {url}')
        return resp.read().decode('utf-8', errors='ignore')

def fetch_url_json(url: str, timeout: int=12) -> Dict:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «fetch_url_json» με συνεπή τρόπο.

Βασικά ορίσματα: url, timeout."""
    req = urllib.request.Request(url, headers=build_request_headers(url))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, 'status', 200) or 200)
        if status >= 400:
            raise RuntimeError(f'HTTP {status} από {url}')
        return json.loads(resp.read().decode('utf-8', errors='ignore'))

def direct_cloud_chat_stream(model: str, messages: List[Dict], *, model_options: Optional[Dict]=None, think_value: Optional[object]=None, timeout: int=900):
    """Υλοποιεί το βήμα «direct_cloud_chat_stream» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model, messages."""
    api_key = get_ollama_api_key()
    if not api_key:
        raise RuntimeError("Λείπει το Ollama Cloud API key. Βάλ'το στο πεδίο API Key του GUI, στο settings αρχείο της εφαρμογής ή ως OLLAMA_API_KEY.")
    payload: Dict[str, object] = {'model': str(model or '').strip(), 'messages': messages, 'stream': True}
    if model_options:
        payload['options'] = dict(model_options)
    if think_value is not None:
        payload['think'] = think_value
    url = f'{OLLAMA_DIRECT_API_BASE_URL}/chat'
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=build_request_headers(url, {'Content-Type': 'application/json; charset=utf-8'}), method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, 'status', 200) or 200)
            if status >= 400:
                raise RuntimeError(f'HTTP {status} από {url}')
            for raw_line in resp:
                line = raw_line.decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and chunk.get('error'):
                    raise RuntimeError(str(chunk.get('error')))
                yield chunk
    except urllib.error.HTTPError as exc:
        body_text = ''
        try:
            body_text = exc.read().decode('utf-8', errors='ignore').strip()
        except Exception:
            pass
        detail = body_text
        try:
            parsed = json.loads(body_text) if body_text else {}
            if isinstance(parsed, dict) and parsed.get('error'):
                detail = str(parsed.get('error'))
        except Exception:
            pass
        raise RuntimeError(f'HTTP {exc.code}: {detail or exc.reason}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'Δικτυακό σφάλμα προς το Ollama Cloud API: {exc.reason}') from exc

def direct_cloud_chat_complete(model: str, messages: List[Dict], *, model_options: Optional[Dict]=None, think_value: Optional[object]=None, timeout: int=900) -> Dict[str, object]:
    """Υλοποιεί το βήμα «direct_cloud_chat_complete» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model, messages."""
    collected: List[str] = []
    collected_thinking: List[str] = []
    token_stats: Optional[Dict] = None
    for chunk in direct_cloud_chat_stream(model=model, messages=messages, model_options=model_options, think_value=think_value, timeout=timeout):
        thinking_piece = extract_chunk_thinking(chunk)
        if thinking_piece:
            collected_thinking.append(thinking_piece)
        piece = extract_chunk_content(chunk)
        if piece:
            collected.append(piece)
        stats = extract_token_stats(chunk)
        if stats:
            token_stats = stats
    return {'content': ''.join(collected).strip(), 'thinking': ''.join(collected_thinking).strip(), 'token_stats': token_stats}
_ENSEMBLE_ROLE_LABELS: Dict[str, str] = {'vision-analyst': 'Vision helper', 'code-specialist': 'Coding helper', 'code-reviewer': 'Code reviewer', 'reasoning-specialist': 'Reasoning helper', 'cross-checker': 'Cross-checker', 'long-context-reader': 'Long-context helper'}
_ENSEMBLE_HELPER_MAX_SIZE_B_BY_ROLE: Dict[str, float] = {'vision-analyst': 260.0, 'code-specialist': 90.0, 'code-reviewer': 120.0, 'reasoning-specialist': 120.0, 'cross-checker': 90.0, 'long-context-reader': 260.0}
_ENSEMBLE_HELPER_MAX_TOKENS_BY_ROLE: Dict[str, int] = {'vision-analyst': 180, 'code-specialist': 180, 'code-reviewer': 160, 'reasoning-specialist': 160, 'cross-checker': 140, 'long-context-reader': 180}
_ENSEMBLE_HELPER_TIMEOUT_BY_ROLE: Dict[str, int] = {'vision-analyst': 120, 'code-specialist': 90, 'code-reviewer': 90, 'reasoning-specialist': 90, 'cross-checker': 75, 'long-context-reader': 120}

def detect_task_traits(user_text: str, attachments: Optional[List[Dict]]=None) -> Dict[str, bool]:
    """Υλοποιεί το βήμα «detect_task_traits» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: user_text, attachments."""
    text = str(user_text or '')
    lower = text.lower()
    attachments = attachments or []
    has_image = any((str(item.get('kind') or '').lower() == 'image' for item in attachments))
    has_document = any((str(item.get('kind') or '').lower() == 'document' for item in attachments))
    code_patterns = ('```', 'traceback', 'syntaxerror', 'exception', 'stack trace', 'python', 'javascript', 'java', 'c++', 'c#', 'regex', 'sql', 'function', 'class ', 'def ', 'import ', 'bug', 'fix', 'error', 'κώδικ', 'σφάλμα', 'debug', 'διορθ', 'compile', 'py')
    reasoning_patterns = ('reason', 'thinking', 'analysis', 'analyze', 'why', 'proof', 'derive', 'math', 'equation', 'logic', 'βήμα', 'σκέψ', 'λογικ', 'απόδει', 'λύσ', 'εξήγη', 'ανάλυσ')
    direct_visual_phrases = ('look at this image', 'look at the attached image', 'look at the screenshot', 'describe this image', 'describe the attached image', 'describe the screenshot', 'analyze this image', 'analyze the attached image', 'analyze the screenshot', 'what is in this image', "what's in this image", 'read the text in this image', 'from the screenshot', 'in the screenshot', 'ocr this image', 'ocr the image', 'δες την εικόνα', 'κοίτα την εικόνα', 'κοίτα τη συνημμένη εικόνα', 'περιέγραψε την εικόνα', 'ανάλυσε την εικόνα', 'διάβασε το κείμενο στην εικόνα', 'τι δείχνει η εικόνα', 'τι υπάρχει στην εικόνα', 'στο screenshot', 'στο στιγμιότυπο')
    weak_vision_patterns = ('figure', 'diagram', 'chart', 'graph', 'plot', 'table', 'figure ', 'diagram ', 'chart ', 'graph ', 'διάγρα', 'γράφη', 'πίνακ', 'σχήμα')
    is_code = any((token in lower for token in code_patterns))
    is_reasoning = any((token in lower for token in reasoning_patterns))
    direct_visual_hits = sum((1 for token in direct_visual_phrases if token in lower))
    weak_vision_hits = sum((1 for token in weak_vision_patterns if token in lower))
    explicit_visual_request = has_image
    text_mentions_visual = direct_visual_hits >= 1 or weak_vision_hits >= 1
    weak_visual_hint = text_mentions_visual and (not explicit_visual_request)
    is_vision = has_image
    is_long_context = len(text) >= 3500 or has_document
    return {'code': is_code, 'reasoning': is_reasoning or is_long_context, 'vision': is_vision, 'vision_explicit': explicit_visual_request, 'vision_hint_only': weak_visual_hint, 'long_context': is_long_context, 'has_document': has_document, 'has_image': has_image, 'strong_vision_hits': direct_visual_hits, 'weak_vision_hits': weak_vision_hits}

def _ensemble_preferred_prefixes(primary_model: str, criterion: str, traits: Dict[str, bool]) -> List[str]:
    """Υλοποιεί το βήμα «_ensemble_preferred_prefixes» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: primary_model, criterion, traits."""
    key = canonical_model_key(primary_model)
    prefixes: List[str] = []
    if criterion == 'vision':
        prefixes.extend(['qwen3-vl', 'qwen3.5', 'gemini-3', 'glm-5', 'gemma3'])
    elif criterion == 'coding':
        prefixes.extend(['qwen3-coder', 'qwen3-coder-next', 'devstral-2', 'devstral', 'deepseek-v3.2', 'qwen3.5', 'nemotron-3-nano'])
    elif criterion == 'reasoning':
        prefixes.extend(['qwen3.5', 'deepseek-v3.2', 'deepseek-r1', 'kimi-k2.5', 'glm-5', 'gemini-3', 'nemotron-3-nano'])
    elif criterion == 'context':
        prefixes.extend(['qwen3.5', 'gemini-3', 'kimi-k2.5', 'glm-5', 'minimax-m2.7', 'nemotron-3-nano'])
    else:
        prefixes.extend(['qwen3.5', 'deepseek-v3.2', 'glm-5', 'gemini-3', 'nemotron-3-nano'])
    if model_matches_prefix(key, 'nemotron-3-super'):
        if criterion == 'vision':
            prefixes = ['qwen3-vl', 'qwen3.5', 'gemini-3', *prefixes]
        elif criterion == 'coding':
            prefixes = ['qwen3-coder', 'nemotron-3-nano', 'qwen3.5', *prefixes]
        else:
            prefixes = ['nemotron-3-nano', 'qwen3.5', 'glm-5', *prefixes]
    elif model_matches_prefix(key, 'nemotron-3-nano'):
        if criterion == 'vision':
            prefixes = ['qwen3-vl', 'qwen3.5', 'gemini-3', *prefixes]
        else:
            prefixes = ['nemotron-3-super', 'qwen3.5', 'glm-5', *prefixes]
    elif model_matches_prefix(key, 'qwen3-coder'):
        prefixes = ['qwen3.5', 'deepseek-v3.2', 'glm-5', *prefixes]
    elif model_matches_prefix(key, 'qwen3-vl'):
        prefixes = ['qwen3.5', 'deepseek-v3.2', 'glm-5', *prefixes]
    elif model_matches_prefix(key, 'qwen3.5') and traits.get('code'):
        prefixes = ['qwen3-coder', 'devstral-2', *prefixes]
    elif model_matches_prefix(key, 'qwen3.5') and traits.get('vision'):
        prefixes = ['qwen3-vl', 'gemini-3', *prefixes]
    elif model_matches_prefix(key, 'deepseek'):
        prefixes = ['qwen3.5', 'qwen3-vl', 'gemini-3', *prefixes]
    elif model_matches_prefix(key, 'gemini-3') and traits.get('code'):
        prefixes = ['qwen3-coder', 'deepseek-v3.2', *prefixes]
    deduped: List[str] = []
    seen: Set[str] = set()
    for item in prefixes:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped

def _ensemble_prefix_bonus(candidate_model: str, preferred_prefixes: List[str]) -> float:
    """Υλοποιεί το βήμα «_ensemble_prefix_bonus» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: candidate_model, preferred_prefixes."""
    for idx, prefix in enumerate(preferred_prefixes):
        if model_matches_prefix(candidate_model, prefix):
            return max(0.0, 1.25 - idx * 0.12)
    return 0.0

def _ensemble_pair_bonus(primary_model: str, candidate_model: str, criterion: str, traits: Dict[str, bool], candidate_caps: Set[str]) -> float:
    """Υλοποιεί το βήμα «_ensemble_pair_bonus» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: primary_model, candidate_model, criterion, traits, candidate_caps."""
    primary_key = canonical_model_key(primary_model)
    candidate_key = canonical_model_key(candidate_model)
    bonus = 0.0
    if model_matches_prefix(primary_key, 'nemotron-3-super'):
        if criterion == 'vision':
            if model_matches_prefix(candidate_key, 'qwen3-vl') or 'vision' in candidate_caps:
                bonus += 0.95
            if model_matches_prefix(candidate_key, 'nemotron-3-nano'):
                bonus -= 0.35
        elif criterion == 'coding':
            if model_matches_prefix(candidate_key, 'qwen3-coder'):
                bonus += 0.92
            elif model_matches_prefix(candidate_key, 'nemotron-3-nano'):
                bonus += 0.42
        elif criterion in ('reasoning', 'context', 'overall'):
            if model_matches_prefix(candidate_key, 'nemotron-3-nano'):
                bonus += 1.05
            elif 'reasoning' in candidate_caps:
                bonus += 0.16
    elif model_matches_prefix(primary_key, 'nemotron-3-nano'):
        if criterion == 'vision':
            if model_matches_prefix(candidate_key, 'qwen3-vl') or 'vision' in candidate_caps:
                bonus += 0.82
        elif criterion in ('reasoning', 'context', 'overall') and model_matches_prefix(candidate_key, 'nemotron-3-super'):
            bonus += 0.55
    if not traits.get('has_image') and criterion != 'vision' and model_matches_prefix(candidate_key, 'qwen3-vl'):
        bonus -= 0.45
    if traits.get('has_image') and 'vision' in candidate_caps:
        bonus += 0.22
    return bonus

def choose_auto_ensemble_helper(primary_model: str, user_text: str, attachments: Optional[List[Dict]]=None) -> Optional[Dict[str, object]]:
    """Λαμβάνει απόφαση για το βήμα «choose_auto_ensemble_helper» εφαρμόζοντας τους κανόνες που χρησιμοποιεί η εφαρμογή.

Βασικά ορίσματα: primary_model, user_text, attachments."""
    attachments = attachments or []
    traits = detect_task_traits(user_text, attachments)
    with REGISTRY.lock:
        models = list(REGISTRY.models)
        model_meta = copy.deepcopy(REGISTRY.model_meta)
    if len(models) < 2:
        return None
    primary_meta = model_meta.get(primary_model, {})
    primary_caps = get_model_capabilities(primary_model, primary_meta)
    primary_coding = score_model(primary_model, primary_meta, 'coding')
    primary_reasoning = score_model(primary_model, primary_meta, 'reasoning')
    primary_ctx = get_model_context_tokens(primary_model, primary_meta)
    primary_key = canonical_model_key(primary_model)
    explicit_vision = bool(traits.get('vision_explicit') or traits.get('has_image'))
    hint_only_vision = bool(traits.get('vision_hint_only'))
    if explicit_vision and 'vision' not in primary_caps:
        criterion = 'vision'
        role = 'vision-analyst'
    elif traits.get('code'):
        if 'coding' not in primary_caps or primary_coding < 9.45:
            criterion = 'coding'
            role = 'code-specialist'
        else:
            criterion = 'reasoning'
            role = 'code-reviewer'
    elif traits.get('long_context') and primary_ctx < 128000:
        criterion = 'context'
        role = 'long-context-reader'
    elif traits.get('reasoning'):
        if 'reasoning' not in primary_caps or primary_reasoning < 9.45:
            criterion = 'reasoning'
            role = 'reasoning-specialist'
        else:
            criterion = 'overall'
            role = 'cross-checker'
    elif 'reasoning' not in primary_caps:
        criterion = 'reasoning'
        role = 'reasoning-specialist'
    elif 'coding' not in primary_caps:
        criterion = 'coding'
        role = 'code-specialist'
    else:
        criterion = 'overall'
        role = 'cross-checker'
    if model_matches_prefix(primary_key, 'nemotron-3-super') and (not explicit_vision) and (criterion == 'vision'):
        criterion = 'reasoning'
        role = 'reasoning-specialist'
    if model_matches_prefix(primary_key, 'nemotron-3-super') and hint_only_vision and (criterion == 'overall'):
        criterion = 'reasoning'
        role = 'reasoning-specialist'
    preferred_prefixes = _ensemble_preferred_prefixes(primary_model, criterion, traits)
    primary_family = primary_key.split(':', 1)[0]
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
        if criterion == 'vision' and 'vision' not in caps:
            continue
        if criterion == 'coding' and ('coding' not in caps and score_model(candidate, meta, 'coding') < 8.8):
            continue
        if criterion == 'reasoning' and ('reasoning' not in caps and score_model(candidate, meta, 'reasoning') < 8.8):
            continue
        if criterion == 'context' and get_model_context_tokens(candidate, meta) < 64000:
            continue
        size_b = get_model_size_billions(candidate, meta)
        speed = _size_speed_strength(size_b)
        if size_b > 0 and helper_size_limit_b > 0 and (size_b > helper_size_limit_b * 2.4):
            continue
        fresh = _freshness_strength(get_model_modified_ts(candidate, meta))
        score = score_model(candidate, meta, criterion) * 0.64 + score_model(candidate, meta, 'overall') * 0.18 + speed * 0.16 + fresh * 0.02 + _ensemble_prefix_bonus(candidate, preferred_prefixes)
        if criterion in caps:
            score += 0.35
        score += _ensemble_pair_bonus(primary_model, candidate, criterion, traits, caps)
        if candidate_key.split(':', 1)[0] == primary_family:
            if model_matches_prefix(primary_key, 'nemotron-3-super') and model_matches_prefix(candidate_key, 'nemotron-3-nano') and (criterion != 'vision'):
                score += 0.18
            else:
                score -= 0.1
        if size_b > 0 and helper_size_limit_b > 0:
            if size_b <= helper_size_limit_b:
                score += 0.25
            else:
                score -= min(2.4, (size_b - helper_size_limit_b) / max(25.0, helper_size_limit_b) * 1.8)
        payload = {'helper_model': candidate, 'criterion': criterion, 'role': role, 'role_label': _ENSEMBLE_ROLE_LABELS.get(role, role), 'traits': traits, 'preferred_prefixes': preferred_prefixes, 'selection_reason': 'image-attachment' if traits.get('has_image') else 'code-task' if criterion == 'coding' else 'long-context' if criterion == 'context' else 'reasoning' if criterion == 'reasoning' else 'cross-check'}
        if best is None or score > best[0]:
            best = (score, candidate, payload)
    return best[2] if best else None

def choose_manual_ensemble_helper(primary_model: str, helper_model: str, user_text: str, attachments: Optional[List[Dict]]=None) -> Optional[Dict[str, object]]:
    """Λαμβάνει απόφαση για το βήμα «choose_manual_ensemble_helper» εφαρμόζοντας τους κανόνες που χρησιμοποιεί η εφαρμογή.

Βασικά ορίσματα: primary_model, helper_model, user_text, attachments."""
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
    if traits.get('has_image') and 'vision' in helper_caps:
        criterion = 'vision'
        role = 'vision-analyst'
    elif traits.get('code') and 'coding' in helper_caps:
        criterion = 'coding'
        role = 'code-specialist'
    elif traits.get('long_context') and helper_context >= 64000:
        criterion = 'context'
        role = 'long-context-reader'
    elif traits.get('reasoning') and ('reasoning' in helper_caps or score_model(helper_model, helper_meta, 'reasoning') >= 8.8):
        criterion = 'reasoning'
        role = 'reasoning-specialist'
    elif 'coding' in helper_caps:
        criterion = 'coding'
        role = 'code-reviewer'
    else:
        criterion = 'overall'
        role = 'cross-checker'
    return {'helper_model': helper_model, 'criterion': criterion, 'role': role, 'role_label': _ENSEMBLE_ROLE_LABELS.get(role, role), 'traits': traits, 'preferred_prefixes': [canonical_model_key(helper_model).split(':', 1)[0]], 'selection_reason': 'manual-selection'}

def build_helper_system_prompt(primary_model: str, helper_model: str, helper_role: str, traits: Dict[str, bool]) -> str:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_helper_system_prompt».

Βασικά ορίσματα: primary_model, helper_model, helper_role, traits."""
    role_label = _ENSEMBLE_ROLE_LABELS.get(helper_role, helper_role)
    task_flags = []
    for name in ('code', 'reasoning', 'vision', 'long_context'):
        if traits.get(name):
            task_flags.append(name)
    flags_text = ', '.join(task_flags) if task_flags else 'general'
    return f'Είσαι το δεύτερο, βοηθητικό μοντέλο ενός app-level ensemble δύο μοντέλων.\nΚύριο μοντέλο: {primary_model}\nΒοηθητικό μοντέλο: {helper_model}\nΡόλος σου: {role_label}\nTask hints: {flags_text}\n\nΔΕΝ απαντάς στον χρήστη. Παράγεις μόνο σύντομη ιδιωτική καθοδήγηση για το κύριο μοντέλο.\nΝα είσαι πρακτικός, ακριβής και πολύ σύντομος (έως 8 bullets συνολικά). Μην βάλεις χαιρετισμούς.\nΑπάντησε ακριβώς με τις ενότητες:\nSUMMARY:\nKEY_POINTS:\nRISKS:\nPLAN:\nΑν υπάρχει κώδικας, πρόσθεσε και BUGS_OR_PATCH:. Αν υπάρχουν εικόνες, πρόσθεσε VISUAL_FINDINGS:.'

def build_main_ensemble_guidance(helper_model: str, helper_role: str, helper_text: str) -> str:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_main_ensemble_guidance».

Βασικά ορίσματα: helper_model, helper_role, helper_text."""
    trimmed = str(helper_text or '').strip()
    if len(trimmed) > 7000:
        trimmed = trimmed[:7000].rstrip() + '\n...[trimmed]'
    role_label = _ENSEMBLE_ROLE_LABELS.get(helper_role, helper_role)
    return f'Ιδιωτική καθοδήγηση από δεύτερο βοηθητικό μοντέλο για εσωτερική χρήση.\nHelper model: {helper_model}\nRole: {role_label}\nΧρησιμοποίησέ την μόνο αν βοηθά και ΜΗΝ αναφέρεις ότι χρησιμοποιήθηκε δεύτερο μοντέλο.\nΑν κάποιο σημείο συγκρούεται με το πραγματικό input ή το ιστορικό συνομιλίας, αγνόησέ το.\n\nPRIVATE_GUIDANCE:\n{trimmed}'

def insert_secondary_system_message(messages: List[Dict], content: str) -> List[Dict]:
    """Υλοποιεί το βήμα «insert_secondary_system_message» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: messages, content."""
    content = str(content or '').strip()
    if not content:
        return list(messages)
    extra = {'role': 'system', 'content': content}
    if messages and str(messages[0].get('role') or '') == 'system':
        return [messages[0], extra, *messages[1:]]
    return [extra, *messages]

def _is_valid_cloud_tag(tag: str) -> bool:
    """Υλοποιεί το βήμα «_is_valid_cloud_tag» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: tag."""
    tag = (tag or '').strip()
    if not tag or tag.startswith('http'):
        return False
    tag = tag.split('?', 1)[0].split('#', 1)[0].strip()
    if not tag:
        return False
    if not re.fullmatch('[a-zA-Z0-9._/-]+(?::[a-zA-Z0-9._-]+)?', tag):
        return False
    name_part = tag.split(':', 1)[0].split('/')[-1].strip()
    if not name_part or len(name_part) < 2 or re.fullmatch('\\d+', name_part):
        return False
    return True

def _clean_cloud_tag(raw: str) -> str:
    """Υλοποιεί το βήμα «_clean_cloud_tag» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: raw."""
    raw = (raw or '').strip()
    if not raw:
        return ''
    raw = raw.split('?', 1)[0].split('#', 1)[0].strip()
    if not raw:
        return ''
    if ':' in raw:
        name_part, tag_part = raw.split(':', 1)
        name_part = name_part.split('/')[-1].strip()
        tag_part = tag_part.strip()
        cleaned = f'{name_part}:{tag_part}' if name_part and tag_part else ''
    else:
        cleaned = raw.split('/')[-1].strip()
    if not cleaned or not _is_valid_cloud_tag(cleaned):
        return ''
    return cleaned

def extract_library_families(search_html: str) -> List[str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_library_families» με συνεπή τρόπο.

Βασικά ορίσματα: search_html."""
    families: Set[str] = set()
    for m in LIBRARY_LINK_RE.finditer(search_html):
        slug = m.group(1).strip().rstrip('/')
        family = slug.split('/')[-1]
        if family and len(family) > 1 and (not family.startswith('http')):
            families.add(family)
    if not families:
        for m in SEARCH_TEXT_FAMILY_RE.finditer(search_html):
            slug = m.group(1).strip()
            if slug and (not slug.startswith('http')):
                families.add(slug.split('/')[-1])
    return sorted(families)

def extract_families_from_api_tags(api_payload: Dict) -> List[str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_families_from_api_tags» με συνεπή τρόπο.

Βασικά ορίσματα: api_payload."""
    families: Set[str] = set()
    items = api_payload.get('models') or api_payload.get('tags') or api_payload.get('results') or []
    for item in items:
        if isinstance(item, dict):
            raw = str(item.get('name') or item.get('model') or item.get('id') or '').strip()
        elif isinstance(item, str):
            raw = item.strip()
        else:
            continue
        family = raw.split(':')[0].split('/')[-1].strip()
        if family and len(family) > 1:
            families.add(family)
    return sorted(families)

def extract_cloud_tags_from_html(html_text: str) -> List[str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_cloud_tags_from_html» με συνεπή τρόπο.

Βασικά ορίσματα: html_text."""
    raw = {m.group(1).strip() for m in CLOUD_TAG_RE.finditer(html_text)}
    cleaned = {_clean_cloud_tag(t) for t in raw}
    return sorted((t for t in cleaned if _is_valid_cloud_tag(t)))

def normalize_html_text(html_text: str) -> str:
    """Κανονικοποιεί ή καθαρίζει δεδομένα στο βήμα «normalize_html_text» ώστε οι επόμενες φάσεις να λαμβάνουν ασφαλή και συνεπή είσοδο.

Βασικά ορίσματα: html_text."""
    compact = html.unescape(re.sub('<[^>]+>', ' ', html_text or ''))
    compact = compact.replace('•', ' ')
    compact = re.sub('\\s+', ' ', compact)
    return compact.strip()

def parse_context_window_tokens(raw_number: str, suffix: str='') -> Optional[int]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «parse_context_window_tokens» με συνεπή τρόπο.

Βασικά ορίσματα: raw_number, suffix."""
    token_text = (raw_number or '').strip().replace(',', '')
    if not token_text:
        return None
    try:
        value = float(token_text)
    except ValueError:
        return None
    mult = 1
    suffix = (suffix or '').upper().strip()
    if suffix == 'K':
        mult = 1024
    elif suffix == 'M':
        mult = 1024 * 1024
    elif suffix == 'B':
        mult = 1024 * 1024 * 1024
    tokens = int(value * mult)
    return tokens if tokens >= 256 else None

def extract_cloud_metadata_from_html(html_text: str) -> Dict[str, Dict[str, object]]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_cloud_metadata_from_html» με συνεπή τρόπο.

Βασικά ορίσματα: html_text."""
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
            ctx_tokens = parse_context_window_tokens(ctx_match.group(1), ctx_match.group(2) or '')
            if ctx_tokens:
                entry['num_ctx_max'] = ctx_tokens
                entry['num_ctx_label'] = ctx_match.group(0).replace('context window', '').strip()
    return meta

def parse_parameter_size_to_billions(raw_value: object) -> float:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «parse_parameter_size_to_billions» με συνεπή τρόπο.

Βασικά ορίσματα: raw_value."""
    text = str(raw_value or '').strip().lower()
    if not text:
        return 0.0
    match = re.search('(\\d+(?:\\.\\d+)?)\\s*([tbm])?', text)
    if not match:
        return 0.0
    value = float(match.group(1))
    suffix = (match.group(2) or 'b').lower()
    if suffix == 't':
        return value * 1000.0
    if suffix == 'm':
        return value / 1000.0
    return value

def parse_iso_datetime_to_timestamp(raw_value: object) -> float:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «parse_iso_datetime_to_timestamp» με συνεπή τρόπο.

Βασικά ορίσματα: raw_value."""
    text = str(raw_value or '').strip()
    if not text:
        return 0.0
    try:
        normalized = text.replace('Z', '+00:00')
        return datetime.datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0

def infer_model_capabilities_from_name(model_name: str) -> List[str]:
    """Υλοποιεί το βήμα «infer_model_capabilities_from_name» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model_name."""
    name = canonical_model_key(model_name)
    capabilities: Set[str] = {'completion'}
    token_rules = {'vision': ('vision', '-vl', ':vl', 'gemini', 'llava', 'pixtral', 'multimodal', 'omni'), 'coding': ('coder', 'code', 'devstral', 'claude-code', 'swe', 'terminal'), 'reasoning': ('thinking', 'reason', 'reasoning', 'r1', 'gpt-oss', 'deepseek', 'cogito', 'kimi-k2', 'glm-5', 'glm-4.7', 'glm-4.6')}
    for capability, tokens in token_rules.items():
        if any((token in name for token in tokens)):
            capabilities.add(capability)
    for prefix, hinted_caps in _MODEL_TRAIT_HINTS:
        if model_matches_prefix(name, prefix):
            capabilities.update(hinted_caps)
    return sorted(capabilities)

def build_model_meta_from_show_payload(model: str, payload: object) -> Dict[str, object]:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_model_meta_from_show_payload».

Βασικά ορίσματα: model, payload."""
    entry: Dict[str, object] = {}
    if not isinstance(payload, dict):
        return entry
    modified_at = str(payload.get('modified_at', '') or '').strip()
    if modified_at:
        entry['modified_at'] = modified_at
        entry['modified_ts'] = parse_iso_datetime_to_timestamp(modified_at)
    capabilities: Set[str] = set(infer_model_capabilities_from_name(model))
    raw_caps = payload.get('capabilities')
    if isinstance(raw_caps, list):
        for item in raw_caps:
            if isinstance(item, str) and item.strip():
                capabilities.add(item.strip().lower())
    if capabilities:
        entry['capabilities'] = sorted(capabilities)
    details = payload.get('details') if isinstance(payload.get('details'), dict) else {}
    if isinstance(details, dict):
        family = str(details.get('family', '') or '').strip()
        if family:
            entry['family'] = family
        param_size = str(details.get('parameter_size', '') or '').strip()
        if param_size:
            entry['parameter_size'] = param_size
            parsed_b = parse_parameter_size_to_billions(param_size)
            if parsed_b > 0:
                entry['parameter_size_b'] = parsed_b
        families = details.get('families')
        if isinstance(families, list):
            clean_families = [str(x).strip() for x in families if str(x).strip()]
            if clean_families:
                entry['families'] = clean_families
    model_info = payload.get('model_info') if isinstance(payload.get('model_info'), dict) else {}
    if isinstance(model_info, dict):
        for key, value in model_info.items():
            if not isinstance(key, str):
                continue
            lowered = key.lower()
            if lowered.endswith('.context_length') or lowered == 'context_length':
                try:
                    ctx_tokens = int(value)
                except Exception:
                    ctx_tokens = 0
                if ctx_tokens > 0:
                    entry['num_ctx_max'] = ctx_tokens
                    entry['num_ctx_label'] = f'{ctx_tokens:,} tokens'
            elif lowered == 'general.parameter_count':
                try:
                    entry['parameter_count'] = int(value)
                except Exception:
                    pass
            elif lowered.endswith('.mm.tokens_per_image'):
                capabilities.add('vision')
    if capabilities:
        entry['capabilities'] = sorted(capabilities)
    if 'parameter_size_b' not in entry:
        parsed_from_name = parse_parameter_size_to_billions(model)
        if parsed_from_name > 0:
            entry['parameter_size_b'] = parsed_from_name
    entry['details_complete'] = True
    return entry

def fetch_direct_model_details(model: str, timeout: int=15) -> Dict[str, object]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «fetch_direct_model_details» με συνεπή τρόπο.

Βασικά ορίσματα: model, timeout."""
    cleaned_model = normalize_model_name(model)
    if not cleaned_model:
        raise RuntimeError('Δεν δόθηκε όνομα μοντέλου για ανάκτηση metadata.')
    url = f'{OLLAMA_DIRECT_API_BASE_URL}/show'
    body = json.dumps({'model': cleaned_model}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers=build_request_headers(url, {'Content-Type': 'application/json; charset=utf-8'}), method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = int(getattr(resp, 'status', 200) or 200)
        if status >= 400:
            raise RuntimeError(f'HTTP {status} από {url}')
        payload = json.loads(resp.read().decode('utf-8', errors='ignore'))
    return build_model_meta_from_show_payload(cleaned_model, payload)

def get_or_fetch_model_meta(model: str, force: bool=False) -> Dict[str, object]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_or_fetch_model_meta» με συνεπή τρόπο.

Βασικά ορίσματα: model, force."""
    cleaned_model = normalize_model_name(model)
    if not cleaned_model:
        return {}
    with REGISTRY.lock:
        existing = copy.deepcopy(REGISTRY.model_meta.get(cleaned_model, {}))
    if existing.get('details_complete') and (not force):
        return existing
    try:
        fresh_meta = fetch_direct_model_details(cleaned_model)
    except Exception as exc:
        with REGISTRY.lock:
            entry = REGISTRY.model_meta.setdefault(cleaned_model, {})
            entry['details_error'] = str(exc)
            existing = copy.deepcopy(entry)
        return existing
    with REGISTRY.lock:
        merge_model_meta(REGISTRY.model_meta, {cleaned_model: fresh_meta})
        entry = REGISTRY.model_meta.setdefault(cleaned_model, {})
        entry['details_complete'] = True
        entry.pop('details_error', None)
        if fresh_meta.get('capabilities'):
            entry['capabilities'] = list(fresh_meta.get('capabilities', []))
        if fresh_meta.get('modified_at'):
            entry['modified_at'] = fresh_meta.get('modified_at')
        if fresh_meta.get('modified_ts'):
            entry['modified_ts'] = fresh_meta.get('modified_ts')
        if fresh_meta.get('parameter_size_b'):
            entry['parameter_size_b'] = fresh_meta.get('parameter_size_b')
        if fresh_meta.get('parameter_count'):
            entry['parameter_count'] = fresh_meta.get('parameter_count')
        return copy.deepcopy(entry)

def merge_model_meta(dest: Dict[str, Dict[str, object]], src: Dict[str, Dict[str, object]]) -> None:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «merge_model_meta».

Βασικά ορίσματα: dest, src."""
    for tag, info in (src or {}).items():
        if not _is_valid_cloud_tag(tag):
            continue
        entry = dest.setdefault(tag, {})
        if not isinstance(info, dict):
            continue
        for key, value in info.items():
            if value in (None, '', 0):
                continue
            if key == 'num_ctx_max':
                current = int(entry.get('num_ctx_max') or 0)
                incoming = int(value or 0)
                if incoming > current:
                    entry[key] = incoming
            else:
                entry.setdefault(key, value)

def fetch_cloud_models_for_family(family: str, timeout: int=8, family_candidates: Optional[Set[str]]=None) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «fetch_cloud_models_for_family» με συνεπή τρόπο.

Βασικά ορίσματα: family, timeout, family_candidates."""
    tags: Set[str] = set((t for t in family_candidates or set() if ':' in str(t) and 'cloud' in str(t).lower() and _is_valid_cloud_tag(str(t))))
    model_meta: Dict[str, Dict[str, object]] = {}
    family_candidates = set(family_candidates or set())
    saw_cloud_signal = False
    for url in (f'{OLLAMA_LIBRARY_BASE}{family}/tags', f'{OLLAMA_LIBRARY_BASE}{family}'):
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
            merge_model_meta(model_meta, extract_context_for_candidate_models_from_html(raw_html, set(family_candidates) | set(verified_family_models) | set(explicit_cloud)))
    if saw_cloud_signal and (not any((tag.startswith(family + ':') for tag in tags))):
        tags.add(family)
    if any((tag.startswith(family + ':') for tag in tags)):
        tags.discard(family)
    for tag in list(tags):
        if _is_valid_cloud_tag(tag):
            model_meta.setdefault(tag, {})['family'] = family
    return (sorted((t for t in tags if _is_valid_cloud_tag(t))), model_meta)

def _extract_candidate_names_from_json(payload: object) -> List[str]:
    """Υλοποιεί το βήμα «_extract_candidate_names_from_json» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: payload."""
    found: Set[str] = set()

    def _walk(obj: object) -> None:
        """Υλοποιεί το βήμα «_walk» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: obj."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {'name', 'model', 'id', 'slug'} and isinstance(value, str):
                    cleaned = _clean_cloud_tag(value)
                    if cleaned:
                        found.add(cleaned)
                _walk(value)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(payload)
    return sorted(found)

def extract_context_for_candidate_models_from_html(html_text: str, candidates: Set[str]) -> Dict[str, Dict[str, object]]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_context_for_candidate_models_from_html» με συνεπή τρόπο.

Βασικά ορίσματα: html_text, candidates."""
    compact = normalize_html_text(html_text)
    meta: Dict[str, Dict[str, object]] = {}
    if not compact or not candidates:
        return meta
    for candidate in sorted(candidates, key=len, reverse=True):
        if not _is_valid_cloud_tag(candidate):
            continue
        pattern = re.compile(f'(?<![A-Za-z0-9._/-]){re.escape(candidate)}(?![A-Za-z0-9._/-])')
        match = pattern.search(compact)
        if not match:
            continue
        window = compact[match.end():match.end() + 260]
        ctx_match = CONTEXT_WINDOW_RE.search(window)
        if not ctx_match:
            continue
        ctx_tokens = parse_context_window_tokens(ctx_match.group(1), ctx_match.group(2) or '')
        if not ctx_tokens:
            continue
        entry = meta.setdefault(candidate, {})
        entry['num_ctx_max'] = ctx_tokens
        entry['num_ctx_label'] = ctx_match.group(0).replace('context window', '').strip()
    return meta

def fetch_direct_api_models(timeout: int=8) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «fetch_direct_api_models» με συνεπή τρόπο.

Βασικά ορίσματα: timeout."""
    data = fetch_url_json(OFFICIAL_CLOUD_API_TAGS_URL, timeout=timeout)
    models = data.get('models', []) if isinstance(data, dict) else []
    exact_models: List[str] = []
    meta: Dict[str, Dict[str, object]] = {}
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            raw_name = str(item.get('model') or item.get('name') or '').strip()
            cleaned = _clean_cloud_tag(raw_name)
            if not cleaned or not _is_valid_cloud_tag(cleaned):
                continue
            exact_models.append(cleaned)
            details = item.get('details') if isinstance(item.get('details'), dict) else {}
            entry = meta.setdefault(cleaned, {})
            entry.setdefault('family', cleaned.split(':', 1)[0])
            size_bytes = int(item.get('size') or 0) if str(item.get('size') or '').strip() else 0
            if size_bytes > 0:
                entry.setdefault('size_bytes', size_bytes)
            modified_at = str(item.get('modified_at') or '').strip()
            if modified_at:
                entry.setdefault('modified_at', modified_at)
                entry.setdefault('modified_ts', parse_iso_datetime_to_timestamp(modified_at))
            inferred_caps = infer_model_capabilities_from_name(cleaned)
            if inferred_caps:
                entry.setdefault('capabilities', inferred_caps)
            if isinstance(details, dict):
                if details.get('parameter_size'):
                    param_size_text = str(details.get('parameter_size'))
                    entry.setdefault('parameter_size', param_size_text)
                    parsed_b = parse_parameter_size_to_billions(param_size_text)
                    if parsed_b > 0:
                        entry.setdefault('parameter_size_b', parsed_b)
                if details.get('family'):
                    entry.setdefault('family', str(details.get('family')))
            if 'parameter_size_b' not in entry:
                parsed_from_name = parse_parameter_size_to_billions(cleaned)
                if parsed_from_name > 0:
                    entry.setdefault('parameter_size_b', parsed_from_name)
    exact_models = sorted(set(exact_models))
    return (exact_models, meta)

def _try_json_apis(timeout: int=6) -> Tuple[Set[str], Set[str]]:
    """Υλοποιεί το βήμα «_try_json_apis» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: timeout."""
    tags: Set[str] = set()
    families: Set[str] = set()
    try:
        data = fetch_url_json(f'{OLLAMA_SEARCH_API_URL}?c=cloud&limit=500', timeout=timeout)
    except Exception:
        return (tags, families)
    for raw in _extract_candidate_names_from_json(data):
        cleaned = _clean_cloud_tag(raw)
        if not cleaned or not _is_valid_cloud_tag(cleaned):
            continue
        family = cleaned.split(':', 1)[0]
        families.add(family)
        if ':' in cleaned and 'cloud' in cleaned.lower():
            tags.add(cleaned)
    families.update(extract_families_from_api_tags(data))
    return (tags, families)

def extract_verified_cloud_models_for_family_from_html(html_text: str, family: str) -> List[str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_verified_cloud_models_for_family_from_html» με συνεπή τρόπο.

Βασικά ορίσματα: html_text, family."""
    compact = normalize_html_text(html_text)
    if not compact or not family:
        return []
    family = family.strip()
    fam_re = re.escape(family)
    pattern = re.compile(f'(?<![A-Za-z0-9._/-])({fam_re}(?::[A-Za-z0-9._-]+)?)(?![A-Za-z0-9._/-])', flags=re.IGNORECASE)
    found: Set[str] = set()
    for match in pattern.finditer(compact):
        candidate = _clean_cloud_tag(match.group(1).strip())
        if not candidate or not _is_valid_cloud_tag(candidate):
            continue
        window = compact[max(0, match.start() - 160):match.end() + 220]
        if CLOUD_WORD_RE.search(window):
            found.add(candidate)
    if any((item.startswith(family + ':') for item in found)):
        found.discard(family)
    return sorted(found)

def fetch_official_cloud_catalog(timeout_per_request: int=8) -> Tuple[List[str], Dict[str, Dict[str, object]]]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «fetch_official_cloud_catalog» με συνεπή τρόπο.

Βασικά ορίσματα: timeout_per_request."""
    import concurrent.futures
    direct_models, direct_meta = fetch_direct_api_models(timeout=max(6, timeout_per_request))
    if not direct_models:
        raise RuntimeError('Δεν βρέθηκαν official direct API models από το Ollama.')
    exact_model_set: Set[str] = set(direct_models)
    all_families: Set[str] = {m.split(':', 1)[0] for m in direct_models if m}
    all_meta: Dict[str, Dict[str, object]] = copy.deepcopy(direct_meta)
    for url in (OFFICIAL_SEARCH_URL, OFFICIAL_GENERAL_SEARCH_URL):
        try:
            raw_html = fetch_url_text(url, timeout=max(8, timeout_per_request + 1))
            all_families.update(extract_library_families(raw_html))
            merge_model_meta(all_meta, extract_context_for_candidate_models_from_html(raw_html, exact_model_set))
        except Exception:
            pass

    def _fetch_family_meta(fam: str) -> Dict[str, Dict[str, object]]:
        """Υλοποιεί το βήμα «_fetch_family_meta» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: fam."""
        try:
            _tags, meta = fetch_cloud_models_for_family(fam, timeout=timeout_per_request, family_candidates={m for m in exact_model_set if m.split(':', 1)[0] == fam})
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
        info.setdefault('family', model.split(':', 1)[0])
        final_meta[model] = info
    result = sorted(direct_models)
    with_context = sum((1 for model in result if final_meta.get(model, {}).get('num_ctx_max')))
    log.info('☁️  Βρέθηκαν %d official Ollama direct API models (%d με context metadata)', len(result), with_context)
    return (result, final_meta)
_SCORING_CRITERIA: Tuple[str, ...] = ('overall', 'coding', 'reasoning', 'context', 'vision', 'speed', 'newest')
_FAMILY_PRIOR_DEFAULTS: Dict[str, float] = {'overall': 7.5, 'coding': 7.2, 'reasoning': 7.35, 'context': 7.05, 'vision': 6.85, 'speed': 7.1}
_MODEL_FAMILY_PROFILES: List[Tuple[str, Dict[str, float]]] = [('gemini-3-flash', {'overall': 9.12, 'coding': 8.62, 'reasoning': 8.82, 'context': 8.95, 'vision': 9.35, 'speed': 9.95}), ('deepseek-v3.2', {'overall': 9.82, 'coding': 9.62, 'reasoning': 9.9, 'context': 9.14, 'vision': 6.2, 'speed': 4.7}), ('deepseek-v3.1', {'overall': 9.72, 'coding': 9.54, 'reasoning': 9.8, 'context': 9.02, 'vision': 6.0, 'speed': 4.82}), ('deepseek-r1', {'overall': 9.66, 'coding': 9.1, 'reasoning': 9.96, 'context': 8.4, 'vision': 5.25, 'speed': 3.86}), ('qwen3.5', {'overall': 9.96, 'coding': 9.74, 'reasoning': 9.92, 'context': 9.52, 'vision': 9.84, 'speed': 4.42}), ('qwen3-coder-next', {'overall': 9.56, 'coding': 9.96, 'reasoning': 9.42, 'context': 9.0, 'vision': 5.35, 'speed': 5.06}), ('qwen3-coder', {'overall': 9.68, 'coding': 9.98, 'reasoning': 9.6, 'context': 9.08, 'vision': 5.38, 'speed': 4.25}), ('qwen3-vl', {'overall': 9.58, 'coding': 9.26, 'reasoning': 9.42, 'context': 9.02, 'vision': 9.98, 'speed': 4.52}), ('qwen3-next', {'overall': 9.24, 'coding': 9.1, 'reasoning': 9.18, 'context': 8.86, 'vision': 7.92, 'speed': 5.12}), ('kimi-k2-thinking', {'overall': 9.62, 'coding': 9.22, 'reasoning': 9.9, 'context': 9.12, 'vision': 6.62, 'speed': 3.72}), ('kimi-k2.5', {'overall': 9.76, 'coding': 9.4, 'reasoning': 9.78, 'context': 9.28, 'vision': 7.12, 'speed': 4.12}), ('kimi-k2', {'overall': 9.58, 'coding': 9.22, 'reasoning': 9.62, 'context': 9.0, 'vision': 6.85, 'speed': 4.25}), ('glm-5', {'overall': 9.6, 'coding': 9.36, 'reasoning': 9.56, 'context': 9.12, 'vision': 8.72, 'speed': 4.15}), ('glm-4.7', {'overall': 9.46, 'coding': 9.18, 'reasoning': 9.44, 'context': 8.92, 'vision': 8.22, 'speed': 4.02}), ('glm-4.6', {'overall': 9.38, 'coding': 9.12, 'reasoning': 9.36, 'context': 8.78, 'vision': 8.05, 'speed': 4.1}), ('minimax-m2.7', {'overall': 9.42, 'coding': 9.06, 'reasoning': 9.4, 'context': 8.96, 'vision': 8.62, 'speed': 4.42}), ('minimax-m2.5', {'overall': 9.34, 'coding': 8.98, 'reasoning': 9.32, 'context': 8.86, 'vision': 8.46, 'speed': 4.58}), ('minimax-m2.1', {'overall': 9.22, 'coding': 8.92, 'reasoning': 9.2, 'context': 8.72, 'vision': 8.18, 'speed': 4.72}), ('minimax-m2', {'overall': 9.14, 'coding': 8.88, 'reasoning': 9.1, 'context': 8.64, 'vision': 8.0, 'speed': 4.86}), ('nemotron-3-super', {'overall': 9.32, 'coding': 8.92, 'reasoning': 9.28, 'context': 8.96, 'vision': 7.42, 'speed': 4.82}), ('nemotron-3-nano', {'overall': 8.76, 'coding': 8.36, 'reasoning': 8.68, 'context': 8.12, 'vision': 6.2, 'speed': 7.2}), ('mistral-large-3', {'overall': 9.22, 'coding': 9.0, 'reasoning': 9.18, 'context': 8.82, 'vision': 7.82, 'speed': 4.32}), ('devstral-small-2', {'overall': 8.98, 'coding': 9.42, 'reasoning': 8.7, 'context': 8.52, 'vision': 5.02, 'speed': 6.62}), ('devstral-2', {'overall': 9.18, 'coding': 9.74, 'reasoning': 8.96, 'context': 8.86, 'vision': 5.1, 'speed': 5.22}), ('devstral', {'overall': 8.98, 'coding': 9.42, 'reasoning': 8.72, 'context': 8.52, 'vision': 5.05, 'speed': 6.2}), ('gpt-oss', {'overall': 9.06, 'coding': 8.92, 'reasoning': 9.04, 'context': 8.62, 'vision': 5.1, 'speed': 5.9}), ('cogito-2.1', {'overall': 9.28, 'coding': 9.08, 'reasoning': 9.42, 'context': 8.92, 'vision': 6.22, 'speed': 3.92}), ('cogito', {'overall': 9.12, 'coding': 8.96, 'reasoning': 9.26, 'context': 8.76, 'vision': 6.02, 'speed': 4.2}), ('gemini-3', {'overall': 9.74, 'coding': 9.42, 'reasoning': 9.72, 'context': 9.46, 'vision': 9.82, 'speed': 5.12}), ('ministral-3', {'overall': 8.74, 'coding': 8.34, 'reasoning': 8.48, 'context': 8.22, 'vision': 6.22, 'speed': 8.24}), ('ministral', {'overall': 8.62, 'coding': 8.22, 'reasoning': 8.36, 'context': 8.06, 'vision': 6.05, 'speed': 8.0}), ('mistral-small', {'overall': 8.54, 'coding': 8.18, 'reasoning': 8.24, 'context': 7.96, 'vision': 5.92, 'speed': 8.2}), ('gemma3', {'overall': 8.58, 'coding': 8.22, 'reasoning': 8.34, 'context': 7.82, 'vision': 8.12, 'speed': 7.5}), ('rnj-1', {'overall': 8.32, 'coding': 7.96, 'reasoning': 8.16, 'context': 7.92, 'vision': 5.42, 'speed': 8.05}), ('rnj', {'overall': 8.24, 'coding': 7.88, 'reasoning': 8.08, 'context': 7.84, 'vision': 5.32, 'speed': 8.1})]
_MODEL_TRAIT_HINTS: List[Tuple[str, Set[str]]] = [('qwen3.5', {'reasoning', 'coding', 'vision'}), ('qwen3-vl', {'vision', 'reasoning', 'coding'}), ('qwen3-coder', {'coding', 'reasoning'}), ('qwen3-next', {'reasoning', 'coding', 'vision'}), ('deepseek-v3.2', {'reasoning', 'coding'}), ('deepseek-v3.1', {'reasoning', 'coding'}), ('deepseek-r1', {'reasoning'}), ('kimi-k2.5', {'reasoning', 'coding'}), ('kimi-k2', {'reasoning', 'coding'}), ('glm-5', {'reasoning', 'coding', 'vision'}), ('glm-4', {'reasoning', 'coding', 'vision'}), ('gemini-3', {'reasoning', 'coding', 'vision'}), ('devstral', {'coding'}), ('gpt-oss', {'reasoning', 'coding'}), ('nemotron-3-super', {'reasoning', 'coding'}), ('nemotron-3-nano', {'reasoning'}), ('mistral-large-3', {'reasoning', 'coding'}), ('cogito', {'reasoning', 'coding'}), ('ministral-3', {'reasoning', 'coding'}), ('gemma3', {'reasoning', 'coding', 'vision'})]

def canonical_model_key(model_name: str) -> str:
    """Υλοποιεί το βήμα «canonical_model_key» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model_name."""
    key = normalize_model_name(str(model_name or '')).strip().lower()
    if not key:
        return ''
    if ':' in key:
        family, tag = key.split(':', 1)
        if tag.endswith('-cloud'):
            tag = tag[:-6]
        key = f'{family}:{tag}'
    elif key.endswith('-cloud'):
        key = key[:-6]
    return key.strip(':')

def model_matches_prefix(model_name: str, prefix: str) -> bool:
    """Υλοποιεί το βήμα «model_matches_prefix» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model_name, prefix."""
    key = canonical_model_key(model_name)
    prefix = str(prefix or '').strip().lower()
    if not key or not prefix:
        return False
    return key.startswith(prefix) or prefix in key

def get_family_profile(model_name: str) -> Dict[str, float]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_family_profile» με συνεπή τρόπο.

Βασικά ορίσματα: model_name."""
    for prefix, profile in _MODEL_FAMILY_PROFILES:
        if model_matches_prefix(model_name, prefix):
            return profile
    return _FAMILY_PRIOR_DEFAULTS

def get_model_capabilities(model_name: str, meta: Optional[Dict[str, object]]=None) -> Set[str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_model_capabilities» με συνεπή τρόπο.

Βασικά ορίσματα: model_name, meta."""
    capabilities: Set[str] = set(infer_model_capabilities_from_name(model_name))
    if isinstance(meta, dict):
        raw_caps = meta.get('capabilities')
        if isinstance(raw_caps, list):
            for item in raw_caps:
                if isinstance(item, str) and item.strip():
                    capabilities.add(item.strip().lower())
        if isinstance(meta.get('families'), list):
            for item in meta.get('families', []):
                if isinstance(item, str):
                    capabilities.update(infer_model_capabilities_from_name(item))
        family = str(meta.get('family') or '').strip()
        if family:
            capabilities.update(infer_model_capabilities_from_name(family))
    capabilities.add('completion')
    return capabilities

def get_model_size_billions(model_name: str, meta: Optional[Dict[str, object]]=None) -> float:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_model_size_billions» με συνεπή τρόπο.

Βασικά ορίσματα: model_name, meta."""
    if isinstance(meta, dict):
        raw_b = meta.get('parameter_size_b')
        try:
            size_b = float(raw_b)
        except Exception:
            size_b = 0.0
        if size_b > 0:
            return max(0.0, min(size_b, 1000.0))
        try:
            size_bytes = float(meta.get('size_bytes') or 0)
        except Exception:
            size_bytes = 0.0
        if size_bytes > 0:
            return max(0.0, min(size_bytes / 1000000000.0, 1000.0))
    parsed = parse_parameter_size_to_billions(canonical_model_key(model_name))
    return max(0.0, min(parsed, 1000.0)) if parsed > 0 else 0.0

def get_model_context_tokens(model_name: str, meta: Optional[Dict[str, object]]=None) -> int:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_model_context_tokens» με συνεπή τρόπο.

Βασικά ορίσματα: model_name, meta."""
    if isinstance(meta, dict):
        try:
            ctx = int(meta.get('num_ctx_max') or 0)
        except Exception:
            ctx = 0
        if ctx > 0:
            return ctx
    return 0

def get_model_modified_ts(model_name: str, meta: Optional[Dict[str, object]]=None) -> float:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_model_modified_ts» με συνεπή τρόπο.

Βασικά ορίσματα: model_name, meta."""
    if isinstance(meta, dict):
        try:
            raw_ts = float(meta.get('modified_ts') or 0)
        except Exception:
            raw_ts = 0.0
        if raw_ts > 0:
            return raw_ts
        raw_date = str(meta.get('modified_at') or '').strip()
        if raw_date:
            return parse_iso_datetime_to_timestamp(raw_date)
    return 0.0

def _clamp(value: float, low: float, high: float) -> float:
    """Υλοποιεί το βήμα «_clamp» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: value, low, high."""
    return max(low, min(value, high))

def _size_quality_strength(size_b: float) -> float:
    """Υλοποιεί το βήμα «_size_quality_strength» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: size_b."""
    import math
    if size_b <= 0:
        return 4.8
    normalized = math.log2(min(size_b, 1000.0) + 1.0) / math.log2(1001.0)
    return 3.8 + normalized * 6.2

def _size_speed_strength(size_b: float) -> float:
    """Υλοποιεί το βήμα «_size_speed_strength» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: size_b."""
    import math
    if size_b <= 0:
        return 7.8
    normalized = math.log2(min(size_b, 1000.0) + 1.0) / math.log2(1001.0)
    return 9.8 - normalized * 7.2

def _context_strength(ctx_tokens: int) -> float:
    """Υλοποιεί το βήμα «_context_strength» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: ctx_tokens."""
    import math
    if ctx_tokens <= 0:
        return 3.2
    normalized = _clamp(math.log2(float(ctx_tokens)) / 18.0, 0.0, 1.08)
    bonus = 0.7 if ctx_tokens >= 200000 else 0.35 if ctx_tokens >= 128000 else 0.0
    return min(10.0, 3.6 + normalized * 6.0 + bonus)

def _freshness_strength(modified_ts: float) -> float:
    """Υλοποιεί το βήμα «_freshness_strength» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: modified_ts."""
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
    """Υλοποιεί το βήμα «_name_signal_bonus» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model_name, criterion."""
    name = canonical_model_key(model_name)
    bonus = 0.0
    if criterion == 'coding':
        if any((token in name for token in ('coder', 'devstral', 'terminal', 'swe'))):
            bonus += 0.9
        if any((token in name for token in ('code', 'oss'))):
            bonus += 0.25
    elif criterion == 'reasoning':
        if any((token in name for token in ('thinking', 'reason', 'reasoning', 'r1'))):
            bonus += 0.95
        if any((token in name for token in ('deepseek', 'cogito'))):
            bonus += 0.2
    elif criterion == 'vision':
        if any((token in name for token in ('-vl', ':vl', 'vision', 'gemini', 'pixtral', 'llava'))):
            bonus += 0.95
    elif criterion == 'speed':
        if any((token in name for token in ('flash', 'nano', 'mini', 'small'))):
            bonus += 1.15
        if any((token in name for token in ('preview',))):
            bonus += 0.2
    elif criterion == 'overall':
        if any((token in name for token in ('thinking', 'coder', '-vl', ':vl', 'vision'))):
            bonus += 0.18
    return bonus

def score_model(model_name: str, meta: Optional[Dict[str, object]]=None, criterion: str='overall') -> float:
    """Υλοποιεί το βήμα «score_model» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model_name, meta, criterion."""
    criterion = (criterion or 'overall').strip().lower()
    if criterion not in _SCORING_CRITERIA:
        criterion = 'overall'
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
    has_reasoning = 10.0 if 'reasoning' in caps else 0.0
    has_coding = 10.0 if 'coding' in caps else 0.0
    has_vision = 10.0 if 'vision' in caps else 0.0
    bonus = _name_signal_bonus(model_name, criterion)
    if criterion == 'coding':
        return base_prior * 0.56 + size_quality * 0.1 + context_strength * 0.1 + freshness * 0.05 + has_coding * 0.14 + has_reasoning * 0.04 + bonus
    if criterion == 'reasoning':
        return base_prior * 0.56 + size_quality * 0.11 + context_strength * 0.06 + freshness * 0.04 + has_reasoning * 0.13 + has_coding * 0.03 + bonus
    if criterion == 'context':
        if ctx > 0:
            return context_strength * 0.74 + base_prior * 0.14 + size_quality * 0.08 + freshness * 0.04
        return base_prior * 0.22 + size_quality * 0.12 + freshness * 0.06
    if criterion == 'vision':
        return base_prior * 0.58 + size_quality * 0.09 + context_strength * 0.06 + freshness * 0.04 + has_vision * 0.18 + has_reasoning * 0.02 + bonus
    if criterion == 'speed':
        return base_prior * 0.15 + size_speed * 0.6 + freshness * 0.1 + context_strength * 0.05 + (0.2 if size_b and size_b <= 24.0 else 0.0) + bonus
    if criterion == 'newest':
        return modified_ts if modified_ts > 0 else 0.0
    return base_prior * 0.56 + size_quality * 0.12 + context_strength * 0.06 + freshness * 0.05 + has_reasoning * 0.08 + has_coding * 0.06 + has_vision * 0.04 + bonus

def recommend_best_model(models: List[str], model_meta: Optional[Dict[str, Dict[str, object]]]=None, criterion: str='overall') -> str:
    """Λαμβάνει απόφαση για το βήμα «recommend_best_model» εφαρμόζοντας τους κανόνες που χρησιμοποιεί η εφαρμογή.

Βασικά ορίσματα: models, model_meta, criterion."""
    if not models:
        return ''
    scored = sorted(models, key=lambda model: score_model(model, (model_meta or {}).get(model, {}), criterion), reverse=True)
    return scored[0]

def wait_for_model_refresh(timeout: float=45.0, poll_interval: float=0.15) -> bool:
    """Υλοποιεί το βήμα «wait_for_model_refresh» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: timeout, poll_interval."""
    deadline = time.time() + max(0.5, timeout)
    while time.time() < deadline:
        with REGISTRY.lock:
            in_progress = REGISTRY.refresh_in_progress
        if not in_progress:
            return True
        time.sleep(max(0.05, poll_interval))
    return False

def refresh_models(force: bool=False, wait_if_running: bool=True) -> None:
    """Υλοποιεί τη λειτουργική ρουτίνα «refresh_models» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: force, wait_if_running."""
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
            REGISTRY.models = list(online_models)
            REGISTRY.model_meta = copy.deepcopy(online_meta)
            REGISTRY.source = 'official-online'
            REGISTRY.last_error = ''
            REGISTRY.last_refresh_ts = time.time()
            REGISTRY.recommended_model = recommend_best_model(online_models, online_meta, 'overall')
    except Exception as exc:
        with REGISTRY.lock:
            REGISTRY.source = 'stale-online-cache' if REGISTRY.models else 'error'
            REGISTRY.last_error = str(exc)
            REGISTRY.last_refresh_ts = time.time()
            REGISTRY.recommended_model = recommend_best_model(REGISTRY.models, REGISTRY.model_meta, 'overall')
    finally:
        with REGISTRY.lock:
            REGISTRY.refresh_in_progress = False

def refresh_models_in_background(force: bool=False) -> None:
    """Υλοποιεί τη λειτουργική ρουτίνα «refresh_models_in_background» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: force."""

    def _runner() -> None:
        """Υλοποιεί το βήμα «_runner» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        with REGISTRY.lock:
            if REGISTRY.refresh_in_progress and (not REGISTRY.last_refresh_ts):
                REGISTRY.refresh_in_progress = False
        refresh_models(force=force, wait_if_running=False)
    threading.Thread(target=_runner, daemon=True).start()

def validate_python_code_block(code_text: str) -> Tuple[bool, str]:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «validate_python_code_block» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: code_text."""
    try:
        ast.parse(code_text, filename='<python_block>')
        return (True, '')
    except SyntaxError as exc:
        line_no = getattr(exc, 'lineno', None) or 0
        offset = getattr(exc, 'offset', None) or 0
        bad_line = ''
        lines = code_text.splitlines()
        if 1 <= line_no <= len(lines):
            bad_line = lines[line_no - 1]
        pointer = ' ' * max(offset - 1, 0) + '^' if offset else ''
        details = [f'SyntaxError στη γραμμή {line_no}: {exc.msg}']
        if bad_line:
            details.append(bad_line)
        if pointer:
            details.append(pointer)
        return (False, '\n'.join(details))
    except Exception as exc:
        return (False, f'Αποτυχία ελέγχου Python block: {exc}')

def resolve_python_for_generated_scripts() -> Tuple[Optional[List[str]], str]:
    """Λαμβάνει απόφαση για το βήμα «resolve_python_for_generated_scripts» εφαρμόζοντας τους κανόνες που χρησιμοποιεί η εφαρμογή."""
    if not getattr(sys, 'frozen', False):
        exe = os.path.normpath(sys.executable or 'python')
        return ([exe], 'sys.executable')
    candidates: List[Tuple[List[str], str]] = [(['py', '-3'], 'Python Launcher (py -3)'), (['python'], 'system python'), (['python3'], 'system python3')]
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    for command, label in candidates:
        try:
            test = subprocess.run(command + ['-c', 'import sys; print(sys.executable)'], capture_output=True, text=True, timeout=8, creationflags=creationflags)
            if test.returncode == 0:
                return (command, label)
        except Exception:
            continue
    return (None, 'missing')

def launch_python_code_in_terminal(code_text: str, suggested_filename: str='') -> Tuple[bool, str]:
    """Υλοποιεί τη λειτουργική ρουτίνα «launch_python_code_in_terminal» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: code_text, suggested_filename."""
    code_text = str(code_text or '')
    if not code_text.strip():
        return (False, 'Το Python block είναι κενό.')
    if len(code_text) > 250000:
        return (False, 'Το Python block είναι υπερβολικά μεγάλο για εκτέλεση.')
    is_valid, validation_message = validate_python_code_block(code_text)
    if not is_valid:
        return (False, validation_message)
    exec_root_dir = os.path.join(tempfile.gettempdir(), 'ollama_cloud_chat_exec')
    os.makedirs(exec_root_dir, exist_ok=True)
    session_dir = tempfile.mkdtemp(prefix='run_', dir=exec_root_dir)
    requested_name = str(suggested_filename or '').strip() or suggest_python_filename(code_text)
    safe_name = sanitize_filename(requested_name)
    if not safe_name.lower().endswith('.py'):
        safe_name += '.py'
    script_name = safe_name
    script_path = os.path.join(session_dir, script_name)
    with open(script_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(code_text)
    python_cmd, python_source = resolve_python_for_generated_scripts()
    if not python_cmd:
        return (False, 'Δεν βρέθηκε εγκατεστημένος Python interpreter για το >Run.\nΣτο packaged .exe το sys.executable δείχνει το ίδιο το app και όχι python.exe.\nΕγκατάστησε Python ή χρησιμοποίησε πρώτα το 💾 Save και μετά τρέξε το .py χειροκίνητα.')
    launcher_stem = Path(safe_name).stem or 'generated_block'
    try:
        if os.name == 'nt':
            launcher_path = os.path.join(session_dir, f'run_{launcher_stem}.bat')
            command_line = subprocess.list2cmdline(python_cmd + [script_path])
            launcher_lines = ['@echo off', 'setlocal', 'chcp 65001>nul', f'title Python Code Block Runner - {safe_name}', command_line, 'echo.', 'echo Exit code: %ERRORLEVEL%', 'pause']
            with open(launcher_path, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write('\r\n'.join(launcher_lines) + '\r\n')
            subprocess.Popen(['cmd.exe', '/k', launcher_path], creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
            return (True, f'Το Python block αποθηκεύτηκε ως {safe_name} και εκτελείται σε νέο terminal με interpreter από {python_source}.')
        elif sys.platform == 'darwin':
            shell_cmd = ' '.join((shlex.quote(part) for part in python_cmd + [script_path]))
            shell_cmd += '; echo; echo Press Enter to close...; read'
            apple_script = f'tell application "Terminal" to do script {json.dumps(shell_cmd)}'
            subprocess.Popen(['osascript', '-e', apple_script])
        else:
            shell_cmd = ' '.join((shlex.quote(part) for part in python_cmd + [script_path]))
            shell_cmd += "; printf '\n\nPress Enter to close...'; read _"
            launched = False
            terminal_commands = [['x-terminal-emulator', '-e', 'bash', '-lc', shell_cmd], ['gnome-terminal', '--', 'bash', '-lc', shell_cmd], ['konsole', '-e', 'bash', '-lc', shell_cmd], ['xfce4-terminal', '-e', f'bash -lc {shlex.quote(shell_cmd)}']]
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
        return (False, f'Αποτυχία ανοίγματος terminal: {exc}')
    return (True, f'Το Python block αποθηκεύτηκε ως {safe_name} και εκτελείται σε νέο terminal με interpreter από {python_source}.')

def _send_security_headers(handler: BaseHTTPRequestHandler) -> None:
    """Υλοποιεί το βήμα «_send_security_headers» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: handler."""
    for key, value in SECURITY_HEADERS.items():
        handler.send_header(key, value)

def json_response(handler: BaseHTTPRequestHandler, payload: Dict, status: int=200) -> None:
    """Εξυπηρετεί το HTTP ή streaming κομμάτι που αντιστοιχεί στο βήμα «json_response».

Βασικά ορίσματα: handler, payload, status."""
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    _send_security_headers(handler)
    handler.end_headers()
    handler.wfile.write(data)

def stream_json_line(handler: BaseHTTPRequestHandler, payload: Dict) -> None:
    """Εξυπηρετεί το HTTP ή streaming κομμάτι που αντιστοιχεί στο βήμα «stream_json_line».

Βασικά ορίσματα: handler, payload."""
    data = (json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8')
    try:
        handler.wfile.write(data)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
        raise BrokenPipeError('Client disconnected during stream')

def is_client_disconnect_error(exc: BaseException) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_client_disconnect_error» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: exc."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
        return True
    if isinstance(exc, OSError):
        winerror = getattr(exc, 'winerror', None)
        errno_ = getattr(exc, 'errno', None)
        return winerror in {10053, 10054} or errno_ in {32, 54, 104, 107, 108}
    return False

def safe_read_json(handler: BaseHTTPRequestHandler) -> Dict:
    """Υλοποιεί το βήμα «safe_read_json» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: handler."""
    try:
        content_length = int(handler.headers.get('Content-Length', '0'))
    except (ValueError, TypeError):
        content_length = 0
    if content_length > MAX_REQUEST_BODY_BYTES:
        log.warning('Απορρίφθηκε request %d bytes (όριο: %d)', content_length, MAX_REQUEST_BODY_BYTES)
        return {'__error__': 'request_too_large'}
    if content_length <= 0:
        return {}
    try:
        body = handler.rfile.read(content_length)
    except (OSError, ConnectionError) as exc:
        log.warning('Αποτυχία ανάγνωσης request body: %s', exc)
        return {}
    if not body:
        return {}
    try:
        return json.loads(body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}

class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Ορίζει την κλάση QuietThreadingHTTPServer και συγκεντρώνει σε ένα σημείο τη σχετική κατάσταση και συμπεριφορά.

Ο διαχωρισμός αυτός βοηθά τον κώδικα να παραμένει οργανωμένος, επεκτάσιμος και ευκολότερος στη συντήρηση."""
    daemon_threads = True
    allow_reuse_address = True
    timeout = 60

    def handle_error(self, request, client_address) -> None:
        """Υλοποιεί το βήμα «handle_error» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: request, client_address."""
        _, exc, _ = sys.exc_info()
        if exc is not None and is_client_disconnect_error(exc):
            return
        super().handle_error(request, client_address)

def is_ollama_connection_refused(exc: object) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_ollama_connection_refused» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: exc."""
    text = str(exc or '').lower()
    needles = ('10061', 'actively refused', 'connection refused', 'failed to establish a new connection', 'max retries exceeded')
    return any((n in text for n in needles))

def build_friendly_chat_error(exc: object) -> str:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_friendly_chat_error».

Βασικά ορίσματα: exc."""
    text = str(exc or '')
    lower = text.lower()
    if 'ollama_api_key' in lower or ('api key' in lower and ('missing' in lower or 'required' in lower)):
        return "Λείπει το Ollama Cloud API key για direct κλήσεις στο Ollama Cloud API. Βάλ'το στο πεδίο API Key του GUI ή αποθήκευσέ το στο settings αρχείο της εφαρμογής ή όρισέ το ως OLLAMA_API_KEY και ξανατρέξε την εφαρμογή."
    if is_ollama_connection_refused(exc):
        return 'Αποτυχία επικοινωνίας με το Ollama Cloud API. Έλεγξε τη σύνδεσή σου στο διαδίκτυο και δοκίμασε ξανά.'
    if '404' in text or 'not found' in lower or 'does not exist' in lower:
        return 'Το μοντέλο δεν βρέθηκε στο direct Ollama Cloud API. Στο direct mode τα επίσημα model names προέρχονται αποκλειστικά από το /api/tags και συχνά διαφέρουν από τα local *-cloud names. Κάνε Refresh Models και επίλεξε κάποιο από την επίσημη direct API λίστα.'
    if '401' in text or '403' in text or 'unauthorized' in lower or ('forbidden' in lower):
        return 'Το OLLAMA_API_KEY λείπει ή δεν είναι έγκυρο για το direct Ollama Cloud API. Έλεγξε το API key και δοκίμασε ξανά.'
    if 'network error' in lower or 'δικτυακό σφάλμα' in lower or 'name or service not known' in lower:
        return 'Δεν ήταν δυνατή η επικοινωνία με το Ollama Cloud API. Έλεγξε σύνδεση internet, firewall ή proxy.'
    if 'timeout' in lower or 'timed out' in lower or 'read timeout' in lower:
        return 'Το αίτημα προς το Ollama Cloud API έληξε (timeout). Το μοντέλο ίσως χρειάζεται περισσότερο χρόνο — δοκίμασε ξανά.'
    if 'context' in lower and ('length' in lower or 'window' in lower or 'exceed' in lower):
        return 'Το context window του μοντέλου ξεπεράστηκε. Δοκίμασε να καθαρίσεις το chat ή να μειώσεις το μέγεθος των συνημμένων.'
    return text or 'Άγνωστο σφάλμα επικοινωνίας με το Ollama Cloud API.'

def normalize_model_name(model: str) -> str:
    """Κανονικοποιεί ή καθαρίζει δεδομένα στο βήμα «normalize_model_name» ώστε οι επόμενες φάσεις να λαμβάνουν ασφαλή και συνεπή είσοδο.

Βασικά ορίσματα: model."""
    model = (model or '').strip()
    if '/' in model and ':' in model:
        name_part, tag_part = model.split(':', 1)
        name_part = name_part.split('/')[-1]
        return f'{name_part}:{tag_part}'
    return model

def extract_chunk_content(chunk: object) -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_chunk_content» με συνεπή τρόπο.

Βασικά ορίσματα: chunk."""
    if chunk is None:
        return ''
    try:
        message = chunk.get('message', {}) if isinstance(chunk, dict) else getattr(chunk, 'message', None)
        if message is None:
            return str(getattr(chunk, 'content', '') or '')
        if isinstance(message, dict):
            return str(message.get('content', '') or '')
        return str(getattr(message, 'content', '') or '')
    except Exception:
        return ''

def extract_chunk_thinking(chunk: object) -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_chunk_thinking» με συνεπή τρόπο.

Βασικά ορίσματα: chunk."""
    if chunk is None:
        return ''
    try:
        message = chunk.get('message', {}) if isinstance(chunk, dict) else getattr(chunk, 'message', None)
        if message is None:
            return str(getattr(chunk, 'thinking', '') or '')
        if isinstance(message, dict):
            return str(message.get('thinking', '') or '')
        return str(getattr(message, 'thinking', '') or '')
    except Exception:
        return ''

def compose_display_assistant_text(content: str, thinking: str='') -> str:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «compose_display_assistant_text».

Βασικά ορίσματα: content, thinking."""
    safe_content = str(content or '')
    safe_thinking = str(thinking or '')
    if safe_thinking and safe_content:
        return f'<think>{safe_thinking}</think>\n\n{safe_content}'
    if safe_thinking:
        return f'<think>{safe_thinking}</think>'
    return safe_content
_INLINE_THINK_RE = re.compile('<think>.*?</think>\\s*', flags=re.IGNORECASE | re.DOTALL)

def strip_inline_think_blocks(text: str) -> str:
    """Υλοποιεί το βήμα «strip_inline_think_blocks» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: text."""
    return _INLINE_THINK_RE.sub('', str(text or '')).strip()

def is_gpt_oss_model(model: str) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_gpt_oss_model» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: model."""
    return 'gpt-oss' in str(model or '').strip().lower()

def is_qwen3_next_model(model: str) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_qwen3_next_model» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: model."""
    model_l = str(model or '').strip().lower()
    return 'qwen3-next' in model_l or 'qwen 3 next' in model_l

def is_qwen3_vl_model(model: str) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_qwen3_vl_model» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: model."""
    model_l = str(model or '').strip().lower()
    return 'qwen3-vl' in model_l or 'qwen 3 vl' in model_l or 'qwen 3-vl' in model_l

def is_qwen3_coder_next_model(model: str) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_qwen3_coder_next_model» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: model."""
    model_l = str(model or '').strip().lower()
    return 'qwen3-coder-next' in model_l or 'qwen 3 coder next' in model_l

def is_reasoning_capable_model(model: str) -> bool:
    """Εκτελεί έλεγχο που σχετίζεται με το βήμα «is_reasoning_capable_model» και επιστρέφει αποτέλεσμα κατάλληλο για άμεση αξιοποίηση.

Βασικά ορίσματα: model."""
    model_l = str(model or '').strip().lower()
    thinking_hints = ('qwen3', 'deepseek-r1', 'deepseek-v3.1', 'reason', 'thinking', 'r1', 'gpt-oss')
    return any((token in model_l for token in thinking_hints))

def apply_qwen3_vl_nothink_workaround(messages: List[Dict], model: str, raw_mode: object) -> List[Dict]:
    """Υλοποιεί το βήμα «apply_qwen3_vl_nothink_workaround» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: messages, model, raw_mode."""
    mode = str(raw_mode or 'auto').strip().lower()
    if mode not in {'off', 'none'}:
        return messages
    if not is_qwen3_vl_model(model):
        return messages
    patched: List[Dict] = []
    last_user_index: Optional[int] = None
    for idx, item in enumerate(messages or []):
        if isinstance(item, dict):
            cloned = dict(item)
            patched.append(cloned)
            if str(cloned.get('role') or '').strip().lower() == 'user':
                last_user_index = idx
        else:
            patched.append(item)
    if last_user_index is None:
        return messages
    target = patched[last_user_index]
    content = str(target.get('content') or '')
    lower = content.lower()
    if '/no_think' not in lower and '/set nothink' not in lower:
        target['content'] = (content.rstrip() + '\n\n/no_think').strip()
    return patched

def resolve_think_mode(model: str, raw_mode: object) -> Optional[object]:
    """Λαμβάνει απόφαση για το βήμα «resolve_think_mode» εφαρμόζοντας τους κανόνες που χρησιμοποιεί η εφαρμογή.

Βασικά ορίσματα: model, raw_mode."""
    mode = str(raw_mode or 'auto').strip().lower()
    model_l = str(model or '').strip().lower()
    if is_qwen3_coder_next_model(model):
        return None
    if mode in {'off', 'none'}:
        if is_gpt_oss_model(model):
            return 'low'
        if is_qwen3_next_model(model):
            return 'low'
        return False
    if mode == 'minimal':
        if is_gpt_oss_model(model):
            return 'low'
        if is_qwen3_next_model(model):
            return 'low'
        return True
    if mode in {'low', 'medium', 'high'}:
        if is_gpt_oss_model(model) or is_qwen3_next_model(model):
            return mode
        return True
    if mode == 'on':
        if is_gpt_oss_model(model):
            return 'medium'
        return True
    if mode != 'auto':
        log.warning('resolve_think_mode: άγνωστο mode %r — fallback σε auto', raw_mode)
    if is_gpt_oss_model(model):
        return 'medium'
    if any((token in model_l for token in ('qwen3-next',))):
        return True
    thinking_hints = ('qwen3', 'deepseek-r1', 'deepseek-v3.1', 'reason', 'thinking', 'r1')
    if any((token in model_l for token in thinking_hints)):
        return True
    return None

def iter_with_leading_chunk(first_chunk: object, iterator):
    """Υλοποιεί το βήμα «iter_with_leading_chunk» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: first_chunk, iterator."""
    yield first_chunk
    for chunk in iterator:
        yield chunk

def _build_think_fallback_candidates(model: str, think_value: Optional[object], raw_mode: object) -> List[Optional[object]]:
    """Υλοποιεί το βήμα «_build_think_fallback_candidates» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model, think_value, raw_mode."""
    candidates: List[Optional[object]] = []
    mode = str(raw_mode or 'auto').strip().lower()

    def add(value: Optional[object]) -> None:
        """Υλοποιεί το βήμα «add» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: value."""
        if value not in candidates:
            candidates.append(value)
    add(think_value)
    if think_value is False:
        if is_qwen3_next_model(model):
            add('low')
            add(None)
        elif is_gpt_oss_model(model):
            add('low')
        else:
            add(None)
    elif think_value in {'low', 'medium', 'high'}:
        if is_qwen3_next_model(model):
            add(True)
            if mode == 'off':
                add(None)
        elif not is_gpt_oss_model(model):
            add(True)
    elif think_value is True:
        if is_qwen3_next_model(model):
            add('medium')
        elif is_gpt_oss_model(model):
            add('medium')
    elif think_value is None and is_reasoning_capable_model(model):
        add(True)
    return candidates

def _is_think_compat_error(exc: Exception) -> bool:
    """Υλοποιεί το βήμα «_is_think_compat_error» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: exc."""
    lower = str(exc).lower()
    return ' think ' in f' {lower} ' or 'invalid think value' in lower or 'reasoning_effort' in lower or ('reasoning effort' in lower)

def open_direct_cloud_chat_stream_with_fallback(*, model: str, messages: List[Dict], model_options: Optional[Dict], think_value: Optional[object], requested_mode: object) -> Tuple[object, Optional[object], List[str], bool]:
    """Υλοποιεί τη λειτουργική ρουτίνα «open_direct_cloud_chat_stream_with_fallback» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο."""
    candidates = _build_think_fallback_candidates(model, think_value, requested_mode)
    suppress_reasoning = str(requested_mode or '').strip().lower() in {'off', 'none'}
    warnings: List[str] = []
    first_error: Optional[Exception] = None
    last_error: Optional[Exception] = None
    for index, candidate in enumerate(candidates):
        stream_iter = direct_cloud_chat_stream(model=model, messages=messages, model_options=model_options if model_options else None, think_value=candidate)
        try:
            first_chunk = next(stream_iter)
            if index > 0:
                if candidate == 'low' and suppress_reasoning:
                    warnings.append(f"Το thinking mode για το μοντέλο {model} δεν δέχτηκε hard off από το Ollama Cloud API/model. Έγινε compatibility fallback σε think='low' και το reasoning trace αποκρύπτεται στο UI.")
                elif candidate is None:
                    warnings.append(f'Το thinking mode για το μοντέλο {model} δεν υποστηρίχθηκε πλήρως από το τρέχον Ollama Cloud API/model. Η απάντηση συνεχίζεται χωρίς ρητό think parameter.')
                else:
                    warnings.append(f'Το thinking mode για το μοντέλο {model} δεν υποστηρίχθηκε όπως ζητήθηκε και έγινε fallback σε think={candidate!r}.')
            return (iter_with_leading_chunk(first_chunk, stream_iter), candidate, warnings, suppress_reasoning)
        except StopIteration:
            if index > 0:
                warnings.append(f'Το thinking mode για το μοντέλο {model} χρειάστηκε fallback σε think={candidate!r}.')
            return (iter(()), candidate, warnings, suppress_reasoning)
        except Exception as exc:
            if first_error is None:
                first_error = exc
            last_error = exc
            if not _is_think_compat_error(exc):
                raise
            log.warning('Αποτυχία think compatibility για model=%s requested_mode=%r candidate=%r: %s', model, requested_mode, candidate, exc)
            continue
    raise last_error or first_error or RuntimeError('Αποτυχία εκκίνησης stream.')

def extract_token_stats(chunk: object) -> Optional[Dict]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_token_stats» με συνεπή τρόπο.

Βασικά ορίσματα: chunk."""
    try:
        if isinstance(chunk, dict):
            eval_count = chunk.get('eval_count')
            eval_duration = chunk.get('eval_duration')
            prompt_eval_count = chunk.get('prompt_eval_count')
            prompt_eval_duration = chunk.get('prompt_eval_duration')
            total_duration = chunk.get('total_duration')
            load_duration = chunk.get('load_duration')
        else:
            eval_count = getattr(chunk, 'eval_count', None)
            eval_duration = getattr(chunk, 'eval_duration', None)
            prompt_eval_count = getattr(chunk, 'prompt_eval_count', None)
            prompt_eval_duration = getattr(chunk, 'prompt_eval_duration', None)
            total_duration = getattr(chunk, 'total_duration', None)
            load_duration = getattr(chunk, 'load_duration', None)
        if not eval_count or not eval_duration or eval_duration <= 0:
            return None
        tokens_per_sec = round(eval_count / (eval_duration / 1000000000.0), 1)
        prompt_tokens_per_sec = None
        if prompt_eval_count and prompt_eval_duration and (prompt_eval_duration > 0):
            prompt_tokens_per_sec = round(prompt_eval_count / (prompt_eval_duration / 1000000000.0), 1)
        end_to_end_tokens_per_sec = None
        if total_duration and total_duration > 0:
            end_to_end_tokens_per_sec = round(eval_count / (total_duration / 1000000000.0), 1)
        return {'eval_count': eval_count, 'eval_duration': eval_duration, 'tokens_per_sec': tokens_per_sec, 'prompt_eval_count': prompt_eval_count, 'prompt_eval_duration': prompt_eval_duration, 'prompt_tokens_per_sec': prompt_tokens_per_sec, 'total_duration': total_duration, 'load_duration': load_duration, 'end_to_end_tokens_per_sec': end_to_end_tokens_per_sec}
    except Exception:
        pass
    return None

def get_effective_system_prompt(gui_system_prompt: str='') -> Tuple[str, str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_effective_system_prompt» με συνεπή τρόπο.

Βασικά ορίσματα: gui_system_prompt."""
    cleaned = (gui_system_prompt or '').strip()
    if cleaned:
        return (cleaned, 'gui-custom')
    return get_embedded_system_prompt()

def build_messages(system_prompt: str, session_messages: List[Dict]) -> List[Dict]:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_messages».

Βασικά ορίσματα: system_prompt, session_messages."""
    messages: List[Dict] = []
    cleaned_system = (system_prompt or '').strip()
    if cleaned_system:
        messages.append({'role': 'system', 'content': cleaned_system})
    for item in session_messages:
        role = item.get('role', '').strip()
        content = item.get('content', '')
        if role in {'user', 'assistant'} and isinstance(content, str):
            msg: Dict = {'role': role, 'content': content}
            if role == 'assistant' and isinstance(item.get('thinking'), str) and item.get('thinking', '').strip():
                msg['thinking'] = item['thinking']
            if role == 'user' and item.get('images'):
                b64_images: List[str] = []
                for img in item['images']:
                    img_str = str(img or '').strip()
                    if not img_str:
                        continue
                    if len(img_str) > 260 or img_str.startswith('/') or (len(img_str) > 1 and img_str[1] == ':'):
                        try:
                            b64_images.append(base64.b64encode(Path(img_str).read_bytes()).decode('ascii'))
                        except Exception:
                            pass
                    else:
                        b64_images.append(img_str)
                if b64_images:
                    msg['images'] = b64_images
            messages.append(msg)
    return messages

def get_history_payload() -> List[Dict]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «get_history_payload» με συνεπή τρόπο."""
    with SESSION.lock:
        return copy.deepcopy(SESSION.history)

def sanitize_filename(filename: str) -> str:
    """Κανονικοποιεί ή καθαρίζει δεδομένα στο βήμα «sanitize_filename» ώστε οι επόμενες φάσεις να λαμβάνουν ασφαλή και συνεπή είσοδο.

Βασικά ορίσματα: filename."""
    basename = Path(filename).name
    cleaned = re.sub('[^\\w.\\-()\\[\\] ]+', '_', basename, flags=re.UNICODE).strip()
    cleaned = cleaned.lstrip('.')
    return cleaned or 'file'

def extract_original_generated_filename(stored_name: str) -> str:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_original_generated_filename» με συνεπή τρόπο.

Βασικά ορίσματα: stored_name."""
    basename = Path(str(stored_name or '')).name
    match = re.match('^\\d{10,}_[0-9a-fA-F]{8}_(.+)$', basename)
    candidate = match.group(1) if match else basename
    safe_name = sanitize_filename(candidate)
    if safe_name and safe_name != 'file':
        return safe_name
    return 'generated_code.py'

def ensure_upload_dir() -> None:
    """Υλοποιεί το βήμα «ensure_upload_dir» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

def ensure_generated_code_dir() -> None:
    """Υλοποιεί το βήμα «ensure_generated_code_dir» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
    GENERATED_CODE_DIR.mkdir(parents=True, exist_ok=True)

def suggest_python_filename(code_text: str) -> str:
    """Υλοποιεί το βήμα «suggest_python_filename» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: code_text."""
    cleaned = (code_text or '').strip()
    if not cleaned:
        return 'generated_code.py'
    patterns = ['^\\s*class\\s+([A-Za-z_][A-Za-z0-9_]*)', '^\\s*def\\s+([A-Za-z_][A-Za-z0-9_]*)', '^\\s*async\\s+def\\s+([A-Za-z_][A-Za-z0-9_]*)']
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.MULTILINE)
        if match:
            return sanitize_filename(match.group(1) + '.py')
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            candidate = stripped.lstrip('#').strip()[:60]
            candidate = re.sub('\\s+', '_', candidate)
            candidate = sanitize_filename(candidate)
            if candidate and candidate != 'file':
                if not candidate.lower().endswith('.py'):
                    candidate += '.py'
                return candidate
            break
    return 'generated_code.py'

def save_generated_python_file(code_text: str, suggested_filename: str='') -> Dict[str, str]:
    """Υλοποιεί τη λειτουργική ρουτίνα «save_generated_python_file» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: code_text, suggested_filename."""
    cleaned = (code_text or '').replace('\r\n', '\n').replace('\r', '\n').strip() + '\n'
    if not cleaned.strip():
        raise ValueError('Δεν υπάρχει Python code για αποθήκευση.')
    ensure_generated_code_dir()
    requested_name = suggested_filename.strip() if suggested_filename else suggest_python_filename(cleaned)
    safe_name = sanitize_filename(requested_name)
    if not safe_name.lower().endswith('.py'):
        safe_name += '.py'
    unique_name = f'{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}_{safe_name}'
    out_path = (GENERATED_CODE_DIR / unique_name).resolve()
    generated_root = str(GENERATED_CODE_DIR.resolve()) + os.sep
    if not str(out_path).startswith(generated_root):
        raise ValueError('Μη ασφαλές όνομα αρχείου για generated Python attachment.')
    out_path.write_text(cleaned, encoding='utf-8')
    with SESSION.lock:
        SESSION.upload_paths.add(str(out_path))
    return {'name': safe_name, 'stored_name': unique_name, 'url': f'/generated-code/{urllib.parse.quote(unique_name)}', 'kind': 'file'}

def model_supports_images(model_name: str) -> bool:
    """Υλοποιεί το βήμα «model_supports_images» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: model_name."""
    name = (model_name or '').lower()
    hints = ('vl', 'vision', 'gemini', 'gemma3', 'llava', 'minicpm-v', 'qwen2.5vl', 'qwen3-vl')
    return any((h in name for h in hints))

def save_uploaded_file(filename: str, data_base64: str) -> Path:
    """Υλοποιεί τη λειτουργική ρουτίνα «save_uploaded_file» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: filename, data_base64."""
    ensure_upload_dir()
    try:
        raw = base64.b64decode(data_base64, validate=True)
    except Exception as exc:
        raise ValueError(f'Μη έγκυρα base64 δεδομένα για το αρχείο: {filename}') from exc
    if len(raw) > MAX_UPLOAD_BYTES_PER_FILE:
        raise ValueError(f"Το αρχείο '{filename}' είναι πολύ μεγάλο. Μέγιστο: {MAX_UPLOAD_BYTES_PER_FILE // (1024 * 1024)} MB.")
    safe_name = sanitize_filename(filename)
    unique_name = f'{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}_{safe_name}'
    out_path = (UPLOADS_DIR / unique_name).resolve()
    uploads_resolved = str(UPLOADS_DIR.resolve()) + os.sep
    if not str(out_path).startswith(uploads_resolved):
        raise ValueError(f'Μη ασφαλές όνομα αρχείου: {filename}')
    out_path.write_bytes(raw)
    with SESSION.lock:
        SESSION.upload_paths.add(str(out_path))
    return out_path

def truncate_text(text: str, limit: int=MAX_TEXT_CHARS_PER_FILE) -> Tuple[str, bool]:
    """Κανονικοποιεί ή καθαρίζει δεδομένα στο βήμα «truncate_text» ώστε οι επόμενες φάσεις να λαμβάνουν ασφαλή και συνεπή είσοδο.

Βασικά ορίσματα: text, limit."""
    cleaned = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if len(cleaned) <= limit:
        return (cleaned, False)
    return (cleaned[:limit].rstrip() + '\n\n...[TRUNCATED]...', True)

def extract_pdf_text(path: Path) -> Tuple[str, bool, str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_pdf_text» με συνεπή τρόπο.

Βασικά ορίσματα: path."""
    try:
        from pypdf import PdfReader
    except Exception:
        return ('', False, "Δεν βρέθηκε το optional package 'pypdf'. Εγκατάσταση: pip install pypdf")
    try:
        reader = PdfReader(str(path))
        parts: List[str] = []
        total_len = 0
        for page in reader.pages:
            extracted = page.extract_text() or ''
            if extracted:
                parts.append(extracted)
                total_len += len(extracted)
            if total_len >= MAX_TEXT_CHARS_PER_FILE:
                break
        joined = '\n\n'.join(parts).strip()
        if not joined:
            return ('', False, 'Δεν βρέθηκε εξαγώγιμο κείμενο στο PDF.')
        truncated_text, was_truncated = truncate_text(joined, MAX_TEXT_CHARS_PER_FILE)
        return (truncated_text, was_truncated, '')
    except Exception as exc:
        return ('', False, f'Αποτυχία ανάγνωσης PDF: {exc}')

def extract_text_for_context(path: Path) -> Tuple[str, bool, str]:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «extract_text_for_context» με συνεπή τρόπο.

Βασικά ορίσματα: path."""
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        for enc in ('utf-8', 'utf-8-sig', 'cp1253', 'cp1252', 'latin-1'):
            try:
                content = path.read_text(encoding=enc)
                truncated_text, was_truncated = truncate_text(content, MAX_TEXT_CHARS_PER_FILE)
                return (truncated_text, was_truncated, '')
            except Exception:
                continue
        return ('', False, 'Το αρχείο δεν μπόρεσε να διαβαστεί ως κείμενο.')
    if suffix == '.pdf':
        return extract_pdf_text(path)
    return ('', False, 'Ο τύπος αρχείου δεν υποστηρίζεται για εξαγωγή κειμένου.')

def prepare_attachments(attachments: List[Dict], model_name: str) -> Tuple[List[Dict], List[str]]:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «prepare_attachments».

Βασικά ορίσματα: attachments, model_name."""
    processed: List[Dict] = []
    warnings: List[str] = []
    if not attachments:
        return (processed, warnings)
    if len(attachments) > MAX_UPLOAD_FILES_PER_MESSAGE:
        raise ValueError(f'Μπορείς να στείλεις έως {MAX_UPLOAD_FILES_PER_MESSAGE} αρχεία ανά μήνυμα.')
    image_capable = model_supports_images(model_name)
    total_text_chars = 0
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError('Ένα από τα συνημμένα δεν είναι σε έγκυρη μορφή.')
        filename = str(item.get('name', 'file')).strip() or 'file'
        data_base64 = str(item.get('data_base64', '')).strip()
        mime_type = str(item.get('mime_type', '')).strip()
        if not data_base64:
            raise ValueError(f"Το αρχείο '{filename}' δεν περιέχει δεδομένα.")
        saved_path = save_uploaded_file(filename, data_base64)
        ext = saved_path.suffix.lower()
        entry: Dict = {'name': filename, 'path': str(saved_path), 'mime_type': mime_type, 'kind': 'other', 'text_excerpt': '', 'text_truncated': False, 'will_send_as_image': False, 'status_message': ''}
        if ext in IMAGE_EXTENSIONS:
            entry['kind'] = 'image'
            if image_capable:
                entry['will_send_as_image'] = True
            else:
                entry['status_message'] = 'Το αρχείο είναι εικόνα, αλλά το τρέχον μοντέλο δεν φαίνεται vision-capable.'
                warnings.append(f"Η εικόνα '{filename}' φορτώθηκε, αλλά για native image ανάλυση προτίμησε vision model όπως qwen3-vl.")
        else:
            entry['kind'] = 'document'
            text_excerpt, was_truncated, status_message = extract_text_for_context(saved_path)
            entry['text_excerpt'] = text_excerpt
            entry['text_truncated'] = was_truncated
            entry['status_message'] = status_message
            if text_excerpt:
                remaining = max(MAX_TOTAL_TEXT_CHARS_PER_MESSAGE - total_text_chars, 0)
                if remaining <= 0:
                    entry['text_excerpt'] = ''
                    entry['status_message'] = 'Το αρχείο φορτώθηκε, αλλά δεν μπήκε στο prompt λόγω ορίου context.'
                elif len(text_excerpt) > remaining:
                    trimmed, _ = truncate_text(text_excerpt, remaining)
                    entry['text_excerpt'] = trimmed
                    entry['text_truncated'] = True
                    total_text_chars += len(trimmed)
                else:
                    total_text_chars += len(text_excerpt)
        processed.append(entry)
    return (processed, warnings)

def build_user_message_content(user_text: str, processed_attachments: List[Dict]) -> str:
    """Συνθέτει το αντικείμενο ή το payload που απαιτεί το βήμα «build_user_message_content».

Βασικά ορίσματα: user_text, processed_attachments."""
    parts: List[str] = [user_text.strip()]
    attachment_lines: List[str] = []
    context_blocks: List[str] = []
    for item in processed_attachments:
        if item['kind'] == 'image':
            if item['will_send_as_image']:
                attachment_lines.append(f"- Εικόνα: {item['name']} (θα σταλεί natively στο model)")
            else:
                note = item['status_message'] or 'Εικόνα χωρίς native vision υποστήριξη.'
                attachment_lines.append(f"- Εικόνα: {item['name']} ({note})")
        else:
            status_note = 'έτοιμο για context' if item['text_excerpt'] else item['status_message'] or 'χωρίς κείμενο'
            attachment_lines.append(f"- Αρχείο: {item['name']} ({status_note})")
            if item['text_excerpt']:
                context_blocks.append(f"### Αρχείο: {item['name']}\n{item['text_excerpt']}")
    if attachment_lines:
        parts.append('[Συνημμένα αρχεία]\n' + '\n'.join(attachment_lines))
    if context_blocks:
        parts.append('[Περιεχόμενο συνημμένων για χρήση ως context]\n\n' + '\n\n'.join(context_blocks))
    return '\n\n'.join((p for p in parts if p.strip()))

def serve_startup_html() -> str:
    """Εξυπηρετεί το HTTP ή streaming κομμάτι που αντιστοιχεί στο βήμα «serve_startup_html»."""
    return f"""<!DOCTYPE html>\n<html lang="el">\n<head>\n  <meta charset="utf-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1" />\n  <title>Εκκίνηση — {html.escape(APP_TITLE)}</title>\n  <style>\n    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}\n\n    body {{\n      min-height: 100vh;\n      background:\n        radial-gradient(circle at top left,  rgba(96,165,250,0.15), transparent 34%),\n        radial-gradient(circle at top right, rgba(94,234,212,0.12), transparent 26%),\n        linear-gradient(135deg, #0b1020, #101a35);\n      color: #e5eefc;\n      font-family: Consolas, "Cascadia Code", "Fira Code", monospace;\n      display: flex; align-items: center; justify-content: center;\n      flex-direction: column;\n      padding: 24px;\n    }}\n\n    .wrap {{ width: 680px; max-width: 100%; }}\n\n    .copyright {{\n      margin-top: 18px;\n      text-align: center;\n      color: #9fb0d1;\n      font-size: 0.92rem;\n      font-family: "Segoe UI", Inter, Arial, sans-serif;\n      letter-spacing: 0.5px;\n      padding-top: 16px;\n      border-top: 1px solid rgba(94,234,212,0.30);\n    }}\n\n    /* ── Header ── */\n    .header {{\n      text-align: center; margin-bottom: 28px;\n      animation: fade-down 0.5s ease-out;\n    }}\n    .logo   {{ font-size: 3.2rem; line-height: 1; margin-bottom: 10px; }}\n    .title  {{\n      font-size: 1.45rem; font-weight: 700; letter-spacing: 0.4px;\n      background: linear-gradient(135deg, #5eead4, #60a5fa);\n      -webkit-background-clip: text; -webkit-text-fill-color: transparent;\n    }}\n    .subtitle {{ color: #9fb0d1; font-size: 0.88rem; margin-top: 6px; }}\n\n    @keyframes fade-down {{\n      from {{ opacity: 0; transform: translateY(-14px); }}\n      to   {{ opacity: 1; transform: translateY(0); }}\n    }}\n\n    /* ── Terminal card ── */\n    .terminal {{\n      background: rgba(15,23,42,0.82);\n      border: 1px solid rgba(94,234,212,0.18);\n      border-radius: 20px;\n      backdrop-filter: blur(18px);\n      box-shadow: 0 24px 64px rgba(0,0,0,0.45);\n      overflow: hidden;\n      animation: fade-up 0.5s ease-out 0.1s both;\n    }}\n    @keyframes fade-up {{\n      from {{ opacity: 0; transform: translateY(14px); }}\n      to   {{ opacity: 1; transform: translateY(0); }}\n    }}\n\n    /* macOS-style titlebar */\n    .titlebar {{\n      display: flex; align-items: center; gap: 8px;\n      padding: 12px 18px;\n      background: rgba(15,23,42,0.98);\n      border-bottom: 1px solid rgba(94,234,212,0.10);\n    }}\n    .dot {{ width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }}\n    .dot-r {{ background: #ff5f57; }}\n    .dot-y {{ background: #febc2e; }}\n    .dot-g {{ background: #28c840; }}\n    .bar-title {{\n      flex: 1; text-align: center;\n      color: #586e75; font-size: 0.8rem; letter-spacing: 0.3px;\n    }}\n\n    /* Log area */\n    .log-area {{\n      padding: 20px 22px;\n      min-height: 230px;\n      max-height: 380px;\n      overflow-y: auto;\n      scrollbar-width: thin;\n      scrollbar-color: rgba(94,234,212,0.2) transparent;\n    }}\n    .log-area::-webkit-scrollbar       {{ width: 5px; }}\n    .log-area::-webkit-scrollbar-thumb {{ background: rgba(94,234,212,0.22); border-radius: 99px; }}\n\n    .log-line {{\n      display: flex; gap: 14px;\n      padding: 2px 0; font-size: 0.875rem; line-height: 1.55;\n      animation: slide-in 0.22s ease-out;\n    }}\n    @keyframes slide-in {{\n      from {{ opacity: 0; transform: translateX(-10px); }}\n      to   {{ opacity: 1; transform: translateX(0); }}\n    }}\n\n    .log-t     {{ color: #586e75; flex-shrink: 0; width: 64px; }}\n    .log-lvl   {{ flex-shrink: 0; width: 56px; font-weight: 700; }}\n    .log-msg   {{ flex: 1; word-break: break-word; }}\n\n    .lvl-INFO    .log-lvl {{ color: #60a5fa; }}\n    .lvl-WARNING .log-lvl {{ color: #f59e0b; }}\n    .lvl-ERROR   .log-lvl {{ color: #f87171; }}\n    .lvl-READY   .log-lvl,\n    .lvl-READY   .log-msg {{ color: #34d399; }}\n    .lvl-READY   .log-msg {{ font-weight: 600; }}\n\n    /* Footer strip */\n    .footer {{\n      padding: 14px 22px;\n      border-top: 1px solid rgba(94,234,212,0.08);\n      background: rgba(15,23,42,0.55);\n    }}\n\n    /* Spinner */\n    .spinner {{\n      display: flex; align-items: center; gap: 10px;\n      color: #9fb0d1; font-size: 0.84rem;\n    }}\n    .dots {{ display: flex; gap: 5px; }}\n    .dots span {{\n      width: 7px; height: 7px; border-radius: 50%;\n      background: #5eead4; opacity: 0.25;\n      animation: dot-pulse 1.2s ease-in-out infinite;\n    }}\n    .dots span:nth-child(2) {{ animation-delay: 0.2s; }}\n    .dots span:nth-child(3) {{ animation-delay: 0.4s; }}\n    @keyframes dot-pulse {{\n      0%,80%,100% {{ opacity: 0.25; transform: scale(0.9); }}\n      40%          {{ opacity: 1;   transform: scale(1.1); }}\n    }}\n\n    /* Ready bar */\n    .ready-bar {{\n      display: none;\n      padding: 12px 16px;\n      background: rgba(52,211,153,0.12);\n      border: 1px solid rgba(52,211,153,0.28);\n      border-radius: 12px;\n      color: #34d399; font-size: 0.88rem; font-weight: 600;\n      text-align: center;\n    }}\n    .ready-bar a {{\n      color: #5eead4; cursor: pointer; text-decoration: underline;\n    }}\n    .progress-bar {{\n      height: 3px; background: rgba(52,211,153,0.15); border-radius: 99px;\n      margin-top: 10px; overflow: hidden;\n    }}\n    .progress-fill {{\n      height: 100%; width: 0;\n      background: linear-gradient(90deg, #5eead4, #60a5fa);\n      border-radius: 99px;\n      transition: width 1.6s linear;\n    }}\n  </style>\n</head>\n<body>\n  <div class="wrap">\n    <div class="header">\n      <div class="logo">☁️</div>\n      <div class="title">{html.escape(APP_TITLE)}</div>\n      <div class="subtitle">Εκκίνηση — παρακαλώ περίμενε…</div>\n    </div>\n\n    <div class="terminal">\n      <div class="titlebar">\n        <div class="dot dot-r"></div>\n        <div class="dot dot-y"></div>\n        <div class="dot dot-g"></div>\n        <div class="bar-title">startup log</div>\n      </div>\n\n      <div class="log-area" id="logArea"></div>\n\n      <div class="footer">\n        <div class="spinner" id="spinner">\n          <div class="dots"><span></span><span></span><span></span></div>\n          <span id="spinMsg">Αρχικοποίηση…</span>\n        </div>\n        <div class="ready-bar" id="readyBar">\n          ✅ Έτοιμο! Μεταβαίνεις αυτόματα…\n          &nbsp;<a onclick="goNow()">Πήγαινε τώρα</a>\n          <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>\n        </div>\n      </div>\n    </div><!-- /.terminal -->\n\n    <div class="copyright">&copy; Ευάγγελος Πεφάνης</div>\n\n  </div><!-- /.wrap -->\n\n  <script>\n    var chatUrl  = null;\n    var logArea  = document.getElementById("logArea");\n    var spinner  = document.getElementById("spinner");\n    var spinMsg  = document.getElementById("spinMsg");\n    var readyBar = document.getElementById("readyBar");\n    var fillEl   = document.getElementById("progressFill");\n\n    var LEVEL_LABEL = {{\n      INFO: "INFO", WARNING: "WARN", ERROR: "ERR ", READY: "READY"\n    }};\n\n    function esc(s) {{\n      return String(s||"")\n        .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");\n    }}\n\n    function addLine(ev) {{\n      var d = document.createElement("div");\n      d.className = "log-line lvl-" + ev.level;\n      d.innerHTML =\n        '<span class="log-t">'   + esc(ev.t)   + '</span>' +\n        '<span class="log-lvl">' + (LEVEL_LABEL[ev.level] || ev.level) + '</span>' +\n        '<span class="log-msg">' + esc(ev.msg)  + '</span>';\n      logArea.appendChild(d);\n      d.scrollIntoView({{ behavior: "smooth", block: "nearest" }});\n    }}\n\n    function goNow() {{\n      if (chatUrl) window.location.replace(chatUrl);\n    }}\n\n    var es = new EventSource("/startup-events");\n\n    es.onmessage = function(e) {{\n      var ev;\n      try {{ ev = JSON.parse(e.data); }} catch(_) {{ return; }}\n      addLine(ev);\n\n      if (ev.level !== "READY") {{\n        spinMsg.textContent = ev.msg.replace(/^[\\p{{Emoji}}\\s]+/u, "");\n      }}\n\n      if (ev.level === "READY") {{\n        chatUrl = ev.msg;\n        es.close();\n        spinner.style.display  = "none";\n        readyBar.style.display = "block";\n        // Animate progress bar → 100% then redirect\n        requestAnimationFrame(function() {{\n          fillEl.style.width = "100%";\n        }});\n        setTimeout(goNow, 1800);\n      }}\n    }};\n\n    es.onerror = function() {{\n      es.close();\n      spinMsg.textContent = "Αποτυχία SSE — ανανέωσε τη σελίδα.";\n      spinner.style.color = "#f59e0b";\n    }};\n  </script>\n</body>\n</html>"""

def serve_index_html() -> str:
    """Εξυπηρετεί το HTTP ή streaming κομμάτι που αντιστοιχεί στο βήμα «serve_index_html»."""
    system_prompt, _ = get_embedded_system_prompt()
    safe_prompt_json = json.dumps(system_prompt, ensure_ascii=False).replace('</', '<\\/')
    accepted_types = ACCEPTED_FILE_TYPES
    html_doc = '<!DOCTYPE html>\n<html lang="el" data-theme="dark">\n<head>\n  <meta charset="utf-8" />\n  <meta name="viewport" content="width=device-width, initial-scale=1" />\n  <title>__APP_TITLE__</title>\n\n  <!-- Prism.js — δύο themes: dark (prism-tomorrow) και light (prism-solarizedlight). -->\n  <!-- Ενεργό theme εναλλάσσεται από JS στο applyTheme().                           -->\n  <link id="prismDark"  rel="stylesheet"\n        href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css" />\n  <link id="prismLight" rel="stylesheet" disabled\n        href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-solarizedlight.min.css" />\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-python.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-javascript.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-typescript.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-bash.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-json.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-sql.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-css.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-markup.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-go.min.js" defer></script>\n  <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/components/prism-rust.min.js" defer></script>\n  <!-- Inline: ενεργοποίηση σωστού Prism theme ΠΡΙΝ το πρώτο paint (αποφυγή flash) -->\n  <script>\n    (function () {\n      var theme = "dark";\n      try { theme = localStorage.getItem("ollama_chat_theme_v2") || "dark"; } catch (_) {}\n      if (theme === "light") {\n        var d = document.getElementById("prismDark");\n        var l = document.getElementById("prismLight");\n        if (d) d.disabled = true;\n        if (l) l.disabled = false;\n      }\n    })();\n  </script>\n\n  <style>\n    /* ── Variables (dark default) ── */\n    :root {\n      --bg1:       #0b1020;\n      --bg2:       #101a35;\n      --panel:     rgba(15, 23, 42, 0.78);\n      --line:      rgba(148, 163, 184, 0.18);\n      --text:      #e5eefc;\n      --muted:     #9fb0d1;\n      --accent:    #5eead4;\n      --accent-2:  #60a5fa;\n      --shadow:    0 20px 60px rgba(0,0,0,0.35);\n      --radius:    22px;\n      --radius-sm: 16px;\n      --mono:      Consolas, "Cascadia Code", "Fira Code", monospace;\n      --sans:      "Segoe UI", Inter, Arial, sans-serif;\n    }\n\n    /* ── Reset ── */\n    *, *::before, *::after { box-sizing: border-box; }\n    html { color-scheme: dark; }\n    html, body {\n      margin: 0; min-height: 100%;\n      font-family: var(--sans); color: var(--text);\n      background:\n        radial-gradient(circle at top left,  rgba(96,165,250,0.15), transparent 34%),\n        radial-gradient(circle at top right, rgba(94,234,212,0.12), transparent 26%),\n        linear-gradient(135deg, var(--bg1), var(--bg2));\n      background-attachment: fixed;\n    }\n    body { padding: 22px; }\n    ::selection { background: rgba(96,165,250,0.28); color: inherit; }\n\n    /* ── Layout ── */\n    .app {\n      max-width: 1850px; margin: 0 auto;\n      display: grid; grid-template-columns: 450px 1fr; gap: 22px;\n    }\n    .card {\n      background: var(--panel); backdrop-filter: blur(18px);\n      border: 1px solid var(--line); border-radius: var(--radius);\n      box-shadow: var(--shadow);\n    }\n\n    /* ── Sidebar ── */\n    .sidebar {\n      padding: 18px;\n      display: flex; flex-direction: column; gap: 16px;\n      height: calc(100vh - 44px);\n      position: sticky; top: 22px;\n      overflow-y: auto;       /* scroll για μικρές οθόνες */\n      scrollbar-width: thin;\n    }\n    .title { display: flex; align-items: center; justify-content: space-between; gap: 12px; }\n    .title h1 { margin: 0; font-size: 1.22rem; line-height: 1.2; letter-spacing: 0.2px; }\n\n    .pill {\n      border-radius: 999px; padding: 7px 12px; font-size: 0.8rem; color: #dffcf6;\n      background: linear-gradient(135deg, rgba(94,234,212,0.22), rgba(96,165,250,0.18));\n      border: 1px solid rgba(94,234,212,0.2); white-space: nowrap;\n    }\n\n    .group {\n      padding: 14px; border-radius: var(--radius-sm);\n      background: rgba(15,23,42,0.52); border: 1px solid var(--line);\n      flex-shrink: 0;\n    }\n\n    .label { display: block; margin-bottom: 8px; color: var(--muted); font-size: 0.92rem; font-weight: 600; }\n\n    select, textarea, input[type="text"], input[type="file"] {\n      width: 100%; border: 1px solid rgba(148,163,184,0.22);\n      background: rgba(2,6,23,0.55); color: var(--text);\n      border-radius: 14px; padding: 12px 14px; outline: none;\n      font-family: var(--sans);\n      transition: border-color 0.16s ease, box-shadow 0.16s ease;\n    }\n    textarea { resize: vertical; min-height: 90px; line-height: 1.45; }\n    select:focus, textarea:focus, input:focus {\n      border-color: rgba(96,165,250,0.55);\n      box-shadow: 0 0 0 4px rgba(96,165,250,0.14);\n    }\n    input[type="file"] { padding: 10px; }\n\n    .btn-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }\n\n    button {\n      border: 0; border-radius: 14px; padding: 12px 14px;\n      cursor: pointer; font-weight: 700; font-size: 0.93rem;\n      transition: transform 0.15s ease, filter 0.15s ease, opacity 0.15s ease;\n    }\n    button:hover:not(:disabled) { transform: translateY(-1px); filter: brightness(1.06); }\n    button:disabled  { opacity: 0.52; cursor: not-allowed; transform: none; }\n    .btn-full { width: 100%; }\n    .primary  { color: #08111d; background: linear-gradient(135deg, var(--accent), var(--accent-2)); }\n    .secondary {\n      color: var(--text); background: rgba(51,65,85,0.85);\n      border: 1px solid rgba(148,163,184,0.18);\n    }\n\n    #confirmThinkingProfileBtn {\n      font-size: 0.82rem;\n      font-weight: 400;\n      padding: 9px 12px;\n      letter-spacing: 0;\n    }\n\n    /* ── Chat panel ── */\n    .chat-panel { height: calc(100vh - 44px); display: flex; flex-direction: column; overflow: hidden; }\n\n    .chat-header {\n      padding: 16px 26px; border-bottom: 1px solid var(--line);\n      display: flex; flex-wrap: wrap; align-items: center;\n      justify-content: space-between; gap: 10px;\n      background: rgba(15,23,42,0.45); flex-shrink: 0;\n    }\n    .chat-header h2 { margin: 0; font-size: 1.08rem; }\n    .header-left    { display: flex; flex-direction: column; gap: 3px; }\n    .status-wrap    { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }\n\n    .badge {\n      border-radius: 999px; padding: 7px 12px; font-size: 0.82rem;\n      background: rgba(51,65,85,0.8); border: 1px solid rgba(148,163,184,0.15);\n      color: var(--muted);\n    }\n    .badge.ok   { color: #d1fae5; background: rgba(34,197,94,0.14);  border-color: rgba(34,197,94,0.24); }\n    .badge.warn { color: #fef3c7; background: rgba(245,158,11,0.12); border-color: rgba(245,158,11,0.22); }\n    .badge.err  { color: #fecaca; background: rgba(239,68,68,0.14);  border-color: rgba(239,68,68,0.24); }\n\n    /* ── Messages ── */\n    .messages-wrap { flex: 1; position: relative; overflow: hidden; }\n    .messages {\n      height: 100%; overflow-y: auto; padding: 22px;\n      display: flex; flex-direction: column; gap: 14px;\n      scroll-behavior: smooth;\n    }\n\n    /* ── Realtime reasoning panel ── */\n    .reasoning-panel {\n      display: none;\n      margin: 14px 22px 0;\n      padding: 14px 16px;\n      border-radius: 18px;\n      border: 1px solid rgba(94,234,212,0.18);\n      background: linear-gradient(180deg, rgba(14,26,50,0.72), rgba(12,22,40,0.62));\n      box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);\n      flex-shrink: 0;\n    }\n    .reasoning-panel.visible { display: block; }\n    .reasoning-panel.streaming {\n      border-color: rgba(94,234,212,0.30);\n      box-shadow: 0 0 0 1px rgba(94,234,212,0.08), 0 10px 30px rgba(0,0,0,0.14);\n    }\n    .reasoning-head {\n      display: flex; align-items: flex-start; justify-content: space-between;\n      gap: 12px; margin-bottom: 10px;\n    }\n    .reasoning-title-wrap { min-width: 0; }\n    .reasoning-title {\n      display: flex; align-items: center; gap: 10px;\n      font-size: 0.95rem; font-weight: 800; letter-spacing: 0.2px;\n    }\n    .reasoning-meta {\n      margin-top: 4px; color: var(--muted); font-size: 0.82rem;\n    }\n    .reasoning-toggle-btn {\n      padding: 8px 12px; font-size: 0.8rem; white-space: nowrap;\n    }\n    .reasoning-body {\n      margin: 0;\n      max-height: 220px;\n      overflow-y: auto;\n      white-space: pre-wrap;\n      word-break: break-word;\n      font-family: var(--mono);\n      font-size: 0.87rem;\n      line-height: 1.56;\n      color: #c9d9f3;\n      background: rgba(2,6,23,0.34);\n      border: 1px solid rgba(148,163,184,0.10);\n      border-radius: 14px;\n      padding: 12px 14px;\n      scrollbar-width: thin;\n      scrollbar-color: rgba(94,234,212,0.22) transparent;\n    }\n    .reasoning-body::-webkit-scrollbar { width: 6px; }\n    .reasoning-body::-webkit-scrollbar-thumb {\n      background: rgba(94,234,212,0.24); border-radius: 99px;\n    }\n\n    .empty-state {\n      margin: auto; max-width: 820px; text-align: center;\n      border: 1px dashed rgba(148,163,184,0.22); border-radius: 22px;\n      padding: 34px 26px; color: var(--muted); background: rgba(15,23,42,0.28);\n    }\n\n    /* Scroll-to-bottom floating button */\n    .scroll-to-bottom {\n      position: absolute; bottom: 14px; right: 20px;\n      background: var(--accent); color: #08111d;\n      border: none; border-radius: 999px;\n      padding: 10px 16px; font-weight: 800; font-size: 0.88rem;\n      cursor: pointer; box-shadow: 0 6px 20px rgba(0,0,0,0.3);\n      opacity: 0; pointer-events: none;\n      transition: opacity 0.2s ease, transform 0.2s ease;\n      z-index: 10;\n    }\n    .scroll-to-bottom.visible { opacity: 1; pointer-events: auto; }\n    .scroll-to-bottom:hover   { transform: translateY(-2px); filter: brightness(1.08); }\n\n    /* ── Messages ── */\n    .msg {\n      max-width: min(1020px, 95%); border-radius: 22px; padding: 14px 16px;\n      border: 1px solid var(--line); box-shadow: 0 10px 30px rgba(0,0,0,0.18);\n    }\n    .msg.user      { align-self: flex-end;   background: linear-gradient(135deg, rgba(96,165,250,0.24), rgba(37,99,235,0.14)); }\n    .msg.assistant { align-self: flex-start; background: rgba(15,23,42,0.75); max-width: 100%; width: 100%; }\n    .msg.system    { align-self: center; background: rgba(51,65,85,0.6); color: var(--muted); max-width: 90%; }\n\n    .msg-head {\n      display: flex; align-items: center; justify-content: space-between;\n      gap: 12px; margin-bottom: 10px; font-size: 0.84rem; color: var(--muted);\n    }\n    .msg-role { font-weight: 800; letter-spacing: 0.2px; }\n    .msg-time { opacity: 0.8; white-space: nowrap; font-size: 0.8rem; }\n    .msg-body { line-height: 1.62; font-size: 0.98rem; overflow-x: auto; }\n\n    /* ── Markdown styles ── */\n    .msg-body .md-h1,.msg-body .md-h2,.msg-body .md-h3,\n    .msg-body .md-h4,.msg-body .md-h5,.msg-body .md-h6 {\n      margin: 14px 0 6px; font-weight: 700; line-height: 1.3; color: var(--accent);\n    }\n    .msg-body .md-h1 { font-size: 1.35em; }\n    .msg-body .md-h2 { font-size: 1.2em;  }\n    .msg-body .md-h3 { font-size: 1.08em; }\n    .msg-body .md-h4,.msg-body .md-h5,.msg-body .md-h6 { font-size: 1em; }\n    .msg-body .md-p  { margin: 5px 0; }\n    .msg-body .md-br { display: block; height: 5px; }\n    .msg-body .md-hr { border: none; border-top: 1px solid var(--line); margin: 12px 0; }\n    .msg-body .md-list { margin: 5px 0 5px 22px; padding: 0; }\n    .msg-body .md-list li { margin: 3px 0; }\n    .msg-body .md-bq {\n      margin: 8px 0; padding: 10px 14px;\n      border-left: 3px solid var(--accent);\n      background: rgba(94,234,212,0.06);\n      border-radius: 0 10px 10px 0; color: var(--muted);\n    }\n    .msg-body .md-bq p { margin: 0; }\n    .msg-body .md-link { color: var(--accent-2); text-decoration: underline; }\n    .msg-body .md-link:hover { opacity: 0.8; }\n    .msg-body strong { color: #e2e8f0; font-weight: 700; }\n    .msg-body em     { font-style: italic; color: #cbd5e1; }\n    .msg-body del    { text-decoration: line-through; opacity: 0.7; }\n\n    /* ── Code blocks ── */\n    .code-block {\n      border: 1px solid rgba(148,163,184,0.18); border-radius: 16px;\n      overflow: hidden; background: rgba(2,6,23,0.92);\n      box-shadow: inset 0 1px 0 rgba(148,163,184,0.06); margin: 8px 0;\n    }\n    .code-toolbar {\n      display: flex; align-items: center; justify-content: space-between;\n      gap: 10px; padding: 9px 12px;\n      background: rgba(15,23,42,0.98);\n      border-bottom: 1px solid rgba(148,163,184,0.14);\n    }\n    .code-language {\n      color: #cbd5e1; font-size: 0.78rem; font-weight: 700;\n      letter-spacing: 0.3px; text-transform: uppercase;\n    }\n    .code-copy-btn {\n      border: 1px solid rgba(148,163,184,0.18); background: rgba(30,41,59,0.9);\n      color: var(--text); border-radius: 10px; padding: 6px 10px;\n      font-size: 0.79rem; font-weight: 700; cursor: pointer;\n    }\n    .code-copy-btn:hover         { filter: brightness(1.1); }\n    .code-copy-btn.done  { color: #d1fae5; border-color: rgba(34,197,94,0.24);  background: rgba(34,197,94,0.14); }\n    .code-copy-btn.error { color: #fecaca; border-color: rgba(239,68,68,0.24);  background: rgba(239,68,68,0.14); }\n\n    .code-pre {\n      margin: 0 !important; padding: 16px 18px !important;\n      overflow-x: auto; font-family: var(--mono) !important;\n      font-size: 0.93rem !important; line-height: 1.65 !important;\n      tab-size: 4; white-space: pre; text-align: left;\n      background: transparent !important;\n      scrollbar-width: thin;\n      scrollbar-color: rgba(148,163,184,0.22) transparent;\n    }\n    .code-pre::-webkit-scrollbar       { height: 6px; }\n    .code-pre::-webkit-scrollbar-track { background: transparent; }\n    .code-pre::-webkit-scrollbar-thumb { background: rgba(148,163,184,0.28); border-radius: 99px; }\n    .code-pre code[class*="language-"] {\n      font-family: var(--mono) !important;\n      font-size: inherit !important;\n      background: none !important;  /* prevent Prism dark background from leaking */\n    }\n\n    .code-inline {\n      display: inline-block; padding: 2px 6px; border-radius: 8px;\n      background: rgba(30,41,59,0.92); border: 1px solid rgba(148,163,184,0.14);\n      font-family: var(--mono); font-size: 0.91em; word-break: break-word;\n    }\n\n    /* ── Attachments ── */\n    .attachment-list { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }\n    .attachment-chip {\n      display: inline-flex; align-items: center; gap: 8px;\n      padding: 6px 10px; border-radius: 999px;\n      background: rgba(30,41,59,0.85); border: 1px solid rgba(148,163,184,0.18);\n      font-size: 0.81rem; color: var(--text);\n      text-decoration: none;\n    }\n    .attachment-chip.link { cursor: pointer; }\n    .attachment-chip.link:hover { filter: brightness(1.08); }\n\n    /* ── Thinking block (DeepSeek-R1, Qwen3, GLM-Z1 κ.ά.) ── */\n    .thinking-block {\n      margin: 8px 0 12px;\n      border: 1px solid rgba(94,234,212,0.22);\n      border-radius: 14px;\n      overflow: hidden;\n      background: rgba(14,26,50,0.55);\n    }\n    .thinking-summary {\n      display: flex; align-items: center; gap: 8px;\n      padding: 9px 14px; cursor: pointer;\n      user-select: none; list-style: none;\n      color: var(--muted); font-size: 0.83rem; font-weight: 600;\n      background: rgba(94,234,212,0.06);\n      border-bottom: 1px solid transparent;\n      transition: background 0.15s;\n    }\n    .thinking-summary:hover { background: rgba(94,234,212,0.10); }\n    details[open] .thinking-summary {\n      border-bottom-color: rgba(94,234,212,0.15);\n    }\n    .thinking-icon { font-size: 0.95rem; }\n    .thinking-label { flex: 1; }\n    .thinking-chevron {\n      font-size: 0.78rem; opacity: 0.6;\n      transition: transform 0.2s;\n    }\n    details[open] .thinking-chevron { transform: rotate(90deg); }\n    .thinking-body {\n      padding: 12px 16px;\n      font-size: 0.88rem; line-height: 1.58;\n      color: #8da4c8;\n      font-style: italic;\n      white-space: pre-wrap;\n      word-break: break-word;\n      max-height: 340px;\n      overflow-y: auto;\n      scrollbar-width: thin;\n      scrollbar-color: rgba(94,234,212,0.18) transparent;\n    }\n    .thinking-body::-webkit-scrollbar       { width: 4px; }\n    .thinking-body::-webkit-scrollbar-thumb { background: rgba(94,234,212,0.22); border-radius: 99px; }\n\n    /* Light theme thinking */\n    html[data-theme="light"] .thinking-block {\n      border-color: rgba(37,99,235,0.18);\n      background: rgba(239,246,255,0.60);\n    }\n    html[data-theme="light"] .thinking-summary {\n      background: rgba(37,99,235,0.06); color: #4a6080;\n    }\n    html[data-theme="light"] .thinking-summary:hover { background: rgba(37,99,235,0.10); }\n    html[data-theme="light"] details[open] .thinking-summary {\n      border-bottom-color: rgba(37,99,235,0.12);\n    }\n    html[data-theme="light"] .thinking-body { color: #5b7299; }\n    .streaming-dots { display: inline-flex; gap: 5px; align-items: center; padding: 6px 0; }\n    .streaming-dots span {\n      width: 8px; height: 8px; border-radius: 50%;\n      background: var(--accent); opacity: 0.25;\n      animation: dot-pulse 1.2s ease-in-out infinite;\n    }\n    .streaming-dots span:nth-child(2) { animation-delay: 0.2s; }\n    .streaming-dots span:nth-child(3) { animation-delay: 0.4s; }\n    @keyframes dot-pulse {\n      0%, 80%, 100% { opacity: 0.25; transform: scale(0.9); }\n      40%            { opacity: 1;    transform: scale(1.1); }\n    }\n\n    /* ── Composer ── */\n    .composer {\n      border-top: 1px solid var(--line); padding: 16px 22px;\n      background: rgba(15,23,42,0.4); flex-shrink: 0;\n    }\n    .composer textarea {\n      min-height: 120px; height: 120px; max-height: 220px;\n      font-size: 0.97rem; line-height: 1.5;\n      font-family: var(--mono);\n    }\n    .composer-footer {\n      margin-top: 10px; display: flex; flex-wrap: wrap; gap: 10px;\n      align-items: center; justify-content: space-between;\n    }\n    .composer-left  { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }\n    .composer-right { display: flex; gap: 10px; align-items: center; }\n    .char-counter   { font-size: 0.81rem; color: var(--muted); }\n    .char-counter.warn { color: #f59e0b; font-weight: 600; }\n    .helper { color: var(--muted); font-size: 0.85rem; }\n\n    /* ── Drag overlay ── */\n    .drop-overlay {\n      display: none; position: fixed; inset: 0;\n      background: rgba(94,234,212,0.10); border: 3px dashed var(--accent);\n      z-index: 9999; align-items: center; justify-content: center;\n      font-size: 1.5rem; color: var(--accent); pointer-events: none;\n      backdrop-filter: blur(2px);\n    }\n    .drop-overlay.active { display: flex; }\n\n    /* ── Message tools ── */\n    .message-tools { margin-top: 10px; display: flex; justify-content: flex-end; gap: 8px; }\n    .tool-btn {\n      padding: 7px 10px; border-radius: 10px;\n      background: rgba(30,41,59,0.85); color: var(--text);\n      font-size: 0.81rem; border: 1px solid rgba(148,163,184,0.16);\n    }\n\n    /* ── Model parameters panel ── */\n    .param-row {\n      display: flex; align-items: center; justify-content: space-between;\n      gap: 10px; margin-bottom: 10px;\n    }\n    .param-row:last-child { margin-bottom: 0; }\n    .param-label {\n      font-size: 0.82rem; color: var(--muted); font-weight: 600;\n      white-space: nowrap; min-width: 80px;\n    }\n    .param-value {\n      font-size: 0.82rem; color: var(--accent); font-weight: 700;\n      min-width: 36px; text-align: right; font-family: var(--mono);\n    }\n    input[type="range"] {\n      flex: 1; height: 4px; border-radius: 4px; outline: none;\n      background: rgba(148,163,184,0.25); padding: 0; border: none;\n      cursor: pointer; accent-color: var(--accent);\n    }\n    input[type="range"]:focus { box-shadow: 0 0 0 3px rgba(94,234,212,0.18); }\n    .param-seed-wrap {\n      display: flex; gap: 8px; align-items: center;\n    }\n    .param-seed-wrap input[type="text"] {\n      flex: 1; padding: 8px 10px; font-family: var(--mono);\n      font-size: 0.82rem; border-radius: 10px;\n    }\n\n    /* ── Misc ── */\n    .support-list { margin: 8px 0 0 18px; padding: 0; color: var(--muted); font-size: 0.81rem; line-height: 1.5; }\n    .footer-note  { margin-top: auto; color: var(--muted); font-size: 0.84rem; line-height: 1.45; flex-shrink: 0; }\n    .footer-note code {\n      font-family: var(--mono); background: rgba(2,6,23,0.55);\n      padding: 2px 7px; border-radius: 8px; font-size: 0.9em;\n    }\n    .muted { color: var(--muted); }\n    .tiny  { font-size: 0.81rem; }\n\n    /* ── Light theme ── */\n    html[data-theme="light"] {\n      color-scheme: light;\n      --bg1:      #f5f8fd; --bg2:      #e7eef9;\n      --panel:    rgba(255,255,255,0.94);\n      --line:     rgba(37,53,84,0.10);\n      --text:     #162338; --muted:    #5c6d86;\n      --accent:   #2563eb; --accent-2: #06b6d4;\n      --shadow:   0 22px 48px rgba(31,41,55,0.10);\n    }\n    html[data-theme="light"] body {\n      background:\n        radial-gradient(circle at top left,  rgba(37,99,235,0.12), transparent 36%),\n        radial-gradient(circle at top right, rgba(6,182,212,0.10), transparent 28%),\n        linear-gradient(135deg, var(--bg1), var(--bg2));\n    }\n    html[data-theme="light"] .card {\n      background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(255,255,255,0.86));\n      border-color: rgba(37,53,84,0.09);\n    }\n    html[data-theme="light"] .group {\n      background: linear-gradient(180deg, rgba(248,251,255,0.96), rgba(242,247,253,0.90));\n      border-color: rgba(37,53,84,0.08);\n    }\n    html[data-theme="light"] .pill { color: #0f3b57; }\n    html[data-theme="light"] select,\n    html[data-theme="light"] textarea,\n    html[data-theme="light"] input {\n      background: rgba(255,255,255,0.98); border-color: rgba(37,53,84,0.10); color: #162338;\n    }\n    html[data-theme="light"] .primary  { color: #fff; background: linear-gradient(135deg, #2563eb, #0ea5e9); }\n    html[data-theme="light"] .secondary,\n    html[data-theme="light"] .tool-btn,\n    html[data-theme="light"] .attachment-chip {\n      background: rgba(248,250,252,0.98); border-color: rgba(37,53,84,0.10); color: #1c2b40;\n    }\n    html[data-theme="light"] .chat-header,\n    html[data-theme="light"] .composer {\n      background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(247,250,254,0.92));\n    }\n    html[data-theme="light"] .reasoning-panel {\n      background: linear-gradient(180deg, rgba(239,246,255,0.98), rgba(232,242,255,0.92));\n      border-color: rgba(37,99,235,0.14);\n    }\n    html[data-theme="light"] .reasoning-panel.streaming {\n      border-color: rgba(37,99,235,0.24);\n      box-shadow: 0 0 0 1px rgba(37,99,235,0.05), 0 12px 28px rgba(37,99,235,0.06);\n    }\n    html[data-theme="light"] .reasoning-body {\n      background: rgba(255,255,255,0.88);\n      border-color: rgba(37,53,84,0.08);\n      color: #365173;\n    }\n    html[data-theme="light"] .msg.user      { background: linear-gradient(135deg, rgba(37,99,235,0.12), rgba(6,182,212,0.10)); }\n    html[data-theme="light"] .msg.assistant { background: linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,253,0.94)); }\n    html[data-theme="light"] .msg.system    { background: rgba(242,246,252,0.98); color: #5b6c83; }\n    html[data-theme="light"] .badge         { background: rgba(243,247,252,0.98); border-color: rgba(37,53,84,0.10); color: #5c6d86; }\n    html[data-theme="light"] .badge.ok      { color: #166534; background: rgba(34,197,94,0.12);  border-color: rgba(34,197,94,0.20); }\n    html[data-theme="light"] .badge.warn    { color: #92400e; background: rgba(245,158,11,0.12); border-color: rgba(245,158,11,0.20); }\n    /* ═══════════════════════════════════════════════════════════════════════\n       Light theme — code blocks: λευκό φόντο, πλήρης vivid token palette\n       Base: Prism Solarized Light  +  custom overrides για μέγιστο χρώμα\n       ═══════════════════════════════════════════════════════════════════════ */\n\n    html[data-theme="light"] .code-block {\n      background:   #eef6ff;               /* ανοιχτό γαλάζιο */\n      border-color: rgba(37,99,235,0.14);\n      box-shadow:   0 2px 12px rgba(37,99,235,0.07);\n    }\n    html[data-theme="light"] .code-toolbar {\n      background:          #dbeafe;        /* blue-100 */\n      border-bottom-color: rgba(37,99,235,0.12);\n    }\n    html[data-theme="light"] .code-language {\n      color: #1e40af; letter-spacing: 0.3px;\n    }\n    html[data-theme="light"] .code-copy-btn {\n      background:   #eff6ff;\n      border-color: rgba(37,99,235,0.18);\n      color:        #1e3a5f;\n      box-shadow:   0 1px 3px rgba(37,99,235,0.06);\n    }\n    html[data-theme="light"] .code-copy-btn:hover {\n      background: #dbeafe; filter: none;\n    }\n    html[data-theme="light"] .code-copy-btn.done  {\n      color: #166534; background: rgba(34,197,94,0.13); border-color: rgba(34,197,94,0.25);\n    }\n    html[data-theme="light"] .code-copy-btn.error {\n      color: #991b1b; background: rgba(239,68,68,0.10); border-color: rgba(239,68,68,0.25);\n    }\n\n    /* Βασικό χρώμα κειμένου */\n    html[data-theme="light"] .code-pre,\n    html[data-theme="light"] .code-pre code[class*="language-"] {\n      color:      #1e293b;\n      background: transparent !important;\n    }\n\n    html[data-theme="light"] .code-pre::-webkit-scrollbar-thumb {\n      background: rgba(37,99,235,0.20);\n    }\n\n    /* ── Vivid token colours (Atom One Light inspired, more saturated) ── */\n\n    /* Comments — readable gray, italic */\n    html[data-theme="light"] .token.comment,\n    html[data-theme="light"] .token.prolog,\n    html[data-theme="light"] .token.doctype,\n    html[data-theme="light"] .token.cdata {\n      color: #93a1a1; font-style: italic;  /* Solarized base1 */\n    }\n\n    /* Keywords — vivid purple: def, class, import, if, for, return… */\n    html[data-theme="light"] .token.keyword,\n    html[data-theme="light"] .token.atrule,\n    html[data-theme="light"] .token.rule {\n      color: #7c3aed; font-weight: 600;   /* violet-600 */\n    }\n\n    /* Strings, chars, template literals — vivid green */\n    html[data-theme="light"] .token.string,\n    html[data-theme="light"] .token.char,\n    html[data-theme="light"] .token.inserted,\n    html[data-theme="light"] .token.attr-value {\n      color: #16a34a;                      /* green-600 */\n    }\n\n    /* Numbers, booleans — amber/orange */\n    html[data-theme="light"] .token.number,\n    html[data-theme="light"] .token.boolean {\n      color: #c2410c;                      /* orange-700 */\n    }\n\n    /* Functions, method names — vivid blue */\n    html[data-theme="light"] .token.function,\n    html[data-theme="light"] .token.function-variable {\n      color: #1d4ed8;                      /* blue-700 */\n    }\n\n    /* Class names, types — pink/magenta */\n    html[data-theme="light"] .token.class-name,\n    html[data-theme="light"] .token.maybe-class-name,\n    html[data-theme="light"] .token.builtin {\n      color: #be185d;                      /* pink-700 */\n    }\n\n    /* Variables, parameters — teal */\n    html[data-theme="light"] .token.variable,\n    html[data-theme="light"] .token.parameter {\n      color: #0f766e;                      /* teal-700 */\n    }\n\n    /* Properties — cyan/teal */\n    html[data-theme="light"] .token.property {\n      color: #0369a1;                      /* sky-700 */\n    }\n\n    /* Operators — dark teal */\n    html[data-theme="light"] .token.operator,\n    html[data-theme="light"] .token.entity,\n    html[data-theme="light"] .token.url {\n      color: #0891b2;                      /* cyan-600 */\n    }\n\n    /* HTML/XML tags — red */\n    html[data-theme="light"] .token.tag,\n    html[data-theme="light"] .token.deleted {\n      color: #dc2626;                      /* red-600 */\n    }\n\n    /* HTML attribute names — purple */\n    html[data-theme="light"] .token.attr-name {\n      color: #9333ea;                      /* purple-600 */\n    }\n\n    /* Punctuation — dark neutral */\n    html[data-theme="light"] .token.punctuation {\n      color: #374151;                      /* gray-700 */\n    }\n\n    /* Regex — deep pink */\n    html[data-theme="light"] .token.regex {\n      color: #be185d;\n    }\n\n    /* Decorators / annotations — indigo */\n    html[data-theme="light"] .token.decorator,\n    html[data-theme="light"] .token.annotation {\n      color: #4338ca; font-style: italic; /* indigo-700 */\n    }\n\n    /* Constants — amber */\n    html[data-theme="light"] .token.constant,\n    html[data-theme="light"] .token.symbol {\n      color: #b45309;                      /* amber-700 */\n    }\n\n    html[data-theme="light"] .token.important,\n    html[data-theme="light"] .token.bold   { font-weight: bold; }\n    html[data-theme="light"] .token.italic { font-style: italic; }\n    html[data-theme="light"] .token.namespace { opacity: 0.75; }\n\n    /* JSON keys (property inside object) */\n    html[data-theme="light"] .language-json .token.property {\n      color: #1d4ed8;\n    }\n\n    /* SQL keywords */\n    html[data-theme="light"] .language-sql .token.keyword {\n      color: #7c3aed; font-weight: 700;\n    }\n\n    /* Bash builtins & variables */\n    html[data-theme="light"] .language-bash .token.function { color: #1d4ed8; }\n    html[data-theme="light"] .language-bash .token.variable { color: #0f766e; }\n\n    /* ── Inline code & footer code ── */\n    html[data-theme="light"] .code-inline {\n      background:   #eef1f7;\n      border-color: rgba(37,53,84,0.13);\n      color:        #c7254e;\n    }\n    html[data-theme="light"] .footer-note code {\n      background: rgba(229,237,248,0.88); color: #0550ae;\n    }\n    html[data-theme="light"] .msg-body .md-h1,\n    html[data-theme="light"] .msg-body .md-h2,\n    html[data-theme="light"] .msg-body .md-h3 { color: #1d4ed8; }\n    html[data-theme="light"] .msg-body .md-bq { border-left-color: #2563eb; background: rgba(37,99,235,0.06); }\n    html[data-theme="light"] .msg-body strong { color: #162338; }\n    html[data-theme="light"] .msg-body em     { color: #334155; }\n    html[data-theme="light"] .param-label  { color: var(--muted); }\n    html[data-theme="light"] .param-value  { color: var(--accent); }\n    html[data-theme="light"] input[type="range"] {\n      background: rgba(37,53,84,0.15);\n    }\n    html[data-theme="light"] .scroll-to-bottom { box-shadow: 0 6px 20px rgba(37,53,84,0.2); }\n\n    /* ── Responsive ── */\n    @media (max-width: 1100px) {\n      .app { grid-template-columns: 1fr; }\n      .sidebar { height: unset; position: static; max-height: none; overflow-y: visible; }\n      .chat-panel { height: 75vh; }\n      .msg { max-width: 100%; }\n    }\n    @media (max-width: 600px) {\n      body { padding: 10px; }\n      .app { gap: 12px; }\n      .chat-panel { height: 65vh; }\n      .composer textarea { min-height: 100px; height: 100px; }\n    }\n  </style>\n</head>\n<body>\n\n  <div class="drop-overlay" id="dropOverlay">📂 Άσε τα αρχεία εδώ</div>\n\n  <div class="app">\n\n    <!-- ── Sidebar ────────────────────────────────────────────────── -->\n    <aside class="sidebar card">\n      <div class="title">\n        <h1>☁️ __APP_TITLE__</h1>\n        <div class="pill">v3.0</div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="modelSelect">Μοντέλο Ollama</label>\n        <input id="modelSearchInput" type="search" placeholder="Αναζήτηση μοντέλου..."\n               title="Γράψε για φιλτράρισμα της λίστας μοντέλων" style="margin-bottom:8px;" />\n        <select id="modelSelect" title="Επίλεξε cloud model"></select>\n        <div class="tiny muted" style="margin-top:8px;">\n          Η λίστα ανακτά τα ακριβή model names του official Ollama direct API catalog από το διαδίκτυο.\n          Η αναζήτηση φιλτράρει τη λίστα χωρίς να επηρεάζει τη φόρτωση των μοντέλων.\n        </div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="modelSortSelect">Ταξινόμηση μοντέλων</label>\n        <select id="modelSortSelect" title="Επίλεξε κριτήριο αξιολόγησης για ταξινόμηση μοντέλων">\n          <option value="overall">Overall / Καλύτερο συνολικά</option>\n          <option value="coding">Coding / Προγραμματισμός</option>\n          <option value="reasoning">Reasoning / Σκέψη</option>\n          <option value="context">Long Context / Max Length</option>\n          <option value="vision">Vision / Εικόνες</option>\n          <option value="speed">Speed / Ταχύτητα</option>\n          <option value="newest">Newest / Πιο νέο</option>\n        </select>\n        <div class="tiny muted" style="margin-top:8px;">\n          Η κατάταξη γίνεται ευρετικά από metadata του direct catalog και model details, όπως context length,\n          capabilities, μέγεθος μοντέλου και πρόσφατη ενημέρωση.\n        </div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="thinkModeSelect">Thinking Mode</label>\n        <select id="thinkModeSelect" title="Ρύθμιση thinking/reasoning mode του μοντέλου">\n          <option value="auto">Auto</option>\n          <option value="on" selected>On</option>\n          <option value="off">Off</option>\n          <option value="low">Low</option>\n          <option value="medium">Medium</option>\n          <option value="high">High</option>\n        </select>\n        <div class="tiny muted" id="thinkingSupportInfo" style="margin-top:8px;">\n          Η λίστα επιλογών προσαρμόζεται αυτόματα ανάλογα με το επιλεγμένο μοντέλο και το thinking mode που υποστηρίζει.\n        </div>\n        <div class="btn-row" style="margin-top:8px;">\n          <button class="secondary btn-full" id="confirmThinkingProfileBtn" title="Επιβεβαίωση του τρέχοντος thinking support profile για το επιλεγμένο μοντέλο">✅ Επιβεβαίωση Profile</button>\n        </div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="ensembleModeSelect">Dual Model Ensemble</label>\n        <select id="ensembleModeSelect" title="Επίλεξε λειτουργία dual model ensemble">\n          <option value="off">Off</option>\n          <option value="auto" selected>Auto</option>\n          <option value="manual">Manual</option>\n        </select>\n        <input id="helperSearchInput" type="search" placeholder="Αναζήτηση helper model..."\n               title="Γράψε για φιλτράρισμα της λίστας helper models" style="margin-top:8px; margin-bottom:8px;" />\n        <select id="helperModelSelect" title="Επίλεξε βοηθητικό μοντέλο" disabled></select>\n        <div class="tiny muted" id="ensembleModeInfo" style="margin-top:8px;">\n          Off: μόνο το κύριο μοντέλο. Auto: αυτόματη επιλογή helper model. Manual: διαλέγεις εσύ το δεύτερο μοντέλο από τη λίστα.\n        </div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="apiKeyInput">Ollama API Key</label>\n        <input id="apiKeyInput" type="password" placeholder="ollama_..." autocomplete="off"\n               title="API key για direct Ollama Cloud API" />\n        <div class="btn-row" style="margin-top:10px;">\n          <button class="primary" id="saveApiKeyBtn" title="Αποθήκευση API key σε αρχείο ρυθμίσεων">💾 Save Key</button>\n          <button class="secondary" id="clearApiKeyBtn" title="Καθαρισμός αποθηκευμένου API key">🗑 Clear Key</button>\n        </div>\n        <div class="tiny muted" id="apiKeyInfo" style="margin-top:8px;">\n          Το API key αποθηκεύεται σε τοπικό αρχείο ρυθμίσεων δίπλα στο .py.\n        </div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="systemPrompt">System Prompt</label>\n        <textarea id="systemPrompt" title="System prompt της συνεδρίας">__SYSTEM_PROMPT__</textarea>\n        <div class="tiny muted" style="margin-top:6px;">\n          Αλλάζει μόνο για τη συνεδρία. Χρησιμοποιείται το embedded default αν είναι κενό.\n        </div>\n      </div>\n\n      <div class="group">\n        <label class="label" for="fileInput">Αρχεία (ή drag & drop)</label>\n        <input id="fileInput" type="file" multiple accept="__ACCEPTED_TYPES__"\n               title="Επίλεξε αρχεία για context" />\n        <div class="attachment-list" id="selectedFiles"></div>\n        <div class="btn-row" style="margin-top:10px;">\n          <button class="secondary" id="clearFilesBtn"    title="Αφαίρεση επιλεγμένων αρχείων">📎 Καθαρισμός</button>\n          <button class="primary"   id="refreshModelsBtn" title="Ανάκτηση τελευταίας λίστας cloud models">🔄 Refresh Models</button>\n        </div>\n        <ul class="support-list">\n          <li>Drag &amp; Drop υποστηρίζεται παντού.</li>\n          <li>Εικόνες → natively σε vision models.</li>\n          <li>TXT, PY, MD, JSON, CSV, PDF κ.ά. → context.</li>\n        </ul>\n      </div>\n\n      <div class="group">\n        <div class="label">⚙️ Παράμετροι μοντέλου</div>\n\n        <div class="param-row">\n          <span class="param-label" title="Δημιουργικότητα απάντησης (0=ντετερμινιστικό, 2=πολύ τυχαίο)">Temperature</span>\n          <input type="range" id="paramTemp" min="0" max="2" step="0.05" value="0.8"\n                 title="Temperature: 0 – 2" />\n          <span class="param-value" id="paramTempVal">0.80</span>\n        </div>\n\n        <div class="param-row">\n          <span class="param-label" title="Nucleus sampling: διατηρεί tokens που καλύπτουν το X% της πιθανότητας">Top-P</span>\n          <input type="range" id="paramTopP" min="0.01" max="1" step="0.01" value="0.9"\n                 title="Top-P: 0.01 – 1.00" />\n          <span class="param-value" id="paramTopPVal">0.90</span>\n        </div>\n\n        <div class="param-row" style="align-items:flex-start; flex-direction:column; gap:6px;">\n          <span class="param-label" title="Seed για αναπαραγώγιμα αποτελέσματα (-1 = τυχαίο)">Seed</span>\n          <div class="param-seed-wrap" style="width:100%;">\n            <input type="text" id="paramSeed" value="-1" placeholder="-1 (τυχαίο)"\n                   title="Seed: αριθμός ≥ 0 για αναπαραγώγιμο, -1 για τυχαίο" />\n            <button class="secondary" id="resetParamsBtn" style="padding:8px 10px; font-size:0.8rem; white-space:nowrap;"\n                    title="Επαναφορά προεπιλεγμένων παραμέτρων">↺ Reset</button>\n          </div>\n        </div>\n\n        <div class="param-row" style="align-items:flex-start; flex-direction:column; gap:6px;">\n          <span class="param-label" title="Μέγιστο context / max length (num_ctx) για το επιλεγμένο μοντέλο">Max Length (num_ctx)</span>\n          <div class="param-seed-wrap" style="width:100%;">\n            <input type="number" id="paramNumCtx" min="256" step="256" value="" placeholder="κενό = auto / default"\n                   title="Context window / max length για το επιλεγμένο μοντέλο" />\n            <button class="secondary" id="clearNumCtxBtn" style="padding:8px 10px; font-size:0.8rem; white-space:nowrap;"\n                    title="Καθαρισμός custom max length για το τρέχον μοντέλο">Auto</button>\n          </div>\n          <div class="tiny muted" id="paramNumCtxInfo">Ισχύει ξεχωριστά για κάθε μοντέλο.</div>\n        </div>\n      </div>\n\n      <div class="group">\n        <div class="label">Κατάσταση</div>\n        <div id="modelInfo" class="muted tiny">Φόρτωση λίστας μοντέλων...</div>\n      </div>\n\n      <div class="btn-row">\n        <button class="secondary" id="resetSystemPromptBtn" title="Επαναφορά default system prompt">🧠 Reset Prompt</button>\n        <button class="secondary" id="clearChatBtn"         title="Καθαρισμός chat και uploads">🧹 Clear Chat</button>\n      </div>\n      <div class="btn-row">\n        <button class="secondary" id="reloadSessionBtn"    title="Επαναφόρτωση ιστορικού από server">♻️ Reload Session</button>\n        <button class="secondary" id="copySystemPromptBtn" title="Αντιγραφή system prompt στο clipboard">📋 Copy Prompt</button>\n      </div>\n      <div class="btn-row">\n        <button class="secondary" id="exportChatBtn"  title="Εξαγωγή συνομιλίας ως Markdown αρχείο">💾 Export .md</button>\n        <button class="secondary" id="autoScrollBtn"  title="Ενεργοποίηση/απενεργοποίηση αυτόματης κύλισης">📜 Auto-Scroll: ON</button>\n      </div>\n\n      <button class="secondary btn-full" id="themeToggleBtn" title="Εναλλαγή dark/light theme">☀️ Light Theme</button>\n\n      <div class="footer-note">\n        Direct Cloud API: βάλε το API key στο πεδίο του GUI και πάτησε <b>Save Key</b> ή όρισε <code>OLLAMA_API_KEY</code><br><br>\n        Settings file: <code>ollama_cloud_chat_settings.json</code> δίπλα στο .py<br><br>\n        Εκτέλεση: <code>python ollama_cloud_chat.py [--port N] [--no-browser]</code><br><br>\n        <span style="display:block; margin-top:10px; padding-top:10px; border-top:1px solid var(--line); opacity:0.85; font-size:0.9rem; text-align:center; letter-spacing:0.3px;">&copy; Ευάγγελος Πεφάνης</span>\n      </div>\n    </aside>\n\n    <!-- ── Chat panel ─────────────────────────────────────────────── -->\n    <main class="chat-panel card">\n      <div class="chat-header">\n        <div class="header-left">\n          <h2>Συνομιλία</h2>\n          <div class="tiny muted">Enter αποστολή · Shift+Enter νέα γραμμή · Ctrl+Enter εναλλακτικό</div>\n        </div>\n        <div class="status-wrap">\n          <span class="badge" id="backendBadge"       title="Κατάσταση direct Ollama Cloud API">⬤ Cloud API</span>\n          <span class="badge" id="msgCountBadge">0 μηνύματα</span>\n          <span class="badge" id="selectedModelBadge">Μοντέλο: -</span>\n          <span class="badge" id="sourceBadge">Πηγή: -</span>\n          <span class="badge" id="tokensPerSecBadge"  title="Ταχύτητα τελευταίας απάντησης" style="display:none;"></span>\n          <span class="badge" id="streamBadge">Έτοιμο</span>\n        </div>\n      </div>\n\n      <div class="reasoning-panel" id="reasoningPanel" aria-live="polite">\n        <div class="reasoning-head">\n          <div class="reasoning-title-wrap">\n            <div class="reasoning-title">🧠 <span>Realtime βαθιά σκέψη</span></div>\n            <div class="reasoning-meta" id="reasoningMeta">Αναμονή για thinking stream…</div>\n          </div>\n          <button class="secondary reasoning-toggle-btn" id="toggleReasoningBtn" title="Εμφάνιση ή απόκρυψη του panel σκέψης">🙈 Απόκρυψη</button>\n        </div>\n        <pre class="reasoning-body" id="reasoningContent"></pre>\n      </div>\n\n      <div class="messages-wrap">\n        <div class="messages" id="messages">\n          <div class="empty-state" id="emptyState">\n            <h3 style="margin-top:0;">Έτοιμο για συνομιλία</h3>\n            <div>Γράψε το δικό σου prompt και, αν θέλεις, πρόσθεσε αρχεία για context.</div>\n            <div style="margin-top:10px;" class="tiny">\n              Enter αποστολή · Shift+Enter νέα γραμμή · Ctrl+Enter εναλλακτικό\n            </div>\n          </div>\n        </div>\n        <button class="scroll-to-bottom" id="scrollToBottomBtn" title="Μετάβαση στο τέλος">↓ Τέλος</button>\n      </div>\n\n      <div class="composer">\n        <textarea id="userInput" placeholder="Γράψε εδώ το user prompt σου…"\n                  title="User prompt — Enter αποστολή, Shift+Enter νέα γραμμή, Ctrl+Enter εναλλακτικό"></textarea>\n        <div class="composer-footer">\n          <div class="composer-left">\n            <span class="char-counter" id="charCounter">0 χαρ. / 0 λέξεις</span>\n            <span class="helper" id="helperText">Enter · Shift+Enter · Ctrl+Enter</span>\n          </div>\n          <div class="composer-right">\n            <button class="secondary" id="stopBtn" disabled title="Διακοπή streaming">⏹ Stop</button>\n            <button class="primary"   id="sendBtn"          title="Αποστολή μηνύματος (Enter)">🚀 Αποστολή</button>\n          </div>\n        </div>\n      </div>\n    </main>\n\n  </div><!-- /.app -->\n\n  <script>\n    "use strict";\n\n    // ── Constants ────────────────────────────────────────────────────────────\n    const DEFAULT_SYSTEM_PROMPT  = __DEFAULT_SYSTEM_PROMPT_JSON__;\n    const THEME_KEY              = "ollama_chat_theme_v2";\n    const MODEL_KEY              = "ollama_chat_model_v2";\n    const PARAMS_KEY             = "ollama_chat_params_v2";\n    const THINK_MODE_KEY         = "ollama_chat_think_mode_v1";\n    const THINK_PROFILE_CONFIRMATIONS_KEY = "ollama_chat_think_profile_confirmations_v1";\n    const MODEL_SORT_KEY         = "ollama_chat_model_sort_v1";\n    const ENSEMBLE_KEY           = "ollama_chat_ensemble_auto_v1";\n    const ENSEMBLE_MODE_KEY      = "ollama_chat_ensemble_mode_v2";\n    const ENSEMBLE_HELPER_KEY    = "ollama_chat_ensemble_helper_v1";\n    const CHAR_WARN              = 8000;\n    const DEFAULT_HELPER         = "Enter · Shift+Enter · Ctrl+Enter";\n    const HEALTH_POLL_MS         = 15_000;  // polling interval για cloud API status\n    const MODEL_REFRESH_POLL_MS  = 400;\n    const BROWSER_SESSION_KEY    = "ollama_chat_browser_session_v1";\n    const BROWSER_HEARTBEAT_MS   = 10_000;\n\n    // ── App state ────────────────────────────────────────────────────────────\n    const state = {\n      isStreaming:            false,\n      abortController:        null,\n      currentAssistantNode:   null,\n      currentThinkingText:    "",\n      reasoningPanelVisible:  false,\n      reasoningAutoOpen:      false,\n      reasoningUserCollapsed: false,\n      currentInlineThinkingOpen: true,\n      reasoningStreamCompleted: false,\n      models:                 [],\n      selectedFiles:          [],\n      theme:                  "dark",\n      autoScroll:             true,\n      chatHistory:            [],  // [{role, content, time}] — for export\n      msgCount:               0,\n      dragCounter:            0,   // reliable drag-leave detection\n      lastTokensPerSec:       null,\n      modelNumCtxByModel:     {},\n      modelMaxNumCtxByModel:  {},\n      modelMetaByModel:       {},\n      modelDetailRequests:    {},\n      currentThinkingProfile: null,\n      confirmedThinkingProfilesByModel: {},\n      helperModels:           [],\n      ensembleMode:           "auto",\n      modelSortCriterion:     "overall",\n      lastModelsRefreshTs:    0,\n      browserSessionId:       "",\n      browserHeartbeatTimer:   null,\n    };\n\n    // ── DOM refs ─────────────────────────────────────────────────────────────\n    const els = {\n      modelSearchInput:     document.getElementById("modelSearchInput"),\n      modelSelect:          document.getElementById("modelSelect"),\n      modelSortSelect:      document.getElementById("modelSortSelect"),\n      thinkModeSelect:      document.getElementById("thinkModeSelect"),\n      thinkingSupportInfo:  document.getElementById("thinkingSupportInfo"),\n      confirmThinkingProfileBtn: document.getElementById("confirmThinkingProfileBtn"),\n      ensembleModeSelect:   document.getElementById("ensembleModeSelect"),\n      helperSearchInput:    document.getElementById("helperSearchInput"),\n      helperModelSelect:    document.getElementById("helperModelSelect"),\n      ensembleModeInfo:     document.getElementById("ensembleModeInfo"),\n      systemPrompt:         document.getElementById("systemPrompt"),\n      fileInput:            document.getElementById("fileInput"),\n      selectedFiles:        document.getElementById("selectedFiles"),\n      refreshModelsBtn:     document.getElementById("refreshModelsBtn"),\n      clearFilesBtn:        document.getElementById("clearFilesBtn"),\n      resetSystemPromptBtn: document.getElementById("resetSystemPromptBtn"),\n      copySystemPromptBtn:  document.getElementById("copySystemPromptBtn"),\n      exportChatBtn:        document.getElementById("exportChatBtn"),\n      autoScrollBtn:        document.getElementById("autoScrollBtn"),\n      themeToggleBtn:       document.getElementById("themeToggleBtn"),\n      clearChatBtn:         document.getElementById("clearChatBtn"),\n      reloadSessionBtn:     document.getElementById("reloadSessionBtn"),\n      modelInfo:            document.getElementById("modelInfo"),\n      msgCountBadge:        document.getElementById("msgCountBadge"),\n      selectedModelBadge:   document.getElementById("selectedModelBadge"),\n      sourceBadge:          document.getElementById("sourceBadge"),\n      streamBadge:          document.getElementById("streamBadge"),\n      backendBadge:         document.getElementById("backendBadge"),\n      tokensPerSecBadge:    document.getElementById("tokensPerSecBadge"),\n      reasoningPanel:       document.getElementById("reasoningPanel"),\n      reasoningMeta:        document.getElementById("reasoningMeta"),\n      reasoningContent:     document.getElementById("reasoningContent"),\n      toggleReasoningBtn:   document.getElementById("toggleReasoningBtn"),\n      messages:             document.getElementById("messages"),\n      userInput:            document.getElementById("userInput"),\n      sendBtn:              document.getElementById("sendBtn"),\n      stopBtn:              document.getElementById("stopBtn"),\n      helperText:           document.getElementById("helperText"),\n      charCounter:          document.getElementById("charCounter"),\n      dropOverlay:          document.getElementById("dropOverlay"),\n      scrollToBottomBtn:    document.getElementById("scrollToBottomBtn"),\n      // Model parameters\n      paramTemp:            document.getElementById("paramTemp"),\n      paramTempVal:         document.getElementById("paramTempVal"),\n      paramTopP:            document.getElementById("paramTopP"),\n      paramTopPVal:         document.getElementById("paramTopPVal"),\n      paramSeed:            document.getElementById("paramSeed"),\n      paramNumCtx:          document.getElementById("paramNumCtx"),\n      paramNumCtxInfo:      document.getElementById("paramNumCtxInfo"),\n      clearNumCtxBtn:       document.getElementById("clearNumCtxBtn"),\n      resetParamsBtn:       document.getElementById("resetParamsBtn"),\n      apiKeyInput:          document.getElementById("apiKeyInput"),\n      apiKeyInfo:           document.getElementById("apiKeyInfo"),\n      saveApiKeyBtn:        document.getElementById("saveApiKeyBtn"),\n      clearApiKeyBtn:       document.getElementById("clearApiKeyBtn"),\n    };\n\n    // ── Utilities ────────────────────────────────────────────────────────────\n\n    function nowString() {\n      return new Date().toLocaleTimeString("el-GR", {\n        hour: "2-digit", minute: "2-digit", second: "2-digit"\n      });\n    }\n\n    function escapeHtml(text) {\n      return String(text || "")\n        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")\n        .replace(/"/g, "&quot;").replace(/\'/g, "&#39;");\n    }\n\n    function setButtonFeedback(btn, successText, defaultText, cls = "done") {\n      btn.textContent = successText;\n      btn.classList.remove("done", "error");\n      btn.classList.add(cls);\n      setTimeout(() => { btn.textContent = defaultText; btn.classList.remove("done", "error"); }, 1500);\n    }\n\n    function countWords(text) {\n      return text.trim() ? text.trim().split(/\\s+/).length : 0;\n    }\n\n    // ── Model parameters ─────────────────────────────────────────────────────\n\n    const DEFAULT_PARAMS = { temperature: 0.8, top_p: 0.9, seed: -1 };\n\n    function normalizeNumCtxValue(rawValue) {\n      const text = String(rawValue ?? "").trim();\n      if (!text) return null;\n      const value = parseInt(text, 10);\n      if (!Number.isFinite(value)) return null;\n      if (value < 256 || value > 1048576) return null;\n      return value;\n    }\n\n    function getSelectedModelKey() {\n      return String(els.modelSelect.value || "").trim();\n    }\n\n    function syncNumCtxInputForSelectedModel() {\n      const model = getSelectedModelKey();\n      const saved = model ? state.modelNumCtxByModel[model] : null;\n      const maxFromServer = model ? state.modelMaxNumCtxByModel[model] : null;\n      const effective = saved != null ? saved : maxFromServer;\n      if (els.paramNumCtx) {\n        els.paramNumCtx.value = effective != null ? String(effective) : "";\n        if (maxFromServer != null) {\n          els.paramNumCtx.placeholder = String(maxFromServer);\n        } else {\n          els.paramNumCtx.placeholder = "ανάκτηση Max Length...";\n        }\n      }\n      if (els.paramNumCtxInfo) {\n        const label = model || "-";\n        let shown = "Ανάκτηση metadata...";\n        let modeLabel = "φόρτωση";\n        if (saved != null) {\n          shown = `${saved.toLocaleString("el-GR")} tokens`;\n          modeLabel = "προσαρμοσμένο";\n        } else if (maxFromServer != null) {\n          shown = `${maxFromServer.toLocaleString("el-GR")} tokens`;\n          modeLabel = "πραγματικό μέγιστο μοντέλου";\n        }\n        els.paramNumCtxInfo.textContent = `Μοντέλο: ${label} · Max Length: ${shown} · ${modeLabel}`;\n      }\n      if (model && maxFromServer == null) {\n        ensureSelectedModelMeta(model);\n      }\n    }\n\n    function getModelOptions() {\n      const temperature = parseFloat(els.paramTemp.value);\n      const top_p       = parseFloat(els.paramTopP.value);\n      const seedRaw     = els.paramSeed.value.trim();\n      const seed        = parseInt(seedRaw, 10);\n      const numCtx      = normalizeNumCtxValue(els.paramNumCtx ? els.paramNumCtx.value : "");\n      const opts = {};\n      if (!isNaN(temperature)) opts.temperature = temperature;\n      if (!isNaN(top_p))       opts.top_p       = top_p;\n      if (!isNaN(seed) && seed >= 0) opts.seed  = seed;\n      if (numCtx != null)      opts.num_ctx     = numCtx;\n      return opts;\n    }\n\n    function saveParams() {\n      try {\n        localStorage.setItem(PARAMS_KEY, JSON.stringify({\n          temperature: els.paramTemp.value,\n          top_p:       els.paramTopP.value,\n          seed:        els.paramSeed.value,\n          num_ctx_by_model: state.modelNumCtxByModel,\n        }));\n      } catch (_) {}\n    }\n\n    function loadParams() {\n      try {\n        const saved = JSON.parse(localStorage.getItem(PARAMS_KEY) || "null");\n        state.modelNumCtxByModel = (saved && saved.num_ctx_by_model && typeof saved.num_ctx_by_model === "object")\n          ? saved.num_ctx_by_model\n          : {};\n        if (!saved) {\n          syncNumCtxInputForSelectedModel();\n          return;\n        }\n        if (saved.temperature != null) {\n          els.paramTemp.value    = saved.temperature;\n          els.paramTempVal.textContent = Number(saved.temperature).toFixed(2);\n        }\n        if (saved.top_p != null) {\n          els.paramTopP.value    = saved.top_p;\n          els.paramTopPVal.textContent = Number(saved.top_p).toFixed(2);\n        }\n        if (saved.seed != null) {\n          els.paramSeed.value    = saved.seed;\n        }\n        syncNumCtxInputForSelectedModel();\n      } catch (_) {\n        state.modelNumCtxByModel = {};\n        syncNumCtxInputForSelectedModel();\n      }\n    }\n\n    function clearNumCtxForCurrentModel(showNotice = true) {\n      const model = getSelectedModelKey();\n      if (model && Object.prototype.hasOwnProperty.call(state.modelNumCtxByModel, model)) {\n        delete state.modelNumCtxByModel[model];\n      }\n      syncNumCtxInputForSelectedModel();\n      saveParams();\n      if (showNotice && model) {\n        renderSystemNotice(`Το Max Length του μοντέλου ${model} επανήλθε στο πραγματικό μέγιστο context του cloud tag.`);\n      }\n    }\n\n    function updateCurrentModelNumCtxFromInput() {\n      const model = getSelectedModelKey();\n      if (!model || !els.paramNumCtx) return;\n      const normalized = normalizeNumCtxValue(els.paramNumCtx.value);\n      if (normalized == null) {\n        delete state.modelNumCtxByModel[model];\n        if (els.paramNumCtx.value.trim()) {\n          els.paramNumCtx.value = "";\n        }\n      } else {\n        state.modelNumCtxByModel[model] = normalized;\n        els.paramNumCtx.value = String(normalized);\n      }\n      syncNumCtxInputForSelectedModel();\n      saveParams();\n    }\n\n    function resetParams() {\n      els.paramTemp.value          = DEFAULT_PARAMS.temperature;\n      els.paramTempVal.textContent = DEFAULT_PARAMS.temperature.toFixed(2);\n      els.paramTopP.value          = DEFAULT_PARAMS.top_p;\n      els.paramTopPVal.textContent = DEFAULT_PARAMS.top_p.toFixed(2);\n      els.paramSeed.value          = DEFAULT_PARAMS.seed;\n      clearNumCtxForCurrentModel(false);\n      saveParams();\n      renderSystemNotice("Παράμετροι μοντέλου επαναφέρθηκαν στις προεπιλογές.");\n    }\n\n    // Live update labels as sliders move\n    els.paramTemp.addEventListener("input", () => {\n      els.paramTempVal.textContent = Number(els.paramTemp.value).toFixed(2);\n      saveParams();\n    });\n    els.paramTopP.addEventListener("input", () => {\n      els.paramTopPVal.textContent = Number(els.paramTopP.value).toFixed(2);\n      saveParams();\n    });\n    els.paramSeed.addEventListener("change", saveParams);\n    if (els.paramNumCtx) {\n      els.paramNumCtx.addEventListener("change", updateCurrentModelNumCtxFromInput);\n      els.paramNumCtx.addEventListener("blur", updateCurrentModelNumCtxFromInput);\n    }\n    if (els.clearNumCtxBtn) {\n      els.clearNumCtxBtn.addEventListener("click", () => clearNumCtxForCurrentModel(true));\n    }\n    // ── Cloud API health polling ────────────────────────────────────────────────\n\n    async function pollBackendHealth() {\n      try {\n        const resp = await fetch("/api/health");\n        const data = await resp.json();\n        if (data.cloud_api_configured) {\n          els.backendBadge.textContent = "⬤ Cloud API: OK";\n          els.backendBadge.className   = "badge ok";\n          const keySource = data.api_key_source || "configured";\n          els.backendBadge.title       = `Direct mode · API key source: ${keySource} · uptime ${Math.round(data.server_uptime_sec)}s`;\n        } else {\n          els.backendBadge.textContent = "⬤ Cloud API: KEY";\n          els.backendBadge.className   = "badge err";\n          els.backendBadge.title       = "Λείπει το Ollama Cloud API key από GUI/settings file ή OLLAMA_API_KEY";\n        }\n      } catch (_) {\n        els.backendBadge.textContent = "⬤ Cloud API: ?";\n        els.backendBadge.className   = "badge warn";\n      }\n    }\n\n    function maskApiKey(value) {\n      const key = String(value || "");\n      if (!key) return "";\n      if (key.length <= 10) return key[0] + "•".repeat(Math.max(0, key.length - 2)) + key.slice(-1);\n      return key.slice(0, 4) + "•".repeat(Math.max(0, key.length - 8)) + key.slice(-4);\n    }\n\n    function setApiKeyInfo(message, tone = "") {\n      if (!els.apiKeyInfo) return;\n      els.apiKeyInfo.textContent = message;\n      els.apiKeyInfo.className = `tiny ${tone === "error" ? "warn" : "muted"}`;\n    }\n\n    async function loadAppConfig() {\n      try {\n        const resp = await fetch("/api/app-config");\n        const data = await resp.json();\n        const key = String(data.ollama_api_key || "");\n        if (els.apiKeyInput) els.apiKeyInput.value = key;\n        if (data.has_ollama_api_key) {\n          const updated = data.updated_at ? ` · αποθήκευση ${data.updated_at}` : "";\n          setApiKeyInfo(`API key φορτώθηκε από settings file (${maskApiKey(key)})${updated}`);\n        } else {\n          setApiKeyInfo("Δεν υπάρχει αποθηκευμένο API key στο settings file.");\n        }\n      } catch (_) {\n        setApiKeyInfo("Αποτυχία φόρτωσης settings αρχείου.", "error");\n      }\n    }\n\n    async function saveApiKey() {\n      try {\n        const key = String((els.apiKeyInput && els.apiKeyInput.value) || "").trim();\n        const resp = await fetch("/api/app-config", {\n          method: "POST",\n          headers: { "Content-Type": "application/json" },\n          body: JSON.stringify({ ollama_api_key: key }),\n        });\n        const data = await resp.json().catch(() => ({}));\n        if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);\n        if (els.apiKeyInput) els.apiKeyInput.value = String((data.config && data.config.ollama_api_key) || key || "");\n        const masked = maskApiKey((data.config && data.config.ollama_api_key) || key);\n        const updated = data.config && data.config.updated_at ? ` · ${data.config.updated_at}` : "";\n        setApiKeyInfo(key ? `API key αποθηκεύτηκε (${masked})${updated}` : `Το αποθηκευμένο API key καθαρίστηκε.${updated}`);\n        await pollBackendHealth();\n        if (key) renderSystemNotice("Αποθηκεύτηκε το Ollama API key στο settings file.");\n        else renderSystemNotice("Καθαρίστηκε το αποθηκευμένο Ollama API key από το settings file.");\n      } catch (err) {\n        const msg = err && err.message ? err.message : String(err);\n        setApiKeyInfo(`Σφάλμα αποθήκευσης API key: ${msg}`, "error");\n        renderSystemNotice(`Σφάλμα αποθήκευσης API key: ${msg}`);\n      }\n    }\n\n    async function clearApiKey() {\n      if (els.apiKeyInput) els.apiKeyInput.value = "";\n      await saveApiKey();\n    }\n\n    // ── Tokens/sec display ───────────────────────────────────────────────────\n\n    function estimateLiveTokenCount(text) {\n      const src = String(text || "");\n      if (!src.trim()) return 0;\n      const words = src.match(/[\\p{L}\\p{N}_]+/gu) || [];\n      const punct = src.match(/[^\\s\\p{L}\\p{N}_]/gu) || [];\n      return words.length + punct.length;\n    }\n\n    function showLiveTokenStats(currentText, streamStartMs, phaseLabel = "Generating") {\n      if (!els.tokensPerSecBadge) return;\n      const elapsedMs = Math.max(1, Date.now() - Number(streamStartMs || Date.now()));\n      const elapsedSec = elapsedMs / 1000;\n      if (elapsedSec < 0.08) return;\n\n      const estimatedTokens = estimateLiveTokenCount(currentText);\n      if (estimatedTokens <= 0) return;\n\n      const liveTps = estimatedTokens / elapsedSec;\n      els.tokensPerSecBadge.textContent = `⚡ ${liveTps.toFixed(1)} tok/s`;\n      els.tokensPerSecBadge.className   = "badge";\n      els.tokensPerSecBadge.title       = [\n        `Live tok/s όσο γίνεται πιο κοντά στο πραγματικό κατά τη ροή`,\n        `Phase: ${phaseLabel}`,\n        `Estimated streamed tokens: ${estimatedTokens}`,\n        `Elapsed: ${elapsedSec.toFixed(2)}s`,\n        `Στο τέλος γίνεται reconcile με τα επίσημα eval_count / eval_duration του Ollama.`,\n      ].join(" · ");\n      els.tokensPerSecBadge.style.display = "";\n    }\n\n    function showTokenStats(tokenStats) {\n      if (!tokenStats || !els.tokensPerSecBadge) return;\n      const tps = Number(tokenStats.tokens_per_sec || 0);\n      const tokens = Number(tokenStats.eval_count || 0);\n      const promptTps = tokenStats.prompt_tokens_per_sec != null\n        ? Number(tokenStats.prompt_tokens_per_sec)\n        : null;\n      const totalTps = tokenStats.end_to_end_tokens_per_sec != null\n        ? Number(tokenStats.end_to_end_tokens_per_sec)\n        : null;\n\n      els.tokensPerSecBadge.textContent = `⚡ ${tps.toFixed(1)} tok/s`;\n      els.tokensPerSecBadge.className   = "badge ok";\n      els.tokensPerSecBadge.title       = [\n        `Πραγματικό output speed: ${tps.toFixed(1)} tok/s`,\n        `Output tokens: ${tokens}`,\n        promptTps != null ? `Prompt speed: ${promptTps.toFixed(1)} tok/s` : null,\n        totalTps != null ? `End-to-end speed: ${totalTps.toFixed(1)} tok/s` : null,\n      ].filter(Boolean).join(" · ");\n      els.tokensPerSecBadge.style.display = "";\n      state.lastTokensPerSec = tps;\n    }\n\n    function hideTokenStats() {\n      if (els.tokensPerSecBadge) els.tokensPerSecBadge.style.display = "none";\n    }\n\n    // ── Markdown renderer ─────────────────────────────────────────────────────\n\n    /**\n     * Inline markdown: escapes HTML first, then applies inline formatting.\n     * Order matters: bold before italic to avoid greedy single-* matching.\n     */\n    function inlineMarkdown(text) {\n      text = escapeHtml(text);\n      text = text.replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>");\n      text = text.replace(/__(.+?)__/g,     "<strong>$1</strong>");\n      text = text.replace(/\\*([^*\\n]+?)\\*/g,            "<em>$1</em>");\n      text = text.replace(/(?<!\\w)_([^_\\n]+?)_(?!\\w)/g, "<em>$1</em>");\n      text = text.replace(/~~(.+?)~~/g,  "<del>$1</del>");\n      text = text.replace(/`([^`\\n]+)`/g, \'<span class="code-inline">$1</span>\');\n      text = text.replace(\n        /\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\)]+)\\)/g,\n        \'<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>\'\n      );\n      return text;\n    }\n\n    /**\n     * Block markdown for a text segment (no code fences — those are handled separately).\n     */\n    function markdownToHtml(rawText) {\n      const lines = rawText.split("\\n");\n      const out   = [];\n      let inUl = false, inOl = false, inBq = false;\n\n      const closeUl  = () => { if (inUl) { out.push("</ul>");          inUl = false; } };\n      const closeOl  = () => { if (inOl) { out.push("</ol>");          inOl = false; } };\n      const closeBq  = () => { if (inBq) { out.push("</blockquote>"); inBq = false; } };\n      const closeLists = () => { closeUl(); closeOl(); };\n\n      for (const line of lines) {\n\n        // Heading  # … ######\n        const hm = line.match(/^(#{1,6})\\s+(.*)/);\n        if (hm) {\n          closeLists(); closeBq();\n          const lvl = hm[1].length;\n          out.push(`<h${lvl} class="md-h${lvl}">${inlineMarkdown(hm[2])}</h${lvl}>`);\n          continue;\n        }\n\n        // Horizontal rule  --- / *** / ___\n        if (/^(\\s*[-*_]){3,}\\s*$/.test(line) && line.trim().length >= 3) {\n          closeLists(); closeBq();\n          out.push(\'<hr class="md-hr" />\');\n          continue;\n        }\n\n        // Blockquote  > ...\n        const bm = line.match(/^>\\s?(.*)/);\n        if (bm) {\n          closeLists();\n          if (!inBq) { out.push(\'<blockquote class="md-bq">\'); inBq = true; }\n          out.push(`<p>${inlineMarkdown(bm[1])}</p>`);\n          continue;\n        }\n        closeBq();\n\n        // Unordered list  - * +\n        const um = line.match(/^[-*+]\\s+(.*)/);\n        if (um) {\n          closeOl();\n          if (!inUl) { out.push(\'<ul class="md-list">\'); inUl = true; }\n          out.push(`<li>${inlineMarkdown(um[1])}</li>`);\n          continue;\n        }\n\n        // Ordered list  1. 2. …\n        const om = line.match(/^\\d+\\.\\s+(.*)/);\n        if (om) {\n          closeUl();\n          if (!inOl) { out.push(\'<ol class="md-list">\'); inOl = true; }\n          out.push(`<li>${inlineMarkdown(om[1])}</li>`);\n          continue;\n        }\n\n        closeLists();\n\n        // Empty line\n        if (!line.trim()) { out.push(\'<div class="md-br"></div>\'); continue; }\n\n        // Normal paragraph\n        out.push(`<p class="md-p">${inlineMarkdown(line)}</p>`);\n      }\n\n      closeLists(); closeBq();\n      return out.join("\\n");\n    }\n\n    // ── Message rendering ─────────────────────────────────────────────────────\n\n    /**\n     * Εξάγει <think>...</think> blocks, code fences και plain text.\n     * Τύποι parts: "think" | "code" | "text"\n     * Τα think blocks εμφανίζονται ως collapsible details element.\n     */\n    function parseMessageParts(sourceText) {\n      const parts  = [];\n      const text   = String(sourceText || "");\n      let   cursor = 0;\n\n      while (cursor < text.length) {\n        // ── <think> block detection ──────────────────────────────────────────\n        const thinkStart = text.indexOf("<think>", cursor);\n        const fenceStart = text.indexOf("```",    cursor);\n\n        // Determine which comes first\n        const nextThink = thinkStart >= 0 ? thinkStart : Infinity;\n        const nextFence = fenceStart >= 0 ? fenceStart : Infinity;\n\n        if (nextThink === Infinity && nextFence === Infinity) {\n          // Only plain text remains\n          const rem = text.slice(cursor);\n          if (rem) parts.push({ type: "text", content: rem });\n          break;\n        }\n\n        if (nextThink < nextFence) {\n          // <think> comes first\n          const before = text.slice(cursor, thinkStart);\n          if (before) parts.push({ type: "text", content: before });\n\n          const thinkEnd = text.indexOf("</think>", thinkStart + 7);\n          if (thinkEnd === -1) {\n            // Still streaming — show partial thinking\n            parts.push({ type: "think", content: text.slice(thinkStart + 7), complete: false });\n            cursor = text.length;\n          } else {\n            parts.push({ type: "think", content: text.slice(thinkStart + 7, thinkEnd), complete: true });\n            cursor = thinkEnd + 8; // length of "</think>"\n          }\n          continue;\n        }\n\n        // ── Code fence ───────────────────────────────────────────────────────\n        const before = text.slice(cursor, fenceStart);\n        if (before) parts.push({ type: "text", content: before });\n\n        const afterFence = fenceStart + 3;\n        const nlPos      = text.indexOf("\\n", afterFence);\n\n        if (nlPos === -1) {\n          parts.push({ type: "code", language: text.slice(afterFence).trim() || "text", content: "", complete: false });\n          cursor = text.length;\n          break;\n        }\n\n        const language  = text.slice(afterFence, nlPos).trim() || "text";\n        const codeStart = nlPos + 1;\n        const fenceEnd  = text.indexOf("```", codeStart);\n\n        if (fenceEnd === -1) {\n          parts.push({ type: "code", language, content: text.slice(codeStart), complete: false });\n          cursor = text.length;\n          break;\n        }\n\n        parts.push({ type: "code", language, content: text.slice(codeStart, fenceEnd), complete: true });\n        cursor = fenceEnd + 3;\n      }\n\n      if (!parts.length) parts.push({ type: "text", content: "" });\n      return parts;\n    }\n\n    // Language aliases → Prism class names\n    const LANG_MAP = {\n      py: "python", js: "javascript", ts: "typescript",\n      sh: "bash", shell: "bash", zsh: "bash", fish: "bash",\n      yml: "yaml", htm: "html", golang: "go",\n    };\n\n    function isPythonLanguage(language) {\n      const normalizedLang = String(language || "").trim().toLowerCase();\n      return normalizedLang === "python" || normalizedLang === "py";\n    }\n\n    function extractSuggestedPyFilenamesFromText(rawText) {\n      const text = String(rawText || "");\n      if (!text) return [];\n\n      const parts = parseMessageParts(text);\n      const textOnly = parts\n        .filter(part => part.type === "text")\n        .map(part => String(part.content || ""))\n        .join("\\n");\n\n      const results = [];\n      const seen = new Set();\n      const regex = /([A-Za-z0-9_][A-Za-z0-9._ -]{0,120}\\.py)\\b/gi;\n      let match;\n      while ((match = regex.exec(textOnly)) !== null) {\n        const candidate = String(match[1] || "").trim().replace(/^[\'"`(\\[]+|[\'"`)\\],.:;!?]+$/g, "");\n        if (!candidate) continue;\n        const lower = candidate.toLowerCase();\n        if (seen.has(lower)) continue;\n        seen.add(lower);\n        results.push(candidate);\n      }\n      return results;\n    }\n\n    function createCodeBlock(language, code, suggestedFilename = "") {\n      const wrapper  = document.createElement("div");\n      wrapper.className = "code-block";\n\n      const toolbar  = document.createElement("div");\n      toolbar.className = "code-toolbar";\n\n      const langNode = document.createElement("div");\n      langNode.className   = "code-language";\n      langNode.textContent = language || "text";\n\n      const copyBtn  = document.createElement("button");\n      copyBtn.type        = "button";\n      copyBtn.className   = "code-copy-btn";\n      copyBtn.textContent = "📋 Copy";\n      copyBtn.title       = "Αντιγραφή κώδικα στο clipboard";\n      copyBtn.addEventListener("click", async () => {\n        try {\n          await navigator.clipboard.writeText(code);\n          setButtonFeedback(copyBtn, "✅ Copied", "📋 Copy");\n        } catch {\n          setButtonFeedback(copyBtn, "❌ Error", "📋 Copy", "error");\n        }\n      });\n\n      toolbar.appendChild(langNode);\n\n      const normalizedLang = String(language || "").trim().toLowerCase();\n      if (isPythonLanguage(normalizedLang)) {\n        const preferredFilename = String(suggestedFilename || "").trim();\n        const defaultSaveLabel = preferredFilename ? `💾 ${preferredFilename}` : "💾 .py";\n        const saveBtn = document.createElement("button");\n        saveBtn.type = "button";\n        saveBtn.className = "code-copy-btn";\n        saveBtn.textContent = defaultSaveLabel;\n        saveBtn.title = preferredFilename\n          ? `Αποθήκευση του Python block ως ${preferredFilename}`\n          : "Αποθήκευση του Python block σε επισυναπτόμενο αρχείο .py";\n        saveBtn.addEventListener("click", async () => {\n          try {\n            const resp = await fetch("/api/export-python-block", {\n              method: "POST",\n              headers: { "Content-Type": "application/json" },\n              body: JSON.stringify({ code, filename: preferredFilename }),\n            });\n            const data = await resp.json().catch(() => ({}));\n            if (!resp.ok || !data.file || !data.file.url) {\n              throw new Error(data.error || "Αποτυχία αποθήκευσης του Python block ως .py αρχείο.");\n            }\n            const messageWrapper = wrapper.closest(\'.msg\');\n            if (messageWrapper) appendGeneratedAttachmentToMessage(messageWrapper, data.file);\n            triggerFileDownload(data.file.url, data.file.name || preferredFilename || \'generated_code.py\');\n            setButtonFeedback(saveBtn, "✅ Saved", defaultSaveLabel);\n            renderSystemNotice(`Αποθηκεύτηκε το Python block ως αρχείο: ${data.file.name}`);\n          } catch (err) {\n            setButtonFeedback(saveBtn, "❌ Error", defaultSaveLabel, "error");\n            renderSystemNotice(`Σφάλμα αποθήκευσης Python block: ${err && err.message ? err.message : String(err)}`);\n          }\n        });\n        toolbar.appendChild(saveBtn);\n\n        const defaultRunLabel = preferredFilename ? `▶ Run ${preferredFilename}` : "▶ Run";\n        const runBtn = document.createElement("button");\n        runBtn.type = "button";\n        runBtn.className = "code-copy-btn";\n        runBtn.textContent = defaultRunLabel;\n        runBtn.title = preferredFilename\n          ? `Άνοιγμα νέου terminal και εκτέλεση του Python block ως ${preferredFilename}`\n          : "Άνοιγμα νέου terminal και εκτέλεση ολόκληρου του Python block";\n        runBtn.addEventListener("click", async () => {\n          const confirmed = window.confirm(\n            preferredFilename\n              ? `Να ανοίξει νέο terminal και να εκτελεστεί το Python block ως ${preferredFilename};`\n              : "Να ανοίξει νέο terminal και να εκτελεστεί ολόκληρο το Python block;"\n          );\n          if (!confirmed) return;\n          try {\n            const resp = await fetch("/api/execute-python", {\n              method: "POST",\n              headers: { "Content-Type": "application/json" },\n              body: JSON.stringify({ code, filename: preferredFilename }),\n            });\n            const data = await resp.json().catch(() => ({}));\n            if (!resp.ok) {\n              throw new Error(data.error || "Αποτυχία εκτέλεσης Python block.");\n            }\n            setButtonFeedback(\n              runBtn,\n              preferredFilename ? `▶ Running ${preferredFilename}` : "▶ Running",\n              defaultRunLabel\n            );\n            renderSystemNotice(data.message || "Το Python block στάλθηκε για εκτέλεση σε νέο terminal.");\n          } catch (err) {\n            setButtonFeedback(runBtn, "❌ Error", defaultRunLabel, "error");\n            renderSystemNotice(`Σφάλμα εκτέλεσης κώδικα: ${err && err.message ? err.message : String(err)}`);\n          }\n        });\n        toolbar.appendChild(runBtn);\n      }\n\n      toolbar.appendChild(copyBtn);\n\n      const pre      = document.createElement("pre");\n      pre.className  = "code-pre";\n\n      const codeNode = document.createElement("code");\n      const prismLang = LANG_MAP[language.toLowerCase()] || language.toLowerCase();\n      codeNode.className   = `language-${prismLang}`;\n      codeNode.textContent = code;\n\n      pre.appendChild(codeNode);\n      wrapper.appendChild(toolbar);\n      wrapper.appendChild(pre);\n\n      // Trigger Prism highlighting after the element is in the DOM\n      requestAnimationFrame(() => {\n        if (window.Prism) {\n          try { Prism.highlightElement(codeNode); } catch (_) {}\n        }\n      });\n\n      return wrapper;\n    }\n\n    function createThinkingBlock(content, complete) {\n      const details = document.createElement("details");\n      details.className = "thinking-block";\n      // Διατήρησε την επιλογή του χρήστη όσο γίνεται rerender κατά το streaming\n      details.open = !complete ? state.currentInlineThinkingOpen !== false : false;\n\n      const summary = document.createElement("summary");\n      summary.className = "thinking-summary";\n\n      const icon = document.createElement("span");\n      icon.className = "thinking-icon"; icon.textContent = "🧠";\n\n      const label = document.createElement("span");\n      label.className = "thinking-label";\n      const wordCount = content.trim() ? content.trim().split(/\\s+/).length : 0;\n      label.textContent = complete\n        ? `Βαθιά σκέψη · ${wordCount} λέξεις — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`\n        : `Σκέψη σε εξέλιξη… — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`;\n\n      const chev = document.createElement("span");\n      chev.className = "thinking-chevron"; chev.textContent = "›";\n\n      summary.appendChild(icon); summary.appendChild(label); summary.appendChild(chev);\n\n      const body = document.createElement("div");\n      body.className = "thinking-body"; body.textContent = content;\n\n      details.appendChild(summary); details.appendChild(body);\n\n      // Update label text when toggled\n      details.addEventListener("toggle", () => {\n        state.currentInlineThinkingOpen = details.open;\n        if (complete) {\n          label.textContent = `Βαθιά σκέψη · ${wordCount} λέξεις — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`;\n        } else {\n          label.textContent = `Σκέψη σε εξέλιξη… — κλικ για ${details.open ? "απόκρυψη" : "εμφάνιση"}`;\n        }\n      });\n\n      return details;\n    }\n\n    function createTextSegment(text) {\n      const div = document.createElement("div");\n      div.innerHTML = markdownToHtml(text);\n      return div;\n    }\n\n    function composeDisplayContent(answerText = "", thinkingText = "") {\n      const answer   = String(answerText || "");\n      const thinking = String(thinkingText || "");\n      if (thinking && answer) return `<think>${thinking}</think>\\n\\n${answer}`;\n      if (thinking) return `<think>${thinking}</think>`;\n      return answer;\n    }\n\n    function getThinkingStateFromRawContent(sourceText) {\n      const parts = parseMessageParts(sourceText);\n      const thinkParts = parts.filter(part => part.type === "think");\n      return {\n        text: thinkParts.map(part => part.content || "").join("\\n\\n"),\n        complete: thinkParts.length ? thinkParts.every(part => part.complete !== false) : true,\n      };\n    }\n\n    function applyReasoningPanelVisibility() {\n      if (!els.reasoningPanel || !els.toggleReasoningBtn) return;\n      const hasContent = Boolean(((els.reasoningContent && els.reasoningContent.textContent) || "").trim());\n      const wantsVisible = state.reasoningPanelVisible || (state.reasoningAutoOpen && !state.reasoningUserCollapsed);\n      const isVisible = hasContent && wantsVisible;\n      els.reasoningPanel.classList.toggle("visible", isVisible);\n      els.toggleReasoningBtn.textContent = isVisible ? "🙈 Απόκρυψη" : "👁 Εμφάνιση";\n      els.toggleReasoningBtn.title = isVisible\n        ? "Απόκρυψη του panel σκέψης"\n        : "Εμφάνιση του panel σκέψης";\n    }\n\n    function resetReasoningPanel(hide = true) {\n      state.currentThinkingText = "";\n      state.reasoningAutoOpen = false;\n      state.reasoningUserCollapsed = false;\n      state.currentInlineThinkingOpen = true;\n      state.reasoningStreamCompleted = false;\n      if (hide) state.reasoningPanelVisible = false;\n      if (els.reasoningContent) els.reasoningContent.textContent = "";\n      if (els.reasoningMeta) els.reasoningMeta.textContent = "Αναμονή για thinking stream…";\n      if (els.reasoningPanel) els.reasoningPanel.classList.remove("streaming");\n      if (hide && els.reasoningPanel) els.reasoningPanel.classList.remove("visible");\n      applyReasoningPanelVisibility();\n    }\n\n    function updateReasoningPanel(text, complete = false, streaming = false) {\n      const safeText = String(text || "");\n      state.currentThinkingText = safeText;\n\n      if (!safeText.trim()) {\n        resetReasoningPanel(true);\n        return;\n      }\n\n      if (streaming && !complete && !state.reasoningUserCollapsed) {\n        state.reasoningAutoOpen = true;\n      }\n\n      if (els.reasoningContent) {\n        els.reasoningContent.textContent = safeText;\n        els.reasoningContent.scrollTop = els.reasoningContent.scrollHeight;\n      }\n\n      const wordCount = safeText.trim() ? safeText.trim().split(/\\s+/).length : 0;\n      if (els.reasoningMeta) {\n        els.reasoningMeta.textContent = streaming && !complete\n          ? `Σκέψη σε εξέλιξη… · ${wordCount} λέξεις`\n          : `Ολοκληρωμένη σκέψη · ${wordCount} λέξεις`;\n      }\n\n      if (els.reasoningPanel) {\n        els.reasoningPanel.classList.toggle("streaming", streaming && !complete);\n      }\n      applyReasoningPanelVisibility();\n\n      if (complete) {\n        setTimeout(() => {\n          if (state.reasoningStreamCompleted) {\n            state.reasoningAutoOpen = false;\n            state.reasoningPanelVisible = false;\n            state.reasoningUserCollapsed = false;\n            applyReasoningPanelVisibility();\n          }\n        }, 350);\n      }\n    }\n\n    function renderAssistantStreamingView(rawAnswerText, separateThinkingText = "", streamFinished = false) {\n      const hasSeparateThinking = Boolean(String(separateThinkingText || "").trim());\n      const displayText = hasSeparateThinking\n        ? composeDisplayContent(rawAnswerText, separateThinkingText)\n        : String(rawAnswerText || "");\n\n      renderMessageContent(state.currentAssistantNode, displayText);\n\n      if (hasSeparateThinking) {\n        const thinkingComplete = state.reasoningStreamCompleted || streamFinished;\n        updateReasoningPanel(separateThinkingText, thinkingComplete, !thinkingComplete);\n      } else {\n        const legacyThinking = getThinkingStateFromRawContent(displayText);\n        if (legacyThinking.text.trim()) {\n          updateReasoningPanel(legacyThinking.text, streamFinished ? true : legacyThinking.complete, !streamFinished && !legacyThinking.complete);\n        } else if (!streamFinished) {\n          resetReasoningPanel(true);\n        }\n      }\n\n      return displayText;\n    }\n\n    function renderMessageContent(container, content) {\n      const sourceText = String(content || "");\n      container.innerHTML          = "";\n      container.dataset.rawContent = sourceText;\n\n      const frag  = document.createDocumentFragment();\n      const parts = parseMessageParts(sourceText);\n      const suggestedPyFilenames = extractSuggestedPyFilenamesFromText(sourceText);\n      let pythonBlockIndex = 0;\n\n      for (const part of parts) {\n        if (part.type === "think") {\n          frag.appendChild(createThinkingBlock(part.content || "", part.complete !== false));\n        } else if (part.type === "code") {\n          const suggestedFilename = isPythonLanguage(part.language)\n            ? (suggestedPyFilenames[pythonBlockIndex] || "")\n            : "";\n          frag.appendChild(createCodeBlock(part.language, part.content || "", suggestedFilename));\n          if (isPythonLanguage(part.language)) pythonBlockIndex += 1;\n        } else {\n          frag.appendChild(createTextSegment(part.content || ""));\n        }\n      }\n      container.appendChild(frag);\n    }\n\n    // ── Message creation ──────────────────────────────────────────────────────\n\n    function createAttachmentChip(item) {\n      const hasUrl = !!(item && item.url);\n      const chip = document.createElement(hasUrl ? "a" : "div");\n      chip.className = `attachment-chip${hasUrl ? " link" : ""}`;\n      if (hasUrl) {\n        chip.href = item.url;\n        chip.target = "_blank";\n        chip.rel = "noopener noreferrer";\n        chip.download = item.name || "attachment";\n        chip.title = `Άνοιγμα / λήψη: ${item.name || "attachment"}`;\n      }\n      const icon = item && item.kind === "image" ? "🖼" : "📄";\n      chip.textContent = `${icon} ${(item && item.name) ? item.name : "attachment"}`;\n      return chip;\n    }\n\n    function ensureMessageAttachmentList(messageWrapper) {\n      let wrap = messageWrapper.querySelector(\'.attachment-list\');\n      if (!wrap) {\n        wrap = document.createElement(\'div\');\n        wrap.className = \'attachment-list\';\n        messageWrapper.appendChild(wrap);\n      }\n      return wrap;\n    }\n\n    function appendGeneratedAttachmentToMessage(messageWrapper, item) {\n      if (!messageWrapper || !item || !item.url) return;\n      const wrap = ensureMessageAttachmentList(messageWrapper);\n      const existing = Array.from(wrap.querySelectorAll(\'a.attachment-chip[href], .attachment-chip[data-name]\'))\n        .some(node => (node.getAttribute(\'href\') || \'\') === item.url || (node.dataset && node.dataset.name) === item.name);\n      if (existing) return;\n      const chip = createAttachmentChip(item);\n      if (chip.dataset) chip.dataset.name = item.name || \'\';\n      wrap.appendChild(chip);\n    }\n\n    function triggerFileDownload(url, filename) {\n      const a = document.createElement(\'a\');\n      a.href = url;\n      a.download = filename || \'\';\n      a.rel = \'noopener noreferrer\';\n      document.body.appendChild(a);\n      a.click();\n      a.remove();\n    }\n\n    function removeEmptyState() {\n      const node = document.getElementById("emptyState");\n      if (node) node.remove();\n    }\n\n    function scrollToBottom(force = false) {\n      if (state.autoScroll || force) {\n        els.messages.scrollTop = els.messages.scrollHeight;\n      }\n    }\n\n    function updateScrollToBottomBtn() {\n      const { scrollTop, scrollHeight, clientHeight } = els.messages;\n      const atBottom = scrollHeight - scrollTop - clientHeight < 80;\n      els.scrollToBottomBtn.classList.toggle("visible", !atBottom && !state.autoScroll);\n    }\n\n    function updateMsgCount() {\n      state.msgCount = els.messages.querySelectorAll(".msg.user, .msg.assistant").length;\n      els.msgCountBadge.textContent = `${state.msgCount} μηνύματα`;\n    }\n\n    function createStreamingPlaceholder() {\n      const d = document.createElement("div");\n      d.className = "streaming-dots";\n      d.innerHTML = "<span></span><span></span><span></span>";\n      return d;\n    }\n\n    function createMessage(role, content, attachments = []) {\n      removeEmptyState();\n\n      const wrapper = document.createElement("div");\n      wrapper.className = `msg ${role}`;\n\n      // Header\n      const head     = document.createElement("div");\n      head.className = "msg-head";\n      const roleNode = document.createElement("div");\n      roleNode.className   = "msg-role";\n      roleNode.textContent = role === "user" ? "Εσύ" : role === "assistant" ? "Assistant" : "System";\n      const timeNode = document.createElement("div");\n      timeNode.className   = "msg-time";\n      timeNode.textContent = nowString();\n      head.appendChild(roleNode);\n      head.appendChild(timeNode);\n\n      // Body\n      const body     = document.createElement("div");\n      body.className = "msg-body";\n      if (role === "assistant" && !content) {\n        body.appendChild(createStreamingPlaceholder());\n      } else {\n        renderMessageContent(body, content || "");\n      }\n\n      wrapper.appendChild(head);\n      wrapper.appendChild(body);\n\n      // Attachments\n      if (attachments && attachments.length) {\n        const wrap = document.createElement("div");\n        wrap.className = "attachment-list";\n        for (const item of attachments) {\n          wrap.appendChild(createAttachmentChip(item));\n        }\n        wrapper.appendChild(wrap);\n      }\n\n      // Copy button\n      const tools   = document.createElement("div");\n      tools.className = "message-tools";\n      const copyBtn = document.createElement("button");\n      copyBtn.type        = "button";\n      copyBtn.className   = "tool-btn";\n      copyBtn.textContent = "📋 Copy";\n      copyBtn.title       = "Αντιγραφή μηνύματος";\n      copyBtn.addEventListener("click", async () => {\n        try {\n          await navigator.clipboard.writeText(body.dataset.rawContent || body.textContent || "");\n          setButtonFeedback(copyBtn, "✅ Copied", "📋 Copy");\n        } catch {\n          setButtonFeedback(copyBtn, "❌ Error", "📋 Copy", "error");\n        }\n      });\n      tools.appendChild(copyBtn);\n      wrapper.appendChild(tools);\n\n      els.messages.appendChild(wrapper);\n      scrollToBottom();\n      updateMsgCount();\n\n      return { wrapper, body };\n    }\n\n    function renderSystemNotice(text) {\n      createMessage("system", text, []);\n    }\n\n    function renderEmptyState() {\n      els.messages.innerHTML = `\n        <div class="empty-state" id="emptyState">\n          <h3 style="margin-top:0;">Έτοιμο για συνομιλία</h3>\n          <div>Γράψε το δικό σου prompt και, αν θέλεις, πρόσθεσε αρχεία για context.</div>\n          <div style="margin-top:10px;" class="tiny">\n            Enter αποστολή · Shift+Enter νέα γραμμή · Ctrl+Enter εναλλακτικό\n          </div>\n        </div>`;\n      state.msgCount = 0;\n      els.msgCountBadge.textContent = "0 μηνύματα";\n    }\n\n    // ── File handling & Drag/Drop ─────────────────────────────────────────────\n\n    function renderSelectedFiles() {\n      els.selectedFiles.innerHTML = "";\n      for (const file of state.selectedFiles) {\n        const chip = document.createElement("div");\n        chip.className   = "attachment-chip";\n        chip.textContent = `📎 ${file.name}`;\n        els.selectedFiles.appendChild(chip);\n      }\n    }\n\n    function addFiles(fileList) {\n      const existing = new Set(state.selectedFiles.map(f => `${f.name}|${f.size}`));\n      for (const file of Array.from(fileList || [])) {\n        const key = `${file.name}|${file.size}`;\n        if (!existing.has(key)) { state.selectedFiles.push(file); existing.add(key); }\n      }\n      renderSelectedFiles();\n    }\n\n    async function readFileAsBase64(file) {\n      return new Promise((resolve, reject) => {\n        const reader  = new FileReader();\n        reader.onload = () => {\n          const parts = String(reader.result || "").split(",");\n          resolve({\n            name: file.name, size: file.size,\n            mime_type: file.type || "",\n            data_base64: parts.length > 1 ? parts[1] : "",\n          });\n        };\n        reader.onerror = () => reject(new Error(`Αποτυχία ανάγνωσης: ${file.name}`));\n        reader.readAsDataURL(file);\n      });\n    }\n\n    async function collectFilesPayload() {\n      const payload = [];\n      for (const file of state.selectedFiles) payload.push(await readFileAsBase64(file));\n      return payload;\n    }\n\n    // Reliable drag-enter / drag-leave with a counter (avoids child-element flicker)\n    document.addEventListener("dragenter", (e) => {\n      e.preventDefault();\n      state.dragCounter++;\n      els.dropOverlay.classList.add("active");\n    });\n    document.addEventListener("dragleave", () => {\n      state.dragCounter--;\n      if (state.dragCounter <= 0) {\n        state.dragCounter = 0;\n        els.dropOverlay.classList.remove("active");\n      }\n    });\n    document.addEventListener("dragover", (e) => e.preventDefault());\n    document.addEventListener("drop", (e) => {\n      e.preventDefault();\n      state.dragCounter = 0;\n      els.dropOverlay.classList.remove("active");\n      if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);\n    });\n\n    // ── Model management ──────────────────────────────────────────────────────\n\n    function getSavedModel(models) {\n      try {\n        const saved = localStorage.getItem(MODEL_KEY);\n        return saved && models.includes(saved) ? saved : null;\n      } catch { return null; }\n    }\n\n    function saveModel(model) {\n      try { localStorage.setItem(MODEL_KEY, model); } catch (_) {}\n    }\n\n    function getSavedSortCriterion() {\n      try {\n        const saved = localStorage.getItem(MODEL_SORT_KEY);\n        return saved || "overall";\n      } catch { return "overall"; }\n    }\n\n    function saveSortCriterion(value) {\n      try { localStorage.setItem(MODEL_SORT_KEY, value || "overall"); } catch (_) {}\n    }\n\n    function normalizeEnsembleMode(value) {\n      const normalized = String(value || "auto").trim().toLowerCase();\n      return ["off", "auto", "manual"].includes(normalized) ? normalized : "auto";\n    }\n\n    function getSavedEnsembleMode() {\n      try {\n        const explicit = localStorage.getItem(ENSEMBLE_MODE_KEY);\n        if (explicit) return normalizeEnsembleMode(explicit);\n      } catch (_) {}\n      try {\n        const legacy = localStorage.getItem(ENSEMBLE_KEY);\n        if (legacy == null) return "auto";\n        return legacy !== "0" ? "auto" : "off";\n      } catch { return "auto"; }\n    }\n\n    function saveEnsembleMode(value) {\n      const mode = normalizeEnsembleMode(value);\n      try { localStorage.setItem(ENSEMBLE_MODE_KEY, mode); } catch (_) {}\n      try { localStorage.setItem(ENSEMBLE_KEY, mode === "off" ? "0" : "1"); } catch (_) {}\n    }\n\n    function getSavedHelperModel(models) {\n      try {\n        const saved = localStorage.getItem(ENSEMBLE_HELPER_KEY);\n        return saved && models.includes(saved) ? saved : null;\n      } catch { return null; }\n    }\n\n    function saveHelperModel(model) {\n      try {\n        if (model) localStorage.setItem(ENSEMBLE_HELPER_KEY, model);\n        else localStorage.removeItem(ENSEMBLE_HELPER_KEY);\n      } catch (_) {}\n    }\n\n    function filterModelsBySearch(modelList, rawQuery) {\n      const models = Array.isArray(modelList) ? modelList.filter(Boolean) : [];\n      const query = String(rawQuery || "").trim().toLowerCase();\n      if (!query) return models;\n      const tokens = query.split(/\\s+/).filter(Boolean);\n      return models.filter((model) => {\n        const haystack = String(model || "").toLowerCase();\n        return tokens.every((token) => haystack.includes(token));\n      });\n    }\n\n    function parseParamSizeBillions(rawValue) {\n      const textValue = String(rawValue || "").trim().toLowerCase();\n      if (!textValue) return 0;\n      const match = textValue.match(/(\\d+(?:\\.\\d+)?)\\s*([tbm])?/i);\n      if (!match) return 0;\n      const value = Number(match[1] || 0);\n      const suffix = String(match[2] || "b").toLowerCase();\n      if (!Number.isFinite(value) || value <= 0) return 0;\n      if (suffix === "t") return value * 1000;\n      if (suffix === "m") return value / 1000;\n      return value;\n    }\n\n    function getModelMeta(model) {\n      return (state.modelMetaByModel && state.modelMetaByModel[model] && typeof state.modelMetaByModel[model] === "object")\n        ? state.modelMetaByModel[model]\n        : {};\n    }\n\n    function getModelCapabilities(model) {\n      const meta = getModelMeta(model);\n      const caps = Array.isArray(meta.capabilities) ? meta.capabilities.map(x => String(x || "").toLowerCase()) : [];\n      const name = String(model || "").toLowerCase();\n      if (!caps.includes("vision") && ["vision", "-vl", ":vl", "gemini", "llava", "pixtral"].some(t => name.includes(t))) caps.push("vision");\n      if (!caps.includes("coding") && ["coder", "code", "devstral"].some(t => name.includes(t))) caps.push("coding");\n      if (!caps.includes("reasoning") && ["thinking", "reason", "r1", "gpt-oss", "qwen3.5", "kimi-k2", "deepseek", "cogito"].some(t => name.includes(t))) caps.push("reasoning");\n      return Array.from(new Set(caps));\n    }\n\n    function getModelSizeBillions(model) {\n      const meta = getModelMeta(model);\n      const byParam = Number(meta.parameter_size_b || 0);\n      if (Number.isFinite(byParam) && byParam > 0) return byParam;\n      const byName = parseParamSizeBillions(model);\n      if (Number.isFinite(byName) && byName > 0) return byName;\n      const sizeBytes = Number(meta.size_bytes || 0);\n      if (Number.isFinite(sizeBytes) && sizeBytes > 0) {\n        return sizeBytes / 1_000_000_000;\n      }\n      return 0;\n    }\n\n    function getModelContextTokens(model) {\n      const meta = getModelMeta(model);\n      const numCtx = Number(meta.num_ctx_max || state.modelMaxNumCtxByModel[model] || 0);\n      return Number.isFinite(numCtx) && numCtx > 0 ? numCtx : 0;\n    }\n\n    function getModelModifiedTs(model) {\n      const meta = getModelMeta(model);\n      const rawTs = Number(meta.modified_ts || 0);\n      if (Number.isFinite(rawTs) && rawTs > 0) return rawTs;\n      const rawDate = String(meta.modified_at || "").trim();\n      if (!rawDate) return 0;\n      const ts = Date.parse(rawDate);\n      return Number.isFinite(ts) ? Math.trunc(ts / 1000) : 0;\n    }\n\n    const FAMILY_PRIOR_DEFAULTS = Object.freeze({\n      overall: 7.50,\n      coding: 7.20,\n      reasoning: 7.35,\n      context: 7.05,\n      vision: 6.85,\n      speed: 7.10,\n    });\n\n    const MODEL_FAMILY_PROFILES = Object.freeze([\n      ["gemini-3-flash",   { overall: 9.12, coding: 8.62, reasoning: 8.82, context: 8.95, vision: 9.35, speed: 9.95 }],\n      ["deepseek-v3.2",    { overall: 9.82, coding: 9.62, reasoning: 9.90, context: 9.14, vision: 6.20, speed: 4.70 }],\n      ["deepseek-v3.1",    { overall: 9.72, coding: 9.54, reasoning: 9.80, context: 9.02, vision: 6.00, speed: 4.82 }],\n      ["deepseek-r1",      { overall: 9.66, coding: 9.10, reasoning: 9.96, context: 8.40, vision: 5.25, speed: 3.86 }],\n      ["qwen3.5",          { overall: 9.96, coding: 9.74, reasoning: 9.92, context: 9.52, vision: 9.84, speed: 4.42 }],\n      ["qwen3-coder-next", { overall: 9.56, coding: 9.96, reasoning: 9.42, context: 9.00, vision: 5.35, speed: 5.06 }],\n      ["qwen3-coder",      { overall: 9.68, coding: 9.98, reasoning: 9.60, context: 9.08, vision: 5.38, speed: 4.25 }],\n      ["qwen3-vl",         { overall: 9.58, coding: 9.26, reasoning: 9.42, context: 9.02, vision: 9.98, speed: 4.52 }],\n      ["qwen3-next",       { overall: 9.24, coding: 9.10, reasoning: 9.18, context: 8.86, vision: 7.92, speed: 5.12 }],\n      ["kimi-k2-thinking", { overall: 9.62, coding: 9.22, reasoning: 9.90, context: 9.12, vision: 6.62, speed: 3.72 }],\n      ["kimi-k2.5",        { overall: 9.76, coding: 9.40, reasoning: 9.78, context: 9.28, vision: 7.12, speed: 4.12 }],\n      ["kimi-k2",          { overall: 9.58, coding: 9.22, reasoning: 9.62, context: 9.00, vision: 6.85, speed: 4.25 }],\n      ["glm-5",            { overall: 9.60, coding: 9.36, reasoning: 9.56, context: 9.12, vision: 8.72, speed: 4.15 }],\n      ["glm-4.7",          { overall: 9.46, coding: 9.18, reasoning: 9.44, context: 8.92, vision: 8.22, speed: 4.02 }],\n      ["glm-4.6",          { overall: 9.38, coding: 9.12, reasoning: 9.36, context: 8.78, vision: 8.05, speed: 4.10 }],\n      ["minimax-m2.7",     { overall: 9.42, coding: 9.06, reasoning: 9.40, context: 8.96, vision: 8.62, speed: 4.42 }],\n      ["minimax-m2.5",     { overall: 9.34, coding: 8.98, reasoning: 9.32, context: 8.86, vision: 8.46, speed: 4.58 }],\n      ["minimax-m2.1",     { overall: 9.22, coding: 8.92, reasoning: 9.20, context: 8.72, vision: 8.18, speed: 4.72 }],\n      ["minimax-m2",       { overall: 9.14, coding: 8.88, reasoning: 9.10, context: 8.64, vision: 8.00, speed: 4.86 }],\n      ["nemotron-3-super", { overall: 9.32, coding: 8.92, reasoning: 9.28, context: 8.96, vision: 7.42, speed: 4.82 }],\n      ["nemotron-3-nano",  { overall: 8.76, coding: 8.36, reasoning: 8.68, context: 8.12, vision: 6.20, speed: 7.20 }],\n      ["mistral-large-3",  { overall: 9.22, coding: 9.00, reasoning: 9.18, context: 8.82, vision: 7.82, speed: 4.32 }],\n      ["devstral-small-2", { overall: 8.98, coding: 9.42, reasoning: 8.70, context: 8.52, vision: 5.02, speed: 6.62 }],\n      ["devstral-2",       { overall: 9.18, coding: 9.74, reasoning: 8.96, context: 8.86, vision: 5.10, speed: 5.22 }],\n      ["devstral",         { overall: 8.98, coding: 9.42, reasoning: 8.72, context: 8.52, vision: 5.05, speed: 6.20 }],\n      ["gpt-oss",          { overall: 9.06, coding: 8.92, reasoning: 9.04, context: 8.62, vision: 5.10, speed: 5.90 }],\n      ["cogito-2.1",       { overall: 9.28, coding: 9.08, reasoning: 9.42, context: 8.92, vision: 6.22, speed: 3.92 }],\n      ["cogito",           { overall: 9.12, coding: 8.96, reasoning: 9.26, context: 8.76, vision: 6.02, speed: 4.20 }],\n      ["gemini-3",         { overall: 9.74, coding: 9.42, reasoning: 9.72, context: 9.46, vision: 9.82, speed: 5.12 }],\n      ["ministral-3",      { overall: 8.74, coding: 8.34, reasoning: 8.48, context: 8.22, vision: 6.22, speed: 8.24 }],\n      ["ministral",        { overall: 8.62, coding: 8.22, reasoning: 8.36, context: 8.06, vision: 6.05, speed: 8.00 }],\n      ["mistral-small",    { overall: 8.54, coding: 8.18, reasoning: 8.24, context: 7.96, vision: 5.92, speed: 8.20 }],\n      ["gemma3",           { overall: 8.58, coding: 8.22, reasoning: 8.34, context: 7.82, vision: 8.12, speed: 7.50 }],\n      ["rnj-1",            { overall: 8.32, coding: 7.96, reasoning: 8.16, context: 7.92, vision: 5.42, speed: 8.05 }],\n      ["rnj",              { overall: 8.24, coding: 7.88, reasoning: 8.08, context: 7.84, vision: 5.32, speed: 8.10 }],\n    ]);\n\n    const MODEL_TRAIT_HINTS = Object.freeze([\n      ["qwen3.5",          ["reasoning", "coding", "vision"]],\n      ["qwen3-vl",         ["vision", "reasoning", "coding"]],\n      ["qwen3-coder",      ["coding", "reasoning"]],\n      ["qwen3-next",       ["reasoning", "coding", "vision"]],\n      ["deepseek-v3.2",    ["reasoning", "coding"]],\n      ["deepseek-v3.1",    ["reasoning", "coding"]],\n      ["deepseek-r1",      ["reasoning"]],\n      ["kimi-k2.5",        ["reasoning", "coding"]],\n      ["kimi-k2",          ["reasoning", "coding"]],\n      ["glm-5",            ["reasoning", "coding", "vision"]],\n      ["glm-4",            ["reasoning", "coding", "vision"]],\n      ["gemini-3",         ["reasoning", "coding", "vision"]],\n      ["devstral",         ["coding"]],\n      ["gpt-oss",          ["reasoning", "coding"]],\n      ["nemotron-3-super", ["reasoning", "coding"]],\n      ["nemotron-3-nano",  ["reasoning"]],\n      ["mistral-large-3",  ["reasoning", "coding"]],\n      ["cogito",           ["reasoning", "coding"]],\n      ["ministral-3",      ["reasoning", "coding"]],\n      ["gemma3",           ["reasoning", "coding", "vision"]],\n    ]);\n\n    function canonicalModelKey(model) {\n      const raw = String(model || "").trim().toLowerCase();\n      if (!raw) return "";\n      const normalized = (raw.includes("/") && raw.includes(":"))\n        ? `${raw.split(":", 1)[0].split("/").slice(-1)[0]}:${raw.slice(raw.indexOf(":") + 1)}`\n        : raw;\n      if (normalized.includes(":")) {\n        const idx = normalized.indexOf(":");\n        const family = normalized.slice(0, idx);\n        let tag = normalized.slice(idx + 1);\n        if (tag.endsWith("-cloud")) tag = tag.slice(0, -6);\n        return `${family}:${tag}`.replace(/:+$/g, "");\n      }\n      return normalized.endsWith("-cloud") ? normalized.slice(0, -6) : normalized;\n    }\n\n    function modelMatchesPrefix(model, prefix) {\n      const key = canonicalModelKey(model);\n      const p = String(prefix || "").trim().toLowerCase();\n      if (!key || !p) return false;\n      return key.startsWith(p) || key.includes(p);\n    }\n\n    function getFamilyProfile(model) {\n      for (const [prefix, profile] of MODEL_FAMILY_PROFILES) {\n        if (modelMatchesPrefix(model, prefix)) return profile;\n      }\n      return FAMILY_PRIOR_DEFAULTS;\n    }\n\n    function getModelCapabilities(model) {\n      const meta = getModelMeta(model);\n      const caps = new Set(Array.isArray(meta.capabilities)\n        ? meta.capabilities.map(x => String(x || "").toLowerCase()).filter(Boolean)\n        : []);\n      const key = canonicalModelKey(model);\n\n      if (["vision", "-vl", ":vl", "gemini", "llava", "pixtral", "multimodal", "omni"].some(t => key.includes(t))) caps.add("vision");\n      if (["coder", "code", "devstral", "claude-code", "swe", "terminal"].some(t => key.includes(t))) caps.add("coding");\n      if (["thinking", "reason", "reasoning", "r1", "gpt-oss", "deepseek", "cogito", "kimi-k2", "glm-5", "glm-4.7", "glm-4.6"].some(t => key.includes(t))) caps.add("reasoning");\n      for (const [prefix, hintedCaps] of MODEL_TRAIT_HINTS) {\n        if (modelMatchesPrefix(key, prefix)) {\n          hintedCaps.forEach(cap => caps.add(cap));\n        }\n      }\n      caps.add("completion");\n      return Array.from(caps);\n    }\n\n    function clamp(value, low, high) {\n      return Math.max(low, Math.min(value, high));\n    }\n\n    function sizeQualityStrength(sizeB) {\n      if (!Number.isFinite(sizeB) || sizeB <= 0) return 4.8;\n      const normalized = Math.log2(Math.min(sizeB, 1000) + 1) / Math.log2(1001);\n      return 3.8 + normalized * 6.2;\n    }\n\n    function sizeSpeedStrength(sizeB) {\n      if (!Number.isFinite(sizeB) || sizeB <= 0) return 7.8;\n      const normalized = Math.log2(Math.min(sizeB, 1000) + 1) / Math.log2(1001);\n      return 9.8 - normalized * 7.2;\n    }\n\n    function contextStrength(ctx) {\n      if (!Number.isFinite(ctx) || ctx <= 0) return 3.2;\n      const normalized = clamp(Math.log2(ctx) / 18.0, 0.0, 1.08);\n      const bonus = ctx >= 200000 ? 0.7 : (ctx >= 128000 ? 0.35 : 0);\n      return Math.min(10.0, 3.6 + normalized * 6.0 + bonus);\n    }\n\n    function freshnessStrength(modifiedTs) {\n      if (!Number.isFinite(modifiedTs) || modifiedTs <= 0) return 4.8;\n      const ageDays = Math.max(0, (Date.now() / 1000 - modifiedTs) / 86400);\n      if (ageDays <= 21) return 10.0;\n      if (ageDays <= 45) return 9.4;\n      if (ageDays <= 90) return 8.6;\n      if (ageDays <= 180) return 7.6;\n      if (ageDays <= 365) return 6.3;\n      if (ageDays <= 540) return 5.2;\n      return 4.3;\n    }\n\n    function nameSignalBonus(model, criterion) {\n      const key = canonicalModelKey(model);\n      let bonus = 0;\n      if (criterion === "coding") {\n        if (["coder", "devstral", "terminal", "swe"].some(t => key.includes(t))) bonus += 0.90;\n        if (["code", "oss"].some(t => key.includes(t))) bonus += 0.25;\n      } else if (criterion === "reasoning") {\n        if (["thinking", "reason", "reasoning", "r1"].some(t => key.includes(t))) bonus += 0.95;\n        if (["deepseek", "cogito"].some(t => key.includes(t))) bonus += 0.20;\n      } else if (criterion === "vision") {\n        if (["-vl", ":vl", "vision", "gemini", "pixtral", "llava"].some(t => key.includes(t))) bonus += 0.95;\n      } else if (criterion === "speed") {\n        if (["flash", "nano", "mini", "small"].some(t => key.includes(t))) bonus += 1.15;\n        if (["preview"].some(t => key.includes(t))) bonus += 0.20;\n      } else if (criterion === "overall") {\n        if (["thinking", "coder", "-vl", ":vl", "vision"].some(t => key.includes(t))) bonus += 0.18;\n      }\n      return bonus;\n    }\n\n    function scoreModelForCriterion(model, criterion = "overall") {\n      const chosenCriterion = ["overall", "coding", "reasoning", "context", "vision", "speed", "newest"].includes(String(criterion || "").toLowerCase())\n        ? String(criterion || "overall").toLowerCase()\n        : "overall";\n      const profile = getFamilyProfile(model);\n      const basePrior = Number(profile[chosenCriterion] || FAMILY_PRIOR_DEFAULTS[chosenCriterion] || 7.0);\n      const sizeB = Math.max(0, Math.min(getModelSizeBillions(model) || 0, 1000));\n      const ctx = Math.max(0, getModelContextTokens(model));\n      const newest = getModelModifiedTs(model);\n      const caps = getModelCapabilities(model);\n      const sizeQuality = sizeQualityStrength(sizeB);\n      const sizeSpeed = sizeSpeedStrength(sizeB);\n      const ctxStrength = contextStrength(ctx);\n      const freshness = freshnessStrength(newest);\n      const hasReasoning = caps.includes("reasoning") ? 10 : 0;\n      const hasCoding = caps.includes("coding") ? 10 : 0;\n      const hasVision = caps.includes("vision") ? 10 : 0;\n      const bonus = nameSignalBonus(model, chosenCriterion);\n\n      switch (chosenCriterion) {\n        case "coding":\n          return basePrior * 0.56 + sizeQuality * 0.10 + ctxStrength * 0.10 + freshness * 0.05 + hasCoding * 0.14 + hasReasoning * 0.04 + bonus;\n        case "reasoning":\n          return basePrior * 0.56 + sizeQuality * 0.11 + ctxStrength * 0.06 + freshness * 0.04 + hasReasoning * 0.13 + hasCoding * 0.03 + bonus;\n        case "context":\n          return ctx > 0\n            ? (ctxStrength * 0.74 + basePrior * 0.14 + sizeQuality * 0.08 + freshness * 0.04)\n            : (basePrior * 0.22 + sizeQuality * 0.12 + freshness * 0.06);\n        case "vision":\n          return basePrior * 0.58 + sizeQuality * 0.09 + ctxStrength * 0.06 + freshness * 0.04 + hasVision * 0.18 + hasReasoning * 0.02 + bonus;\n        case "speed":\n          return basePrior * 0.15 + sizeSpeed * 0.60 + freshness * 0.10 + ctxStrength * 0.05 + ((sizeB > 0 && sizeB <= 24) ? 0.20 : 0) + bonus;\n        case "newest":\n          return newest > 0 ? newest : 0;\n        case "overall":\n        default:\n          return basePrior * 0.56 + sizeQuality * 0.12 + ctxStrength * 0.06 + freshness * 0.05 + hasReasoning * 0.08 + hasCoding * 0.06 + hasVision * 0.04 + bonus;\n      }\n    }\n\n    function sortModelsByCriterion(modelList, criterion = "overall") {\n      const models = Array.isArray(modelList) ? [...modelList].filter(Boolean) : [];\n      return models.sort((a, b) => {\n        const diff = scoreModelForCriterion(b, criterion) - scoreModelForCriterion(a, criterion);\n        if (Math.abs(diff) > 1e-9) return diff > 0 ? 1 : -1;\n        return String(a).localeCompare(String(b), "en", { sensitivity: "base" });\n      });\n    }\n\n    function getSortCriterionLabel(value) {\n      const mapping = {\n        overall: "Overall",\n        coding: "Coding",\n        reasoning: "Reasoning",\n        context: "Long Context",\n        vision: "Vision",\n        speed: "Speed",\n        newest: "Newest",\n      };\n      return mapping[value] || "Overall";\n    }\n\n    function getSavedThinkMode() {\n      try {\n        const saved = String(localStorage.getItem(THINK_MODE_KEY) || "").trim().toLowerCase();\n        return ["auto", "on", "off", "low", "medium", "high"].includes(saved) ? saved : "on";\n      } catch (_) {\n        return "on";\n      }\n    }\n\n    function saveThinkMode(value) {\n      try {\n        const normalized = String(value || "").trim().toLowerCase();\n        if (normalized) localStorage.setItem(THINK_MODE_KEY, normalized);\n      } catch (_) {}\n    }\n\n    function getThinkingSupportProfile(model) {\n      const targetModel = String(model || "").trim();\n      const key = canonicalModelKey(targetModel);\n      const caps = getModelCapabilities(targetModel);\n      const hasReasoning = caps.includes("reasoning");\n\n      if (!targetModel) {\n        return {\n          profileKey: "empty",\n          displayName: "Αναμονή μοντέλου",\n          supportedModes: ["auto", "on", "off"],\n          defaultMode: getSavedThinkMode(),\n          exact: false,\n          tone: "",\n          note: "Επίλεξε μοντέλο για να προσαρμοστούν αυτόματα οι διαθέσιμες επιλογές Thinking Mode.",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "qwen3-coder-next")) {\n        return {\n          profileKey: "qwen3-coder-next",\n          displayName: "Qwen3-Coder-Next",\n          supportedModes: ["auto", "off"],\n          defaultMode: "off",\n          exact: true,\n          tone: "",\n          note: "Official non-thinking mode only. Το μοντέλο είναι γρήγορο coding model χωρίς ξεχωριστό reasoning trace.",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "gpt-oss")) {\n        return {\n          profileKey: "gpt-oss",\n          displayName: "GPT-OSS",\n          supportedModes: ["auto", "low", "medium", "high"],\n          defaultMode: "medium",\n          exact: true,\n          tone: "",\n          note: "Official reasoning effort only: low / medium / high. Το trace δεν απενεργοποιείται πλήρως.",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "qwen3-next")) {\n        return {\n          profileKey: "qwen3-next",\n          displayName: "Qwen3-Next",\n          supportedModes: ["auto", "on", "off", "low", "medium", "high"],\n          defaultMode: "on",\n          exact: false,\n          tone: "warn",\n          note: "Thinking-capable family. Στο Ollama Cloud το hard Off μπορεί να χρειάζεται compatibility fallback, οπότε το trace κρύβεται πλήρως στο UI όταν χρειαστεί.",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "deepseek-v3.1")) {\n        return {\n          profileKey: "deepseek-v3.1",\n          displayName: "DeepSeek-V3.1",\n          supportedModes: ["auto", "on", "off"],\n          defaultMode: "on",\n          exact: true,\n          tone: "",\n          note: "Official hybrid thinking / non-thinking model. Χρησιμοποιεί boolean thinking control (think=true/false).",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "deepseek-r1")) {\n        return {\n          profileKey: "deepseek-r1",\n          displayName: "DeepSeek-R1",\n          supportedModes: ["auto", "on", "off"],\n          defaultMode: "on",\n          exact: true,\n          tone: "",\n          note: "Official thinking model με boolean thinking control (think=true/false).",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "qwen3-vl")) {\n        return {\n          profileKey: "qwen3-vl",\n          displayName: "Qwen3-VL",\n          supportedModes: ["auto", "on", "off"],\n          defaultMode: "on",\n          exact: true,\n          tone: "",\n          note: "Thinking-capable vision model. Το Off στέλνει think=false και το app κρύβει τυχόν leaked trace αν το backend το επιστρέψει.",\n        };\n      }\n\n      if (modelMatchesPrefix(key, "qwen3")) {\n        return {\n          profileKey: "qwen3",\n          displayName: "Qwen3",\n          supportedModes: ["auto", "on", "off"],\n          defaultMode: "on",\n          exact: true,\n          tone: "",\n          note: "Official thinking model με boolean thinking control (think=true/false).",\n        };\n      }\n\n      if (hasReasoning) {\n        return {\n          profileKey: "generic-reasoning",\n          displayName: "Reasoning-capable",\n          supportedModes: ["auto", "on", "off"],\n          defaultMode: "on",\n          exact: false,\n          tone: "warn",\n          note: "Το μοντέλο φαίνεται reasoning-capable από metadata/όνομα. Εφαρμόζεται ασφαλές boolean mapping μέχρι να επιβεβαιωθεί πιο ειδικό profile.",\n        };\n      }\n\n      return {\n        profileKey: "non-thinking",\n        displayName: "Non-thinking",\n        supportedModes: ["auto", "off"],\n        defaultMode: "off",\n        exact: false,\n        tone: "",\n        note: "Δεν εντοπίστηκε official thinking support για το επιλεγμένο μοντέλο. Ενεργά παραμένουν μόνο τα ασφαλή modes Auto / Off.",\n      };\n    }\n\n    function loadThinkingProfileConfirmations() {\n      try {\n        const raw = localStorage.getItem(THINK_PROFILE_CONFIRMATIONS_KEY);\n        const parsed = raw ? JSON.parse(raw) : {};\n        state.confirmedThinkingProfilesByModel = (parsed && typeof parsed === "object") ? parsed : {};\n      } catch (_) {\n        state.confirmedThinkingProfilesByModel = {};\n      }\n    }\n\n    function saveThinkingProfileConfirmations() {\n      try {\n        localStorage.setItem(\n          THINK_PROFILE_CONFIRMATIONS_KEY,\n          JSON.stringify(state.confirmedThinkingProfilesByModel && typeof state.confirmedThinkingProfilesByModel === "object"\n            ? state.confirmedThinkingProfilesByModel\n            : {})\n        );\n      } catch (_) {}\n    }\n\n    function buildThinkingProfileSignature(profile) {\n      const modes = Array.isArray(profile && profile.supportedModes) ? profile.supportedModes.join("|") : "";\n      return `${String((profile && profile.profileKey) || "")}|${modes}`;\n    }\n\n    function getConfirmedThinkingProfileRecord(model) {\n      const key = canonicalModelKey(model);\n      const records = (state.confirmedThinkingProfilesByModel && typeof state.confirmedThinkingProfilesByModel === "object")\n        ? state.confirmedThinkingProfilesByModel\n        : {};\n      return key ? (records[key] || null) : null;\n    }\n\n    function updateThinkingProfileConfirmButton(model, profile) {\n      if (!els.confirmThinkingProfileBtn) return;\n      const targetModel = String(model || "").trim();\n      const confirmed = getConfirmedThinkingProfileRecord(targetModel);\n      const currentSignature = buildThinkingProfileSignature(profile || {});\n      const isConfirmed = !!(confirmed && confirmed.signature === currentSignature);\n      els.confirmThinkingProfileBtn.disabled = !targetModel;\n      els.confirmThinkingProfileBtn.textContent = isConfirmed ? "✅ Profile Επιβεβαιώθηκε" : "✅ Επιβεβαίωση Profile";\n      els.confirmThinkingProfileBtn.title = targetModel\n        ? (isConfirmed\n            ? `Το profile για ${targetModel} έχει ήδη επιβεβαιωθεί.`\n            : `Επιβεβαίωση του detected thinking profile για ${targetModel}`)\n        : "Επίλεξε πρώτα μοντέλο για επιβεβαίωση profile.";\n      els.confirmThinkingProfileBtn.dataset.confirmed = isConfirmed ? "1" : "0";\n      els.confirmThinkingProfileBtn.classList.toggle("done", isConfirmed);\n    }\n\n    function confirmCurrentThinkingProfile() {\n      const model = getSelectedModelKey();\n      const profile = state.currentThinkingProfile || getThinkingSupportProfile(model);\n      if (!model) {\n        renderSystemNotice("Επίλεξε πρώτα μοντέλο για να επιβεβαιώσεις profile.");\n        return;\n      }\n      const key = canonicalModelKey(model);\n      state.confirmedThinkingProfilesByModel[key] = {\n        model,\n        profileKey: String((profile && profile.profileKey) || ""),\n        displayName: String((profile && profile.displayName) || ""),\n        signature: buildThinkingProfileSignature(profile || {}),\n        confirmedAt: new Date().toISOString(),\n      };\n      saveThinkingProfileConfirmations();\n      updateThinkingProfileConfirmButton(model, profile);\n      applyThinkingModeSupportForModel(model, { preferredMode: (els.thinkModeSelect && els.thinkModeSelect.value) || getSavedThinkMode() });\n      renderSystemNotice(`Επιβεβαιώθηκε το thinking profile για το μοντέλο ${model}.`);\n    }\n\n    function applyThinkingModeSupportForModel(model, options = {}) {\n      const profile = getThinkingSupportProfile(model);\n      state.currentThinkingProfile = profile;\n      if (!els.thinkModeSelect) return profile;\n\n      const labels = {\n        auto: "Auto",\n        on: "On",\n        off: "Off",\n        low: "Low",\n        medium: "Medium",\n        high: "High",\n      };\n      const allowed = new Set(Array.isArray(profile.supportedModes) ? profile.supportedModes : ["auto"]);\n      const preferredRaw = Object.prototype.hasOwnProperty.call(options, "preferredMode")\n        ? String(options.preferredMode || "")\n        : String(els.thinkModeSelect.value || getSavedThinkMode() || profile.defaultMode || "auto");\n      const preferred = preferredRaw.trim().toLowerCase();\n\n      for (const opt of Array.from(els.thinkModeSelect.options || [])) {\n        const value = String(opt.value || "").trim().toLowerCase();\n        if (!opt.dataset.baseLabel) opt.dataset.baseLabel = opt.textContent;\n        opt.textContent = opt.dataset.baseLabel;\n        opt.disabled = !allowed.has(value);\n      }\n\n      let selected = preferred;\n      if (!allowed.has(selected)) {\n        selected = String(profile.defaultMode || "").trim().toLowerCase();\n      }\n      if (!allowed.has(selected)) {\n        selected = allowed.has("auto") ? "auto" : (Array.from(allowed)[0] || "auto");\n      }\n      els.thinkModeSelect.value = selected;\n      saveThinkMode(selected);\n\n      const supportedPretty = Array.from(allowed).map(value => labels[value] || value).join(", ");\n      const adjusted = preferred && selected !== preferred\n        ? ` · προσαρμόστηκε σε <b>${labels[selected] || escapeHtml(selected)}</b>`\n        : "";\n      const confirmed = getConfirmedThinkingProfileRecord(model);\n      const confirmedMatches = !!(confirmed && confirmed.signature === buildThinkingProfileSignature(profile));\n      const confirmedHtml = confirmedMatches\n        ? `<br><span class="tiny" style="display:inline-block; margin-top:4px; color:var(--ok);">✅ Επιβεβαιωμένο profile: ${escapeHtml((confirmed && confirmed.displayName) || (profile.displayName || "Thinking"))}</span>`\n        : "";\n\n      if (els.thinkingSupportInfo) {\n        els.thinkingSupportInfo.innerHTML = `${profile.exact ? "Υποστήριξη" : "Υποστήριξη / συμβατότητα"} για <code>${escapeHtml(model || "-")}</code>: <b>${supportedPretty || "-"}</b>${adjusted}<br>${escapeHtml(profile.note || "")}${confirmedHtml}`;\n        els.thinkingSupportInfo.className = `tiny ${profile.tone === "warn" ? "warn" : "muted"}`;\n      }\n\n      updateThinkingProfileConfirmButton(model, profile);\n      els.thinkModeSelect.title = `${profile.displayName || "Thinking"} · ${profile.note || ""}`.trim();\n      return profile;\n    }\n\n    function populateModelSelect(modelList, criterionRecommended = "", preferredModel = "", options = {}) {\n      const allModels = Array.isArray(modelList) ? modelList.filter(Boolean) : [];\n      const searchText = options && Object.prototype.hasOwnProperty.call(options, "searchText")\n        ? String(options.searchText || "")\n        : String((els.modelSearchInput && els.modelSearchInput.value) || "");\n      const models = filterModelsBySearch(allModels, searchText);\n      const preferWinner = !!(options && options.preferWinner);\n      const allowSavedModel = options && Object.prototype.hasOwnProperty.call(options, "allowSavedModel")\n        ? !!options.allowSavedModel\n        : !preferWinner;\n      els.modelSelect.innerHTML = "";\n\n      if (!allModels.length) {\n        const opt = document.createElement("option");\n        opt.value = "";\n        opt.textContent = "Δεν βρέθηκαν μοντέλα";\n        els.modelSelect.appendChild(opt);\n        return [];\n      }\n\n      if (!models.length) {\n        const opt = document.createElement("option");\n        opt.value = "";\n        opt.textContent = "Καμία αντιστοίχιση στην αναζήτηση";\n        els.modelSelect.appendChild(opt);\n        return [];\n      }\n\n      for (const m of models) {\n        const opt = document.createElement("option");\n        opt.value = m;\n        opt.textContent = (criterionRecommended && m === criterionRecommended) ? `★ ${m}` : m;\n        els.modelSelect.appendChild(opt);\n      }\n\n      const saved = allowSavedModel ? getSavedModel(allModels) : null;\n      const winner = (criterionRecommended && allModels.includes(criterionRecommended)) ? criterionRecommended : "";\n      const currentValue = String(els.modelSelect.dataset.currentValue || els.modelSelect.value || "").trim();\n      const preferred = (preferWinner ? winner : "")\n        || (preferredModel && models.includes(preferredModel) ? preferredModel : "")\n        || (currentValue && models.includes(currentValue) ? currentValue : "")\n        || (saved && models.includes(saved) ? saved : "")\n        || (winner && models.includes(winner) ? winner : "")\n        || models[0] || "";\n\n      els.modelSelect.value = preferred;\n      els.modelSelect.dataset.currentValue = preferred;\n      return models;\n    }\n\n    function rebuildModelSelect(preferredModel = "", preferWinner = false) {\n      const criterion = (els.modelSortSelect && els.modelSortSelect.value) ? els.modelSortSelect.value : "overall";\n      state.modelSortCriterion = criterion;\n      const originalModels = Array.isArray(state.models) ? [...state.models] : [];\n      const sortedModels = sortModelsByCriterion(originalModels, criterion);\n      const criterionWinner = sortedModels[0] || "";\n      const chosenModel = preferWinner ? "" : (preferredModel || els.modelSelect.value || "");\n      populateModelSelect(sortedModels, criterionWinner, chosenModel, {\n        preferWinner,\n        allowSavedModel: !preferWinner,\n      });\n      updateHelperModelSelect();\n      updateModelBadges();\n      syncNumCtxInputForSelectedModel();\n      return criterionWinner;\n    }\n\n    function updateHelperModelSelect(preferredModel = "") {\n      if (!els.helperModelSelect) return [];\n      const primaryModel = getSelectedModelKey();\n      const allModels = sortModelsByCriterion(Array.isArray(state.models) ? [...state.models] : [], "overall")\n        .filter((model) => model && model !== primaryModel);\n      state.helperModels = allModels;\n      els.helperModelSelect.innerHTML = "";\n\n      if (!allModels.length) {\n        const opt = document.createElement("option");\n        opt.value = "";\n        opt.textContent = "Δεν υπάρχουν helper models";\n        els.helperModelSelect.appendChild(opt);\n        return [];\n      }\n\n      const filtered = filterModelsBySearch(allModels, (els.helperSearchInput && els.helperSearchInput.value) || "");\n      if (!filtered.length) {\n        const opt = document.createElement("option");\n        opt.value = "";\n        opt.textContent = "Καμία αντιστοίχιση στην αναζήτηση";\n        els.helperModelSelect.appendChild(opt);\n        return [];\n      }\n\n      for (const model of filtered) {\n        const opt = document.createElement("option");\n        opt.value = model;\n        opt.textContent = model;\n        els.helperModelSelect.appendChild(opt);\n      }\n\n      const saved = getSavedHelperModel(allModels);\n      const currentValue = String(els.helperModelSelect.dataset.currentValue || els.helperModelSelect.value || "").trim();\n      const preferred = (preferredModel && filtered.includes(preferredModel) ? preferredModel : "")\n        || (currentValue && filtered.includes(currentValue) ? currentValue : "")\n        || (saved && filtered.includes(saved) ? saved : "")\n        || filtered[0] || "";\n\n      els.helperModelSelect.value = preferred;\n      els.helperModelSelect.dataset.currentValue = preferred;\n      return filtered;\n    }\n\n    function refreshHelperControls(preferredModel = "") {\n      const mode = normalizeEnsembleMode((els.ensembleModeSelect && els.ensembleModeSelect.value) || state.ensembleMode || "auto");\n      state.ensembleMode = mode;\n      const manual = mode === "manual";\n      if (els.helperSearchInput) els.helperSearchInput.disabled = !manual;\n      if (els.helperModelSelect) els.helperModelSelect.disabled = !manual;\n      updateHelperModelSelect(preferredModel);\n      if (els.ensembleModeInfo) {\n        els.ensembleModeInfo.textContent = manual\n          ? "Manual: επίλεξε εσύ το δεύτερο helper model από τη λίστα. Το κύριο μοντέλο αποκλείεται αυτόματα."\n          : mode === "auto"\n            ? "Auto: το helper model επιλέγεται αυτόματα από το κύριο μοντέλο και το είδος του task."\n            : "Off: χρησιμοποιείται μόνο το κύριο μοντέλο χωρίς helper.";\n      }\n      if (!state.isStreaming && els.helperText) {\n        if (mode === "auto") {\n          els.helperText.textContent = "🤝 Dual-model ensemble auto: ON";\n        } else if (mode === "manual") {\n          const helper = String((els.helperModelSelect && els.helperModelSelect.value) || "").trim();\n          els.helperText.textContent = helper ? `🤝 Manual helper: ${helper}` : "🤝 Manual helper: επίλεξε δεύτερο μοντέλο";\n        } else {\n          els.helperText.textContent = DEFAULT_HELPER;\n        }\n      }\n    }\n\n    function updateModelBadges(data = null) {\n      const model = els.modelSelect.value || "-";\n      els.selectedModelBadge.textContent = `Μοντέλο: ${model}`;\n      if (!data) return;\n\n      const sourceText =\n        data.source === "official-online" ? "Πηγή: official direct API catalog" :\n        data.source === "stale-online-cache" ? "Πηγή: τελευταία επιτυχής official direct API λίστα" :\n        data.source === "initializing" ? "Πηγή: αρχικοποίηση" :\n        "Πηγή: σφάλμα online λίστας";\n\n      els.sourceBadge.textContent = sourceText;\n      els.sourceBadge.className   =\n        data.source === "official-online" ? "badge ok" :\n        data.last_error ? "badge warn" : "badge";\n    }\n\n    async function ensureSelectedModelMeta(model, force = false) {\n      const targetModel = String(model || "").trim();\n      if (!targetModel) return null;\n\n      const existing = getModelMeta(targetModel);\n      if (!force && existing && Number(existing.num_ctx_max || 0) >= 256 && existing.details_complete) {\n        return existing;\n      }\n      if (!force && state.modelDetailRequests[targetModel]) {\n        return state.modelDetailRequests[targetModel];\n      }\n\n      const request = (async () => {\n        try {\n          const query = `/api/model-details?model=${encodeURIComponent(targetModel)}${force ? "&force=1" : ""}`;\n          const resp = await fetch(query);\n          const data = await resp.json();\n          if (resp.ok && data && data.meta && typeof data.meta === "object") {\n            const merged = { ...(state.modelMetaByModel[targetModel] || {}), ...data.meta };\n            state.modelMetaByModel[targetModel] = merged;\n            const numCtxMax = Number(merged.num_ctx_max || 0);\n            if (Number.isFinite(numCtxMax) && numCtxMax >= 256) {\n              state.modelMaxNumCtxByModel[targetModel] = Math.trunc(numCtxMax);\n            }\n            if (targetModel === getSelectedModelKey()) {\n              syncNumCtxInputForSelectedModel();\n              applyThinkingModeSupportForModel(targetModel, { preferredMode: (els.thinkModeSelect && els.thinkModeSelect.value) || "" });\n            }\n            return merged;\n          }\n          return existing || null;\n        } catch (_) {\n          return existing || null;\n        } finally {\n          delete state.modelDetailRequests[targetModel];\n        }\n      })();\n\n      state.modelDetailRequests[targetModel] = request;\n      return request;\n    }\n\n    async function loadModels() {\n      try {\n        const currentSelection = getSelectedModelKey() || "";\n        const resp = await fetch("/api/models");\n        const data = await resp.json();\n\n        const serverModels  = Array.isArray(data.models) ? data.models.filter(Boolean) : [];\n        const modelMeta     = (data.model_meta && typeof data.model_meta === "object") ? data.model_meta : {};\n        state.lastModelsRefreshTs = Number(data.last_refresh_ts || 0) || 0;\n        state.modelMaxNumCtxByModel = {};\n        state.modelMetaByModel = {};\n        for (const [model, meta] of Object.entries(modelMeta)) {\n          const safeMeta = (meta && typeof meta === "object") ? meta : {};\n          state.modelMetaByModel[model] = safeMeta;\n          const numCtxMax = Number((safeMeta && safeMeta.num_ctx_max) || 0);\n          if (Number.isFinite(numCtxMax) && numCtxMax >= 256) {\n            state.modelMaxNumCtxByModel[model] = Math.trunc(numCtxMax);\n          }\n        }\n\n        state.models = Array.isArray(serverModels) ? [...serverModels] : [];\n        const winner = rebuildModelSelect(currentSelection, !currentSelection);\n        if (!currentSelection && winner) saveModel(winner);\n        updateModelBadges(data);\n\n        let info = `${state.models.length} μοντέλα Ollama Cloud/API · ταξινόμηση: καλύτερο → χειρότερο · πηγή: ${data.source || "-"}`;\n        if (data.refresh_in_progress) info += " · ανανέωση σε εξέλιξη";\n        if (winner && state.models.length) info += ` · 🏆 ${winner} (${getSortCriterionLabel(state.modelSortCriterion)})`;\n        if (data.models_with_context != null) info += ` · ${data.models_with_context}/${state.models.length} με Max Length metadata`;\n        if (data.last_error)  info += ` · ⚠ ${data.last_error}`;\n        if (!serverModels.length) info += " · δεν βρέθηκε online official λίστα";\n        els.modelInfo.textContent = info;\n        syncNumCtxInputForSelectedModel();\n        applyThinkingModeSupportForModel(getSelectedModelKey(), { preferredMode: getSavedThinkMode() });\n        refreshHelperControls(getSavedHelperModel(Array.isArray(state.models) ? state.models : []) || "");\n        ensureSelectedModelMeta(getSelectedModelKey());\n\n      } catch (_) {\n        state.modelMetaByModel = {};\n        state.modelMaxNumCtxByModel = {};\n        state.models = [];\n        populateModelSelect([], "", "");\n        updateHelperModelSelect();\n        updateModelBadges({ source: "error", last_error: "Αποτυχία /api/models" });\n        els.modelInfo.textContent = "Αποτυχία φόρτωσης official Ollama direct API models.";\n        syncNumCtxInputForSelectedModel();\n        applyThinkingModeSupportForModel("", { preferredMode: getSavedThinkMode() });\n      }\n    }\n\n    async function waitForModelsRefresh(previousTs = 0) {\n      const deadline = Date.now() + 45000;\n      while (Date.now() < deadline) {\n        try {\n          const resp = await fetch("/api/models");\n          const data = await resp.json();\n          const ts = Number(data.last_refresh_ts || 0) || 0;\n          if (!data.refresh_in_progress && (!previousTs || ts >= previousTs)) {\n            return data;\n          }\n        } catch (_) {}\n        await new Promise(resolve => setTimeout(resolve, MODEL_REFRESH_POLL_MS));\n      }\n      return null;\n    }\n\n    async function refreshModels(showNotice = false) {\n      try {\n        const previousTs = state.lastModelsRefreshTs || 0;\n        els.modelInfo.textContent = "Ανανέωση όλων των διαθέσιμων official Ollama direct API models...";\n        const resp = await fetch("/api/refresh-models", {\n          method: "POST",\n          headers: { "Content-Type": "application/json" },\n          body: JSON.stringify({ force: true }),\n        });\n        try {\n          const data = await resp.json();\n          if (data && data.last_refresh_ts != null) {\n            state.lastModelsRefreshTs = Number(data.last_refresh_ts || 0) || state.lastModelsRefreshTs;\n          }\n        } catch (_) {}\n        await waitForModelsRefresh(previousTs);\n        await loadModels();\n        if (showNotice) renderSystemNotice(`Ανανεώθηκαν ${state.models.length} official Ollama direct API models.`);\n      } catch (_) {\n        updateModelBadges({ source: "error", last_error: "Αποτυχία ανανέωσης" });\n        renderSystemNotice("Αποτυχία ανανέωσης official Ollama direct API models.");\n      }\n    }\n\n    // ── Session management ────────────────────────────────────────────────────\n\n    async function loadSession() {\n      try {\n        const resp = await fetch("/api/session");\n        const data = await resp.json();\n\n        els.messages.innerHTML = "";\n        state.chatHistory      = [];\n        resetReasoningPanel(true);\n\n        if (!data.history || !data.history.length) { renderEmptyState(); return; }\n\n        for (const item of data.history) {\n          createMessage(item.role, item.content, item.attachments || []);\n          state.chatHistory.push({ role: item.role, content: item.content, time: nowString() });\n        }\n      } catch (_) {\n        renderSystemNotice("Αποτυχία φόρτωσης session.");\n      }\n    }\n\n    async function clearChat() {\n      let serverOk = false;\n      let serverError = "";\n\n      try {\n        const resp = await fetch("/api/reset-chat", {\n          method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",\n        });\n        let data = {};\n        try { data = await resp.json(); } catch (_) {}\n        if (!resp.ok || data.ok === false) {\n          throw new Error((data && data.error) || `HTTP ${resp.status}`);\n        }\n        serverOk = true;\n      } catch (err) {\n        serverError = (err && err.message) ? err.message : String(err || "Άγνωστο σφάλμα");\n      }\n\n      try {\n        state.selectedFiles = [];\n        state.chatHistory   = [];\n        state.currentAssistantNode = null;\n        state.currentThinkingText = "";\n        state.reasoningStreamCompleted = false;\n        resetReasoningPanel(true);\n        renderSelectedFiles();\n        renderEmptyState();\n        if (serverOk) {\n          renderSystemNotice("Το chat και τα προσωρινά αρχεία καθαρίστηκαν.");\n        } else {\n          renderSystemNotice(`Το chat καθαρίστηκε τοπικά, αλλά ο server δεν ολοκλήρωσε πλήρως τον καθαρισμό: ${serverError}`);\n        }\n      } catch (uiErr) {\n        const uiMessage = (uiErr && uiErr.message) ? uiErr.message : String(uiErr || "Άγνωστο σφάλμα UI");\n        renderSystemNotice(`Αποτυχία καθαρισμού chat: ${uiMessage}`);\n      }\n    }\n\n    // ── Export chat ───────────────────────────────────────────────────────────\n\n    function exportChat() {\n      if (!state.chatHistory.length) {\n        renderSystemNotice("Δεν υπάρχει ιστορικό για εξαγωγή."); return;\n      }\n      const model = els.modelSelect.value || "unknown";\n      const date  = new Date().toLocaleString("el-GR");\n      let md = `# Ollama Chat Export\\n\\n**Μοντέλο:** ${model}  \\n**Ημερομηνία:** ${date}\\n\\n---\\n\\n`;\n\n      for (const item of state.chatHistory) {\n        md += `## ${item.role === "user" ? "👤 Χρήστης" : "🤖 Assistant"}`;\n        md += `  \\n*${item.time}*\\n\\n${item.content}\\n\\n---\\n\\n`;\n      }\n\n      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });\n      const url  = URL.createObjectURL(blob);\n      const a    = document.createElement("a");\n      a.href     = url;\n      a.download = `ollama-chat-${new Date().toISOString().slice(0, 10)}.md`;\n      // Append to DOM, click, then remove — required for Firefox\n      document.body.appendChild(a);\n      a.click();\n      document.body.removeChild(a);\n      URL.revokeObjectURL(url);\n    }\n\n    // ── Streaming controls ────────────────────────────────────────────────────\n\n    function setControlsDisabled(active) {\n      const controls = [\n        els.modelSearchInput, els.modelSelect, els.thinkModeSelect, els.confirmThinkingProfileBtn, els.ensembleModeSelect,\n        els.helperSearchInput, els.helperModelSelect, els.systemPrompt, els.fileInput,\n        els.refreshModelsBtn, els.clearFilesBtn, els.resetSystemPromptBtn,\n        els.copySystemPromptBtn, els.themeToggleBtn, els.clearChatBtn,\n        els.reloadSessionBtn, els.userInput, els.sendBtn,\n        els.exportChatBtn, els.autoScrollBtn,\n        els.paramTemp, els.paramTopP, els.paramSeed, els.paramNumCtx,\n        els.clearNumCtxBtn, els.resetParamsBtn,\n        els.apiKeyInput, els.saveApiKeyBtn, els.clearApiKeyBtn,\n      ];\n      for (const el of controls) if (el) el.disabled = active;\n      if (els.stopBtn) els.stopBtn.disabled = !active;\n    }\n\n    function finalizeStream(completionLabel = "") {\n      state.isStreaming = false;\n      setControlsDisabled(false);\n      refreshHelperControls();\n      if (els.stopBtn)     els.stopBtn.disabled     = true;\n      if (els.streamBadge) {\n        els.streamBadge.textContent = "Έτοιμο";\n        els.streamBadge.className   = "badge ok";\n        // Reset back to neutral after 4s\n        setTimeout(() => {\n          if (!state.isStreaming && els.streamBadge) {\n            els.streamBadge.textContent = "Έτοιμο";\n            els.streamBadge.className   = "badge";\n          }\n        }, 4000);\n      }\n      if (completionLabel && els.helperText) {\n        els.helperText.textContent = completionLabel;\n      }\n    }\n\n    function setStreamState(active, label = null) {\n      state.isStreaming           = active;\n      setControlsDisabled(active);\n      els.streamBadge.textContent = label || (active ? "Streaming..." : "Έτοιμο");\n      els.streamBadge.className   = "badge" + (active ? " warn" : "");\n    }\n\n    function stopStreaming() {\n      if (state.abortController) state.abortController.abort();\n    }\n\n    // ── Send message ──────────────────────────────────────────────────────────\n\n    async function sendMessage() {\n      if (state.isStreaming) return;\n\n      const userText     = els.userInput.value.trim();\n      const model        = els.modelSelect.value;\n      const thinkMode    = els.thinkModeSelect ? els.thinkModeSelect.value : "on";\n      const systemPrompt = els.systemPrompt.value;\n\n      if (!userText) { els.userInput.focus(); renderSystemNotice("Γράψε πρώτα το user prompt."); return; }\n      if (!model)    { renderSystemNotice("Δεν υπάρχει επιλεγμένο μοντέλο."); return; }\n\n      let attachmentsPayload = [];\n      try {\n        attachmentsPayload = await collectFilesPayload();\n      } catch (err) {\n        renderSystemNotice(`Σφάλμα αρχείων: ${err.message || err}`); return;\n      }\n\n      const optimisticAttachments = state.selectedFiles.map(f => ({\n        name: f.name,\n        kind: (f.type || "").startsWith("image/") ? "image" : "document",\n      }));\n\n      createMessage("user", userText, optimisticAttachments);\n      state.chatHistory.push({ role: "user", content: userText, time: nowString() });\n\n      els.userInput.value         = "";\n      els.charCounter.textContent = "0 χαρ. / 0 λέξεις";\n      els.charCounter.className   = "char-counter";\n      state.selectedFiles         = [];\n      els.fileInput.value         = "";\n      renderSelectedFiles();\n\n      const assistantMsg         = createMessage("assistant", "", []);\n      state.currentAssistantNode = assistantMsg.body;\n      state.abortController      = new AbortController();\n      resetReasoningPanel(true);\n      state.reasoningStreamCompleted = false;\n\n      const ensembleMode = normalizeEnsembleMode((els.ensembleModeSelect && els.ensembleModeSelect.value) || state.ensembleMode || "auto");\n      const manualHelperModel = ensembleMode === "manual"\n        ? String((els.helperModelSelect && els.helperModelSelect.value) || "").trim()\n        : "";\n      if (ensembleMode === "manual" && !manualHelperModel) {\n        renderSystemNotice("Επίλεξε helper model από τη λίστα πριν στείλεις μήνυμα.");\n        if (state.currentAssistantNode && state.currentAssistantNode.parentElement) {\n          state.currentAssistantNode.parentElement.remove();\n        }\n        state.currentAssistantNode = null;\n        state.abortController = null;\n        return;\n      }\n\n      setStreamState(true, "Streaming...");\n      els.helperText.textContent = `Αποστολή προς ${model}…`;\n      saveModel(model);   // persist model selection\n      if (manualHelperModel) saveHelperModel(manualHelperModel);\n      let completionText = "";\n\n      try {\n        const response = await fetch("/api/chat", {\n          method: "POST",\n          headers: { "Content-Type": "application/json" },\n          body: JSON.stringify({\n            model, think_mode: thinkMode, system_prompt: systemPrompt,\n            user_text: userText, attachments: attachmentsPayload,\n            options: getModelOptions(),\n            ensemble_mode: ensembleMode,\n            ensemble_helper_model: manualHelperModel,\n            ensemble_auto: ensembleMode === "auto",\n          }),\n          signal: state.abortController.signal,\n        });\n\n        if (!response.ok) {\n          let serverError = `HTTP ${response.status}`;\n          try { const d = await response.json(); if (d.error) serverError = d.error; } catch (_) {}\n          throw new Error(serverError);\n        }\n        if (!response.body) throw new Error("Η ροή απάντησης δεν είναι διαθέσιμη.");\n\n        const reader   = response.body.getReader();\n        const decoder  = new TextDecoder("utf-8");\n        let buffer       = "";\n        let finalText    = "";\n        let finalThinking = "";\n        const streamStartMs = Date.now();\n\n        while (true) {\n          const { value, done } = await reader.read();\n          if (done) break;\n\n          buffer += decoder.decode(value, { stream: true });\n          const lines = buffer.split("\\n");\n          buffer = lines.pop() || "";\n\n          for (const line of lines) {\n            if (!line.trim()) continue;\n            let payload = null;\n            try { payload = JSON.parse(line); } catch { continue; }\n\n            if (payload.type === "meta") {\n              if (payload.ensemble && payload.ensemble.enabled && payload.ensemble.helper_model && els.helperText) {\n                const roleLabel = payload.ensemble.role_label || payload.ensemble.role || "helper";\n                const reasonLabel = payload.ensemble.selection_reason ? ` · ${payload.ensemble.selection_reason}` : "";\n                els.helperText.textContent = `🤝 Ensemble: ${payload.ensemble.primary_model || model} + ${payload.ensemble.helper_model} (${roleLabel}${reasonLabel})`;\n              } else if (payload.ensemble && payload.ensemble.mode === "manual" && els.helperText) {\n                els.helperText.textContent = "🤝 Manual helper ενεργό";\n              }\n              if (payload.warnings && payload.warnings.length) {\n                renderSystemNotice(payload.warnings.join("\\n"));\n              }\n            } else if (payload.type === "thinking") {\n              state.reasoningStreamCompleted = false;\n              finalThinking += payload.content || "";\n              renderAssistantStreamingView(finalText, finalThinking, false);\n              els.streamBadge.textContent = "🧠 Thinking...";\n              showLiveTokenStats(finalThinking, streamStartMs, "Thinking");\n              scrollToBottom();\n            } else if (payload.type === "thinking_done") {\n              state.reasoningStreamCompleted = true;\n              if (finalThinking.trim()) {\n                updateReasoningPanel(finalThinking, true, false);\n              }\n            } else if (payload.type === "delta") {\n              finalText += payload.content || "";\n              renderAssistantStreamingView(finalText, finalThinking, false);\n              if (!finalText.length && finalThinking.length) {\n                els.streamBadge.textContent = "🧠 Thinking...";\n                showLiveTokenStats(finalThinking, streamStartMs, "Thinking");\n              } else {\n                els.streamBadge.textContent = "✍️ Generating...";\n                showLiveTokenStats(finalText, streamStartMs, "Generating");\n              }\n              scrollToBottom();\n            } else if (payload.type === "error") {\n              throw new Error(payload.error || "Άγνωστο σφάλμα.");\n            } else if (payload.type === "done") {\n              if (payload.elapsed_sec != null) {\n                completionText = `✅ ${payload.elapsed_sec.toFixed(2)}s`;\n              }\n              if (payload.token_stats) {\n                showTokenStats(payload.token_stats);\n                const realTps = Number(payload.token_stats.tokens_per_sec || 0);\n                if (payload.elapsed_sec != null) {\n                  completionText += ` · ⚡ ${realTps.toFixed(1)} tok/s`;\n                }\n                els.streamBadge.textContent = `⚡ ${realTps.toFixed(1)} tok/s`;\n                els.streamBadge.className = "badge ok";\n              }\n              finalizeStream(completionText);\n            }\n          }\n        }\n\n        const displayText = finalThinking.trim()\n          ? composeDisplayContent(finalText, finalThinking)\n          : finalText;\n\n        if (!finalText.trim() && !finalThinking.trim()) {\n          renderMessageContent(\n            state.currentAssistantNode,\n            "Δεν επιστράφηκε κείμενο. Έλεγξε το API key από το GUI/settings file και αν το μοντέλο είναι διαθέσιμο στο direct cloud catalog."\n          );\n          resetReasoningPanel(true);\n        } else {\n          renderAssistantStreamingView(finalText, finalThinking, true);\n          state.chatHistory.push({ role: "assistant", content: displayText, time: nowString() });\n        }\n\n      } catch (err) {\n        const errText = err && err.name === "AbortError"\n          ? "Η ροή σταμάτησε από τον χρήστη."\n          : `Σφάλμα: ${err && err.message ? err.message : String(err)}`;\n        renderMessageContent(state.currentAssistantNode, errText);\n        resetReasoningPanel(true);\n        renderSystemNotice(errText);\n      } finally {\n        state.currentAssistantNode = null;\n        state.abortController      = null;\n        finalizeStream(completionText);\n      }\n    }\n\n    function generateBrowserSessionId() {\n      try {\n        if (window.crypto && typeof window.crypto.randomUUID === "function") {\n          return window.crypto.randomUUID();\n        }\n      } catch (_) {}\n      return `browser_${Date.now()}_${Math.random().toString(16).slice(2)}`;\n    }\n\n    function getOrCreateBrowserSessionId() {\n      try {\n        const saved = sessionStorage.getItem(BROWSER_SESSION_KEY);\n        if (saved) return saved;\n        const created = generateBrowserSessionId();\n        sessionStorage.setItem(BROWSER_SESSION_KEY, created);\n        return created;\n      } catch (_) {\n        return generateBrowserSessionId();\n      }\n    }\n\n    function postBrowserLifecycle(eventName, useBeacon = false) {\n      const sessionId = String(state.browserSessionId || "").trim();\n      if (!sessionId) return;\n      const payload = JSON.stringify({ session_id: sessionId, event: eventName });\n      if (useBeacon && navigator.sendBeacon) {\n        try {\n          const blob = new Blob([payload], { type: "application/json" });\n          navigator.sendBeacon("/api/browser-session", blob);\n          return;\n        } catch (_) {}\n      }\n      fetch("/api/browser-session", {\n        method: "POST",\n        headers: { "Content-Type": "application/json" },\n        body: payload,\n        keepalive: true,\n      }).catch(() => {});\n    }\n\n    function startBrowserHeartbeat() {\n      if (state.browserHeartbeatTimer) {\n        clearInterval(state.browserHeartbeatTimer);\n      }\n      state.browserHeartbeatTimer = setInterval(() => {\n        postBrowserLifecycle("heartbeat", false);\n      }, BROWSER_HEARTBEAT_MS);\n    }\n\n    function setupBrowserLifecycle() {\n      state.browserSessionId = getOrCreateBrowserSessionId();\n      postBrowserLifecycle("open", false);\n      startBrowserHeartbeat();\n      window.addEventListener("pageshow", () => postBrowserLifecycle("open", false));\n      window.addEventListener("pagehide", () => postBrowserLifecycle("close", true));\n      window.addEventListener("beforeunload", () => postBrowserLifecycle("close", true));\n      document.addEventListener("visibilitychange", () => {\n        if (document.visibilityState === "visible") {\n          postBrowserLifecycle("heartbeat", false);\n        }\n      });\n    }\n\n    // ── Theme ─────────────────────────────────────────────────────────────────\n\n    function getSavedTheme() {\n      try { const t = localStorage.getItem(THEME_KEY); return t === "light" ? "light" : "dark"; }\n      catch { return "dark"; }\n    }\n\n    function switchPrismTheme(theme) {\n      const dark  = document.getElementById("prismDark");\n      const light = document.getElementById("prismLight");\n      if (!dark || !light) return;\n      if (theme === "light") {\n        dark.disabled  = true;\n        light.disabled = false;\n      } else {\n        light.disabled = true;\n        dark.disabled  = false;\n      }\n      // Re-highlight ολόκληρη η σελίδα μετά το CSS swap\n      requestAnimationFrame(() => {\n        if (window.Prism) {\n          document.querySelectorAll(".code-pre code[class*=\'language-\']").forEach(node => {\n            try { Prism.highlightElement(node); } catch (_) {}\n          });\n        }\n      });\n    }\n\n    function applyTheme(theme) {\n      state.theme = theme === "light" ? "light" : "dark";\n      document.documentElement.setAttribute("data-theme", state.theme);\n      try { localStorage.setItem(THEME_KEY, state.theme); } catch (_) {}\n      els.themeToggleBtn.textContent = state.theme === "light" ? "🌙 Dark Theme" : "☀️ Light Theme";\n      switchPrismTheme(state.theme);\n    }\n\n    function toggleTheme() {\n      applyTheme(state.theme === "light" ? "dark" : "light");\n    }\n\n    // ── System prompt helpers ─────────────────────────────────────────────────\n\n    function resetSystemPrompt() {\n      els.systemPrompt.value = DEFAULT_SYSTEM_PROMPT;\n      renderSystemNotice("System prompt επανήλθε στην προεπιλογή.");\n    }\n\n    async function copySystemPrompt() {\n      try {\n        await navigator.clipboard.writeText(els.systemPrompt.value || "");\n        renderSystemNotice("System prompt αντιγράφηκε στο clipboard.");\n      } catch {\n        renderSystemNotice("Αποτυχία αντιγραφής.");\n      }\n    }\n\n    // ── Auto-scroll ───────────────────────────────────────────────────────────\n\n    function toggleAutoScroll() {\n      state.autoScroll = !state.autoScroll;\n      els.autoScrollBtn.textContent = `📜 Auto-Scroll: ${state.autoScroll ? "ON" : "OFF"}`;\n      els.autoScrollBtn.style.opacity = state.autoScroll ? "1" : "0.6";\n      updateScrollToBottomBtn();\n      if (state.autoScroll) scrollToBottom(true);\n    }\n\n    // ── Char counter ──────────────────────────────────────────────────────────\n\n    function updateCharCounter() {\n      const text  = els.userInput.value;\n      const chars = text.length;\n      const words = countWords(text);\n      els.charCounter.textContent = `${chars.toLocaleString("el-GR")} χαρ. / ${words} λέξεις`;\n      els.charCounter.className   = `char-counter${chars > CHAR_WARN ? " warn" : ""}`;\n    }\n\n    // ── Event listeners ───────────────────────────────────────────────────────\n\n    els.fileInput.addEventListener("change", (e) => addFiles(e.target.files));\n\n    els.sendBtn.addEventListener("click",              sendMessage);\n    els.stopBtn.addEventListener("click",              stopStreaming);\n    els.resetSystemPromptBtn.addEventListener("click", resetSystemPrompt);\n    els.copySystemPromptBtn.addEventListener("click",  copySystemPrompt);\n    els.themeToggleBtn.addEventListener("click",       toggleTheme);\n    els.exportChatBtn.addEventListener("click",        exportChat);\n    els.autoScrollBtn.addEventListener("click",        toggleAutoScroll);\n    els.scrollToBottomBtn.addEventListener("click",    () => scrollToBottom(true));\n    els.resetParamsBtn.addEventListener("click",       resetParams);\n    els.clearFilesBtn.addEventListener("click", () => {\n      state.selectedFiles = []; els.fileInput.value = ""; renderSelectedFiles();\n    });\n    els.clearChatBtn.addEventListener("click",    clearChat);\n    els.reloadSessionBtn.addEventListener("click", loadSession);\n    if (els.toggleReasoningBtn) {\n      els.toggleReasoningBtn.addEventListener("click", () => {\n        const hasContent = Boolean(((els.reasoningContent && els.reasoningContent.textContent) || "").trim());\n        const currentlyVisible = hasContent && (state.reasoningPanelVisible || (state.reasoningAutoOpen && !state.reasoningUserCollapsed));\n        if (currentlyVisible) {\n          state.reasoningPanelVisible = false;\n          state.reasoningAutoOpen = false;\n          state.reasoningUserCollapsed = true;\n        } else {\n          state.reasoningPanelVisible = true;\n          state.reasoningAutoOpen = false;\n          state.reasoningUserCollapsed = false;\n        }\n        applyReasoningPanelVisibility();\n      });\n    }\n    if (els.saveApiKeyBtn) els.saveApiKeyBtn.addEventListener("click", saveApiKey);\n    if (els.clearApiKeyBtn) els.clearApiKeyBtn.addEventListener("click", clearApiKey);\n    if (els.apiKeyInput) {\n      els.apiKeyInput.addEventListener("keydown", (e) => {\n        if (e.key === "Enter") { e.preventDefault(); saveApiKey(); }\n      });\n    }\n    els.refreshModelsBtn.addEventListener("click", () => refreshModels(true));\n    if (els.modelSortSelect) {\n      els.modelSortSelect.addEventListener("change", () => {\n        state.modelSortCriterion = els.modelSortSelect.value || "overall";\n        saveSortCriterion(state.modelSortCriterion);\n        const winner = rebuildModelSelect("", true);\n        if (winner) saveModel(winner);\n        applyThinkingModeSupportForModel(getSelectedModelKey(), { preferredMode: getSavedThinkMode() });\n        let info = `${state.models.length} μοντέλα Ollama Cloud/API · ταξινόμηση: καλύτερο → χειρότερο`;\n        if (winner) info += ` · 🏆 ${winner} (${getSortCriterionLabel(state.modelSortCriterion)})`;\n        els.modelInfo.textContent = info;\n      });\n    }\n    if (els.modelSearchInput) {\n      els.modelSearchInput.addEventListener("input", () => {\n        const previous = String(els.modelSelect.value || "").trim();\n        populateModelSelect(sortModelsByCriterion(Array.isArray(state.models) ? [...state.models] : [], state.modelSortCriterion), "", previous, {\n          preferWinner: false,\n          allowSavedModel: true,\n          searchText: els.modelSearchInput.value,\n        });\n        updateModelBadges();\n      });\n      els.modelSearchInput.addEventListener("keydown", (e) => {\n        if (e.key === "Enter" && els.modelSelect && els.modelSelect.options.length > 0) {\n          e.preventDefault();\n          const first = els.modelSelect.options[0];\n          if (first && first.value) {\n            els.modelSelect.value = first.value;\n            els.modelSelect.dataset.currentValue = first.value;\n            saveModel(first.value);\n            updateModelBadges();\n            syncNumCtxInputForSelectedModel();\n            applyThinkingModeSupportForModel(first.value, { preferredMode: getSavedThinkMode() });\n            ensureSelectedModelMeta(first.value);\n            refreshHelperControls();\n          }\n        }\n      });\n    }\n    if (els.thinkModeSelect) {\n      els.thinkModeSelect.addEventListener("change", () => {\n        saveThinkMode(els.thinkModeSelect.value || "auto");\n        applyThinkingModeSupportForModel(getSelectedModelKey(), { preferredMode: els.thinkModeSelect.value || "auto" });\n      });\n    }\n    if (els.confirmThinkingProfileBtn) {\n      els.confirmThinkingProfileBtn.addEventListener("click", confirmCurrentThinkingProfile);\n    }\n    if (els.ensembleModeSelect) {\n      els.ensembleModeSelect.addEventListener("change", () => {\n        const mode = normalizeEnsembleMode(els.ensembleModeSelect.value);\n        els.ensembleModeSelect.value = mode;\n        saveEnsembleMode(mode);\n        refreshHelperControls();\n      });\n    }\n    if (els.helperSearchInput) {\n      els.helperSearchInput.addEventListener("input", () => {\n        updateHelperModelSelect();\n      });\n    }\n    if (els.helperModelSelect) {\n      els.helperModelSelect.addEventListener("change", () => {\n        const helper = String(els.helperModelSelect.value || "").trim();\n        els.helperModelSelect.dataset.currentValue = helper;\n        saveHelperModel(helper);\n        if (!state.isStreaming && state.ensembleMode === "manual" && els.helperText) {\n          els.helperText.textContent = helper ? `🤝 Manual helper: ${helper}` : "🤝 Manual helper: επίλεξε δεύτερο μοντέλο";\n        }\n      });\n    }\n    els.modelSelect.addEventListener("change", () => {\n      const selectedModel = String(els.modelSelect.value || "").trim();\n      els.modelSelect.dataset.currentValue = selectedModel;\n      updateModelBadges();\n      saveModel(selectedModel);\n      syncNumCtxInputForSelectedModel();\n      applyThinkingModeSupportForModel(selectedModel, { preferredMode: els.thinkModeSelect ? els.thinkModeSelect.value : getSavedThinkMode() });\n      ensureSelectedModelMeta(selectedModel);\n      refreshHelperControls();\n      if (selectedModel && els.modelSearchInput) {\n        els.modelSearchInput.blur();\n      }\n      if (els.modelSelect) {\n        els.modelSelect.blur();\n      }\n    });\n\n    // Char counter + focus reset\n    els.userInput.addEventListener("input", updateCharCounter);\n    els.userInput.addEventListener("focus", () => {\n      if (!state.isStreaming) els.helperText.textContent = DEFAULT_HELPER;\n    });\n\n    // Keyboard shortcuts: Enter = send, Shift+Enter = newline, Ctrl+Enter = send\n    els.userInput.addEventListener("keydown", (e) => {\n      const send = (e.key === "Enter" && !e.shiftKey) || (e.key === "Enter" && e.ctrlKey);\n      if (send) { e.preventDefault(); sendMessage(); }\n    });\n\n    // Scroll-to-bottom button visibility\n    els.messages.addEventListener("scroll", updateScrollToBottomBtn);\n\n    // ── Initialisation ────────────────────────────────────────────────────────\n\n    applyTheme(getSavedTheme());\n    if (els.modelSortSelect) {\n      els.modelSortSelect.value = getSavedSortCriterion();\n      state.modelSortCriterion = els.modelSortSelect.value || "overall";\n    }\n    state.ensembleMode = getSavedEnsembleMode();\n    if (els.ensembleModeSelect) {\n      els.ensembleModeSelect.value = state.ensembleMode;\n    }\n    loadParams();\n    loadThinkingProfileConfirmations();\n    if (els.thinkModeSelect) {\n      els.thinkModeSelect.value = getSavedThinkMode();\n    }\n    applyThinkingModeSupportForModel("", { preferredMode: getSavedThinkMode() });\n    applyReasoningPanelVisibility();\n    setupBrowserLifecycle();\n    loadAppConfig();\n    loadModels().finally(() => {\n      refreshHelperControls(getSavedHelperModel(Array.isArray(state.models) ? state.models : []) || "");\n    });\n    loadSession();\n    renderSystemNotice("🔄 Αυτόματη ανανέωση official direct API models σε εξέλιξη…");\n    // Cloud API health — immediate check + polling\n    pollBackendHealth();\n    setInterval(pollBackendHealth, HEALTH_POLL_MS);\n\n    // Αν η online απογραφή ολοκληρωθεί μετά το πρώτο paint, ενημέρωσε το dropdown αυτόματα και ενημέρωσε τον χρήστη.\n    (function pollForOnlineModels() {\n      let attempts = 0;\n      let announced = false;\n      const MAX_ATTEMPTS = 30; // 30 × 3s = 90s\n      const timer = setInterval(async () => {\n        attempts++;\n        try {\n          const resp = await fetch("/api/models");\n          const data = await resp.json();\n          if (data.source === "official-online") {\n            clearInterval(timer);\n            await loadModels();\n            announced = true;\n            renderSystemNotice(`✅ Αυτόματο Refresh Models: βρέθηκαν ${data.models?.length || 0} official direct API models.`);\n          } else if (!data.refresh_in_progress && data.last_error) {\n            clearInterval(timer);\n            announced = true;\n            await loadModels();\n            renderSystemNotice(`❌ Αποτυχία αυτόματης ανανέωσης official direct API models: ${data.last_error}`);\n          }\n        } catch (_) {}\n        if (attempts >= MAX_ATTEMPTS) {\n          clearInterval(timer);\n          if (!announced) {\n            renderSystemNotice("⚠ Δεν ολοκληρώθηκε έγκαιρα η αυτόματη ανανέωση official direct API models.");\n          }\n        }\n      }, 3000);\n    })();\n  </script>\n</body>\n</html>'
    html_doc = html_doc.replace('__APP_TITLE__', html.escape(APP_TITLE)).replace('__SYSTEM_PROMPT__', html.escape(system_prompt)).replace('__DEFAULT_SYSTEM_PROMPT_JSON__', safe_prompt_json).replace('__ACCEPTED_TYPES__', accepted_types)
    return html_doc

class AppHandler(BaseHTTPRequestHandler):
    """HTTP request handler της εφαρμογής.

Συγκεντρώνει τη λογική των GET και POST endpoints που εξυπηρετούν το frontend, τα uploads και το chat."""
    server_version = 'OllamaCloudChat/5.0'

    def log_message(self, format: str, *args) -> None:
        """Υλοποιεί το βήμα «log_message» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: format."""
        return

    def do_GET(self) -> None:
        """Υλοποιεί το βήμα «do_GET» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        try:
            self._handle_GET()
        except Exception as exc:
            if is_client_disconnect_error(exc):
                return
            log.error('Unexpected GET error: %s', exc)
            try:
                json_response(self, {'error': 'Internal server error'}, status=500)
            except Exception:
                pass

    def _handle_GET(self) -> None:
        """Υλοποιεί το βήμα «_handle_GET» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        if self.path == '/' or self.path.startswith('/?'):
            body = serve_index_html().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/startup':
            body = serve_startup_html().encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == '/startup-events':
            q = STARTUP.subscribe()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('X-Accel-Buffering', 'no')
            _send_security_headers(self)
            self.end_headers()
            try:
                while True:
                    try:
                        event = q.get(timeout=20)
                        data = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f'data: {data}\n\n'.encode('utf-8'))
                        self.wfile.flush()
                        if event.get('level') == 'READY':
                            break
                    except _queue.Empty:
                        self.wfile.write(b': keepalive\n\n')
                        self.wfile.flush()
            except Exception:
                pass
            finally:
                STARTUP.unsubscribe(q)
            return
        if self.path.startswith('/generated-code/'):
            ensure_generated_code_dir()
            requested_name = urllib.parse.unquote(self.path.split('?', 1)[0][len('/generated-code/'):])
            safe_name = Path(requested_name).name
            file_path = (GENERATED_CODE_DIR / safe_name).resolve()
            generated_root = str(GENERATED_CODE_DIR.resolve()) + os.sep
            if not safe_name or not str(file_path).startswith(generated_root) or (not file_path.exists()) or (not file_path.is_file()):
                json_response(self, {'error': 'Το ζητούμενο generated .py αρχείο δεν βρέθηκε.'}, status=404)
                return
            raw = file_path.read_bytes()
            download_name = extract_original_generated_filename(safe_name)
            self.send_response(200)
            self.send_header('Content-Type', 'text/x-python; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Content-Disposition', f'attachment; filename="{download_name}"')
            self.send_header('Cache-Control', 'no-store')
            _send_security_headers(self)
            self.end_headers()
            self.wfile.write(raw)
            return
        if self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        if self.path == '/api/models':
            with REGISTRY.lock:
                no_models = not REGISTRY.models
                in_progress = REGISTRY.refresh_in_progress
            if no_models and in_progress:
                wait_for_model_refresh(timeout=60.0)
            elif no_models:
                refresh_models(force=True, wait_if_running=True)
            json_response(self, REGISTRY.as_dict())
            return
        if self.path.startswith('/api/model-details'):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query or '')
            model = normalize_model_name(str((query.get('model') or [''])[0]).strip())
            force = str((query.get('force') or [''])[0]).strip().lower() in {'1', 'true', 'yes', 'on'}
            if not model:
                json_response(self, {'error': 'Δεν δόθηκε μοντέλο για metadata.'}, status=400)
                return
            meta = get_or_fetch_model_meta(model, force=force)
            if not meta:
                json_response(self, {'error': f'Δεν βρέθηκαν metadata για το μοντέλο {model}.'}, status=404)
                return
            json_response(self, {'model': model, 'meta': meta})
            return
        if self.path == '/api/session':
            json_response(self, {'history': get_history_payload()})
            return
        if self.path == '/api/app-config':
            payload = APP_CONFIG.as_public_dict()
            payload['api_key_source'] = get_ollama_api_key_source()
            payload['config_path'] = str(APP_CONFIG_FILE)
            json_response(self, payload)
            return
        if self.path == '/api/health':
            configured = is_direct_cloud_api_configured()
            json_response(self, {'status': 'ok' if configured else 'unavailable', 'mode': 'direct-cloud', 'cloud_api_configured': configured, 'api_key_source': get_ollama_api_key_source(), 'server_uptime_sec': round(time.time() - _SERVER_START_TIME, 1)}, status=200 if configured else 503)
            return
        json_response(self, {'error': 'Not found'}, status=404)

    def do_POST(self) -> None:
        """Υλοποιεί το βήμα «do_POST» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        try:
            self._handle_POST()
        except Exception as exc:
            if is_client_disconnect_error(exc):
                return
            log.exception('Unexpected POST error: %s', exc)
            try:
                json_response(self, {'error': 'Internal server error'}, status=500)
            except Exception:
                pass

    def _handle_POST(self) -> None:
        """Υλοποιεί το βήμα «_handle_POST» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        if self.path == '/api/browser-session':
            payload = safe_read_json(self)
            if payload.get('__error__') == 'request_too_large':
                json_response(self, {'error': 'Αίτημα πολύ μεγάλο.'}, status=413)
                return
            session_id = str(payload.get('session_id', '') or '').strip()[:128]
            event_name = str(payload.get('event', 'heartbeat') or 'heartbeat').strip().lower()
            if session_id:
                if event_name in {'open', 'heartbeat', 'visible', 'focus'}:
                    BROWSER_MONITOR.touch(session_id)
                elif event_name in {'close', 'hidden', 'blur'}:
                    BROWSER_MONITOR.close(session_id)
            json_response(self, {'ok': True, 'active_sessions': BROWSER_MONITOR.active_count()})
            return
        if self.path == '/api/refresh-models':
            payload = safe_read_json(self)
            if payload.get('__error__') == 'request_too_large':
                json_response(self, {'error': 'Αίτημα πολύ μεγάλο.'}, status=413)
                return
            refresh_models(force=bool(payload.get('force', True)), wait_if_running=True)
            json_response(self, REGISTRY.as_dict())
            return
        if self.path == '/api/reset-chat':
            try:
                SESSION.reset()
                json_response(self, {'ok': True})
            except Exception as exc:
                json_response(self, {'error': f'Αποτυχία εκκαθάρισης session: {exc}'}, status=500)
            return
        if self.path == '/api/app-config':
            payload = safe_read_json(self)
            if payload.get('__error__') == 'request_too_large':
                json_response(self, {'error': 'Αίτημα πολύ μεγάλο.'}, status=413)
                return
            try:
                key = str(payload.get('ollama_api_key', '') or '')
                config = save_app_config_to_disk(key)
                json_response(self, {'ok': True, 'config': config.as_public_dict(), 'config_path': str(APP_CONFIG_FILE)})
            except Exception as exc:
                json_response(self, {'error': f'Αποτυχία αποθήκευσης settings file: {exc}'}, status=500)
            return
        if self.path == '/api/execute-python':
            payload = safe_read_json(self)
            if payload.get('__error__') == 'request_too_large':
                json_response(self, {'error': 'Αίτημα πολύ μεγάλο.'}, status=413)
                return
            code_text = str(payload.get('code', '') or '')
            suggested_filename = str(payload.get('filename', '') or '')
            ok, message = launch_python_code_in_terminal(code_text, suggested_filename=suggested_filename)
            json_response(self, {'ok': ok, 'message': message} if ok else {'error': message}, status=200 if ok else 400)
            return
        if self.path == '/api/export-python-block':
            payload = safe_read_json(self)
            if payload.get('__error__') == 'request_too_large':
                json_response(self, {'error': 'Αίτημα πολύ μεγάλο.'}, status=413)
                return
            code_text = str(payload.get('code', '') or '')
            suggested_filename = str(payload.get('filename', '') or '')
            try:
                file_info = save_generated_python_file(code_text, suggested_filename=suggested_filename)
                json_response(self, {'ok': True, 'file': file_info})
            except Exception as exc:
                json_response(self, {'error': f'Αποτυχία δημιουργίας .py αρχείου: {exc}'}, status=400)
            return
        if self.path == '/api/chat':
            payload = safe_read_json(self)
            if payload.get('__error__') == 'request_too_large':
                json_response(self, {'error': 'Το αίτημα είναι πολύ μεγάλο. Μείωσε αριθμό ή μέγεθος αρχείων.'}, status=413)
                return
            model = normalize_model_name(str(payload.get('model', '')).strip())
            gui_system_prompt = str(payload.get('system_prompt', ''))
            think_mode = payload.get('think_mode', 'on')
            ensemble_mode_raw = str(payload.get('ensemble_mode', '') or '').strip().lower()
            if ensemble_mode_raw not in {'off', 'auto', 'manual'}:
                ensemble_mode_raw = 'auto' if bool(payload.get('ensemble_auto', True)) else 'off'
            ensemble_auto = ensemble_mode_raw == 'auto'
            ensemble_helper_model = normalize_model_name(str(payload.get('ensemble_helper_model', '') or '').strip())
            system_prompt, system_prompt_source = get_effective_system_prompt(gui_system_prompt)
            user_text = str(payload.get('user_text', '')).strip()
            attachments = payload.get('attachments', [])
            raw_opts = payload.get('options', {}) or {}
            model_options: Dict = {}
            try:
                temperature = float(raw_opts.get('temperature', -1))
                if 0.0 <= temperature <= 2.0:
                    model_options['temperature'] = temperature
            except (TypeError, ValueError):
                pass
            try:
                top_p = float(raw_opts.get('top_p', -1))
                if 0.0 < top_p <= 1.0:
                    model_options['top_p'] = top_p
            except (TypeError, ValueError):
                pass
            try:
                seed = int(raw_opts.get('seed', -1))
                if seed >= 0:
                    model_options['seed'] = seed
            except (TypeError, ValueError):
                pass
            try:
                num_ctx = int(raw_opts.get('num_ctx', 0))
                if 256 <= num_ctx <= 1048576:
                    model_options['num_ctx'] = num_ctx
            except (TypeError, ValueError):
                pass
            if not model:
                json_response(self, {'error': 'Δεν δόθηκε μοντέλο.'}, status=400)
                return
            if not user_text:
                json_response(self, {'error': 'Το user prompt πρέπει να δοθεί από εσένα.'}, status=400)
                return
            if attachments and (not isinstance(attachments, list)):
                json_response(self, {'error': 'Μη έγκυρα attachments.'}, status=400)
                return
            try:
                processed_attachments, warnings = prepare_attachments(attachments, model)
            except (ValueError, OSError, AttributeError, TypeError) as exc:
                json_response(self, {'error': str(exc)}, status=400)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            _send_security_headers(self)
            self.end_headers()
            start_time = time.time()
            try:
                prepared_user_content = build_user_message_content(user_text, processed_attachments)
                user_message: Dict = {'role': 'user', 'content': prepared_user_content}
                image_b64_list: List[str] = []
                for item in processed_attachments:
                    if item['kind'] == 'image' and item['will_send_as_image']:
                        try:
                            raw_bytes = Path(item['path']).read_bytes()
                            image_b64_list.append(base64.b64encode(raw_bytes).decode('ascii'))
                        except Exception as img_exc:
                            log.warning('Αδυναμία ανάγνωσης εικόνας %s: %s', item.get('name'), img_exc)
                if image_b64_list:
                    user_message['images'] = image_b64_list
                history_user_item: Dict = {'role': 'user', 'content': user_text, 'attachments': [{'name': item['name'], 'kind': item['kind']} for item in processed_attachments]}
                with SESSION.lock:
                    session_messages = list(SESSION.messages)
                    messages = build_messages(system_prompt, session_messages + [user_message])
                if not is_direct_cloud_api_configured():
                    raise RuntimeError("Λείπει το Ollama Cloud API key. Η εφαρμογή τρέχει μόνο σε direct Ollama Cloud API mode. Βάλ'το στο πεδίο API Key του GUI, στο settings file ή στο OLLAMA_API_KEY.")
                ensemble_info: Optional[Dict[str, object]] = None
                final_messages = list(messages)
                if ensemble_mode_raw == 'auto':
                    try:
                        ensemble_info = choose_auto_ensemble_helper(model, user_text, processed_attachments)
                    except Exception as ensemble_pick_exc:
                        log.warning('Αποτυχία επιλογής helper model για ensemble: %s', ensemble_pick_exc)
                        ensemble_info = None
                elif ensemble_mode_raw == 'manual':
                    try:
                        ensemble_info = choose_manual_ensemble_helper(model, ensemble_helper_model, user_text, processed_attachments)
                    except Exception as ensemble_pick_exc:
                        log.warning('Αποτυχία manual helper model για ensemble: %s', ensemble_pick_exc)
                        ensemble_info = None
                stream_json_line(self, {'type': 'meta', 'warnings': warnings, 'attachments': history_user_item['attachments'], 'system_prompt_source': system_prompt_source, 'ensemble': {'enabled': bool(ensemble_info), 'mode': ensemble_mode_raw, 'primary_model': model, 'helper_model': str((ensemble_info or {}).get('helper_model') or ''), 'criterion': str((ensemble_info or {}).get('criterion') or ''), 'role': str((ensemble_info or {}).get('role') or ''), 'role_label': str((ensemble_info or {}).get('role_label') or ''), 'selection_reason': str((ensemble_info or {}).get('selection_reason') or '')}})
                if ensemble_info:
                    helper_model = str(ensemble_info.get('helper_model') or '').strip()
                    helper_role = str(ensemble_info.get('role') or 'cross-checker').strip()
                    helper_meta = {}
                    with REGISTRY.lock:
                        helper_meta = copy.deepcopy(REGISTRY.model_meta.get(helper_model, {}))
                    helper_system = build_helper_system_prompt(model, helper_model, helper_role, dict(ensemble_info.get('traits') or {}))
                    helper_messages = insert_secondary_system_message(messages, helper_system)
                    helper_options = dict(model_options) if model_options else {}
                    if float(helper_options.get('temperature', 0.2) or 0.2) > 0.35:
                        helper_options['temperature'] = 0.2
                    helper_max_ctx = get_model_context_tokens(helper_model, helper_meta)
                    try:
                        requested_ctx = int(helper_options.get('num_ctx') or 0)
                    except Exception:
                        requested_ctx = 0
                    if requested_ctx > 0 and helper_max_ctx > 0:
                        helper_options['num_ctx'] = min(requested_ctx, helper_max_ctx)
                    helper_num_predict = int(_ENSEMBLE_HELPER_MAX_TOKENS_BY_ROLE.get(helper_role, 160) or 160)
                    try:
                        current_num_predict = int(helper_options.get('num_predict') or 0)
                    except Exception:
                        current_num_predict = 0
                    if current_num_predict > 0:
                        helper_options['num_predict'] = min(current_num_predict, helper_num_predict)
                    else:
                        helper_options['num_predict'] = helper_num_predict
                    helper_timeout = int(_ENSEMBLE_HELPER_TIMEOUT_BY_ROLE.get(helper_role, 90) or 90)
                    stream_json_line(self, {'type': 'meta', 'status': f'🤝 Συμβουλεύομαι helper model {helper_model}…'})
                    helper_think_value = None
                    try:
                        helper_result = direct_cloud_chat_complete(model=helper_model, messages=helper_messages, model_options=helper_options if helper_options else None, think_value=helper_think_value, timeout=helper_timeout)
                        helper_text = str(helper_result.get('content') or '').strip()
                        if not helper_text:
                            helper_text = str(helper_result.get('thinking') or '').strip()
                        if helper_text:
                            final_messages = insert_secondary_system_message(messages, build_main_ensemble_guidance(helper_model, helper_role, helper_text))
                            stream_json_line(self, {'type': 'meta', 'status': f'✅ Έτοιμο το helper guidance από {helper_model}. Ξεκινά το κύριο μοντέλο…'})
                        else:
                            stream_json_line(self, {'type': 'meta', 'warnings': [f'Το βοηθητικό ensemble model {helper_model} δεν επέστρεψε guidance και η απάντηση συνεχίζεται μόνο με το κύριο μοντέλο.'], 'status': f'⚠️ Το helper model {helper_model} δεν έδωσε guidance. Συνεχίζω με το κύριο μοντέλο…'})
                    except Exception as helper_exc:
                        log.warning('Αποτυχία helper ensemble model %s: %s', helper_model, helper_exc)
                        stream_json_line(self, {'type': 'meta', 'warnings': [f'Το βοηθητικό ensemble model {helper_model} απέτυχε ({build_friendly_chat_error(helper_exc)}). Η απάντηση συνεχίζεται μόνο με το κύριο μοντέλο.'], 'status': f'⚠️ Παράλειψη helper model {helper_model}. Συνεχίζω με το κύριο μοντέλο…'})
                final_messages = apply_qwen3_vl_nothink_workaround(final_messages, model, think_mode)
                think_value = resolve_think_mode(model, think_mode)
                stream_json_line(self, {'type': 'meta', 'status': f'🧠 Το κύριο μοντέλο {model} ξεκινά να απαντά…'})
                response, effective_think_value, compat_warnings, suppress_reasoning_output = open_direct_cloud_chat_stream_with_fallback(model=model, messages=final_messages, model_options=model_options if model_options else None, think_value=think_value, requested_mode=think_mode)
                if compat_warnings:
                    warnings = list(warnings) + list(compat_warnings)
                    stream_json_line(self, {'type': 'meta', 'warnings': compat_warnings})
                collected: List[str] = []
                collected_thinking: List[str] = []
                token_stats: Optional[Dict] = None
                thinking_started = False
                thinking_done_sent = False
                for chunk in response:
                    thinking_piece = extract_chunk_thinking(chunk)
                    if thinking_piece:
                        thinking_started = True
                        if not suppress_reasoning_output:
                            collected_thinking.append(thinking_piece)
                            stream_json_line(self, {'type': 'thinking', 'content': thinking_piece})
                    piece = extract_chunk_content(chunk)
                    if piece:
                        if thinking_started and (not thinking_done_sent):
                            if not suppress_reasoning_output:
                                stream_json_line(self, {'type': 'thinking_done'})
                            thinking_done_sent = True
                        collected.append(piece)
                        stream_json_line(self, {'type': 'delta', 'content': piece})
                    stats = extract_token_stats(chunk)
                    if stats:
                        token_stats = stats
                if collected_thinking and (not thinking_done_sent) and (not suppress_reasoning_output):
                    stream_json_line(self, {'type': 'thinking_done'})
                assistant_text = ''.join(collected).strip()
                assistant_text = strip_inline_think_blocks(assistant_text) if suppress_reasoning_output else assistant_text
                assistant_thinking = '' if suppress_reasoning_output else ''.join(collected_thinking).strip()
                if not assistant_text and (not assistant_thinking):
                    raise RuntimeError('Το μοντέλο δεν επέστρεψε περιεχόμενο. Έλεγξε το API key από το GUI/settings file και αν το μοντέλο είναι διαθέσιμο στο direct cloud catalog.')
                assistant_display_text = compose_display_assistant_text(assistant_text, assistant_thinking)
                elapsed = time.time() - start_time
                with SESSION.lock:
                    SESSION.messages.append(user_message)
                    SESSION.history.append(history_user_item)
                    SESSION.messages.append({'role': 'assistant', 'content': assistant_text, 'thinking': assistant_thinking})
                    SESSION.history.append({'role': 'assistant', 'content': assistant_display_text, 'attachments': []})
                    if len(SESSION.messages) > MAX_HISTORY_MESSAGES:
                        SESSION.messages[:] = SESSION.messages[-MAX_HISTORY_MESSAGES:]
                    if len(SESSION.history) > MAX_HISTORY_MESSAGES:
                        SESSION.history[:] = SESSION.history[-MAX_HISTORY_MESSAGES:]
                stream_json_line(self, {'type': 'done', 'elapsed_sec': elapsed, 'token_stats': token_stats})
            except Exception as exc:
                if is_client_disconnect_error(exc):
                    return
                friendly = build_friendly_chat_error(exc)
                log.error('Chat error: %s', exc)
                try:
                    stream_json_line(self, {'type': 'error', 'error': friendly})
                except Exception:
                    pass
            return
        json_response(self, {'error': 'Not found'}, status=404)

def parse_args() -> argparse.Namespace:
    """Επιστρέφει ή ανακτά το αποτέλεσμα του βήματος «parse_args» με συνεπή τρόπο."""
    parser = argparse.ArgumentParser(prog='ollama_cloud_chat', description=f'{APP_TITLE} — Web chat για Ollama cloud μοντέλα', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help='Port του web server')
    parser.add_argument('--host', type=str, default=HOST, help='Host του web server')
    parser.add_argument('--no-browser', action='store_true', help='Μην ανοίξεις αυτόματα τον browser')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Επίπεδο logging')
    parser.add_argument('--system-prompt-file', type=str, default='', metavar='FILE', help='Φόρτωση system prompt από εξωτερικό αρχείο .txt')
    return parser.parse_args()

def load_system_prompt_from_file(filepath: str) -> Optional[str]:
    """Υλοποιεί τη λειτουργική ρουτίνα «load_system_prompt_from_file» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: filepath."""
    if not filepath:
        return None
    path = Path(filepath)
    if not path.exists():
        log.error('Το αρχείο system prompt δεν βρέθηκε: %s', filepath)
        return None
    try:
        content = path.read_text(encoding='utf-8').strip()
        if content:
            log.info('📄 System prompt φορτώθηκε από: %s (%d χαρ.)', filepath, len(content))
            return content
        log.warning('Το αρχείο system prompt είναι κενό: %s', filepath)
        return None
    except Exception as exc:
        log.error('Αποτυχία ανάγνωσης system prompt: %s', exc)
        return None

def open_browser_later(url: str, delay: float=0.9) -> None:
    """Υλοποιεί τη λειτουργική ρουτίνα «open_browser_later» και χειρίζεται τους σχετικούς πόρους με ελεγχόμενο τρόπο.

Βασικά ορίσματα: url, delay."""

    def _worker() -> None:
        """Υλοποιεί το βήμα «_worker» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή."""
        time.sleep(delay)
        webbrowser.open(url, new=2)
    threading.Thread(target=_worker, daemon=True).start()

def _run_initialization(args: argparse.Namespace, port: int) -> None:
    """Υλοποιεί το βήμα «_run_initialization» σε ξεχωριστή συνάρτηση ώστε η κύρια ροή του αρχείου να παραμένει καθαρή.

Βασικά ορίσματα: args, port."""
    global DEFAULT_SYSTEM_PROMPT
    url = f'http://{HOST}:{port}'
    if args.system_prompt_file:
        custom_prompt = load_system_prompt_from_file(args.system_prompt_file)
        if custom_prompt:
            DEFAULT_SYSTEM_PROMPT = custom_prompt
            slog('INFO', '📄 System prompt: %s (%d χαρ.)', args.system_prompt_file, len(custom_prompt))
        else:
            slog('WARNING', '⚠  Αποτυχία φόρτωσης system prompt — χρήση embedded.')
    else:
        slog('INFO', '📄 System prompt: embedded-in-code')
    slog('INFO', '📎 Αρχεία: drag & drop + file picker')
    slog('INFO', '☁️  Λειτουργία: direct Ollama Cloud API mode')
    if is_direct_cloud_api_configured():
        slog('INFO', '🔐 Ollama Cloud API key: βρέθηκε (στο .py ή στο περιβάλλον)')
    else:
        slog('WARNING', '⚠  Ollama Cloud API key: δεν βρέθηκε — βάλε το από το GUI ή στο %s ή όρισε OLLAMA_API_KEY', APP_CONFIG_FILE)
    ensure_upload_dir()
    with REGISTRY.lock:
        REGISTRY.models = []
        REGISTRY.model_meta = {}
        REGISTRY.source = 'initializing'
        REGISTRY.last_refresh_ts = 0.0
        REGISTRY.last_error = ''
        REGISTRY.recommended_model = ''
        REGISTRY.refresh_in_progress = True
    slog('INFO', '🔄 Ανάκτηση όλων των διαθέσιμων official Ollama direct-cloud models…')
    slog('INFO', '✅ Server: %s', url)
    slog('INFO', '🛑 Ctrl+C για τερματισμό.')
    STARTUP.set_ready(url)
    refresh_models_in_background(force=True)

def main() -> None:
    """Σημείο εισόδου της εφαρμογής.

Η συνάρτηση εκτελεί τα βασικά βήματα αρχικοποίησης με σωστή σειρά και ενεργοποιεί τις επιμέρους ρουτίνες που χρειάζονται για να ξεκινήσει το πρόγραμμα."""
    global HOST
    args = parse_args()
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    HOST = args.host
    sep = '=' * 68
    print(sep)
    print(f'  {APP_TITLE}')
    print(sep)
    port = find_free_port(HOST, start_port=args.port)
    server = QuietThreadingHTTPServer((HOST, port), AppHandler)
    BROWSER_MONITOR.attach_server(server)
    start_browser_session_watchdog()
    startup_url = f'http://{HOST}:{port}/startup'
    chat_url = f'http://{HOST}:{port}'
    print(f'  🌐 Server  : {chat_url}')
    print(f'  🚀 Startup : {startup_url}')
    if not args.no_browser:
        print('  🌍 Άνοιγμα browser…')
        open_browser_later(startup_url, delay=0.25)
    else:
        print('  🚫 --no-browser: ο browser δεν άνοιξε αυτόματα.')
    print('  🛑 Ctrl+C για τερματισμό.')
    print(sep)
    threading.Thread(target=_run_initialization, args=(args, port), daemon=True, name='startup-init').start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n🛑 Τερματισμός εφαρμογής…')
    finally:
        server.server_close()
        try:
            SESSION.reset()
        except Exception:
            pass
        print('✅ Server έκλεισε.')
if __name__ == '__main__':
    main()
