#!/usr/bin/env python3
"""
Hermes Profile Migrator — Standalone Installer
================================================

Any Hermes Agent (or human) can run this script to install the plugin
from a GitHub repository. No pre-existing Hermes plugin required.

Usage:
    python install.py --repo https://github.com/Neito112/hermes-profile-migrator
    python install.py --repo https://github.com/USERNAME/hermes-profile-migrator --profile default
    python install.py --repo https://github.com/USERito/hermes-profile-migrator --force

The script will:
  1. Clone the repo into ~/.hermes/plugins/<plugin-name>/
  2. Verify required files exist
  3. Save install record (for tracking)
  4. Attempt to reload Hermes plugins (non-fatal if Hermes not running)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HERMES_PLUGINS_DIR = HERMES_HOME / "plugins"
INSTALLED_RECORD = HERMES_HOME / ".installed_plugins.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return CompletedProcess."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"ERROR: {' '.join(cmd)}", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode != 0:
            sys.exit(result.returncode)
    return result


def _parse_github_url(url: str) -> tuple[str, str]:
    """
    Parse a GitHub URL into (owner, repo).
    Accepts:
      - https://github.com/OWNER/REPO
      - https://github.com/OWNER/REPO.git
      - https://github.com/OWNER/REPO/
    Returns (owner, repo_name).
    """
    url = url.strip().rstrip("/").removesuffix(".git")
    parts = url.split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid GitHub URL: {url}")
    owner = parts[-2]
    repo = parts[-1]
    if not owner or not repo:
        raise ValueError(f"Invalid GitHub URL: {url}")
    return owner, repo


def install_plugin(repo_url: str, profile: str | None = None, force: bool = False) -> dict:
    """
    Clone plugin repo into Hermes plugins dir and configure.

    Args:
        repo_url: GitHub repo URL (https://github.com/OWNER/REPO)
        profile: Optional Hermes profile name to associate. None = all profiles.
        force: If True, reinstall even if already exists.

    Returns:
        Dict with success, plugin_name, install_dir, tools, message.
    """
    owner, repo = _parse_github_url(repo_url)
    plugin_name = repo  # e.g. "hermes-profile-migrator"
    install_dir = HERMES_PLUGINS_DIR / plugin_name

    # Check existing installation
    if install_dir.exists():
        if force:
            print(f"⚠ Removing existing installation at {install_dir}")
            shutil.rmtree(install_dir)
        else:
            return {
                "success": True,
                "already_installed": True,
                "plugin_name": plugin_name,
                "install_dir": str(install_dir),
                "message": f"Plugin '{plugin_name}' already installed at {install_dir}. Use --force to reinstall.",
            }

    # Ensure plugins directory exists
    HERMES_PLUGINS_DIR.mkdir(parents=True, exist_ok=True)

    # Clone repo (shallow clone for speed)
    print(f"Cloning {repo_url} into {install_dir} ...", flush=True)
    result = _run(
        ["git", "clone", "--depth", "1", repo_url, str(install_dir)],
        check=False,
    )
    if result.returncode != 0:
        return {
            "success": False,
            "message": f"Failed to clone repository: {result.stderr.strip()}",
        }

    # Verify minimal structure
    required = ["plugin_api.py", "package.json"]
    missing = [f for f in required if not (install_dir / f).exists()]

    if missing:
        print(f"WARNING: Missing required files: {missing}", file=sys.stderr)
        print("Plugin may not work correctly.", file=sys.stderr)

    # Load package.json to discover tool names (if exists)
    tools = []
    pkg_path = install_dir / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
            tools = pkg.get("hermes", {}).get("tools", [])
        except Exception:
            pass

    # Save install record
    record = {}
    if INSTALLED_RECORD.exists():
        try:
            record = json.loads(INSTALLED_RECORD.read_text(encoding="utf-8"))
        except Exception:
            record = {}

    record[plugin_name] = {
        "repo_url": repo_url,
        "owner": owner,
        "installed_at": _now_iso(),
        "profile": profile or "all",
    }
    INSTALLED_RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    # Attempt to reload Hermes plugins (non-fatal)
    reload_msg = ""
    try:
        result = _run(["hermes", "plugins", "reload"], check=False)
        if result.returncode == 0:
            reload_msg = "Hermes plugins reloaded successfully."
        else:
            reload_msg = f"⚠ Could not reload Hermes plugins automatically. Run: hermes plugins reload"
    except FileNotFoundError:
        reload_msg = "⚠ Hermes CLI not found. Run `hermes plugins reload` manually after installation."
    except Exception as e:
        reload_msg = f"⚠ Could not reload Hermes plugins: {e}. Run: hermes plugins reload"

    tools_str = "\n   - ".join(tools) if tools else "see schema.json"

    return {
        "success": True,
        "plugin_name": plugin_name,
        "owner": owner,
        "repo_url": repo_url,
        "install_dir": str(install_dir),
        "tools": tools,
        "message": (
            f"✅ Plugin '{plugin_name}' installed successfully!\n"
            f"   Location: {install_dir}\n"
            f"   Repo: {repo_url}\n"
            f"\n"
            f"Available tools:\n"
            f"   - {tools_str}\n"
            f"\n"
            f"{reload_msg}\n"
            f"\n"
            f"To verify:  hermes tools list | grep -i {plugin_name}\n"
            f"To uninstall: rm -rf {install_dir} && hermes plugins reload\n"
        ),
    }


def list_installed() -> dict:
    """List all installed plugins from the record file."""
    if not INSTALLED_RECORD.exists():
        return {
            "count": 0,
            "plugins": [],
            "message": "No plugins installed yet.",
        }

    try:
        record = json.loads(INSTALLED_RECORD.read_text(encoding="utf-8"))
    except Exception:
        return {
            "count": 0,
            "plugins": [],
            "message": "Installed plugins record corrupted.",
        }

    plugins = []
    for name, info in record.items():
        plugins.append({
            "name": name,
            "repo_url": info.get("repo_url", ""),
            "installed_at": info.get("installed_at", ""),
            "profile": info.get("profile", "all"),
            "install_dir": str(HERMES_PLUGINS_DIR / name),
            "exists": (HERMES_PLUGINS_DIR / name).exists(),
        })

    return {
        "count": len(plugins),
        "plugins": plugins,
        "message": f"{len(plugins)} plugin(s) installed.",
    }


def uninstall_plugin(plugin_name: str) -> dict:
    """Remove a plugin from Hermes plugins directory."""
    install_dir = HERMES_PLUGINS_DIR / plugin_name

    if not install_dir.exists():
        return {
            "success": False,
            "message": f"Plugin '{plugin_name}' not found at {install_dir}.",
        }

    shutil.rmtree(install_dir)

    # Update record
    if INSTALLED_RECORD.exists():
        try:
            record = json.loads(INSTALLED_RECORD.read_text(encoding="utf-8"))
            record.pop(plugin_name, None)
            INSTALLED_RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # Attempt reload
    try:
        _run(["hermes", "plugins", "reload"], check=False)
    except Exception:
        pass

    return {
        "success": True,
        "plugin_name": plugin_name,
        "message": f"Plugin '{plugin_name}' uninstalled. Run `hermes plugins reload` to complete.",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install Hermes Profile Migrator (or any Hermes plugin) from GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Install from official repo
  python install.py --repo https://github.com/Neito112/hermes-profile-migrator

  # Install from a fork
  python install.py --repo https://github.com/OTHERUSER/hermes-profile-migrator

  # Reinstall (overwrite)
  python install.py --repo https://github.com/Neito112/hermes-profile-migrator --force

  # List installed plugins
  python install.py --list

  # Uninstall
  python install.py --uninstall hermes-profile-migrator
""",
    )

    parser.add_argument(
        "--repo",
        type=str,
        help="GitHub repository URL to install from",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Hermes profile to associate with this install (default: all profiles)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall even if plugin already exists",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all installed plugins",
    )
    parser.add_argument(
        "--uninstall",
        type=str,
        metavar="PLUGIN_NAME",
        help="Uninstall a plugin by name",
    )

    args = parser.parse_args()

    if args.list:
        result = list_installed()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    if args.uninstall:
        result = uninstall_plugin(args.uninstall)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["success"] else 1)

    if not args.repo:
        parser.print_help()
        sys.exit(1)

    result = install_plugin(args.repo, args.profile, args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
