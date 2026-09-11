# Hermes Profile Migrator — Agent Handshake Protocol

**Bản dành cho AI Agent** — đọc file này để biết cách cài và sử dụng plugin mà không cần human intervention.

---

## Cá nhân hóa

Bạn là một Hermes Agent. Kamu memiliki:
- `${HERMES_HOME}` — thư mục cấu hình Hermes của host (thường là `~/.hermes/`)
- `gh` CLI — đã được auth sẵn qua Hermes OAuth
- Python 3.11+ — có thể chạy script

---

## Context: Tại sao cần plugin này?

Agent có thể có nhiều profile khác nhau trên nhiều máy. Mục đích của plugin:
- **Backup**: lưu profile vào private GitHub repo, tránh mất khi format/reinstall
- **Sync**: chia sẻ state.db, memories, sessions, skills giữa các máy
- **Portability**: di chuyển profile giữa máy dễ dàng

---

## STEP 1: Kiểm tra plugin đã cài chưa

Chạy lệnh:

```bash
python3 "${HERMES_HOME}/plugins/hermes-profile-migrator/install.py" --list
```

Hoặc kiểm tra trực tiếp:

```bash
[ -d "${HERMES_HOME}/plugins/hermes-profile-migrator" ] && echo "INSTALLED" || echo "NOT INSTALLED"
```

---

## STEP 2: Cài plugin (nếu chưa có)

Nếu chưa cài, chạy:

```bash
python3 "${HERMES_HOME}/plugins/hermes-profile-migrator/install.py" \
  --repo https://github.com/Neito112/hermes-profile-migrator
```

Hoặc nếu muốn cài từ fork khác:

```bash
python3 "${HERMES_HOME}/plugins/hermes-profile-migrator/install.py" \
  --repo https://github.com/USERNAME/hermes-profile-migrator
```

Script sẽ:
1. Clone repo vào `${HERMES_HOME}/plugins/hermes-profile-migrator`
2. Kiểm tra file cần thiết (`plugin_api.py`, `package.json`)
3. Lưu record vào `${HERMES_HOME}/.installed_plugins.json`
4. Tự chạy `hermes plugins reload` (nếu Hermes CLI có sẵn)

---

## STEP 3: Sử dụng plugin

Sau khi cài, plugin tự đăng ký với Hermes. Bạn có thể gọi tools:

### Auto-sync on load (tự động chạy khi Hermes khởi động)

Plugin tự động gọi `auto_sync_on_load()` khi Hermes load. Bạn không cần làm gì — plugin sẽ:
- Check GitHub auth
- Tạo private repo nếu chưa có
- Pull remote changes về local
- Push local lên remote

Nếu plugin cần human action (vd: cần `gh auth login`), plugin sẽ trả về message chứa `action_needed`.

### Gọi tool thủ công

```python
# Nếu đang chạy trong Hermes Agent session, bạn có thể gọi:
export_profile(profile_name="default", mode="sanitized")
import_profile(archive_path="/path/to/archive.zip", overwrite=False)
setup_backup_repo(repo_name="hermes-profile-backup", profile_name="default")
sync_profile(profile_name="default", mode="sanitized")
restore_profile(profile_name="default", version="main")
```

### CLI standalone (nếu không có Hermes Agent session)

```bash
python3 plugin_api.py export --profile default --mode sanitized
python3 plugin_api.py import /path/to/archive.zip --profile default --overwrite
python3 plugin_api.py setup --profile default
python3 plugin_api.py sync --profile default --mode sanitized
python3 plugin_api.py restore --profile default --version main
python3 plugin_api.py auto-check
```

---

## STEP 4: Sync giữa các máy

Công thức sync:

**Trên MÁY A (có dữ liệu mới):**
```bash
python3 plugin_api.py sync --profile default --mode sanitized
```

**Trên MÁY B (muốn nhận dữ liệu từ A):**
```bash
python3 plugin_api.py restore --profile default
```

Hoặc chỉ cần đảm bảo plugin auto_sync_on_load hoạt động khi Hermes khởi động — plugin tự pull remote về.

---

## STEP 5: Hỏi human nếu cần

Nếu plugin trả về message chứa `action_needed` hoặc `success: false` với lý do auth-related:

- **GitHub auth failed**: Hỏi human chạy `gh auth login`
- **Repo public**: Hỏi human đổi repo về private: `gh repo edit hermes-profile-backup --visibility private`
- **Clone failed**: Hỏi human check network / GitHub access

---

## Tóm tắt tool signatures

```
export_profile(profile_name:str="default", output_path:str="", mode:"sanitized"|"full"="sanitized", format:"zip"|"tar.gz"="zip") →
  {success:bool, archive_path:str, mode:str, files_sanitized:int, message:str}

import_profile(archive_path:str="", target_profile:str="", overwrite:bool=false, preserve_relative_paths:bool=true) →
  {success:bool, profile_name:str, profile_path:str, paths_updated:int, message:str}

setup_backup_repo(repo_name:str="hermes-profile-backup", profile_name:str="default", add_readme:bool=true) →
  {success:bool, repo_url:str, repo_name:str, profile_name:str, message:str}

sync_profile(profile_name:str="", mode:"sanitized"|"full"="sanitized", message:str="") →
  {success:bool, repo_url:str, commit:str, profile_name:str, remote_synced:bool, merge_stats:object, message:str}

restore_profile(profile_name:str="", version:str="") →
  {success:bool, profile_name:str, profile_path:str, message:str}

auto_sync_on_load() →
  {success:bool, message:str, repo_url:str, profile_name:str, synced:bool, repo_created:bool, action_needed:str?}
```

---

## Security awareness

Plugin **luôn kiểm tra visibility của repo** trước mỗi sync. Nếu repo bị đổi thành public, plugin REFUSE sync và trả về message rõ ràng.

Plugin **không bao giờ tạo public repo** — chỉ private. Nếu repo becomes public, user phải tự convert về private trước khi sync được.

Plugin **không lưu credential** trong config — chỉ lưu repo_url và profile_name (không gửi GitHub token).

---

## Uninstall

```bash
python3 "${HERMES_HOME}/plugins/hermes-profile-migrator/install.py" --uninstall hermes-profile-migrator
```

Hoặc thủ công:

```bash
rm -rf "${HERMES_HOME}/plugins/hermes-profile-migrator"
hermes plugins reload
```

---

## Troubleshooting agent-side

| Lỗi | Nguyên nhân | Hành động |
|-----|------------|-----------|
| `GitHub CLI not authenticated` | `gh auth status` failed | Hỏi human chạy `gh auth login` |
| `Cannot access repo` | Repo không tồn tại, hoặc token không có permission | Kiểm tra repo URL, kiểm tra token scope (`repo` permission) |
| `No backup repo configured` | Chưa chạy `setup_backup_repo` | Chạy `setup_backup_repo` trước |
| `Archive not found in repo` | Repo trống, chưa có profile archive nào được push | Chạy `sync_profile` từ máy có dữ liệu trước |
| `Plugin not registered` | Hermes chưa reload plugins | Chạy `hermes plugins reload` |

---

*Plugin tự động hóa profile backup + sync. Bạn chỉ cần cài 1 lần — sau đó tự hoạt động.*
