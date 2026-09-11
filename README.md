# Hermes Profile Migrator

> Export and import Hermes Agent profiles with automatic API key sanitization and path remapping.

[![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)](package.json)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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

> ⚠️ **Không có plugin tương tự** trong registry hiện tại — đây là tool độc lập đầu tiên cho Hermes profile migration.

---

## Features / Tính năng

| Tính năng | Mô tả |
|-----------|-------|
| **Sanitized export** (mặc định) | Tự động quét `.env`, `config.yaml`, `auth.json` và thay thế API key bằng `"YOUR_API_KEY_HERE"`. Tạo file `.env.example`, `config.example.yaml`. Xóa `auth.json` hoàn toàn. |
| **Full export** | Archive nguyên bản, dùng riêng để chuyển máy → máy trong cùng một người dùng. |
| **Tự động detect username Windows** | Khi import, plugin đọc đường dẫn cũ từ config, trích xuất username, và remap tất cả path sang machine mới. |
| **Hỗ trợ cả Linux/macOS** | Path remapping hoạt động với `/home/username` và `C:\Users\username`. |
| **Hai định dạng archive** | `.zip` (mặc định, cross-platform) và `.tar.gz` (nhỏ hơn, Linux/macOS friendly). |
| **CLI standalone** | Chạy trực tiếp `python plugin_api.py export|import` mà không cần Hermes đang chạy. |
| **Hermes plugin integration** | Đăng ký với Hermes plugin system, gọi qua `hermes tools` hoặc gateway API. |

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
