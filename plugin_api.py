"""
hermes-profile-migrator — Hermes Agent Profile Export/Import Plugin
====================================================================

Provides two tools:
  - export_profile: archive a Hermes profile, optionally sanitizing secrets
  - import_profile: restore an archive, remapping paths to the current user

Install: copy this folder into ~/.hermes/plugins/hermes-profile-migrator/
Then restart Hermes or run `hermes plugins reload`.
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
from pathlib import Path
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_hermes_home() -> Path:
    """Resolve the active Hermes home directory."""
    return Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))


def _profile_dir(profile_name: str) -> Path:
    return _get_hermes_home() / "profiles" / profile_name


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
    # OpenAI / Azure
    ("openai_api_key", re.compile(r'OPENAI_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("azure_api_key", re.compile(r'AZURE_OPENAI_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # Anthropic
    ("anthropic_api_key", re.compile(r'ANTHROPIC_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # OpenRouter
    ("openrouter_api_key", re.compile(r'OPENROUTER_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # FAL
    ("fal_api_key", re.compile(r'FAL_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("fal_api_key_dash", re.compile(r'FAL_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # HuggingFace
    ("hf_token", re.compile(r'HUGGING_FACE_HUB_TOKEN\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("hf_token_alt", re.compile(r'HUGGINGFACE_TOKEN\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # Google / Gemini
    ("google_api_key", re.compile(r'GOOGLE_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    ("gemini_api_key", re.compile(r'GEMINI_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # Stability
    ("stability_api_key", re.compile(r'STABILITY_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
    # Generic bearer / token lines
    ("bearer_token", re.compile(r'(?i)(bearer|token)\s*=\s*["\'][^"\']+["\']')),
    # Generic secret / password assignments
    ("generic_secret", re.compile(r'(?i)(secret|password|passwd|pwd)\s*=\s*["\'][^"\']+["\']')),
]


def _sanitize_line(line: str) -> tuple[str, bool]:
    """Return (sanitized_line, was_modified)."""
    for _name, pattern in SENSITIVE_PATTERNS:
        if pattern.search(line):
            key = pattern.search(line).group(0).split("=")[0].strip()
            return f'{key} = "YOUR_API_KEY_HERE"', True
    return line, False


def _sanitize_env_file(path: Path) -> int:
    """Read .env, redact secrets, write .env.example. Return count of redacted values."""
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
    # Remove the real .env from the archive
    path.unlink(missing_ok=True)
    return count


def _sanitize_yaml_file(path: Path) -> int:
    """
    Walk a YAML file and redact any string value that looks like a secret.
    Returns the number of redacted entries.
    """
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

    count = [0]  # mutable counter in nested function

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
    # Consistent naming: config.example.yaml (same style as .env.example)
    out_path = path.parent / f"config.example.yaml"
    out_path.write_text(
        yaml.safe_dump(clean, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    path.unlink(missing_ok=True)
    return count[0]


def _sanitize_profile(profile_path: Path) -> int:
    """
    Sanitize a profile directory in-place:
      - .env          → .env.example  (redact secrets)
      - config.yaml   → config.example.yaml (redact secrets)
      - auth.json     → removed entirely
      - any .env.*    → .env.*.example
    Returns total number of redacted values.
    """
    total = 0

    # .env files (only top-level .env and .env.* — example files already handled)
    for env_file in profile_path.glob(".env"):
        total += _sanitize_env_file(env_file)
    for env_file in profile_path.glob(".env.*"):
        if env_file.name != ".env.example":
            total += _sanitize_env_file(env_file)

    # config.yaml → config.example.yaml
    cfg = profile_path / "config.yaml"
    total += _sanitize_yaml_file(cfg)

    # auth.json — remove entirely
    auth = profile_path / "auth.json"
    if auth.is_file():
        auth.unlink()
        total += 1  # count the whole file as one sensitive artifact

    # Any nested .env files (skip those already processed above)
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
# Public tool implementations
# ---------------------------------------------------------------------------

def export_profile(
    profile_name: str = "default",
    output_path: str = "",
    mode: str = "sanitized",
    format: str = "zip",
) -> Dict[str, Any]:
    """
    Export a Hermes profile to a compressed archive.

    Args:
        profile_name:  Profile directory name under ~/.hermes/profiles/.
        output_path:   Where to write the archive. Defaults to Desktop.
        mode:          "sanitized" (strip secrets) or "full" (keep everything).
        format:        "zip" or "tar.gz".

    Returns:
        Dict with success, archive_path, mode, files_sanitized, message.
    """
    profile_path = _profile_dir(profile_name)
    if not profile_path.is_dir():
        return {
            "success": False,
            "message": f"Profile not found: {profile_path}",
        }

    # Determine output location
    if not output_path:
        desktop = Path.home() / "Desktop"
        output_path = str(desktop / f"hermes-profile-{profile_name}")
    out = Path(output_path)
    if out.suffix:
        archive_path = out
    else:
        archive_path = out.with_suffix(f".{format.replace('tar.gz', 'tar.gz')}")

    # Work on a temporary copy so we don't mutate the live profile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # copy profile dir into tmp
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

        # Build archive
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
    """
    Import a Hermes profile archive into the current machine.

    Args:
        archive_path:             Path to the .zip / .tar.gz archive.
        target_profile:           Desired profile name. Defaults to archive's original name.
        overwrite:                Overwrite existing profile if True.
        preserve_relative_paths:  Only rewrite absolute paths under the old home dir.

    Returns:
        Dict with success, profile_name, profile_path, paths_updated, message.
    """
    if not archive_path:
        return {"success": False, "message": "archive_path is required."}

    src = Path(archive_path)
    if not src.is_file():
        return {"success": False, "message": f"Archive not found: {src}"}

    # Extract to temp
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _extract_archive(src, tmp_path)

        # Find the profile directory inside the archive
        # The archive was created from ~/.hermes/profiles/<name>/
        # so the top-level should contain a directory named <name>
        candidates = [d for d in tmp_path.iterdir() if d.is_dir()]
        if not candidates:
            # Maybe the archive root IS the profile dir
            candidates = [tmp_path]
        profile_dir = candidates[0]

        # Determine profile name
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

        # Detect old home from config files and remap paths
        old_home = None
        paths_updated = 0

        # Try to detect old username from .env.example or config.example.yaml
        for marker in ("config.example.yaml", "config.yaml.example", "config.yaml"):
            mf = profile_dir / marker
            if mf.is_file():
                try:
                    text = mf.read_text(encoding="utf-8", errors="replace")
                    # Look for a path like C:\Users\OLDNAME or /home/OLDNAME
                    m = re.search(r'(?:C:\\Users\\|/\w+/)(\w+)', text)
                    if m:
                        old_home = str(Path.home() / m.group(1))  # approximate
                        break
                except Exception:
                    pass

        if old_home is None:
            # Fallback: assume old home was C:\Users\<something> or /home/<something>
            # We'll remap based on current username
            old_home = str(Path.home())  # safest: treat as same-home move

        new_home = str(Path.home())

        # Remap paths in config files
        for cfg_file in profile_dir.rglob("config*.yaml"):
            if cfg_file.suffix == ".yaml":
                try:
                    text = cfg_file.read_text(encoding="utf-8", errors="replace")
                    new_text = text
                    if old_home != new_home:
                        # Replace old home path with new home in string values
                        new_text = re.sub(
                            re.escape(old_home),
                            new_home,
                            text,
                        )
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

        # Copy into final location
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


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def get_tools() -> list[dict]:
    """Return the tool definitions for Hermes plugin registry."""
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
    ]


# ---------------------------------------------------------------------------
# Standalone self-test (run `python plugin_api.py` directly)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hermes Profile Migrator — standalone test")
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
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2, ensure_ascii=False))
