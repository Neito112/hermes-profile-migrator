"""
hermes-profile-migrator — Hermes Agent Profile Export/Import Plugin
====================================================================

Provides tools for profile migration with auto-sync to private GitHub repo.

FEATURES:
  - export_profile: archive a Hermes profile, optionally sanitizing secrets
  - import_profile: restore an archive, remapping paths to the current user
  - setup_backup_repo: create a private GitHub repo for profile sync (auto-called on install)
  - sync_profile: bidirectional sync — pull remote + push local, merge state
  - restore_profile: pull from private repo and import locally

ON INSTALL (plugin loaded by Hermes):
  1. Check GitHub auth via `gh auth status`
  2. Check if private backup repo exists for this user
  3. If exists → auto-sync bidirectional + merge Hermes state
  4. If not → create private repo, save config, ready for manual sync
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_hermes_home() -> Path:
    """Resolve the active Hermes home directory."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _get_profile_name_from_env() -> str | None:
    """
    Try to detect current profile name from environment.
    Returns profile name if detected, None otherwise.
    """
    # Check if there's a profiles/ subdirectory — normal Hermes multi-profile setup
    hermes_home = _get_hermes_home()
    profiles_dir = hermes_home / "profiles"
    if profiles_dir.is_dir():
        # Could be any profile — we don't know which without explicit config
        # Fall back to config.json or "default"
        return None

    # If no profiles/ subdir, the Hermes home itself IS the profile directory
    # Profile name = last component of Hermes home path
    home_name = hermes_home.name
    if home_name and home_name != ".hermes":
        return home_name

    # Fallback: check parent dir name (for profiles/<name> structure)
    parent = hermes_home.parent
    if parent.name == "profiles" and hermes_home.name:
        return hermes_home.name

    return None


def _get_current_profile_dir() -> Path:
    """
    Get the current profile directory, handling both:
    - Multi-profile: ~/.hermes/profiles/<name>/
    - Single-profile (this env): ~/.hermes/ itself is the profile dir
    """
    hermes_home = _get_hermes_home()
    profiles_dir = hermes_home / "profiles"

    if profiles_dir.is_dir():
        # Multi-profile setup: find profile from config or use "default"
        profile_name = _get_plugin_config().get("profile_name", "default")
        return _profile_dir(profile_name)

    # Single-profile setup: Hermes home IS the profile
    return hermes_home


def _profile_dir(profile_name: str) -> Path:
    """Get profile directory for a given profile name."""
    hermes_home = _get_hermes_home()
    profiles_dir = hermes_home / "profiles"

    if profiles_dir.is_dir():
        # Multi-profile: standard layout
        return profiles_dir / profile_name
    else:
        # Single-profile: profiles dir doesn't exist, Hermes home IS the profile
        # Only return non-hermes-home path if profile_name is "default" or matches home name
        if profile_name == "default" or profile_name == hermes_home.name:
            return hermes_home
        # Otherwise, try standard layout anyway (may not exist)
        return profiles_dir / profile_name


def _windows_username() -> str:
    """Return the current Windows username, or fall back to $USER / $USERNAME."""
    for var in ("USERNAME", "USER"):
        val = os.environ.get(var, "")
        if val:
            return val
    return Path.home().name


def _squash_home(path_str: str, old_home: str, new_home: str) -> str:
    """If *path_str* starts with *old_home*, replace with *new_home*."""
    if not path_str:
        return path_str
    old = Path(old_home).expanduser().resolve()
    new = Path(new_home).expanduser().resolve()
    try:
        p = Path(path_str).expanduser().resolve()
        if old in p.parents or p == old:
            rel = p.relative_to(old)
            return str(new / rel)
    except (ValueError, OSError):
        pass
    return path_str


# ---------------------------------------------------------------------------
# Sensitive-value patterns
# ---------------------------------------------------------------------------

SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai_api_key", re.compile(r'OPENAI_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("azure_api_key", re.compile(r'AZURE_OPENAI_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("anthropic_api_key", re.compile(r'ANTHROPIC_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("openrouter_api_key", re.compile(r'OPENROUTER_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("fal_api_key", re.compile(r'FAL_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("fal_api_key_dash", re.compile(r'FAL_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("hf_token", re.compile(r'HUGGING_FACE_HUB_TOKEN\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("hf_token_alt", re.compile(r'HUGGINGFACE_TOKEN\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("google_api_key", re.compile(r'GOOGLE_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("gemini_api_key", re.compile(r'GEMINI_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("stability_api_key", re.compile(r'STABILITY_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("bearer_token", re.compile(r'(?i)(bearer|token)\s*=\s*["\'][^"\']+["\']')),
    ("generic_secret", re.compile(r'(?i)(secret|password|passwd|pwd)\s*=\s*["\'][^"\']+["\']')),
]


def _sanitize_line(line: str) -> tuple[str, bool]:
    for _name, pattern in SENSITIVE_PATTERNS:
        if pattern.search(line):
            key = pattern.search(line).group(0).split("=")[0].strip()
            return f'{key} = "YOUR_API_KEY_HERE"', True
    return line, False


def _sanitize_env_file(path: Path) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    count = 0
    new_lines = []
    for line in lines:
        sanitized, modified = _sanitize_line(line)
        if modified:
            count += 1
        new_lines.append(sanitized)
    example_path = path.parent / f"{path.name}.example"
    # Guard: if .env.example already exists, do not re-process .env.example as input
    if example_path.exists() and path.name.endswith(".example"):
        return 0
    example_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    path.unlink(missing_ok=True)
    return count


def _sanitize_yaml_file(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        import yaml
    except ImportError:
        return 0

    text = path.read_text(encoding="utf-8", errors="replace")
    data = yaml.safe_load(text)
    if data is None:
        return 0

    count = [0]

    def _walk(node: Any, key_path: str = "") -> Any:
        if isinstance(node, dict):
            return {
                k: _walk(v, f"{key_path}.{k}" if key_path else k)
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk(v, f"{key_path}[]") for v in node]
        if isinstance(node, str):
            for _name, pattern in SENSITIVE_PATTERNS:
                if pattern.search(node):
                    count[0] += 1
                    return "YOUR_API_KEY_HERE"
        return node

    clean = _walk(data)
    out_path = path.parent / "config.example.yaml"
    out_path.write_text(
        yaml.safe_dump(clean, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    path.unlink(missing_ok=True)
    return count[0]


def _sanitize_profile(profile_path: Path) -> int:
    total = 0

    for env_file in profile_path.glob(".env"):
        total += _sanitize_env_file(env_file)
    for env_file in profile_path.glob(".env.*"):
        if env_file.name != ".env.example":
            total += _sanitize_env_file(env_file)

    cfg = profile_path / "config.yaml"
    total += _sanitize_yaml_file(cfg)

    auth = profile_path / "auth.json"
    if auth.is_file():
        auth.unlink()
        total += 1

    for env_file in profile_path.rglob(".env"):
        if env_file.name not in (".env", ".env.example"):
            total += _sanitize_env_file(env_file)

    return total


# ---------------------------------------------------------------------------
# Archive I/O
# ---------------------------------------------------------------------------

def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _archive_zip(source: Path, dest: Path) -> None:
    _ensure_parent(dest)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in source.rglob("*"):
            if entry.is_file():
                arcname = entry.relative_to(source.parent)
                zf.write(entry, arcname)


def _archive_tar(source: Path, dest: Path) -> None:
    _ensure_parent(dest)
    with tarfile.open(dest, "w:gz") as tf:
        tf.add(source, arcname=source.name)


def _extract_archive(archive: Path, dest: Path) -> None:
    _ensure_parent(dest)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
    elif archive.suffix in (".gz", ".tar.gz", ".tgz") or archive.name.endswith(".tar.gz"):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
    else:
        raise ValueError(f"Unsupported archive format: {archive.suffix}")


# ---------------------------------------------------------------------------
# GitHub helper functions
# ---------------------------------------------------------------------------

def _gh_api(endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
    cmd = ["gh", "api", endpoint, "-X", method]
    if data is not None:
        import json as _json
        payload = _json.dumps(data)
        cmd.extend(["-f", f"data={payload}"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh api failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _gh_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh"] + args, capture_output=True, text=True)


def _ensure_gh_auth() -> dict:
    result = _gh_cli(["auth", "status"])
    if result.returncode != 0:
        raise RuntimeError(
            "GitHub CLI not authenticated. Run `gh auth login` first, "
            "or ensure Hermes has valid GitHub OAuth."
        )
    user = _gh_api("/user")
    return user


def _repo_exists(owner: str, repo: str) -> bool:
    try:
        _gh_api(f"/repos/{owner}/{repo}")
        return True
    except Exception:
        return False


def _get_repo_info(owner: str, repo: str) -> dict:
    return _gh_api(f"/repos/{owner}/{repo}")


def _create_private_repo(name: str, description: str, add_readme: bool = True) -> dict:
    result = _gh_cli([
        "repo", "create", name,
        "--private",
        "--description", description,
    ])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create repo: {result.stderr.strip()}")
    user = _ensure_gh_auth()
    return _get_repo_info(user["login"], name)


def _get_latest_archive_from_repo(owner: str, repo: str, ref: str = "main") -> Path | None:
    import tempfile as _tempfile

    try:
        contents = _gh_api(f"/repos/{owner}/{repo}/contents/", params={"ref": ref})
    except Exception:
        return None

    archives = []
    for item in contents:
        name = item.get("name", "")
        if name.endswith(".zip") or name.endswith(".tar.gz") or name.endswith(".tgz"):
            archives.append(item)

    if not archives:
        for item in contents:
            if item.get("type") == "dir":
                try:
                    sub = _gh_api(f"/repos/{owner}/{repo}/contents/{item['name']}", params={"ref": ref})
                    for s in sub:
                        name = s.get("name", "")
                        if name.endswith(".zip") or name.endswith(".tar.gz") or name.endswith(".tgz"):
                            archives.append(s)
                except Exception:
                    pass

    if not archives:
        return None

    latest = sorted(archives, key=lambda x: x.get("download_url", ""), reverse=True)[0]
    temp_dir = _tempfile.mkdtemp()
    dest_path = Path(temp_dir) / latest["name"]
    download_url = latest["download_url"]

    token_result = _gh_cli(["auth", "token"])
    token = token_result.stdout.strip()

    import urllib.request
    req = urllib.request.Request(download_url)
    req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req) as resp:
        dest_path.write_bytes(resp.read())

    return dest_path


def _push_archive_to_repo(owner: str, repo: str, archive_path: Path, commit_msg: str, branch: str = "main") -> str:
    """
    Push an archive file to the backup repo using gh CLI (authenticated).
    Handles both empty repos (first commit) and existing repos.
    """
    import tempfile as _tempfile

    # Clone using gh (authenticated) instead of raw git@ssh
    temp_dir = _tempfile.mkdtemp()
    repo_dir = Path(temp_dir) / "repo"

    # Try gh repo clone first (uses gh auth, works with HTTPS)
    clone_result = subprocess.run(
        ["gh", "repo", "clone", f"{owner}/{repo}", str(repo_dir)],
        capture_output=True, text=True,
    )

    if clone_result.returncode != 0:
        # Fallback: maybe repo is empty and gh clone fails — try git clone
        subprocess.run(
            ["git", "clone", f"https://github.com/{owner}/{repo}.git", str(repo_dir)],
            check=True, capture_output=True,
        )

    # Ensure we're on the right branch
    subprocess.run(["git", "checkout", "-b", branch], cwd=repo_dir, capture_output=True)

    # Copy archive into repo root
    arc_name = archive_path.name
    dest_file = repo_dir / arc_name
    shutil.copy2(archive_path, dest_file)

    # Git add + commit
    subprocess.run(["git", "add", arc_name], cwd=repo_dir, check=True, capture_output=True)

    # Configure git user for commit (use gh auth info if available)
    try:
        user_info = _gh_api("/user")
        email = user_info.get("email", "hermes@agent.local")
        username = user_info.get("login", "hermes-agent")
        subprocess.run(["git", "config", "user.email", email], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", username], cwd=repo_dir, check=True, capture_output=True)
    except Exception:
        subprocess.run(["git", "config", "user.email", "hermes@agent.local"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Hermes Agent"], cwd=repo_dir, check=True, capture_output=True)

    subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=repo_dir, check=True, capture_output=True,
    )

    # Push using gh (authenticated HTTPS push)
    push_result = subprocess.run(
        ["git", "push", "origin", branch],
        cwd=repo_dir, capture_output=True, text=True,
    )

    if push_result.returncode != 0:
        # Maybe need to set upstream first
        subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=repo_dir, check=True, capture_output=True,
        )

    # Get commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_dir, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _pull_repo(owner: str, repo: str, dest: Path) -> Path:
    if dest.exists():
        subprocess.run(["git", "-C", str(dest), "pull"], check=True, capture_output=True)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", f"git@github.com:{owner}/{repo}.git", str(dest)],
            check=True, capture_output=True,
        )
    return dest


# ---------------------------------------------------------------------------
# Hermes State Merge Logic
# ---------------------------------------------------------------------------

def _get_hermes_state_path() -> Path:
    return _get_hermes_home() / "state.db"


def _merge_state_databases(local_path: Path, remote_profile_path: Path) -> dict:
    import sqlite3

    if not local_path.is_file():
        return {"sessions_merged": 0, "sessions_conflicted": 0, "message": "No local state.db found."}

    if not remote_profile_path.is_file():
        return {"sessions_merged": 0, "sessions_conflicted": 0, "message": "No remote state.db found in profile."}

    local_stat = local_path.stat()
    remote_stat = remote_profile_path.stat()

    if remote_stat.st_mtime > local_stat.st_mtime:
        backup = local_path.with_suffix(".db.backup")
        if not backup.exists():
            shutil.copy2(local_path, backup)
        shutil.copy2(remote_profile_path, local_path)
        return {
            "sessions_merged": 1,
            "sessions_conflicted": 0,
            "strategy": "replace_newer",
            "message": f"Replaced local state.db with remote (remote newer). Local backup at {backup}."
        }
    else:
        return {
            "sessions_merged": 0,
            "sessions_conflicted": 0,
            "strategy": "keep_local",
            "message": "Local state.db is newer or same age — kept local version."
        }


def _merge_hermes_memory(local_home: Path, remote_profile_path: Path) -> dict:
    memories_dir = local_home / "memories"
    remote_memories = remote_profile_path / "memories"

    stats = {"files_copied": 0, "files_skipped": 0, "message": ""}

    if not remote_memories.is_dir():
        stats["message"] = "No remote memories directory found."
        return stats

    if not memories_dir.exists():
        memories_dir.mkdir(parents=True, exist_ok=True)

    for mem_file in remote_memories.iterdir():
        if mem_file.is_file():
            local_file = memories_dir / mem_file.name
            if not local_file.exists():
                shutil.copy2(mem_file, local_file)
                stats["files_copied"] += 1
            else:
                if mem_file.read_bytes() != local_file.read_bytes():
                    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    backup_name = f"{mem_file.stem}_{ts}{mem_file.suffix}"
                    shutil.copy2(local_file, memories_dir / backup_name)
                    shutil.copy2(mem_file, local_file)
                    stats["files_copied"] += 1
                else:
                    stats["files_skipped"] += 1

    stats["message"] = f"Merged memories: {stats['files_copied']} copied, {stats['files_skipped']} skipped."
    return stats


def _merge_hermes_sessions(local_home: Path, remote_profile_path: Path) -> dict:
    sessions_dir = local_home / "sessions"
    remote_sessions = remote_profile_path / "sessions"

    stats = {"files_copied": 0, "files_skipped": 0, "message": ""}

    if not remote_sessions.is_dir():
        stats["message"] = "No remote sessions directory found."
        return stats

    if not sessions_dir.exists():
        sessions_dir.mkdir(parents=True, exist_ok=True)

    for sess_file in remote_sessions.iterdir():
        if sess_file.is_file():
            local_file = sessions_dir / sess_file.name
            if not local_file.exists():
                shutil.copy2(sess_file, local_file)
                stats["files_copied"] += 1
            else:
                stats["files_skipped"] += 1

    stats["message"] = f"Merged sessions: {stats['files_copied']} copied, {stats['files_skipped']} skipped."
    return stats


def _merge_hermes_skills(local_home: Path, remote_profile_path: Path) -> dict:
    skills_dir = local_home / "skills"
    remote_skills = remote_profile_path / "skills"

    stats = {"files_copied": 0, "dirs_copied": 0, "message": ""}

    if not remote_skills.is_dir():
        stats["message"] = "No remote skills directory found."
        return stats

    if not skills_dir.exists():
        skills_dir.mkdir(parents=True, exist_ok=True)

    for item in remote_skills.iterdir():
        local_item = skills_dir / item.name
        if not local_item.exists():
            if item.is_dir():
                shutil.copytree(item, local_item)
                stats["dirs_copied"] += 1
            else:
                shutil.copy2(item, local_item)
                stats["files_copied"] += 1

    stats["message"] = f"Merged skills: {stats['files_copied']} files, {stats['dirs_copied']} dirs copied."
    return stats


# ---------------------------------------------------------------------------
# Config management (local plugin config)
# ---------------------------------------------------------------------------

def _get_plugin_config() -> dict:
    plugin_dir = Path(__file__).parent
    config_path = plugin_dir / "config.json"
    if config_path.is_file():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {}


def _save_plugin_config(config: dict) -> None:
    plugin_dir = Path(__file__).parent
    config_path = plugin_dir / "config.json"
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def _detect_github_username() -> str:
    user = _ensure_gh_auth()
    return user["login"]


# ---------------------------------------------------------------------------
# Public tool implementations
# ---------------------------------------------------------------------------

def export_profile(
    profile_name: str = "default",
    output_path: str = "",
    mode: str = "sanitized",
    format: str = "zip",
) -> Dict[str, Any]:
    profile_path = _profile_dir(profile_name)
    if not profile_path.is_dir():
        return {
            "success": False,
            "message": f"Profile not found: {profile_path}",
        }

    if not output_path:
        desktop = Path.home() / "Desktop"
        output_path = str(desktop / f"hermes-profile-{profile_name}")
    out = Path(output_path)
    if out.suffix:
        archive_path = out
    else:
        archive_path = out.with_suffix(f".{format.replace('tar.gz', 'tar.gz')}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        copy_dest = tmp_path / profile_path.name
        shutil.copytree(profile_path, copy_dest)

        files_sanitized = 0
        actual_mode = mode

        if mode == "sanitized":
            files_sanitized = _sanitize_profile(copy_dest)
            actual_mode = "sanitized"
        elif mode == "full":
            actual_mode = "full"
        else:
            return {"success": False, "message": f"Unknown mode: {mode}"}

        _ensure_parent(archive_path)
        if format == "zip":
            _archive_zip(copy_dest.parent, archive_path)
        else:
            _archive_tar(copy_dest.parent, archive_path)

    return {
        "success": True,
        "archive_path": str(archive_path.resolve()),
        "mode": actual_mode,
        "files_sanitized": files_sanitized if actual_mode == "sanitized" else 0,
        "message": (
            f"Profile '{profile_name}' exported {actual_mode} to "
            f"{archive_path.resolve()}"
            + (f" ({files_sanitized} sensitive values redacted)." if actual_mode == "sanitized" else "")
        ),
    }


def import_profile(
    archive_path: str = "",
    target_profile: str = "",
    overwrite: bool = False,
    preserve_relative_paths: bool = True,
) -> Dict[str, Any]:
    if not archive_path:
        return {"success": False, "message": "archive_path is required."}

    src = Path(archive_path)
    if not src.is_file():
        return {"success": False, "message": f"Archive not found: {src}"}

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _extract_archive(src, tmp_path)

        candidates = [d for d in tmp_path.iterdir() if d.is_dir()]
        if not candidates:
            candidates = [tmp_path]
        profile_dir = candidates[0]

        detected_name = profile_dir.name
        if target_profile:
            profile_name = target_profile
        else:
            profile_name = detected_name

        hermes_home = _get_hermes_home()
        dest = hermes_home / "profiles" / profile_name

        if dest.exists():
            if overwrite:
                shutil.rmtree(dest)
            else:
                return {
                    "success": False,
                    "message": (
                        f"Profile '{profile_name}' already exists at {dest}. "
                        f"Set overwrite=true to replace it."
                    ),
                }

        old_home = None
        paths_updated = 0

        for marker in ("config.example.yaml", "config.yaml.example", "config.yaml", ".env.example", ".env"):
            mf = profile_dir / marker
            if mf.is_file():
                try:
                    text = mf.read_text(encoding="utf-8", errors="replace")
                    m = re.search(r'(?:C:\\Users\\|/)(\w+)', text)
                    if m:
                        old_home = str(Path.home() / m.group(1))
                        break
                except Exception:
                    pass

        if old_home is None:
            old_home = str(Path.home())

        new_home = str(Path.home())

        for cfg_file in profile_dir.rglob("config*.yaml"):
            if cfg_file.suffix == ".yaml":
                try:
                    text = cfg_file.read_text(encoding="utf-8", errors="replace")
                    new_text = text
                    if old_home != new_home:
                        new_text = re.sub(re.escape(old_home), new_home, text)
                    if new_text != text:
                        paths_updated += 1
                    cfg_file.write_text(new_text, encoding="utf-8")
                except Exception:
                    pass

        for cfg_file in profile_dir.rglob("config*.json"):
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                modified = False

                def _remap(obj: Any) -> Any:
                    nonlocal modified
                    if isinstance(obj, dict):
                        return {k: _remap(v) for k, v in obj.items()}
                    if isinstance(obj, list):
                        return [_remap(v) for v in obj]
                    if isinstance(obj, str) and old_home != new_home:
                        if old_home in obj:
                            modified = True
                            return obj.replace(old_home, new_home)
                    return obj

                new_data = _remap(data)
                if modified:
                    paths_updated += 1
                    cfg_file.write_text(
                        json.dumps(new_data, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
            except Exception:
                pass

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(profile_dir, dest)

    return {
        "success": True,
        "profile_name": profile_name,
        "profile_path": str(dest.resolve()),
        "paths_updated": paths_updated,
        "message": (
            f"Profile '{profile_name}' imported to {dest.resolve()}"
            + (f" ({paths_updated} path(s) remapped)." if paths_updated else "")
        ),
    }


def setup_backup_repo(
    repo_name: str = "hermes-profile-backup",
    profile_name: str = "default",
    add_readme: bool = True,
) -> Dict[str, Any]:
    try:
        user = _ensure_gh_auth()
        github_user = user["login"]
    except Exception as e:
        return {
            "success": False,
            "message": f"GitHub auth check failed: {str(e)}. Run `gh auth login` first.",
        }

    if _repo_exists(github_user, repo_name):
        repo_info = _get_repo_info(github_user, repo_name)
        if repo_info.get("visibility") != "private":
            return {
                "success": False,
                "message": (
                    f"Repo {github_user}/{repo_name} exists but is NOT private "
                    f"(visibility: {repo_info.get('visibility')}). "
                    f"Convert to private with: gh repo edit {repo_name} --visibility private"
                ),
            }
        config = _get_plugin_config()
        config["backup_repo"] = f"{github_user}/{repo_name}"
        config["github_user"] = github_user
        config["profile_name"] = profile_name
        config["repo_name"] = repo_name
        _save_plugin_config(config)

        return {
            "success": True,
            "repo_url": repo_info.get("html_url"),
            "repo_name": repo_name,
            "profile_name": profile_name,
            "message": (
                f"Private backup repo already exists: {repo_info.get('html_url')}. "
                f"Config saved. Ready for sync_profile / restore_profile."
            ),
        }

    try:
        repo_info = _create_private_repo(
            name=repo_name,
            description=f"Hermes profile backup for '{profile_name}' — PRIVATE. Do not make public.",
            add_readme=add_readme,
        )
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to create private repo: {str(e)}",
        }

    config = _get_plugin_config()
    config["backup_repo"] = f"{github_user}/{repo_name}"
    config["github_user"] = github_user
    config["profile_name"] = profile_name
    config["repo_name"] = repo_name
    config["repo_created_at"] = datetime.now(timezone.utc).isoformat()
    _save_plugin_config(config)

    return {
        "success": True,
        "repo_url": repo_info.get("html_url"),
        "repo_name": repo_name,
        "profile_name": profile_name,
        "message": (
            f"Private backup repo created: {repo_info.get('html_url')}. "
            f"Config saved locally. Use sync_profile to push your profile, "
            f"or restore_profile to pull from this repo."
        ),
    }


def sync_profile(
    profile_name: str = "",
    mode: str = "sanitized",
    message: str = "",
) -> Dict[str, Any]:
    config = _get_plugin_config()
    if not config.get("backup_repo"):
        return {
            "success": False,
            "message": "No backup repo configured. Run setup_backup_repo first.",
        }

    repo_slug = config["backup_repo"]
    github_user = config.get("github_user", _detect_github_username())
    target_profile = profile_name or config.get("profile_name", "default")

    if "/" in repo_slug:
        owner, repo = repo_slug.split("/", 1)
    else:
        owner = github_user
        repo = repo_slug

    try:
        repo_info = _get_repo_info(owner, repo)
        if repo_info.get("visibility") != "private":
            return {
                "success": False,
                "message": (
                    f"SECURITY: Repo {owner}/{repo} is now PUBLIC. "
                    f"Convert back to private: gh repo edit {repo} --visibility private"
                ),
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Cannot access repo {owner}/{repo}: {str(e)}",
        }

    remote_archive = _get_latest_archive_from_repo(owner, repo)
    remote_imported = False
    merge_stats = {}

    if remote_archive is not None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _extract_archive(remote_archive, tmp_path)
            candidates = [d for d in tmp_path.iterdir() if d.is_dir()]
            if candidates:
                remote_profile_dir = candidates[0]
                temp_profile_name = f"_sync_temp_{target_profile}"
                temp_dest = _get_hermes_home() / "profiles" / temp_profile_name
                if temp_dest.exists():
                    shutil.rmtree(temp_dest)
                shutil.copytree(remote_profile_dir, temp_dest)

                local_state = _get_hermes_state_path()
                remote_state = temp_dest / "state.db"
                if remote_state.is_file() and local_state.is_file():
                    merge_stats = _merge_state_databases(local_state, remote_state)

                hermes_home = _get_hermes_home()
                merge_stats_mem = _merge_hermes_memory(hermes_home, temp_dest)
                merge_stats_sessions = _merge_hermes_sessions(hermes_home, temp_dest)
                merge_stats_skills = _merge_hermes_skills(hermes_home, temp_dest)

                shutil.rmtree(temp_dest)
                remote_imported = True

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        archive_name = f"hermes-profile-{target_profile}-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
        archive_path = tmp_path / archive_name

        export_result = export_profile(
            profile_name=target_profile,
            output_path=str(archive_path),
            mode=mode,
            format="zip",
        )

        if not export_result["success"]:
            return export_result

        commit_msg = message or f"Sync profile '{target_profile}' at {datetime.now(timezone.utc).isoformat()}"
        try:
            commit_sha = _push_archive_to_repo(github_user, repo, Path(export_result["archive_path"]), commit_msg)
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to push to repo: {str(e)}",
            }

    return {
        "success": True,
        "repo_url": f"https://github.com/{owner}/{repo}",
        "commit": commit_sha,
        "profile_name": target_profile,
        "remote_synced": remote_imported,
        "merge_stats": merge_stats,
        "message": (
            f"Profile '{target_profile}' synced to {owner}/{repo}. "
            f"Commit: {commit_sha}. "
            + (f"Remote changes merged: {merge_stats.get('message', 'none')}. " if merge_stats else "")
            + (f"Push mode: {mode}. " if mode else "")
        ),
    }


def restore_profile(
    profile_name: str = "",
    version: str = "",
) -> Dict[str, Any]:
    config = _get_plugin_config()
    if not config.get("backup_repo"):
        return {
            "success": False,
            "message": "No backup repo configured. Run setup_backup_repo first.",
        }

    repo_slug = config["backup_repo"]
    github_user = config.get("github_user", _detect_github_username())
    target_profile = profile_name or config.get("profile_name", "default")

    if "/" in repo_slug:
        owner, repo = repo_slug.split("/", 1)
    else:
        owner = github_user
        repo = repo_slug

    try:
        repo_info = _get_repo_info(owner, repo)
        if repo_info.get("visibility") != "private":
            return {
                "success": False,
                "message": (
                    f"SECURITY: Repo {owner}/{repo} is PUBLIC. "
                    f"Convert to private: gh repo edit {repo} --visibility private"
                ),
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Cannot access repo {owner}/{repo}: {str(e)}",
        }

    ref = version or "main"
    archive_path = _get_latest_archive_from_repo(owner, repo, ref=ref)
    if archive_path is None:
        return {
            "success": False,
            "message": f"No profile archive found in {owner}/{repo} (ref: {ref}).",
        }

    import_result = import_profile(
        archive_path=str(archive_path),
        target_profile=target_profile,
        overwrite=True,
    )

    if not import_result["success"]:
        return import_result

    return {
        "success": True,
        "profile_name": target_profile,
        "profile_path": import_result["profile_path"],
        "message": (
            f"Profile '{target_profile}' restored from {owner}/{repo} "
            f"(ref: {ref}) to {import_result['profile_path']}."
        ),
    }


def auto_sync_on_load() -> Dict[str, Any]:
    result_parts = []

    try:
        user = _ensure_gh_auth()
        github_user = user["login"]
        result_parts.append(f"✓ GitHub auth OK (user: {github_user})")
    except Exception as e:
        result_parts.append(f"✗ GitHub auth failed: {str(e)}. Run `gh auth login`.")
        return {
            "success": False,
            "message": " | ".join(result_parts),
            "action_needed": "Run `gh auth login` to authenticate with GitHub.",
        }

    config = _get_plugin_config()
    repo_name = config.get("repo_name", "hermes-profile-backup")
    profile_name = config.get("profile_name", "default")

    if _repo_exists(github_user, repo_name):
        repo_info = _get_repo_info(github_user, repo_name)
        if repo_info.get("visibility") != "private":
            result_parts.append(
                f"⚠ Repo {github_user}/{repo_name} is PUBLIC — security risk. "
                f"Convert to private: gh repo edit {repo_name} --visibility private"
            )
            return {
                "success": False,
                "message": " | ".join(result_parts),
                "action_needed": "Convert repo to private immediately.",
            }
        result_parts.append(f"✓ Private backup repo found: {repo_info.get('html_url')}")

        try:
            sync_result = sync_profile(profile_name=profile_name, mode="sanitized")
            if sync_result["success"]:
                result_parts.append(f"✓ Sync complete: {sync_result.get('message', '')}")
            else:
                result_parts.append(f"⚠ Sync had issues: {sync_result.get('message', '')}")
        except Exception as e:
            result_parts.append(f"⚠ Sync failed: {str(e)}")

        return {
            "success": True,
            "message": " | ".join(result_parts),
            "repo_url": repo_info.get("html_url"),
            "profile_name": profile_name,
            "synced": True,
        }
    else:
        result_parts.append(f"No backup repo found for {github_user}. Creating private repo...")

        setup_result = setup_backup_repo(
            repo_name=repo_name,
            profile_name=profile_name,
            add_readme=True,
        )

        if setup_result["success"]:
            result_parts.append(f"✓ Private repo created: {setup_result.get('repo_url', '')}")
            result_parts.append("  Run sync_profile to push your first profile archive.")
        else:
            result_parts.append(f"✗ Failed to create repo: {setup_result.get('message', '')}")

        return {
            "success": setup_result["success"],
            "message": " | ".join(result_parts),
            "repo_url": setup_result.get("repo_url"),
            "profile_name": profile_name,
            "repo_created": setup_result["success"],
        }


def __init_auto_sync():
    """Auto-run sync khi Hermes load plugin — trigger self on import."""
    import logging
    import sys as _sys

    logger = logging.getLogger(__name__)

    # Guard: chỉ chạy 1 lần per process
    if getattr(_sys, "_hermes_profile_migrator_auto_sync_done", False):
        return

    _sys._hermes_profile_migrator_auto_sync_done = True

    logger.info("Profile migrator: auto-sync starting...")

    try:
        result = auto_sync_on_load()
        if result.get("success"):
            logger.info(f"Profile migrator auto-sync OK: {result.get('message', '')[:200]}")
        else:
            logger.warning(f"Profile migrator auto-sync issue: {result.get('message', '')[:200]}")
    except Exception as e:
        logger.error(f"Profile migrator auto-sync failed: {e}")

    return True


# ---------------------------------------------------------------------------
# Trigger auto-sync khi module được import (Hermes load plugin)
# ---------------------------------------------------------------------------

# Chạy tự động khi Hermes import plugin_api module
# Guard bằng flag để tránh trigger nhiều lần
if not getattr(sys, "_hermes_profile_migrator_auto_sync_done", False):
    try:
        __init_auto_sync()
    except Exception:
        pass  # Không break Hermes load process


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def get_tools() -> list[dict]:
    return [
        {
            "name": "export_profile",
            "description": "Export a Hermes profile directory into a compressed archive. In 'sanitized' mode (default), sensitive API keys are stripped and replaced with placeholder examples. In 'full' mode, the entire profile is archived as-is for internal machine-to-machine transfer.",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "profile_name": {
                        "type": "string",
                        "description": "Name of the profile to export. Defaults to the active/default profile.",
                        "default": "default",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Destination path for the exported archive. Defaults to Desktop.",
                        "default": "",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["sanitized", "full"],
                        "description": "'sanitized' strips API keys and secrets (safe for sharing). 'full' archives everything verbatim (for private migration only).",
                        "default": "sanitized",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["zip", "tar.gz"],
                        "description": "Archive format.",
                        "default": "zip",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "import_profile",
            "description": "Import a previously exported Hermes profile archive into the current machine. Automatically detects the Windows username and updates all stored paths in config files to match the new environment.",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "archive_path": {
                        "type": "string",
                        "description": "Path to the exported profile archive (.zip or .tar.gz).",
                        "default": "",
                    },
                    "target_profile": {
                        "type": "string",
                        "description": "Name for the imported profile. Defaults to the archive's original profile name.",
                        "default": "",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "If true, overwrite an existing profile with the same name. If false, abort when a conflict is detected.",
                        "default": False,
                    },
                    "preserve_relative_paths": {
                        "type": "boolean",
                        "description": "If true, only absolute paths under the old home directory are remapped. Relative paths and paths outside the home are left untouched.",
                        "default": True,
                    },
                },
                "required": ["archive_path"],
            },
        },
        {
            "name": "setup_backup_repo",
            "description": "Create a PRIVATE GitHub repository for automated profile backup and sync. This repo will store your sanitized profile archives. ALWAYS PRIVATE — never public, to protect your agent config from exposure.",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "repo_name": {
                        "type": "string",
                        "description": "Name for the backup repository. Defaults to 'hermes-profile-backup'.",
                        "default": "hermes-profile-backup",
                    },
                    "profile_name": {
                        "type": "string",
                        "description": "The Hermes profile this repo will back up. Defaults to 'default'.",
                        "default": "default",
                    },
                    "add_readme": {
                        "type": "boolean",
                        "description": "Whether to add a README.md to the new repository.",
                        "default": True,
                    },
                },
                "required": [],
            },
        },
        {
            "name": "sync_profile",
            "description": "Bidirectional sync: pull remote changes from private backup repo first, then push local profile. Merges Hermes state (state.db, memories, sessions, skills) when remote is newer. Requires setup_backup_repo to have been run first.",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "profile_name": {
                        "type": "string",
                        "description": "Profile to sync. Defaults to the one configured in setup_backup_repo.",
                        "default": "",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["sanitized", "full"],
                        "description": "Export mode for push. 'sanitized' (default) strips API keys; 'full' keeps everything.",
                        "default": "sanitized",
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message. Defaults to auto-generated 'Sync profile <name> at <timestamp>'.",
                        "default": "",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "restore_profile",
            "description": "Pull the latest profile archive from your private backup repository and import it into your local Hermes installation. Optionally specify a git ref (branch name, tag, or commit SHA) to restore from.",
            "parameter_schema": {
                "type": "object",
                "properties": {
                    "profile_name": {
                        "type": "string",
                        "description": "Profile to restore. Defaults to the one configured in setup_backup_repo.",
                        "default": "",
                    },
                    "version": {
                        "type": "string",
                        "description": "Git ref to restore from (branch name, tag, or commit SHA). Defaults to 'main'.",
                        "default": "",
                    },
                },
                "required": [],
            },
        },
        {
            "name": "auto_sync_on_load",
            "description": "Internal: called automatically when plugin loads. Checks GitHub auth, detects existing private backup repo, performs bidirectional sync + state merge, or creates repo if missing. Returns status for logging.",
            "parameter_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    ]


# ---------------------------------------------------------------------------
# Standalone CLI (run `python plugin_api.py <command>`)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hermes Profile Migrator — standalone CLI")
    sub = parser.add_subparsers(dest="command")

    p_exp = sub.add_parser("export")
    p_exp.add_argument("--profile", default="default")
    p_exp.add_argument("--output", default="")
    p_exp.add_argument("--mode", choices=["sanitized", "full"], default="sanitized")
    p_exp.add_argument("--format", choices=["zip", "tar.gz"], default="zip")

    p_imp = sub.add_parser("import")
    p_imp.add_argument("archive", help="Path to archive")
    p_imp.add_argument("--profile", default="")
    p_imp.add_argument("--overwrite", action="store_true")

    p_setup = sub.add_parser("setup")
    p_setup.add_argument("--repo-name", default="hermes-profile-backup")
    p_setup.add_argument("--profile", default="default")
    p_setup.add_argument("--no-readme", action="store_true")

    p_sync = sub.add_parser("sync")
    p_sync.add_argument("--profile", default="")
    p_sync.add_argument("--mode", choices=["sanitized", "full"], default="sanitized")
    p_sync.add_argument("--message", default="")

    p_restore = sub.add_parser("restore")
    p_restore.add_argument("--profile", default="")
    p_restore.add_argument("--version", default="")

    p_auto = sub.add_parser("auto-check")

    args = parser.parse_args()

    if args.command == "export":
        result = export_profile(
            profile_name=args.profile,
            output_path=args.output,
            mode=args.mode,
            format=args.format,
        )
    elif args.command == "import":
        result = import_profile(
            archive_path=args.archive,
            target_profile=args.profile,
            overwrite=args.overwrite,
        )
    elif args.command == "setup":
        result = setup_backup_repo(
            repo_name=args.repo_name,
            profile_name=args.profile,
            add_readme=not args.no_readme,
        )
    elif args.command == "sync":
        result = sync_profile(
            profile_name=args.profile,
            mode=args.mode,
            message=args.message,
        )
    elif args.command == "restore":
        result = restore_profile(
            profile_name=args.profile,
            version=args.version,
        )
    elif args.command == "auto-check":
        result = auto_sync_on_load()
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))
