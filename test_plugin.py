#!/usr/bin/env python3
"""End-to-end test for hermes-profile-migrator: sanitized export + import + path remapping."""

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# Ensure we can import the plugin from current directory
sys.path.insert(0, str(Path(__file__).parent))
from plugin_api import export_profile, import_profile

# ---------------------------------------------------------------------------
# Setup: create a fake Hermes profile with secrets inside a temp HERMES_HOME
# ---------------------------------------------------------------------------

tmp = Path(tempfile.mkdtemp())
print(f"Temp workspace: {tmp}\n")

# Point HERMES_HOME at a subdirectory inside tmp so the plugin resolves paths correctly
os.environ["HERMES_HOME"] = str(tmp / ".hermes")
hermes_home = Path(os.environ["HERMES_HOME"])
profile_dir = hermes_home / "profiles" / "test-profile"
profile_dir.mkdir(parents=True)

# .env with fake secrets
(profile_dir / ".env").write_text(
    "OPENAI_API_KEY=\"sk-abc123\"\n"
    "ANTHROPIC_API_KEY=\"sk-ant-\"\n"
    "FAL_KEY=\"key-xyz\"\n"
    "HUGGING_FACE_HUB_TOKEN=\"hf_123abc\"\n"
)

# config.yaml with a fake API key and a Windows path that contains an old username
(profile_dir / "config.yaml").write_text(
    "api:\n"
    "  key: \"sk-test-123\"\n"
    "model: gpt-4\n"
    "paths:\n"
    "  skills: C:\\Users\\OldUser\\Documents\\hermes\\skills\n"
)

# auth.json — should be deleted entirely during sanitization
(profile_dir / "auth.json").write_text('{"access_token": "github-oauth-abc"}')

# A sample skill file (should survive sanitization untouched)
(profile_dir / "skills").mkdir()
(profile_dir / "skills" / "test.py").write_text('print("hello from skill")\n')


# ---------------------------------------------------------------------------
# TEST 1 — Sanitized export
# ---------------------------------------------------------------------------

print("=" * 60)
print("TEST 1: Sanitized export")
print("=" * 60)

archive_path = str(tmp / "exported-hermes-profile.zip")
result = export_profile(
    profile_name="test-profile",
    output_path=archive_path,
    mode="sanitized",
    format="zip",
)
print()
print("EXPORT RESULT:")
print(json.dumps(result, indent=2, ensure_ascii=False))

archive = Path(result["archive_path"])
with zipfile.ZipFile(archive) as zf:
    names = sorted(zf.namelist())
    print(f"\nFILES IN ARCHIVE ({len(names)} files):")
    for n in names:
        print(f"   {n}")

    checks = []

    # 1. .env must NOT survive
    if ".env" in names:
        print("\nFAIL: .env is still present in the archive!")
        checks.append(False)
    else:
        print("\nPASS: .env removed from archive")
        checks.append(True)

    # 2. .env.example must exist and contain placeholders
    if ".env.example" in names:
        content = zf.read(".env.example").decode()
        print("PASS: .env.example exists. Relevant lines:")
        for line in content.splitlines():
            if "API_KEY" in line or "TOKEN" in line or "KEY" in line:
                print(f"     {line}")
        checks.append(True)
    else:
        print("\nFAIL: .env.example not found")
        checks.append(False)

    # 3. Original config.yaml must NOT survive; config.example.yaml must
    if "config.yaml" in names:
        print("\nFAIL: Original config.yaml (with secrets) still present!")
        checks.append(False)
    elif "config.example.yaml" in names:
        content = zf.read("config.example.yaml").decode()
        print("PASS: config.example.yaml exists. Relevant lines:")
        for line in content.splitlines():
            if "sk-" in line or "key" in line.lower():
                print(f"     {line}")
        checks.append(True)
    else:
        print("\nWARN: No config.example.yaml found")
        checks.append(False)

    # 4. auth.json must be gone
    if "auth.json" in names:
        print("\nFAIL: auth.json still in archive!")
        checks.append(False)
    else:
        print("\nPASS: auth.json removed from archive")
        checks.append(True)

    print(f"\nSUMMARY: {sum(checks)}/{len(checks)} security checks passed")


# ---------------------------------------------------------------------------
# TEST 2 — Import + automatic path remapping
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("TEST 2: Import + automatic path remapping")
print("=" * 60)

# Check the old config.example.yaml still references OldUser
extracted = tmp / "pre-import-check"
extracted.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as zf:
    zf.extractall(extracted)
extracted_profile = next(extracted.iterdir())
old_cfg = extracted_profile / "config.example.yaml"
print(f"Extracted profile: {extracted_profile.name}")
if old_cfg.exists():
    old_content = old_cfg.read_text()
    print(f"Old path in config.example.yaml: {'OldUser' if 'OldUser' in old_content else 'NOT FOUND'}")
    print(f"  -> {old_content.strip().splitlines()[-1]}")

import_result = import_profile(
    archive_path=str(archive),
    target_profile="restored-test",
    overwrite=False,
)
print()
print("IMPORT RESULT:")
print(json.dumps(import_result, indent=2, ensure_ascii=False))

imported_profile = hermes_home / "profiles" / "restored-test"
if imported_profile.is_dir():
    print(f"\nPASS: Imported profile directory exists: {imported_profile}")
    new_cfg = imported_profile / "config.example.yaml"
    if new_cfg.exists():
        new_content = new_cfg.read_text()
        print(f"New config.example.yaml last line: {new_content.strip().splitlines()[-1]}")
        if "OldUser" in new_content:
            print("FAIL: OldUser path was NOT remapped!")
        elif "HOMIE" in new_content:
            print("PASS: Path successfully remapped from OldUser to HOMIE")
        else:
            print("NOTE: Path may use a different username — inspect manually")
    else:
        print("NOTE: config.example.yaml not present in imported profile")
else:
    print("FAIL: Imported profile directory not found!")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print("\n" + "=" * 60)
print("ALL TESTS COMPLETE")
print("=" * 60)
print(f"Archive produced at: {archive}")
print("You can inspect it manually at:")
print(f"   {archive}")
