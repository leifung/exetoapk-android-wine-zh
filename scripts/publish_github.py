#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 port/github/ 推到 GitHub 仓库，创建 Release 并上传轻量版 APK。

Token 只从环境变量 GH_TOKEN 读取，绝不写入文件、不打印、不进仓库。
  GH_TOKEN=xxx python port/scripts/publish_github.py              # 全量
  GH_TOKEN=xxx python port/scripts/publish_github.py --no-asset  # 只推文件+建 Release
  GH_TOKEN=xxx python port/scripts/publish_github.py --asset-only # 只补传 APK

脚本可重复运行：仓库/Release/asset 已存在时复用，内容有变化才覆盖。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "github"
DIST = ROOT / "dist"
APK_LOCAL = "exetoapk安卓wine模拟器汉化.apk"      # 本地构建产物（应用显示名同名）
# GitHub 会把 Release 附件名里的非 ASCII 字符清理成点号（中文名会变成 exetoapk.wine.apk），
# 因此附件统一用规范 ASCII 名，并在 README / RELEASE_NOTES 中写明。
ASSET_NAME = "exetoapk-android-wine-zh.apk"
REPO = os.environ.get("GITHUB_REPO", "exetoapk-android-wine-zh")
TAG = "v1.0.0"
RELEASE_TITLE = "exetoapk安卓wine模拟器汉化 v1.0"
UA = "workbuddy-publisher"
TOKEN = os.environ.get("GH_TOKEN", "")


def api(method: str, path: str, data=None, allow_404: bool = False, timeout: int = 120):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request("https://api.github.com" + path, data=body,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8")
            return (json.loads(raw) if raw.strip() else {}), r.headers
    except urllib.error.HTTPError as e:
        if allow_404 and e.code == 404:
            return None, e.headers
        detail = e.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from None


def payload_files() -> list[tuple[str, Path]]:
    out = []
    for p in sorted(PAYLOAD.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(PAYLOAD).parts
        if any(x.startswith(".") and x != ".gitignore" for x in parts):
            continue
        if p.suffix.lower() in (".apk", ".idsig", ".jks", ".keystore", ".tzst", ".pyc"):
            continue
        out.append((p.relative_to(PAYLOAD).as_posix(), p))
    return out


def push_files(owner: str, repo: str, branch: str) -> str:
    ref, _ = api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
    base_commit = ref["object"]["sha"]
    commit, _ = api("GET", f"/repos/{owner}/{repo}/git/commits/{base_commit}")
    base_tree = commit["tree"]["sha"]

    tree_items = []
    for rel, p in payload_files():
        blob, _ = api("POST", f"/repos/{owner}/{repo}/git/blobs",
                      {"content": base64.b64encode(p.read_bytes()).decode("ascii"),
                       "encoding": "base64"})
        tree_items.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob {rel} ({p.stat().st_size} B)", flush=True)

    tree, _ = api("POST", f"/repos/{owner}/{repo}/git/trees",
                  {"base_tree": base_tree, "tree": tree_items})
    if tree["sha"] == base_tree:
        print(">>> 仓库内容已是最新，跳过提交", flush=True)
        return base_commit
    new_commit, _ = api("POST", f"/repos/{owner}/{repo}/git/commits",
                        {"message": "chore: 发布 exetoapk 安卓 wine 模拟器汉化版（全中文界面 + 容器模板修复）",
                         "tree": tree["sha"], "parents": [base_commit]})
    api("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
        {"sha": new_commit["sha"]})
    print(f">>> 已提交 {len(tree_items)} 个文件，commit {new_commit['sha'][:10]}", flush=True)
    return new_commit["sha"]


def ensure_release(owner: str, repo: str, branch: str) -> dict:
    notes = (PAYLOAD / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    rel, _ = api("GET", f"/repos/{owner}/{repo}/releases/tags/{urllib.parse.quote(TAG)}",
                 allow_404=True)
    if rel is None:
        rel, _ = api("POST", f"/repos/{owner}/{repo}/releases", {
            "tag_name": TAG, "target_commitish": branch, "name": RELEASE_TITLE,
            "body": notes, "draft": False, "prerelease": False})
        print(f">>> Release 已创建：{rel['html_url']}", flush=True)
    else:
        api("PATCH", f"/repos/{owner}/{repo}/releases/{rel['id']}",
            {"name": RELEASE_TITLE, "body": notes, "draft": False, "prerelease": False})
        print(f">>> Release 已更新：{rel['html_url']}", flush=True)
    return rel


class Progress:
    """流式读取 APK，边传边报进度，避免把 150MB 一次性读进内存。"""

    def __init__(self, fh, total: int):
        self.fh, self.total, self.done, self.mark = fh, total, 0, 0

    def read(self, n: int = -1) -> bytes:
        b = self.fh.read(n)
        self.done += len(b)
        step = self.done // (16 * 1024 * 1024)
        if step > self.mark:
            self.mark = step
            print(f"    已发送 {self.done / 1024 / 1024:.0f}/{self.total / 1024 / 1024:.0f} MB",
                  flush=True)
        return b


def upload_asset(owner: str, repo: str, rel: dict) -> dict:
    apk = DIST / APK_LOCAL
    if not apk.exists():
        raise FileNotFoundError(apk)
    size = apk.stat().st_size
    h = hashlib.sha256()
    with apk.open("rb") as f:
        for blk in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(blk)
    sha = "sha256:" + h.hexdigest()

    assets, _ = api("GET", f"/repos/{owner}/{repo}/releases/{rel['id']}/assets?per_page=100")
    apk_assets = [a for a in assets if a["name"].lower().endswith(".apk")]
    target = next((a for a in apk_assets if a["name"] == ASSET_NAME), None)
    if (len(apk_assets) == 1 and target and target["size"] == size
            and (not target.get("digest") or target["digest"] == sha)):
        print(">>> APK 附件已是最新，跳过上传", flush=True)
        return target
    for a in apk_assets:
        print(f">>> 删除旧附件 {a['name']}", flush=True)
        api("DELETE", f"/repos/{owner}/{repo}/releases/assets/{a['id']}")

    q = urllib.parse.quote(ASSET_NAME, safe="")
    url = (f"https://uploads.github.com/repos/{owner}/{repo}/releases/"
           f"{rel['id']}/assets?name={q}")
    headers = {
        "Authorization": "Bearer " + TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": UA,
        "Content-Type": "application/octet-stream",
        "Content-Length": str(size),
    }
    last = None
    for attempt in (1, 2):
        try:
            with apk.open("rb") as f:
                req = urllib.request.Request(url, data=Progress(f, size),
                                             headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=900) as r:
                    asset = json.loads(r.read().decode("utf-8"))
            print(f">>> APK 上传完成：{asset['name']}  {asset['size'] / 1024 / 1024:.1f} MB", flush=True)
            return asset
        except Exception as e:
            last = e
            print(f">>> 第 {attempt} 次上传失败：{type(e).__name__}: {str(e)[:200]}", flush=True)
    raise RuntimeError(f"APK 上传失败：{last}")


def main() -> int:
    if not TOKEN:
        print("[ERROR] 缺少环境变量 GH_TOKEN", file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-asset", action="store_true")
    ap.add_argument("--asset-only", action="store_true")
    args = ap.parse_args()

    me, _ = api("GET", "/user")
    owner = os.environ.get("GITHUB_OWNER") or me["login"]
    repo, _ = api("GET", f"/repos/{owner}/{REPO}")
    branch = repo.get("default_branch") or "main"
    print(f">>> 目标仓库 {repo['html_url']}（分支 {branch}，公开={not repo['private']}）", flush=True)

    if not args.asset_only:
        push_files(owner, REPO, branch)
    rel = ensure_release(owner, REPO, branch)
    if not args.no_asset:
        upload_asset(owner, REPO, rel)

    rel, _ = api("GET", f"/repos/{owner}/{REPO}/releases/tags/{urllib.parse.quote(TAG)}")
    assets, _ = api("GET", f"/repos/{owner}/{REPO}/releases/{rel['id']}/assets?per_page=100")
    result = {
        "repo": f"https://github.com/{owner}/{REPO}",
        "release": rel["html_url"],
        "tag": TAG,
        "assets": [{"name": a["name"], "size_mb": round(a["size"] / 1024 / 1024, 1),
                    "url": a["browser_download_url"], "digest": a.get("digest")}
                   for a in assets],
    }
    print("\n=== 发布结果 ===\n" + json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
