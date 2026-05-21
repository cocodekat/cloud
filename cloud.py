#!/usr/bin/env python3
"""
cloud.py — Your personal GitHub-powered cloud storage CLI

Commands:
  upload <local_path> <repo_name>              Upload a file or folder
  list   <repo_name> [remote_path]             List files in a repo (or subfolder)
  fetch  <repo_name> <remote_path>             Download a file or folder locally
  delete <repo_name> <remote_path>             Delete a file or folder from a repo
  repos                                        Show all configured repos
"""

import sys
import os
import json
import base64
import mimetypes
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌  Missing dependency: pip install requests")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "list.json"

RESET  = "\033[0m"
BOLD   = "\033[1m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
RED    = "\033[91m"
DIM    = "\033[2m"

def clr(color, text): return f"{color}{text}{RESET}"

# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> list[dict]:
    if not CONFIG_FILE.exists():
        print(clr(RED, f"❌  Config not found: {CONFIG_FILE}"))
        print(f"    Create it with at least one repo entry. See the README.")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_repo(name: str) -> dict:
    repos = load_config()
    for r in repos:
        if r["name"] == name:
            return r
    names = ", ".join(r["name"] for r in repos)
    print(clr(RED, f"❌  Repo '{name}' not found in list.json"))
    print(f"    Available: {names}")
    sys.exit(1)


# ── GitHub API helpers ────────────────────────────────────────────────────────

def gh_headers(token: str) -> dict:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def gh_get(url: str, token: str) -> requests.Response:
    r = requests.get(url, headers=gh_headers(token))
    return r


def gh_put(url: str, token: str, payload: dict) -> requests.Response:
    r = requests.put(url, headers=gh_headers(token), json=payload)
    return r


def api_url(repo_full: str, path: str = "") -> str:
    path = path.lstrip("/")
    base = f"https://api.github.com/repos/{repo_full}/contents"
    return f"{base}/{path}" if path else base


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_file(local_path: Path, remote_path: str, repo: dict):
    """Upload a single file, creating or updating as needed."""
    token     = repo["token"]
    repo_full = repo["repo"]
    url       = api_url(repo_full, remote_path)

    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    # Check if file exists (need SHA to update)
    sha = None
    existing = gh_get(url, token)
    if existing.status_code == 200:
        sha = existing.json().get("sha")

    payload = {
        "message": f"cloud: upload {remote_path}",
        "content": content,
    }
    if sha:
        payload["sha"] = sha

    resp = gh_put(url, token, payload)

    if resp.status_code in (200, 201):
        action = "Updated" if sha else "Uploaded"
        print(clr(GREEN, f"  ✓ {action}") + f"  {remote_path}")
    else:
        print(clr(RED, f"  ✗ Failed")  + f"  {remote_path}  →  {resp.status_code}: {resp.json().get('message','')}")


def upload(local: str, repo_name: str):
    repo       = get_repo(repo_name)
    local_path = Path(local)

    if not local_path.exists():
        print(clr(RED, f"❌  Path not found: {local}"))
        sys.exit(1)

    print(clr(BOLD, f"\n☁  Uploading to [{repo_name}]  ({repo['repo']})\n"))

    if local_path.is_file():
        upload_file(local_path, local_path.name, repo)

    elif local_path.is_dir():
        folder_name = local_path.name
        files = [p for p in local_path.rglob("*") if p.is_file()]
        if not files:
            print(clr(YELLOW, "  (empty folder — nothing to upload)"))
            return
        for f in sorted(files):
            relative   = f.relative_to(local_path.parent)   # keeps folder name
            remote_path = str(relative).replace("\\", "/")
            upload_file(f, remote_path, repo)
    else:
        print(clr(RED, f"❌  Unsupported path type: {local}"))
        sys.exit(1)

    print()


# ── List ──────────────────────────────────────────────────────────────────────

def list_repo(repo_name: str, remote_path: str = ""):
    repo      = get_repo(repo_name)
    token     = repo["token"]
    repo_full = repo["repo"]

    print(clr(BOLD, f"\n☁  [{repo_name}]  ({repo['repo']})  /{remote_path}\n"))

    def _list(path: str, indent: int = 0):
        url  = api_url(repo_full, path)
        resp = gh_get(url, token)

        if resp.status_code == 404:
            print(clr(RED, f"❌  Path not found: /{path}"))
            return
        if resp.status_code != 200:
            print(clr(RED, f"❌  GitHub error {resp.status_code}: {resp.json().get('message','')}"))
            return

        items = resp.json()
        if isinstance(items, dict):
            # Single file returned
            size = items.get("size", 0)
            print("  " * indent + clr(CYAN, "📄  ") + items["name"] + clr(DIM, f"  ({_human(size)})"))
            return

        dirs  = [i for i in items if i["type"] == "dir"]
        files = [i for i in items if i["type"] == "file"]

        for d in sorted(dirs, key=lambda x: x["name"]):
            print("  " * indent + clr(YELLOW, "📁  ") + clr(BOLD, d["name"] + "/"))
            _list(d["path"], indent + 1)

        for fi in sorted(files, key=lambda x: x["name"]):
            size = fi.get("size", 0)
            print("  " * indent + clr(CYAN, "📄  ") + fi["name"] + clr(DIM, f"  ({_human(size)})"))

    _list(remote_path)
    print()


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"

# ── Delete ────────────────────────────────────────────────────────────────────

def delete(repo_name: str, remote_path: str, force: bool = False):
    repo      = get_repo(repo_name)
    token     = repo["token"]
    repo_full = repo["repo"]

    print(clr(BOLD, f"\n☁  Deleting from [{repo_name}]  ({repo['repo']})  /{remote_path}\n"))

    def _delete_file(path: str):
        url  = api_url(repo_full, path)
        resp = gh_get(url, token)

        if resp.status_code == 404:
            print(clr(RED, f"❌  Not found on remote: {path}"))
            sys.exit(1)
        if resp.status_code != 200:
            print(clr(RED, f"❌  GitHub error {resp.status_code}: {resp.json().get('message', '')}"))
            sys.exit(1)

        data = resp.json()
        sha  = data["sha"]

        resp2 = requests.delete(url, headers=gh_headers(token), json={
            "message": f"cloud: delete {path}",
            "sha": sha,
        })

        if resp2.status_code == 200:
            print(clr(GREEN, f"  ✓ Deleted") + f"  {path}")
        else:
            print(clr(RED, f"  ✗ Failed") + f"  {path}  →  {resp2.status_code}: {resp2.json().get('message', '')}")

    def _delete_item(path: str):
        url  = api_url(repo_full, path)
        resp = gh_get(url, token)

        if resp.status_code == 404:
            print(clr(RED, f"❌  Not found on remote: {path}"))
            sys.exit(1)
        if resp.status_code != 200:
            print(clr(RED, f"❌  GitHub error {resp.status_code}: {resp.json().get('message', '')}"))
            sys.exit(1)

        data = resp.json()

        if isinstance(data, list):
            # Directory — delete all children recursively first
            for item in data:
                _delete_item(item["path"])
        elif isinstance(data, dict):
            if data["type"] == "dir":
                _delete_item(data["path"])
            else:
                _delete_file(data["path"])

    if not force:
        answer = input(clr(YELLOW, f"  Delete '{remote_path}' from {repo_full}? [y/N] "))
        if answer.strip().lower() != "y":
            print("  Aborted.")
            return

    _delete_item(remote_path)
    print()

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch(repo_name: str, remote_path: str):
    repo      = get_repo(repo_name)
    token     = repo["token"]
    repo_full = repo["repo"]

    print(clr(BOLD, f"\n☁  Fetching from [{repo_name}]  →  ./{Path(remote_path).name}\n"))

    def _fetch_item(path: str):
        url  = api_url(repo_full, path)
        resp = gh_get(url, token)

        if resp.status_code == 404:
            print(clr(RED, f"❌  Not found on remote: {path}"))
            sys.exit(1)
        if resp.status_code != 200:
            print(clr(RED, f"❌  GitHub error {resp.status_code}: {resp.json().get('message','')}"))
            sys.exit(1)

        data = resp.json()

        if isinstance(data, list):
            # It's a directory
            for item in data:
                _fetch_item(item["path"])

        elif isinstance(data, dict):
            if data["type"] == "dir":
                _fetch_item(data["path"])
            else:
                _save_file(data)

    def _save_file(data: dict):
        local_path = Path(data["path"])
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if data.get("encoding") == "base64":
            content = base64.b64decode(data["content"])
        else:
            # Fallback: fetch raw
            raw = requests.get(data["download_url"], headers=gh_headers(token))
            content = raw.content

        local_path.write_bytes(content)
        size = len(content)
        print(clr(GREEN, f"  ✓ Saved") + f"  {data['path']}  " + clr(DIM, f"({_human(size)})"))

    _fetch_item(remote_path)
    print()


# ── Repos ─────────────────────────────────────────────────────────────────────

def show_repos():
    repos = load_config()
    print(clr(BOLD, f"\n☁  Configured repos  ({CONFIG_FILE})\n"))
    for r in repos:
        token_preview = r["token"][:8] + "..." if len(r.get("token","")) > 8 else "(no token)"
        print(f"  {clr(BOLD+CYAN, r['name'])}  →  {r['repo']}  {clr(DIM, token_preview)}")
    print()


# ── Help ──────────────────────────────────────────────────────────────────────

def show_help():
    print(f"""
{clr(BOLD, "☁  cloud.py — GitHub-powered personal cloud")}

{clr(BOLD, "Usage:")}
  python cloud.py upload <local_path> <repo_name>        Upload file or folder
  python cloud.py list   <repo_name> [remote_path]       List files (optional subfolder)
  python cloud.py fetch  <repo_name> <remote_path>       Download file or folder
  python cloud.py delete <repo_name> <remote_path>       Delete file or folder
  python cloud.py repos                                  Show configured repos

{clr(BOLD, "Examples:")}
  python cloud.py upload ./test.py         myrepo
  python cloud.py upload ./src/            myrepo
  python cloud.py list   myrepo
  python cloud.py list   myrepo src/
  python cloud.py fetch  myrepo test.py
  python cloud.py fetch  myrepo src/
  python cloud.py delete myrepo test.py
  python cloud.py delete myrepo src/

{clr(BOLD, "Config:")}
  Edit list.json to add repos. Each entry needs:
    name   — short name you use in commands
    repo   — GitHub repo as owner/reponame
    token  — GitHub personal access token (needs repo scope)
""")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        show_help()
        return

    cmd = args[0].lower()

    if cmd == "upload":
        if len(args) < 3:
            print(clr(RED, "Usage: cloud.py upload <local_path> <repo_name>"))
            sys.exit(1)
        upload(args[1], args[2])

    elif cmd == "list":
        if len(args) < 2:
            print(clr(RED, "Usage: cloud.py list <repo_name> [remote_path]"))
            sys.exit(1)
        remote = args[2] if len(args) >= 3 else ""
        list_repo(args[1], remote)

    elif cmd == "fetch":
        if len(args) < 3:
            print(clr(RED, "Usage: cloud.py fetch <repo_name> <remote_path>"))
            sys.exit(1)
        fetch(args[1], args[2])

    elif cmd == "delete":
        if len(args) < 3:
            print(clr(RED, "Usage: cloud.py delete <repo_name> <remote_path>"))
            sys.exit(1)
        force = "--force" in args or "-f" in args
        delete(args[1], args[2], force=force)

    elif cmd == "repos":
        show_repos()

    else:
        print(clr(RED, f"❌  Unknown command: {cmd}"))
        show_help()
        sys.exit(1)


if __name__ == "__main__":
    main()