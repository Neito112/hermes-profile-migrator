# Hermes Profile Migrator

> Export and import Hermes Agent profiles with automatic API key sanitization and path remapping.

[![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)](package.json)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![GitHub repo](https://img.shields.io/badge/repo-Neito112%2Fhermes--profile--migrator-24292e.svg)](https://github.com/Neito112/hermes-profile-migrator)

> A Hermes Agent plugin for exporting and importing profiles — with automatic API key sanitization and cross-machine path remapping. **v1.1+ adds bidirectional sync to your own private GitHub repo** — install once, auto-sync profile + memories + sessions across machines.

**Repository:** https://github.com/Neito112/hermes-profile-migrator

---

## Table of Contents

- [Overview / Tổng quan](#overview--tổng-quan)
- [Features / Tính năng](#features--tính-năng)
- [Installation / Cài đặt](#installation--cài-đặt)
- [Usage — CLI / Sử dụng qua CLI](#usage--cli--sử-dụng-qua-cli)
- [Usage — Hermes Plugin / Sử dụng như plugin Hermes](#usage--hermes-plugin--sử-dụng-như-plugin-hermes)
- [Tool: export_profile / Công cụ xuất profile](#tool-export_profile--công-cụ-xuất-profile)
- [Tool: import_profile / Công cụ nhập profile](#tool-import_profile--công-cụ-nhập-profile)
- [Security & Privacy / Bảo mật & Riêng tư](#security--privacy--bảo-mật--riêng-tư)
- [Folder Structure / Cấu trúc thư mục](#folder-structure--cấu-trúc-thư-mục)
- [Troubleshooting / Sửa lỗi](#troubleshooting--sửa-lỗi)
- [Contributing / Đóng góp](#contributing--đóng-góp)
- [License / Giấy phép](#license--giấy-phép)

---

## Overview / Tổng quan

**Hermes Profile Migrator** là plugin Hermes Agent giúp bạn:

- **Xuất (export)** entire Hermes profile directory thành file nén `.zip` hoặc `.tar.gz`
- **Loại bỏ tự động** các API key nhạy cảm (OpenRouter, OpenAI, Anthropic, FAL, HuggingFace, v.v.) trước khi chia sẻ ra cộng đồng — chế độ **sanitized** (mặc định)
- **Di chuyển toàn bộ profile** giữa các máy của riêng bạn — chế độ **full**
- **Nhập (import)** profile đã xuất vào máy mới, tự động phát hiện username Windows và cập nhật lại tất cả đường dẫn trong config
- **[v1.1] Tự động đồng bộ 2 chiều** với private GitHub repo riêng của bạn — cài 1 lần, mọi máy cùng chia sẻ 1 profile, bộ nhớ (memories), phiên trò chuyện (sessions) và skills được hợp nhất tự động
- **[v1.1] Auto-check khi cài plugin** — Hermes sẽ tự check GitHub auth, tạo repo private nếu chưa có, hoặc sync bidirectional ngay nếu repo đã tồn tại

> ⚠️ **Không có plugin tương tự** trong registry hiện tại — đây là tool độc lập đầu tiên cho Hermes profile migration + sync.

---

## Features / Tính năng

| Tính năng | Mô tả |
|-----------|-------|
| **Sanitized export** (mặc định) | Tự động quét `.env`, `config.yaml`, `auth.json` và thay thế API key bằng `"YOUR_API_KEY_HERE"`. Tạo file `.env.example`, `config.example.yaml`. Xóa `auth.json` hoàn toàn. |
| **Full export** | Archive nguyên bản, dùng riêng để chuyển máy → máy trong cùng một người dùng. |
| **Tự động detect username Windows** | Khi import, plugin đọc đường dẫn cũ từ config, trích xuất username, và remap tất cả path sang machine mới. |
| **Hỗ trợ cả Linux/macOS** | Path remapping hoạt động với `/home/username` và `C:\Users\username`. |
| **Hai định dạng archive** | `.zip` (mặc định, cross-platform) và `.tar.gz` (nhỏ hơn, Linux/macOS friendly). |
| **CLI standalone** | Chạy trực tiếp `python plugin_api.py export|import|setup|sync|restore` mà không cần Hermes đang chạy. |
| **Hermes plugin integration** | Đăng ký với Hermes plugin system, gọi qua `hermes tools` hoặc gateway API. |
| **[v1.1] Private GitHub repo auto-create** | `setup_backup_repo` tự tạo private repo trên GitHub của bạn — không bao giờ public, bảo vệ config khỏi người khác xem. |
| **[v1.1] Bidirectional sync** | `sync_profile` kéo dữ liệu remote về local (nếu remote mới hơn), sau đó đẩy profile local lên repo. Hợp nhất state.db, memories, sessions, skills tự động. |
| **[v1.1] Auto-sync on plugin load** | `auto_sync_on_load()` chạy tự động khi Hermes load plugin — check auth, detect repo, sync hoặc tạo repo mới. |
| **[v1.1] Private enforcement** | Plugin kiểm tra visibility của repo trước mỗi sync — nếu repo bị public, REFUSE sync và báo user convert về private ngay. |

---

## 🔄 Bidirectional Sync — Đặc quyền v1.1

### Tại sao cần sync?

Thay vì export/import thủ công từng lần, plugin v1.1 cho phép bạn có **1 profile duy nhất được đồng bộ giữa mọi máy** qua private GitHub repo:

```
Máy A (Đà Nẵng)          Máy B (Hà Nội)           Máy C (nước ngoài)
     ↓                         ↓                         ↓
  [profile]  ←─────────→  [profile]  ←─────────→  [profile]
     ↓                         ↓                         ↓
  private repo ◄────────── private repo ◄────────── private repo
  (GitHub)                 (GitHub)                 (GitHub)
```

Mọi thay đổi trên máy này sẽ được đẩy lên repo, và các máy khác sẽ pull về khi sync.

---

## Installation / Cài đặt

### Option A — Install as Hermes plugin (recommended)

```bash
# 1. Copy folder into Hermes plugins directory
cp -r ~/Desktop/hermes-profile-migrator ~/.hermes/plugins/

# 2. Restart Hermes, or reload plugins live
hermes plugins reload

# 3. Verify tools are registered
hermes tools list | grep -i migrator
```

> **Windows:** Thay `~/.hermes` bằng `%USERPROFILE%\.hermes` hoặc `C:\Users\<tên>\.hermes`.

### Option B — Run standalone (no Hermes needed)

```bash
cd ~/Desktop/hermes-profile-migrator
python plugin_api.py export --profile default --mode sanitized
python plugin_api.py import ~/Desktop/hermes-profile-default.zip
```

### Option C — Install as Python package (future)

```bash
pip install -e ~/Desktop/hermes-profile-migrator
```

---

## Usage — CLI / Sử dụng qua CLI

### Export a profile / Xuất một profile

```bash
# Sanitized export (mặc định — an toàn để chia sẻ)
python plugin_api.py export --profile default --mode sanitized --format zip

# Full export (chuyển máy riêng, giữ nguyên mọi secret)
python plugin_api.py export --profile default --mode full --format zip

# Xuất ra đường dẫn cụ thể
python plugin_api.py export --profile default --output "D:/backups/hermes-profile.zip" --mode sanitized
```

**Output ví dụ:**
```json
{
  "success": true,
  "archive_path": "C:\\Users\\Neito\\Desktop\\hermes-profile-default.zip",
  "mode": "sanitized",
  "files_sanitized": 7,
  "message": "Profile 'default' exported sanitized to C:\\Users\\Neito\\Desktop\\hermes-profile-default.zip (7 sensitive values redacted)."
}
```

### Import a profile / Nhập một profile

```bash
# Nhập profile từ file nén
python plugin_api.py import ~/Desktop/hermes-profile-default.zip

# Đổi tên profile khi nhập
python plugin_api.py import ~/Desktop/hermes-profile-default.zip --profile my-new-profile

# Ghi đè profile cũ nếu đã tồn tại
python plugin_api.py import ~/Desktop/hermes-profile-default.zip --overwrite
```

**Output ví dụ:**
```json
{
  "success": true,
  "profile_name": "default",
  "profile_path": "C:\\Users\\Neito\\.hermes\\profiles\\default",
  "paths_updated": 12,
  "message": "Profile 'default' imported to C:\\Users\\Neito\\.hermes\\profiles\\default (12 path(s) remapped)."
}
```

---

## Usage — Hermes Plugin / Sử dụng như plugin Hermes

Khi đã cài vào `~/.hermes/plugins/hermes-profile-migrator/`, hai tool `export_profile` và `import_profile` tự động đăng ký với Hermes. Bạn có thể gọi chúng trong bất kỳ phiên Hermes Agent nào:

```
export_profile(profile_name="default", mode="sanitized", format="zip")
```

```
import_profile(archive_path="/path/to/hermes-profile-default.zip", overwrite=false)
```

Tool definitions are declared in `schema.json` — Hermes reads them at plugin load time.

---

## 🔄 Setup & Sync Workflow / Quy trình đồng bộ

### Bước 1: Cài plugin (chỉ làm 1 lần)

```bash
# Copy vào Hermes plugins
cp -r ~/Desktop/hermes-profile-migrator ~/.hermes/plugins/

# Reload plugin
hermes plugins reload
```

### Bước 2: Plugin tự động chạy khi Hermes khởi động

Khi Hermes load plugin, `auto_sync_on_load()` tự động chạy:

1. **Check GitHub auth** — nếu chưa auth, báo user chạy `gh auth login`
2. **Check private repo** — nếu chưa có, tự tạo private repo `hermes-profile-backup` trên GitHub của user
3. **Nếu repo đã có** — pull remote archive về, merge state (state.db, memories, sessions, skills), sau đó push local profile lên repo
4. **Lưu config** vào `plugin_dir/config.json` để lần sau không phải setup lại

Output ví dụ khi Hermes khởi động:

```
✓ GitHub auth OK (user: Neito112)
✓ Private backup repo found: https://github.com/Neito112/hermes-profile-backup
✓ Sync complete: Profile 'default' synced to Neito112/hermes-profile-backup.
   Commit: a1b2c3d4e5f6. Remote changes merged: Merged memories: 2 copied, 0 skipped.
```

### Bước 3: Sync thủ công (khi muốn đồng bộ ngay)

```bash
# Sync profile (pull remote + push local)
python plugin_api.py sync --profile default --mode sanitized

# Hoặc qua Hermes tool
sync_profile(profile_name="default", mode="sanitized")
```

### Bước 4: Restore từ repo (nếu làm mới máy hoặc muốn reset về state cũ)

```bash
# Restore latest từ repo
python plugin_api.py restore --profile default

# Restore từ commit cụ thể (branch, tag, hoặc commit SHA)
python plugin_api.py restore --profile default --version v1.0.0
```

### Tool mới trong v1.1

| Tool | Mô tả |
|------|-------|
| `setup_backup_repo` | Tạo private repo trên GitHub của user. Chỉ private — không bao giờ public. Lưu config local. |
| `sync_profile` | Pull remote archive về → merge state.db/memories/sessions/skills → push local profile lên repo. |
| `restore_profile` | Pull archive từ repo (có thể chọn branch/tag/commit) → import vào local profile. |
| `auto_sync_on_load` | Chạy tự động khi Hermes load plugin. Check auth, detect repo, sync hoặc tạo repo mới. |

### Flow chi tiết của `sync_profile`

```
1. Kiểm tra config → lấy repo_slug, profile_name
2. Verify repo vẫn private (nếu public → REFUSE syncing, bảo lưu security)
3. Pull remote archive mới nhất từ repo (tìm file *.zip trong repo)
4. Nếu có remote archive:
   a. Extract ra temp dir
   b. So sánh state.db: nếu remote mới hơn → replace local (backup local trước)
   c. Merge memories: copy remote memories chưa có local, nếu conflict → keep cả 2 (local backup dengan timestamp)
   d. Merge sessions: copy remote sessions chưa có local
   e. Merge skills: copy remote skills chưa có local
5. Export local profile sang archive (sanitized hoặc full tùy mode)
6. Push archive lên repo với commit message
7. Trả về result: repo_url, commit_sha, merge_stats
```

### State merge strategy

| Component | Chiến lược merge |
|-----------|-----------------|
| **state.db** (SQLite session store) | Nếu remote mới hơn local → replace local, backup local trước. Nếu local mới hơn → keep local. |
| **memories/** | Copy remote files chưa có local. Nếu file cùng tên nhưng content khác → backup local với timestamp suffix, replace bằng remote. |
| **sessions/** | Copy remote session files chưa có local. Không overwrite local sessions. |
| **skills/** | Copy remote skills (files + dirs) chưa có local. Không overwrite local skills. |

### Private enforcement

Plugin tự động check visibility của repo trước mỗi sync:

```python
if repo_info.get("visibility") != "private":
    return {
        "success": False,
        "message": f"SECURITY: Repo {owner}/{repo} is now PUBLIC. Convert back to private.",
    }
```

Nếu user vô tình đổi repo thành public (hoặc ai đó invite user vào org làm public), plugin sẽ REFUSE sync và báo user convert về private ngay. Đảm bảo profile không để lộ ra public.

---

## Tool: export_profile / Công cụ xuất profile

| Tham số | Kiểu | Mặc định | Mô tả |
|---------|------|----------|-------|
| `profile_name` | string | `"default"` | Tên profile directory trong `~/.hermes/profiles/<name>`. |
| `output_path` | string | *(Desktop)* | Đường dẫn file đích. Nếu không truyền, sẽ nằm trên Desktop với tên `hermes-profile-<name>.zip`. |
| `mode` | `"sanitized"` \| `"full"` | `"sanitized"` | `"sanitized"`: loại bỏ API key, tạo file example, xóa `auth.json`. `"full"`: giữ nguyên mọi thứ, chỉ dùng chuyển máy nội bộ. |
| `format` | `"zip"` \| `"tar.gz"` | `"zip"` | Định dạng nén. |

**Behavior / Hành vi:**

1. Copy profile directory vào temporary folder
2. Nếu `mode == "sanitized"`:
   - `.env` → xóa, tạo `.env.example` với các dòng `KEY = "YOUR_API_KEY_HERE"`
   - `.env.*` (ví dụ `.env.local`) → xử lý tương tự
   - `config.yaml` → quét tất cả string value, thay thế API key bằng placeholder, tạo `config.example.yaml`
   - `auth.json` → xóa hoàn toàn
   - Count số lượng giá trị đã redact
3. Nén thư mục temporary thành file archive
4. Trả về đường dẫn archive và số lượng sensitive values đã xử lý

**API keys được detect (pattern matching):**

| Service | Environment variable / YAML key |
|---------|--------------------------------|
| OpenAI | `OPENAI_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |
| FAL | `FAL_KEY`, `FAL_API_KEY` |
| HuggingFace | `HUGGING_FACE_HUB_TOKEN`, `HUGGINGFACE_TOKEN` |
| Google / Gemini | `GOOGLE_API_KEY`, `GEMINI_API_KEY` |
| Stability AI | `STABILITY_API_KEY` |
| Generic bearer/token | `bearer = "..."` , `token = "..."` |
| Generic secret/password | `secret = "..."`, `password = "..."` |

> Mọi pattern dùng regex case-insensitive. Nếu bạn có API key theo dạng khác, hãy mở issue để thêm pattern.

---

## Tool: import_profile / Công cụ nhập profile

| Tham số | Kiểu | Mặc định | Mô tả |
|---------|------|----------|-------|
| `archive_path` | string | *(bắt buộc)* | Đường dẫn file `.zip` hoặc `.tar.gz` đã export. |
| `target_profile` | string | *(tên gốc)* | Tên profile sau khi import. Nếu không truyền, dùng tên directory trong archive. |
| `overwrite` | boolean | `false` | Nếu `true`, xóa profile cũ nếu trùng tên. Nếu `false`, abort và báo lỗi. |
| `preserve_relative_paths` | boolean | `true` | Chỉ remap absolute path dưới thư mục home cũ. Path tương đối và path ngoài home giữ nguyên. |

**Behavior / Hành vi:**

1. Giải nén archive vào temporary folder
2. Tìm profile directory bên trong (nếu archive chứa thư mục `<name>/`)
3. Đọc `config.yaml` và `config.json` bên trong, tìm đường dẫn chứa username cũ (ví dụ `C:\Users\OldName\...` hoặc `/home/oldname/...`)
4. Tự động thay thế đường dẫn cũ bằng đường dẫn mới dựa trên username hiện tại
5. Copy profile vào `~/.hermes/profiles/<target_profile>/`
6. Trả về số lượng path đã remap

**Path remapping logic / Logic cập nhật đường dẫn:**

- Plugin đọc `config.yaml` / `config.json` trong archive, tìm các string value chứa đường dẫn home cũ
- Thay thế toàn bộ occurrence của old home path bằng new home path
- Ví dụ: `C:\Users\OldUser\.hermes\skills` → `C:\Users\NewUser\.hermes\skills`
- Path tương đối (ví dụ `./skills`) không bị đụng

---

## Security & Privacy / Bảo mật & Riêng tư

### Chế độ Sanitized (mặc định — recommended cho community sharing)

- ✅ Tất cả API key trong `.env` được thay thế bằng `"YOUR_API_KEY_HERE"` trước khi nén
- ✅ `.env` gốc được **xóa** — không bao giờ xuất hiện trong archive
- ✅ `config.yaml` được scan toàn bộ nested structure, mọi string trùng pattern key được redact
- ✅ `auth.json` (chứa OAuth token) bị **xóa hoàn toàn**
- ✅ File example (`.env.example`, `config.example.yaml`) được tạo để người nhận biết trước dạng cấu hình cần điền

**Những gì vẫn còn trong archive sanitized:**
- Cấu hình không nhạy cảm: model settings, display preferences, plugin configurations, slash commands, cron jobs
- Skills và templates (nếu có trong profile)
- Session transcripts và memory (nếu có)

### Chế độ Full

- ⚠️ **CHỈ dùng để chuyển giữa các máy của riêng bạn.**
- Không chia sẻ ra cộng đồng, GitHub, forum.
- Chứa toàn bộ: API keys, OAuth tokens, session data, memory DB.

### Sau khi import

- Hãy kiểm tra lại `.env` và `config.yaml` sau khi import — một số cấu hình có thể cần điều chỉnh theo environment mới
- Nếu profile import là sanitized version, hãy điền lại API key vào `.env` từ `.env.example`
- Chạy `hermes doctor` để verify config sau import

---

## Folder Structure / Cấu trúc thư mục

```
hermes-profile-migrator/
├── package.json          # Plugin metadata (tên, version, dependencies)
├── schema.json           # JSON Schema cho export_profile & import_profile tools
├── plugin_api.py         # Mã nguồn chính: 2 tool + helper functions + standalone CLI
├── README.md             # Tài liệu này (bilingual EN + VI)
└── LICENSE               # MIT License (tự tạo hoặc dùng ls để check)
```

Khi cài vào Hermes:
```
~/.hermes/plugins/hermes-profile-migrator/
├── package.json
├── schema.json
└── plugin_api.py
```

---

## Troubleshooting / Sửa lỗi

| Vấn đề | Nguyên nhân | Giải pháp |
|--------|------------|-----------|
| `Profile not found` khi export | Tên profile sai hoặc chưa tạo | Kiểm tra `~/.hermes/profiles/` và dùng đúng tên folder |
| `Archive not found` khi import | Đường dẫn file sai | Dùng đường dẫn tuyệt đối, kiểm tra file thực sự tồn tại |
| Import báo `Profile already exists` | Profile đích đã có | Thêm `overwrite=true` hoặc đổi `target_profile` |
| API key vẫn còn trong archive sanitized | Pattern không match format key của bạn | Mở issue, cung cấp dạng API key để thêm regex pattern |
| Path không được remap khi import | Thư mục gốc không nằm trong home, hoặc username không thay đổi | Kiểm tra `paths_updated` trong output — nếu = 0 thì config đã dùng relative path hoặc same-username |
| `ModuleNotFoundError: No module named 'yaml'` | Thiếu PyYAML | `pip install pyyaml` |
| Plugin không xuất hiện trong Hermes | Chưa reload hoặc cài sai thư mục | `hermes plugins reload`, kiểm tra lại đường dẫn `~/.hermes/plugins/` |

---

## Contributing / Đóng góp

1. Fork repo (nếu có) hoặc clone folder
2. Tạo branch: `git checkout -b feat/my-improvement`
3. Test: `python plugin_api.py export --profile default --mode sanitized`
4. Commit: `git commit -am 'feat: improve something'`
5. Push và mở Pull Request

**Cách thêm API key pattern mới:**

Chỉnh sửa tuple `SENSITIVE_PATTERNS` trong `plugin_api.py`:

```python
SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # ... existing patterns ...
    ("my_service_api_key", re.compile(r'MY_SERVICE_API_KEY\s*=\s*["\'][^"\']+["\']', re.IGNORECASE)),
]
```

---

## LICENSE

MIT License — xét theo `package.json`. Bạn được tự do sử dụng, sửa đổi, và phân phối cho cộng đồng Hermes.

---

*Dominoes by the community, for the community.*
