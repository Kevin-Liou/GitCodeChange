# -*- coding: utf-8 -*-
"""
Git Commit Extractor
匯出指定 commit(或工作區未提交變更)的「變更前 / 變更後」檔案。
選多筆 commit 時可分開匯出(每筆一個資料夾),或合併成一包
(ORG = 最舊 commit 之前的版本,MOD = 最新 commit 之後的版本)。

輸出結構:
    <輸出資料夾>/<YYYY-MM-DD_commit 標題>/
        ORG/                變更前的檔案(原始版本)
        MOD/                變更後的檔案(修改版本)
        commit_message.txt  commit 資訊 + 變更檔案清單
        changes.patch       unified diff(可關閉)
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from tkinter import filedialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from ttkbootstrap.tooltip import ToolTip
from git import Repo, InvalidGitRepositoryError, NoSuchPathError

APP_NAME = "Git Commit Extractor"
APP_VERSION = "2.3"
CONFIG_FILE = os.path.expanduser("~/.git_export_tool_config.json")
MAX_HISTORY = 12

DEFAULT_THEME = "darkly"
THEME_CHOICES = ["darkly", "cyborg", "superhero", "solar", "vapor",
                 "flatly", "cosmo", "litera", "minty", "sandstone", "yeti"]
COMMIT_LIMITS = ["50", "100", "200", "500", "1000"]

UI_FONT_CANDIDATES = ["Microsoft JhengHei UI", "Microsoft JhengHei",
                      "Noto Sans TC", "Segoe UI"]
MONO_FONT_CANDIDATES = ["Cascadia Mono", "Consolas", "Courier New"]

# Files/folders that identify a directory as produced by this tool.
EXPORT_MARKERS = ("ORG", "MOD", "commit_message.txt")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def sanitize_filename(name, max_length=50):
    name = re.sub(r'[\\/*?:"<>| \n\r\t]+', "_", name.strip())
    return name[:max_length].strip("._ ") or "no_message"


def long_path(path):
    """Bypass the Windows MAX_PATH limit for deeply nested repositories."""
    if os.name != "nt":
        return path
    full = os.path.abspath(path)
    if len(full) < 240 or full.startswith("\\\\?\\"):
        return full
    if full.startswith("\\\\"):
        return "\\\\?\\UNC" + full[1:]
    return "\\\\?\\" + full


def ensure_parent(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(long_path(parent), exist_ok=True)


def write_blob(dest, blob, repo=None, attr_source=None, reporter=None):
    """Write a blob out the way `git checkout` would.

    blob.data_stream gives the raw object contents. With core.autocrlf=true or a
    .gitattributes `text=auto`, git stores text normalised to LF and only converts back
    to CRLF on checkout - so writing the raw stream produces LF files that differ from
    every file in the user's working tree.

    `git cat-file --filters` runs the same smudge/eol filters checkout does, which keeps
    ORG/ and MOD/ byte-identical to a real checkout.

    attr_source is the revision whose .gitattributes should govern the conversion.
    Without it git reads .gitattributes from the CURRENT working tree, so exporting a
    historical commit made before a .gitattributes change would apply today's rules and
    silently produce the wrong line endings. GIT_ATTR_SOURCE (git >= 2.40) points the
    attribute lookup at the right revision; on older git it is ignored and behaviour
    falls back to today's rules.

    strip_newline_in_stdout=False is required: GitPython otherwise eats the final byte,
    which on a CRLF file leaves a broken lone \\r at EOF.

    If the filtered read fails for any reason the raw stream is used, and - unlike a
    silent fallback - the reporter is told, because that output may have the wrong line
    endings and nothing else would reveal it.
    """
    ensure_parent(dest)
    data = None
    if repo is not None:
        try:
            args = ("--filters", blob.hexsha, "--path=" + blob.path)
            kw = dict(stdout_as_string=False, strip_newline_in_stdout=False)
            if attr_source:
                with repo.git.custom_environment(GIT_ATTR_SOURCE=str(attr_source)):
                    data = repo.git.cat_file(*args, **kw)
            else:
                data = repo.git.cat_file(*args, **kw)
        except Exception as e:
            data = None
            if reporter is not None:
                reporter.log(
                    f"   ⚠ {blob.path}：無法套用 checkout 轉換({e}),"
                    f"改用未轉換內容,換行符可能與工作區不同", "warning")
    if data is None:
        data = blob.data_stream.read()
    with open(long_path(dest), "wb") as f:
        f.write(data)


def copy_file(src, dest):
    ensure_parent(dest)
    shutil.copyfile(long_path(src), long_path(dest))


def looks_like_export_dir(path):
    return any(os.path.exists(os.path.join(path, m)) for m in EXPORT_MARKERS)


def push_history(history, path, limit=MAX_HISTORY):
    """Move path to the front of a most-recently-used list (case-insensitive)."""
    if not path or not path.strip():
        return history
    path = os.path.normpath(path.strip())
    kept = [p for p in history if p.lower() != path.lower()]
    kept.insert(0, path)
    del kept[limit:]
    return kept


def open_folder(path):
    if not path or not os.path.isdir(path):
        return False
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
    return True


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(data):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class Reporter:
    """Bridges the extraction core to a front-end (GUI or console)."""

    def __init__(self, log_fn=None, progress_fn=None, cancel_event=None):
        self._log_fn = log_fn or (lambda msg, tag="info": print(msg))
        self._progress_fn = progress_fn or (lambda done, total: None)
        self._cancel = cancel_event

    def log(self, msg, tag="info"):
        self._log_fn(msg, tag)

    def progress(self, done, total):
        self._progress_fn(done, total)

    @property
    def cancelled(self):
        return self._cancel is not None and self._cancel.is_set()


# --------------------------------------------------------------------------
# Extraction core
# --------------------------------------------------------------------------
def _prepare_output_dir(out_dir, reporter, overwrite):
    """Return True when out_dir is ready to receive files."""
    name = os.path.basename(out_dir)
    if os.path.exists(out_dir):
        if not overwrite:
            reporter.log(f"⚠ 已存在,略過：{name}", "warning")
            return False
        if not looks_like_export_dir(out_dir):
            reporter.log(f"⚠ 目標資料夾不像本工具的輸出，為避免誤刪而略過：{name}", "warning")
            return False
        shutil.rmtree(long_path(out_dir), ignore_errors=True)
        reporter.log(f"↻ 覆蓋既有資料夾：{name}", "warning")
    os.makedirs(long_path(os.path.join(out_dir, "ORG")), exist_ok=True)
    os.makedirs(long_path(os.path.join(out_dir, "MOD")), exist_ok=True)
    return True


def _write_note(path, header_lines, message, entries):
    counts = {}
    for status, _path in entries:
        counts[status] = counts.get(status, 0) + 1
    with open(long_path(path), "w", encoding="utf-8", errors="replace") as f:
        for line in header_lines:
            f.write(line + "\n")
        if message:
            f.write("\nMessage:\n")
            f.write(message.strip() + "\n")
        f.write("\nSummary: " +
                ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) +
                f"  (total {len(entries)})\n")
        f.write("\nChanged files:\n")
        for status, item in entries:
            f.write(f"  [{status}] {item}\n")


def _write_patch(out_dir, data, reporter):
    try:
        if not isinstance(data, bytes):
            data = data.encode("utf-8", "replace")
        # A patch whose last line has no trailing newline makes `git apply` fail with
        # "corrupt patch at line N". Callers pass strip_newline_in_stdout=False so this
        # should already hold; kept as a backstop for any other caller.
        if data and not data.endswith(b"\n"):
            data += b"\n"
        with open(long_path(os.path.join(out_dir, "changes.patch")), "wb") as f:
            f.write(data)
    except Exception as e:
        reporter.log(f"⚠ 無法輸出 changes.patch：{e}", "warning")


def _diff_to_changes(diff):
    """Turn a GitPython diff into (status, display path, ORG blob, MOD blob) tuples."""
    changes = []
    for ch in diff:
        if ch.renamed_file:
            changes.append(("RENAMED", f"{ch.rename_from} → {ch.rename_to}",
                            ch.a_blob, ch.b_blob))
        elif ch.deleted_file:
            changes.append(("DELETED", ch.a_path, ch.a_blob, ch.b_blob))
        elif ch.new_file:
            changes.append(("ADDED", ch.b_path, ch.a_blob, ch.b_blob))
        else:
            changes.append(("MODIFIED", ch.a_path, ch.a_blob, ch.b_blob))
    return changes


def _tree_to_changes(commit):
    """Every file of a root commit counts as newly added."""
    return [("ADDED", item.path, None, item)
            for item in commit.tree.traverse() if item.type == "blob"]


def _write_changes(out_dir, changes, reporter, repo=None,
                   org_rev=None, mod_rev=None):
    """Write every change into ORG/ and MOD/. Returns (entries, failed).

    repo is passed through to write_blob so blobs go through the checkout filters
    (line-ending conversion). Without it the output silently becomes LF-only.

    org_rev / mod_rev name the revisions each side came from, so .gitattributes is read
    from the right point in history rather than from today's working tree.
    """
    total = len(changes)
    entries, failed = [], 0
    for idx, (status, display, a_blob, b_blob) in enumerate(changes, 1):
        if reporter.cancelled:
            reporter.log("■ 使用者已取消", "warning")
            break
        reporter.progress(idx, total)
        try:
            if a_blob is not None:
                write_blob(os.path.join(out_dir, "ORG", a_blob.path), a_blob,
                           repo, org_rev, reporter)
            if b_blob is not None:
                write_blob(os.path.join(out_dir, "MOD", b_blob.path), b_blob,
                           repo, mod_rev, reporter)
            entries.append((status, display))
            reporter.log(f"   [{status}] {display}", status.lower())
        except Exception as e:
            failed += 1
            reporter.log(f"   ✖ 無法輸出 {display}：{e}", "error")
    return entries, failed


def is_same_line(repo, oldest, newest):
    """True when oldest is reachable from newest (i.e. they form a range)."""
    try:
        return repo.is_ancestor(oldest, newest)
    except Exception:
        return False


def order_commit_chain(commits, repo=None):
    """Return (oldest, newest, contiguous) for a set of commits.

    Uses first-parent links so the endpoints stay correct even when commit
    dates are out of order (rebase / cherry-pick / same-second commits).
    When the selection has gaps, falls back to an ancestry scan; commit dates
    only decide the scan order, never the result.
    """
    by_sha = {c.hexsha: c for c in commits}
    parent_of = {c.hexsha: (c.parents[0].hexsha
                            if c.parents and c.parents[0].hexsha in by_sha else None)
                 for c in commits}
    linked_parents = {p for p in parent_of.values() if p}
    tips = [c for c in commits if c.hexsha not in linked_parents]
    roots = [c for c in commits if parent_of[c.hexsha] is None]
    if len(tips) == 1 and len(roots) == 1:
        walk, cur = [], tips[0]
        while cur is not None:
            walk.append(cur)
            nxt = parent_of[cur.hexsha]
            cur = by_sha[nxt] if nxt else None
        if len(walk) == len(commits):
            return walk[-1], walk[0], True

    repo = repo or commits[0].repo
    ordered = sorted(commits, key=lambda c: c.committed_date)
    oldest = newest = ordered[0]
    for c in ordered[1:]:
        if is_same_line(repo, newest, c):
            newest = c
        if is_same_line(repo, c, oldest):
            oldest = c
    return oldest, newest, False


def commits_in_range(repo, oldest, newest):
    """SHAs covered by the oldest..newest range, oldest included."""
    try:
        shas = {c.hexsha for c in repo.iter_commits(f"{oldest.hexsha}..{newest.hexsha}")}
    except Exception:
        return set()
    shas.add(oldest.hexsha)
    return shas


def analyze_merge_selection(repo, commits):
    """Work out the range a merged export would cover.

    Returns (oldest, newest, contiguous, covered, outside) where covered is the
    number of commits inside the range and outside lists the selected commits
    that do not belong to it (i.e. they sit on a different branch).
    """
    oldest, newest, contiguous = order_commit_chain(commits, repo)
    if not is_same_line(repo, oldest, newest):
        return oldest, newest, False, 0, list(commits)
    range_shas = commits_in_range(repo, oldest, newest)
    outside = [c for c in commits if c.hexsha not in range_shas]
    return oldest, newest, contiguous, len(range_shas), outside


def extract_commit(repo, rev, output_base, reporter,
                   overwrite=False, with_patch=True, name_with_sha=False):
    """Export the before/after files of one commit. Returns a stats dict or None."""
    try:
        commit = repo.commit(rev)
    except Exception as e:
        reporter.log(f"✖ 找不到 commit「{rev}」：{e}", "error")
        return None

    message = (commit.message or "").strip()
    subject = next((l for l in message.splitlines() if l.strip()), "no_message")
    date = datetime.fromtimestamp(commit.committed_date)
    folder = f"{date.strftime('%Y-%m-%d')}_{sanitize_filename(subject)}"
    if name_with_sha:
        folder += f"_{commit.hexsha[:8]}"
    out_dir = os.path.join(output_base, folder)

    reporter.log(f"▶ {commit.hexsha[:8]}  {subject}", "head")
    if not _prepare_output_dir(out_dir, reporter, overwrite):
        return None

    parent = commit.parents[0] if commit.parents else None
    if parent is None:
        reporter.log("ℹ 此 commit 沒有父節點,視為全新加入所有檔案", "muted")
        changes = _tree_to_changes(commit)
    else:
        changes = _diff_to_changes(parent.diff(commit))

    if not changes:
        reporter.log("ℹ 此 commit 沒有檔案變更", "muted")
    entries, failed = _write_changes(
        out_dir, changes, reporter, repo,
        org_rev=(parent.hexsha if parent is not None else None),
        mod_rev=commit.hexsha)

    header = [
        f"Commit:  {commit.hexsha}",
        f"Author:  {commit.author.name} <{commit.author.email}>",
        f"Date:    {date.isoformat()}",
        f"Parent:  {parent.hexsha if parent else '(root commit)'}",
    ]
    _write_note(os.path.join(out_dir, "commit_message.txt"), header, message, entries)

    if with_patch:
        try:
            if parent is not None:
                data = repo.git.diff(parent.hexsha, commit.hexsha,
                                     stdout_as_string=False,
                                     strip_newline_in_stdout=False)
            else:
                data = repo.git.show(commit.hexsha,
                                     stdout_as_string=False,
                                     strip_newline_in_stdout=False)
            _write_patch(out_dir, data, reporter)
        except Exception as e:
            reporter.log(f"⚠ 無法產生 diff：{e}", "warning")

    reporter.log(f"✔ 完成 {len(entries)} 個檔案"
                 f"{f'(失敗 {failed})' if failed else ''} → {folder}", "success")
    return {"folder": folder, "out_dir": out_dir,
            "files": len(entries), "failed": failed}


def extract_commit_range(repo, revs, output_base, reporter,
                         overwrite=False, with_patch=True, name_with_sha=False):
    """Export several commits as ONE package: the combined change of the whole run.

    ORG holds the files as they were before the oldest commit, MOD as they are
    after the newest one, so intermediate edits collapse into a single result.
    """
    commits = []
    for rev in revs:
        try:
            commits.append(repo.commit(rev))
        except Exception as e:
            reporter.log(f"✖ 找不到 commit「{rev}」：{e}", "error")
            return None
    # Drop duplicates, keep it deterministic.
    commits = list({c.hexsha: c for c in commits}.values())
    if len(commits) == 1:
        return extract_commit(repo, commits[0].hexsha, output_base, reporter,
                              overwrite=overwrite, with_patch=with_patch,
                              name_with_sha=name_with_sha)

    oldest, newest, contiguous, covered, outside = analyze_merge_selection(repo, commits)
    if outside:
        reporter.log("✖ 選取的 commit 不在同一條線上(分屬不同分支),無法合併成一包", "error")
        return None
    subject = next((l for l in (newest.message or "").strip().splitlines()
                    if l.strip()), "no_message")
    date = datetime.fromtimestamp(newest.committed_date)
    folder = (f"{date.strftime('%Y-%m-%d')}_{sanitize_filename(subject, 40)}"
              f"_merged{len(commits)}")
    if name_with_sha:
        folder += f"_{oldest.hexsha[:8]}-{newest.hexsha[:8]}"
    out_dir = os.path.join(output_base, folder)

    reporter.log(f"▶ 合併匯出 {len(commits)} 筆 commit："
                 f"{oldest.hexsha[:8]} → {newest.hexsha[:8]}", "head")
    if not contiguous:
        reporter.log("⚠ 選取的 commit 並非單一連續鏈,已依 commit 祖先關係決定頭尾", "warning")
    if covered > len(commits):
        reporter.log(f"⚠ 這段範圍實際包含 {covered} 筆 commit,"
                     f"其中 {covered - len(commits)} 筆未被選取,變更也會一併匯出", "warning")
    if not _prepare_output_dir(out_dir, reporter, overwrite):
        return None

    base = oldest.parents[0] if oldest.parents else None
    if base is None:
        reporter.log("ℹ 起點是初始 commit,視為全新加入所有檔案", "muted")
        changes = _tree_to_changes(newest)
    else:
        changes = _diff_to_changes(base.diff(newest))

    if not changes:
        reporter.log("ℹ 這段範圍的總變更為空(可能互相抵銷了)", "muted")
    entries, failed = _write_changes(
        out_dir, changes, reporter, repo,
        org_rev=(base.hexsha if base is not None else None),
        mod_rev=newest.hexsha)

    ordered = sorted(commits, key=lambda c: c.committed_date)
    header = [
        f"Range:   {base.hexsha if base else '(root)'}..{newest.hexsha}",
        f"Commits: {len(commits)}"
        f"{'' if contiguous else ' (非連續選取)'}",
        f"Date:    {datetime.fromtimestamp(ordered[0].committed_date):%Y-%m-%d %H:%M}"
        f" ~ {date:%Y-%m-%d %H:%M}",
        "",
        "Merged commits (oldest → newest):",
    ]
    for c in ordered:
        line = next((l for l in (c.message or "").strip().splitlines() if l.strip()), "")
        header.append(f"  {c.hexsha[:8]}  "
                      f"{datetime.fromtimestamp(c.committed_date):%Y-%m-%d %H:%M}  "
                      f"{c.author.name}  {line}")
    if covered > len(commits):
        header.append(f"  (範圍內另有 {covered - len(commits)} 筆未選取的 commit)")
    _write_note(os.path.join(out_dir, "commit_message.txt"), header, None, entries)

    if with_patch:
        try:
            if base is not None:
                data = repo.git.diff(base.hexsha, newest.hexsha,
                                     stdout_as_string=False,
                                     strip_newline_in_stdout=False)
            else:
                data = repo.git.show(newest.hexsha,
                                     stdout_as_string=False,
                                     strip_newline_in_stdout=False)
            _write_patch(out_dir, data, reporter)
        except Exception as e:
            reporter.log(f"⚠ 無法產生 diff：{e}", "warning")

    reporter.log(f"✔ 完成 {len(entries)} 個檔案"
                 f"{f'(失敗 {failed})' if failed else ''} → {folder}", "success")
    return {"folder": folder, "out_dir": out_dir,
            "files": len(entries), "failed": failed}


def extract_working_tree(repo, output_base, reporter,
                         overwrite=False, with_patch=True, include_untracked=True):
    """Export uncommitted changes (working tree + index) against HEAD."""
    work_dir = repo.working_tree_dir
    folder = datetime.now().strftime("%Y-%m-%d_%H%M") + "_uncommitted"
    out_dir = os.path.join(output_base, folder)

    reporter.log("▶ 工作區未提交的變更", "head")
    try:
        head = repo.head.commit
    except Exception as e:
        reporter.log(f"✖ 無法讀取 HEAD：{e}", "error")
        return None

    # (status, path, blob for ORG, on-disk file for MOD)
    changes = []
    for d in head.diff(None):
        path = d.b_path or d.a_path
        disk = os.path.join(work_dir, path)
        if not os.path.exists(disk):
            changes.append(("DELETED", d.a_path, d.a_blob, None))
        elif d.a_blob is None:
            changes.append(("ADDED", path, None, disk))
        else:
            changes.append(("MODIFIED", path, d.a_blob, disk))

    if include_untracked:
        for path in repo.untracked_files:
            disk = os.path.join(work_dir, path)
            if os.path.isfile(disk):
                changes.append(("UNTRACKED", path, None, disk))

    if not changes:
        reporter.log("ℹ 工作區沒有任何未提交的變更", "muted")
        return None
    if not _prepare_output_dir(out_dir, reporter, overwrite):
        return None

    total = len(changes)
    entries, failed = [], 0
    for idx, (status, path, a_blob, disk) in enumerate(changes, 1):
        if reporter.cancelled:
            reporter.log("■ 使用者已取消", "warning")
            break
        reporter.progress(idx, total)
        try:
            if a_blob is not None:
                write_blob(os.path.join(out_dir, "ORG", a_blob.path), a_blob,
                           repo, "HEAD", reporter)
            if disk is not None:
                copy_file(disk, os.path.join(out_dir, "MOD", path))
            entries.append((status, path))
            reporter.log(f"   [{status}] {path}",
                         "added" if status == "UNTRACKED" else status.lower())
        except Exception as e:
            failed += 1
            reporter.log(f"   ✖ 無法輸出 {path}：{e}", "error")

    header = [
        "Commit:  (uncommitted working tree)",
        f"Base:    {head.hexsha}",
        f"Date:    {datetime.now().isoformat(timespec='seconds')}",
    ]
    _write_note(os.path.join(out_dir, "commit_message.txt"), header, None, entries)

    if with_patch:
        try:
            _write_patch(out_dir,
                         repo.git.diff("HEAD",
                                       stdout_as_string=False,
                                       strip_newline_in_stdout=False),
                         reporter)
            reporter.log("ℹ changes.patch 不包含未追蹤(untracked)檔案", "muted")
        except Exception as e:
            reporter.log(f"⚠ 無法產生 diff：{e}", "warning")

    reporter.log(f"✔ 完成 {len(entries)} 個檔案"
                 f"{f'(失敗 {failed})' if failed else ''} → {folder}", "success")
    return {"folder": folder, "out_dir": out_dir,
            "files": len(entries), "failed": failed}


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------
def pick_font(candidates, fallback):
    available = set(tkfont.families())
    for name in candidates:
        if name in available:
            return name
    return fallback


class GitExportApp(ttk.Window):

    def __init__(self):
        self.config_data = load_config()
        theme = self.config_data.get("theme", DEFAULT_THEME)
        if theme not in THEME_CHOICES:
            theme = DEFAULT_THEME
        super().__init__(title=f"{APP_NAME}  v{APP_VERSION}", themename=theme,
                         size=(1180, 880), minsize=(980, 640))

        self.queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker = None
        self.repo_ok = False
        self.commits = []
        self._validate_job = None
        # Most-recently-used path lists; legacy single-value keys are migrated in.
        self.repo_history = push_history(
            list(self.config_data.get("repo_history", [])),
            self.config_data.get("git", ""))
        self.out_history = push_history(
            list(self.config_data.get("out_history", [])),
            self.config_data.get("out", ""))

        self.ui_font = pick_font(UI_FONT_CANDIDATES, "TkDefaultFont")
        self.mono_font = pick_font(MONO_FONT_CANDIDATES, "TkFixedFont")
        self._init_fonts()
        self._build_ui()
        self._apply_palette()
        self._restore_config()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._drain_queue)
        self._validate_repo()

    # -- setup -------------------------------------------------------------
    def _init_fonts(self):
        for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10),
                           ("TkMenuFont", 10), ("TkHeadingFont", 10)):
            try:
                tkfont.nametofont(name).configure(family=self.ui_font, size=size)
            except tk.TclError:
                pass
        try:
            tkfont.nametofont("TkFixedFont").configure(family=self.mono_font, size=10)
        except tk.TclError:
            pass
        self.style.configure("Treeview", rowheight=26)
        self.style.configure("Treeview.Heading", font=(self.ui_font, 10, "bold"))
        # Secondary text: readable in both light and dark themes.
        self.style.configure("Muted.TLabel", foreground=self._muted_color())

    def _muted_color(self):
        c = self.style.colors
        try:
            return c.make_transparent(0.6, c.fg, c.bg)
        except Exception:
            return c.secondary

    def _build_ui(self):
        root = ttk.Frame(self, padding=(16, 12, 16, 10))
        root.pack(fill=BOTH, expand=YES)
        root.rowconfigure(3, weight=1)
        root.columnconfigure(0, weight=1)

        self._build_header(root).grid(row=0, column=0, sticky=EW)
        ttk.Separator(root).grid(row=1, column=0, sticky=EW, pady=(10, 12))
        self._build_repo_card(root).grid(row=2, column=0, sticky=EW)

        body = ttk.Frame(root)
        body.grid(row=3, column=0, sticky=NSEW, pady=(12, 0))
        body.rowconfigure(0, weight=3, minsize=300)
        body.rowconfigure(1, weight=2, minsize=180)
        body.columnconfigure(0, weight=1)

        upper = ttk.Frame(body)
        upper.grid(row=0, column=0, sticky=NSEW)
        upper.rowconfigure(0, weight=1)
        upper.columnconfigure(0, weight=1)
        upper.columnconfigure(1, minsize=340)
        self._build_source_card(upper).grid(row=0, column=0, sticky=NSEW)
        self._build_side_column(upper).grid(row=0, column=1, sticky="new", padx=(12, 0))

        self._build_log_card(body).grid(row=1, column=0, sticky=NSEW, pady=(12, 0))
        self._build_action_bar(root).grid(row=4, column=0, sticky=EW, pady=(12, 0))
        self._build_status_bar(root).grid(row=5, column=0, sticky=EW, pady=(10, 0))

        self.bind("<Control-Return>", lambda e: self._start_export())
        self.bind("<F5>", lambda e: self._load_commits())

    def _build_header(self, master):
        bar = ttk.Frame(master)
        bar.columnconfigure(1, weight=1)

        text = ttk.Frame(bar)
        text.grid(row=0, column=0, sticky=W)
        ttk.Label(text, text=APP_NAME,
                  font=(self.ui_font, 19, "bold")).pack(anchor=W)
        ttk.Label(text, text="匯出 commit 的變更前 / 變更後檔案,方便比對與存檔",
                  style="Muted.TLabel").pack(anchor=W, pady=(2, 0))

        right = ttk.Frame(bar)
        right.grid(row=0, column=2, sticky=E)
        ttk.Label(right, text="外觀主題", style="Muted.TLabel").pack(side=LEFT, padx=(0, 8))
        self.theme_var = tk.StringVar(value=self.style.theme.name)
        theme_box = ttk.Combobox(right, textvariable=self.theme_var, width=12,
                                 values=THEME_CHOICES, state="readonly")
        theme_box.pack(side=LEFT)
        theme_box.bind("<<ComboboxSelected>>", self._on_theme_change)
        return bar

    def _build_repo_card(self, master):
        card = ttk.Labelframe(master, text=" ① Git 儲存庫 ", padding=12)
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="路徑").grid(row=0, column=0, sticky=W, padx=(0, 10))
        self.repo_var = tk.StringVar()
        self.repo_box = ttk.Combobox(card, textvariable=self.repo_var,
                                     values=self.repo_history, font=(self.mono_font, 10))
        self.repo_box.grid(row=0, column=1, sticky=EW)
        ToolTip(self.repo_box, text="可直接輸入,或從下拉選單挑選用過的儲存庫",
                bootstyle=(INFO, INVERSE))
        self.repo_var.trace_add("write", lambda *_: self._schedule_validate())

        ttk.Button(card, text="瀏覽…", bootstyle=(OUTLINE, PRIMARY), width=8,
                   command=self._browse_repo).grid(row=0, column=2, padx=(8, 0))
        forget = ttk.Button(card, text="✕", bootstyle=(OUTLINE, DANGER), width=3,
                            command=lambda: self._forget_path("repo"))
        forget.grid(row=0, column=3, padx=(6, 0))
        ToolTip(forget, text="把目前路徑從歷史紀錄中移除", bootstyle=(INFO, INVERSE))

        self.repo_state = ttk.Label(card, text="尚未選擇儲存庫", style="Muted.TLabel")
        self.repo_state.grid(row=1, column=1, columnspan=3, sticky=W, pady=(8, 0))
        return card

    def _build_source_card(self, master):
        card = ttk.Labelframe(master, text=" ② 要匯出的內容 ", padding=12)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        self.tabs = ttk.Notebook(card, bootstyle=PRIMARY)
        self.tabs.grid(row=0, column=0, sticky=NSEW)
        self.tabs.add(self._build_commit_tab(self.tabs), text="  Commit 清單  ")
        self.tabs.add(self._build_manual_tab(self.tabs), text="  手動輸入 SHA  ")
        self.tabs.add(self._build_dirty_tab(self.tabs), text="  未提交的變更  ")
        return card

    def _build_commit_tab(self, master):
        tab = ttk.Frame(master, padding=12)
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky=EW, pady=(0, 10))
        bar.columnconfigure(5, weight=1)

        ttk.Label(bar, text="分支").grid(row=0, column=0, padx=(0, 6))
        self.branch_var = tk.StringVar(value="HEAD")
        self.branch_box = ttk.Combobox(bar, textvariable=self.branch_var,
                                       width=22, values=["HEAD"], state="readonly")
        self.branch_box.grid(row=0, column=1)
        self.branch_box.bind("<<ComboboxSelected>>", lambda e: self._load_commits())

        ttk.Label(bar, text="筆數").grid(row=0, column=2, padx=(12, 6))
        self.limit_var = tk.StringVar(value="100")
        ttk.Combobox(bar, textvariable=self.limit_var, width=6,
                     values=COMMIT_LIMITS, state="readonly").grid(row=0, column=3)

        reload_btn = ttk.Button(bar, text="重新載入", bootstyle=(OUTLINE, INFO),
                                command=self._load_commits)
        reload_btn.grid(row=0, column=4, padx=(12, 0))
        ToolTip(reload_btn, text="重新讀取 commit 清單 (F5)", bootstyle=(INFO, INVERSE))

        ttk.Label(bar, text="搜尋", style="Muted.TLabel").grid(row=0, column=6,
                                                             sticky=E, padx=(12, 6))
        self.filter_var = tk.StringVar()
        filter_entry = ttk.Entry(bar, textvariable=self.filter_var, width=24)
        filter_entry.grid(row=0, column=7, sticky=E)
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ToolTip(filter_entry, text="以 SHA / 作者 / 標題關鍵字過濾",
                bootstyle=(INFO, INVERSE))

        wrap = ttk.Frame(tab)
        wrap.grid(row=1, column=0, sticky=NSEW)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        columns = ("sha", "date", "author", "subject")
        self.tree = ttk.Treeview(wrap, columns=columns, show="headings", height=10,
                                 selectmode=EXTENDED, bootstyle=PRIMARY)
        for col, title, width, anchor, stretch in (
                ("sha", "SHA", 90, W, False),
                ("date", "日期", 130, W, False),
                ("author", "作者", 130, W, False),
                ("subject", "標題", 420, W, True)):
            self.tree.heading(col, text=title, anchor=W)
            self.tree.column(col, width=width, anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky=NSEW)
        self.tree.bind("<Double-1>", self._show_commit_detail)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_selection_hint())

        vbar = ttk.Scrollbar(wrap, orient=VERTICAL, command=self.tree.yview,
                             bootstyle=ROUND)
        vbar.grid(row=0, column=1, sticky=NS)
        self.tree.configure(yscrollcommand=vbar.set)

        self.select_hint = ttk.Label(
            tab, text="可用 Ctrl / Shift 複選;連按兩下可查看完整 commit 訊息",
            style="Muted.TLabel")
        self.select_hint.grid(row=2, column=0, sticky=W, pady=(8, 0))
        return tab

    def _build_manual_tab(self, master):
        tab = ttk.Frame(master, padding=12)
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

        ttk.Label(tab, text="輸入一或多筆 commit SHA / 分支 / tag,以空白、逗號或換行分隔:",
                  style="Muted.TLabel").grid(row=0, column=0, sticky=W, pady=(0, 8))

        wrap = ttk.Frame(tab)
        wrap.grid(row=1, column=0, sticky=NSEW)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.sha_text = tk.Text(wrap, height=6, wrap="word", relief=FLAT,
                                font=(self.mono_font, 10), padx=10, pady=8)
        self.sha_text.grid(row=0, column=0, sticky=NSEW)
        sbar = ttk.Scrollbar(wrap, orient=VERTICAL, command=self.sha_text.yview,
                             bootstyle=ROUND)
        sbar.grid(row=0, column=1, sticky=NS)
        self.sha_text.configure(yscrollcommand=sbar.set)
        return tab

    def _build_dirty_tab(self, master):
        tab = ttk.Frame(master, padding=12)
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky=EW, pady=(0, 8))
        bar.columnconfigure(0, weight=1)
        ttk.Label(bar, text="直接匯出工作區中尚未 commit 的變更(含已 staged 的內容)",
                  style="Muted.TLabel").grid(row=0, column=0, sticky=W)
        ttk.Button(bar, text="重新檢查", bootstyle=(OUTLINE, INFO),
                   command=self._refresh_dirty).grid(row=0, column=1)

        wrap = ttk.Frame(tab)
        wrap.grid(row=1, column=0, sticky=NSEW)
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)

        self.dirty_text = tk.Text(wrap, wrap="none", relief=FLAT, state=DISABLED,
                                  font=(self.mono_font, 10), padx=10, pady=8)
        self.dirty_text.grid(row=0, column=0, sticky=NSEW)
        dbar = ttk.Scrollbar(wrap, orient=VERTICAL, command=self.dirty_text.yview,
                             bootstyle=ROUND)
        dbar.grid(row=0, column=1, sticky=NS)
        self.dirty_text.configure(yscrollcommand=dbar.set)
        return tab

    def _build_side_column(self, master):
        col = ttk.Frame(master)
        col.columnconfigure(0, weight=1)

        out = ttk.Labelframe(col, text=" ③ 輸出資料夾 ", padding=12)
        out.grid(row=0, column=0, sticky=EW)
        out.columnconfigure(0, weight=1)

        out.columnconfigure(1, weight=1)
        self.out_var = tk.StringVar()
        self.out_box = ttk.Combobox(out, textvariable=self.out_var,
                                    values=self.out_history, font=(self.mono_font, 10))
        self.out_box.grid(row=0, column=0, columnspan=3, sticky=EW)
        ToolTip(self.out_box, text="可直接輸入,或從下拉選單挑選用過的輸出資料夾",
                bootstyle=(INFO, INVERSE))

        ttk.Button(out, text="瀏覽…", bootstyle=(OUTLINE, PRIMARY),
                   command=self._browse_output).grid(row=1, column=0, sticky=EW,
                                                     pady=(8, 0), padx=(0, 4))
        ttk.Button(out, text="開啟資料夾", bootstyle=(OUTLINE, INFO),
                   command=self._open_output).grid(row=1, column=1, sticky=EW,
                                                   pady=(8, 0), padx=(0, 4))
        forget = ttk.Button(out, text="✕", bootstyle=(OUTLINE, DANGER), width=3,
                            command=lambda: self._forget_path("out"))
        forget.grid(row=1, column=2, sticky=E, pady=(8, 0))
        ToolTip(forget, text="把目前路徑從歷史紀錄中移除", bootstyle=(INFO, INVERSE))

        opt = ttk.Labelframe(col, text=" ④ 選項 ", padding=12)
        opt.grid(row=1, column=0, sticky=EW, pady=(12, 0))
        opt.columnconfigure(0, weight=1)

        self.opt_overwrite = tk.BooleanVar(value=False)
        self.opt_patch = tk.BooleanVar(value=True)
        self.opt_sha_suffix = tk.BooleanVar(value=False)
        self.opt_untracked = tk.BooleanVar(value=True)
        self.opt_auto_open = tk.BooleanVar(value=False)

        for row, (var, text, tip) in enumerate((
                (self.opt_overwrite, "覆蓋已存在的輸出資料夾",
                 "關閉時會略過同名資料夾。開啟時只會覆蓋本工具產生的資料夾"),
                (self.opt_patch, "同時輸出 changes.patch",
                 "以 git diff 產生 unified diff 檔"),
                (self.opt_sha_suffix, "資料夾名稱加上短 SHA",
                 "避免同日期、同標題的 commit 互相衝突"),
                (self.opt_untracked, "未提交模式包含未追蹤檔案",
                 "把 untracked 檔案一併複製到 MOD"),
                (self.opt_auto_open, "完成後自動開啟輸出資料夾", None))):
            cb = ttk.Checkbutton(opt, text=text, variable=var,
                                 bootstyle="round-toggle")
            cb.grid(row=row, column=0, sticky=W, pady=4)
            if tip:
                ToolTip(cb, text=tip, bootstyle=(INFO, INVERSE))

        merge = ttk.Labelframe(col, text=" ⑤ 選多筆 commit 時 ", padding=12)
        merge.grid(row=2, column=0, sticky=EW, pady=(12, 0))
        merge.columnconfigure(0, weight=1)

        self.merge_mode = tk.StringVar(value="separate")
        for row, (value, text, tip) in enumerate((
                ("separate", "分開匯出(每筆一個資料夾)",
                 "選幾筆就產生幾個資料夾,各自是該 commit 的變更"),
                ("merged", "合併成一包(整段總變更)",
                 "把連續的 commit 當成一次修改：ORG 是最舊 commit 之前的版本,"
                 "MOD 是最新 commit 之後的版本,中間過程會被壓平"))):
            rb = ttk.Radiobutton(merge, text=text, value=value,
                                 variable=self.merge_mode, bootstyle=PRIMARY,
                                 command=self._update_selection_hint)
            rb.grid(row=row, column=0, sticky=W, pady=4)
            ToolTip(rb, text=tip, bootstyle=(INFO, INVERSE))
        return col

    def _build_log_card(self, master):
        card = ttk.Labelframe(master, text=" ⑥ 執行紀錄 ", padding=12)
        card.rowconfigure(0, weight=1)
        card.columnconfigure(0, weight=1)

        self.log_text = tk.Text(card, wrap="none", relief=FLAT, state=DISABLED, height=8,
                                font=(self.mono_font, 10), padx=10, pady=8)
        self.log_text.grid(row=0, column=0, sticky=NSEW)
        vbar = ttk.Scrollbar(card, orient=VERTICAL, command=self.log_text.yview,
                             bootstyle=ROUND)
        vbar.grid(row=0, column=1, sticky=NS)
        hbar = ttk.Scrollbar(card, orient=HORIZONTAL, command=self.log_text.xview,
                             bootstyle=ROUND)
        hbar.grid(row=1, column=0, sticky=EW)
        self.log_text.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        return card

    def _build_action_bar(self, master):
        bar = ttk.Frame(master)
        bar.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(bar, mode="determinate",
                                        bootstyle=(SUCCESS, STRIPED))
        self.progress.grid(row=0, column=0, sticky=EW, padx=(0, 16))

        self.clear_btn = ttk.Button(bar, text="清除紀錄", bootstyle=(LINK, INFO),
                                    command=self._clear_log)
        self.clear_btn.grid(row=0, column=1, padx=(0, 8))

        self.cancel_btn = ttk.Button(bar, text="取消", bootstyle=(OUTLINE, DANGER),
                                     width=8, state=DISABLED, command=self._cancel)
        self.cancel_btn.grid(row=0, column=2, padx=(0, 8))

        self.export_btn = ttk.Button(bar, text="開始匯出", bootstyle=SUCCESS,
                                     width=14, command=self._start_export)
        self.export_btn.grid(row=0, column=3)
        ToolTip(self.export_btn, text="Ctrl + Enter", bootstyle=(INFO, INVERSE))
        return bar

    def _build_status_bar(self, master):
        bar = ttk.Frame(master)
        bar.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="就緒")
        ttk.Label(bar, textvariable=self.status_var,
                  style="Muted.TLabel").grid(row=0, column=0, sticky=W)
        ttk.Label(bar, text=f"{APP_NAME} v{APP_VERSION}",
                  style="Muted.TLabel").grid(row=0, column=1, sticky=E)
        return bar

    # -- appearance --------------------------------------------------------
    def _apply_palette(self):
        c = self.style.colors
        for widget in (self.log_text, self.sha_text, self.dirty_text):
            widget.configure(background=c.inputbg, foreground=c.inputfg,
                             insertbackground=c.inputfg,
                             selectbackground=c.selectbg,
                             selectforeground=c.selectfg,
                             highlightthickness=0, borderwidth=0)
        tags = {
            "info": c.inputfg,
            "muted": self._muted_color(),
            "head": c.primary,
            "success": c.success,
            "warning": c.warning,
            "error": c.danger,
            "added": c.success,
            "deleted": c.danger,
            "modified": c.info,
            "renamed": c.warning,
            "untracked": c.success,
        }
        for tag, color in tags.items():
            self.log_text.tag_configure(tag, foreground=color)
        self.log_text.tag_configure("head", foreground=c.primary,
                                    font=(self.mono_font, 10, "bold"))

    def _on_theme_change(self, _event=None):
        name = self.theme_var.get()
        try:
            self.style.theme_use(name)
        except Exception:
            return
        self._init_fonts()
        self._apply_palette()

    # -- repository --------------------------------------------------------
    def _browse_repo(self):
        initial = self.repo_var.get().strip() or os.getcwd()
        path = filedialog.askdirectory(title="選擇 Git 儲存庫", initialdir=initial)
        if path:
            self.repo_var.set(os.path.normpath(path))

    def _browse_output(self):
        initial = self.out_var.get().strip() or os.getcwd()
        path = filedialog.askdirectory(title="選擇輸出資料夾", initialdir=initial)
        if path:
            self.out_var.set(os.path.normpath(path))
            self._remember_path("out", path)

    # -- path history ------------------------------------------------------
    def _remember_path(self, kind, path):
        if kind == "repo":
            self.repo_history = push_history(self.repo_history, path)
        else:
            self.out_history = push_history(self.out_history, path)
        self._refresh_history()

    def _forget_path(self, kind):
        box, current = ((self.repo_box, self.repo_var.get())
                        if kind == "repo" else (self.out_box, self.out_var.get()))
        current = os.path.normpath(current.strip()) if current.strip() else ""
        if not current:
            return
        keep = [p for p in (self.repo_history if kind == "repo" else self.out_history)
                if p.lower() != current.lower()]
        if kind == "repo":
            self.repo_history = keep
        else:
            self.out_history = keep
        self._refresh_history()
        box.set("")
        self.status_var.set(f"已從歷史紀錄移除：{current}")

    def _refresh_history(self):
        self.repo_box.configure(values=self.repo_history)
        self.out_box.configure(values=self.out_history)

    def _open_output(self):
        if not open_folder(self.out_var.get().strip()):
            Messagebox.show_warning("輸出資料夾不存在", title="開啟失敗", parent=self)

    def _schedule_validate(self):
        if self._validate_job:
            self.after_cancel(self._validate_job)
        self._validate_job = self.after(400, self._validate_repo)

    def _validate_repo(self):
        self._validate_job = None
        path = self.repo_var.get().strip()
        self.repo_ok = False
        if not path:
            self.repo_state.configure(text="尚未選擇儲存庫", style="Muted.TLabel")
            return
        try:
            repo = Repo(path, search_parent_directories=False)
            head = repo.head.commit
            try:
                branch = repo.active_branch.name
            except TypeError:
                branch = "(detached HEAD)"
            dirty = repo.is_dirty(untracked_files=True)
            self.repo_ok = True
            self.repo_state.configure(
                text=f"✓ 分支 {branch} · HEAD {head.hexsha[:8]} · "
                     f"{'有未提交變更' if dirty else '工作區乾淨'}",
                bootstyle=SUCCESS)
            self._remember_path("repo", path)
            branches = ["HEAD"] + sorted(b.name for b in repo.branches)
            self.branch_box.configure(values=branches)
            if self.branch_var.get() not in branches:
                self.branch_var.set("HEAD")
            self._load_commits()
            self._refresh_dirty()
        except (InvalidGitRepositoryError, NoSuchPathError):
            self.repo_state.configure(text="✖ 此路徑不是 Git 儲存庫", bootstyle=DANGER)
        except Exception as e:
            self.repo_state.configure(text=f"✖ 無法讀取儲存庫：{e}", bootstyle=DANGER)

    # -- commit list -------------------------------------------------------
    def _load_commits(self):
        if not self.repo_ok:
            return
        path = self.repo_var.get().strip()
        rev = self.branch_var.get() or "HEAD"
        try:
            limit = int(self.limit_var.get())
        except ValueError:
            limit = 100
        self.status_var.set("載入 commit 清單…")

        def work():
            rows, err = [], None
            try:
                repo = Repo(path)
                for c in repo.iter_commits(rev, max_count=limit):
                    subject = next((l for l in (c.message or "").splitlines()
                                    if l.strip()), "")
                    rows.append((
                        c.hexsha,
                        c.hexsha[:8],
                        datetime.fromtimestamp(c.committed_date).strftime("%Y-%m-%d %H:%M"),
                        c.author.name or "",
                        subject.strip(),
                    ))
            except Exception as e:
                err = str(e)
            self.queue.put(("commits", rows, err))

        threading.Thread(target=work, daemon=True).start()

    def _fill_tree(self, rows):
        self.tree.delete(*self.tree.get_children())
        keyword = self.filter_var.get().strip().lower()
        shown = 0
        for full_sha, short, date, author, subject in rows:
            if keyword and keyword not in f"{full_sha} {author} {subject}".lower():
                continue
            self.tree.insert("", END, iid=full_sha,
                             values=(short, date, author, subject))
            shown += 1
        self._update_selection_hint(shown)

    def _apply_filter(self):
        self._fill_tree(self.commits)

    def _update_selection_hint(self, shown=None):
        if shown is None:
            shown = len(self.tree.get_children())
        picked = len(self.tree.selection())
        if picked > 1:
            tail = (" · 合併成 1 包匯出" if self.merge_mode.get() == "merged"
                    else f" · 分開匯出成 {picked} 個資料夾")
        elif picked:
            tail = ""
        else:
            tail = " · 可用 Ctrl / Shift 複選,連按兩下看完整訊息"
        self.select_hint.configure(text=f"顯示 {shown} 筆 · 已選取 {picked} 筆{tail}")

    def _show_commit_detail(self, _event=None):
        sel = self.tree.selection()
        if not sel or not self.repo_ok:
            return
        try:
            commit = Repo(self.repo_var.get().strip()).commit(sel[0])
        except Exception as e:
            self._append_log(f"✖ 無法讀取 commit：{e}", "error")
            return
        self._append_log(f"── {commit.hexsha}", "head")
        self._append_log(f"   作者 : {commit.author.name} <{commit.author.email}>", "muted")
        self._append_log(
            f"   時間 : {datetime.fromtimestamp(commit.committed_date):%Y-%m-%d %H:%M:%S}",
            "muted")
        for line in (commit.message or "").strip().splitlines():
            self._append_log(f"   {line}", "info")

    # -- uncommitted -------------------------------------------------------
    def _refresh_dirty(self):
        if not self.repo_ok:
            return
        path = self.repo_var.get().strip()

        def work():
            lines = []
            try:
                repo = Repo(path)
                head = repo.head.commit
                for d in head.diff(None):
                    p = d.b_path or d.a_path
                    disk = os.path.join(repo.working_tree_dir, p)
                    if not os.path.exists(disk):
                        lines.append(f"[DELETED]   {d.a_path}")
                    elif d.a_blob is None:
                        lines.append(f"[ADDED]     {p}")
                    else:
                        lines.append(f"[MODIFIED]  {p}")
                for p in repo.untracked_files:
                    lines.append(f"[UNTRACKED] {p}")
                text = "\n".join(lines) if lines else "工作區沒有未提交的變更。"
                text = f"共 {len(lines)} 個檔案\n\n" + text if lines else text
            except Exception as e:
                text = f"無法讀取工作區狀態：{e}"
            self.queue.put(("dirty", text))

        threading.Thread(target=work, daemon=True).start()

    # -- export ------------------------------------------------------------
    def _collect_targets(self):
        """Return (mode, targets) based on the active tab, or (None, None)."""
        idx = self.tabs.index(self.tabs.select())
        if idx == 0:
            picked = list(self.tree.selection())
            if not picked:
                Messagebox.show_warning("請先在清單中選擇至少一筆 commit",
                                        title="尚未選取", parent=self)
                return None, None
            order = [row[0] for row in self.commits]
            picked.sort(key=lambda s: order.index(s) if s in order else 0)
            return "commit", picked
        if idx == 1:
            raw = self.sha_text.get("1.0", END).strip()
            targets = [s for s in re.split(r"[\s,;]+", raw) if s]
            if not targets:
                Messagebox.show_warning("請輸入至少一筆 commit SHA",
                                        title="欄位未填", parent=self)
                return None, None
            return "commit", targets
        return "worktree", [None]

    def _start_export(self):
        if self.worker and self.worker.is_alive():
            return
        repo_path = self.repo_var.get().strip()
        out_path = self.out_var.get().strip()

        if not self.repo_ok:
            Messagebox.show_error("請先選擇有效的 Git 儲存庫", title="錯誤", parent=self)
            return
        if not out_path:
            Messagebox.show_error("請選擇輸出資料夾", title="錯誤", parent=self)
            return
        if not os.path.isdir(out_path):
            try:
                os.makedirs(out_path, exist_ok=True)
                self._append_log(f"ℹ 已建立輸出資料夾：{out_path}", "muted")
            except Exception as e:
                Messagebox.show_error(f"無法建立輸出資料夾：{e}", title="錯誤", parent=self)
                return

        mode, targets = self._collect_targets()
        if not targets:
            return
        if mode == "commit" and len(targets) > 1 and self.merge_mode.get() == "merged":
            if not self._confirm_merge(repo_path, targets):
                return
            mode = "range"
        self._remember_path("out", out_path)

        options = {
            "overwrite": self.opt_overwrite.get(),
            "with_patch": self.opt_patch.get(),
            "name_with_sha": self.opt_sha_suffix.get(),
            "include_untracked": self.opt_untracked.get(),
        }
        self.cancel_event.clear()
        self._set_running(True)
        self.worker = threading.Thread(
            target=self._run_export, daemon=True,
            args=(repo_path, out_path, mode, targets, options))
        self.worker.start()

    def _confirm_merge(self, repo_path, targets):
        """Pre-flight for merged export: same line of history? any commit in between?"""
        try:
            repo = Repo(repo_path)
            commits = list({repo.commit(t).hexsha: repo.commit(t) for t in targets}.values())
            oldest, newest, contiguous, covered, outside = \
                analyze_merge_selection(repo, commits)
            if outside:
                Messagebox.show_error(
                    "選取的 commit 不在同一條線上(分屬不同分支),無法合併成一包。\n"
                    "請改用「分開匯出」,或只選同一條路徑上的 commit。",
                    title="無法合併", parent=self)
                return False
        except Exception as e:
            Messagebox.show_error(f"無法分析選取的 commit：{e}", title="錯誤", parent=self)
            return False

        if contiguous and covered == len(commits):
            return True
        extra = max(covered - len(commits), 0)
        answer = Messagebox.show_question(
            f"選取的 {len(commits)} 筆 commit 並不連續。\n\n"
            f"{oldest.hexsha[:8]} → {newest.hexsha[:8]} 這段範圍實際包含 {covered} 筆 commit,"
            f"其中 {extra} 筆並未被選取,\n它們的變更也會一併被合併進來。\n\n要繼續嗎?",
            title="選取的 commit 不連續", parent=self,
            buttons=["取消:secondary", "繼續合併:success"])
        return answer == "繼續合併"

    def _run_export(self, repo_path, out_path, mode, targets, options):
        reporter = Reporter(
            log_fn=lambda msg, tag="info": self.queue.put(("log", msg, tag)),
            progress_fn=lambda done, total: self.queue.put(("progress", done, total)),
            cancel_event=self.cancel_event)
        results = []
        try:
            repo = Repo(repo_path)
            if mode == "range":
                self.queue.put(("status", f"合併匯出 {len(targets)} 筆 commit…"))
                stats = extract_commit_range(
                    repo, targets, out_path, reporter,
                    overwrite=options["overwrite"],
                    with_patch=options["with_patch"],
                    name_with_sha=options["name_with_sha"])
                if stats:
                    results.append(stats)
            else:
                total = len(targets)
                for i, target in enumerate(targets, 1):
                    if reporter.cancelled:
                        break
                    self.queue.put(("status", f"處理中 {i}/{total}"))
                    if mode == "worktree":
                        stats = extract_working_tree(
                            repo, out_path, reporter,
                            overwrite=options["overwrite"],
                            with_patch=options["with_patch"],
                            include_untracked=options["include_untracked"])
                    else:
                        stats = extract_commit(
                            repo, target, out_path, reporter,
                            overwrite=options["overwrite"],
                            with_patch=options["with_patch"],
                            name_with_sha=options["name_with_sha"])
                    if stats:
                        results.append(stats)
        except Exception as e:
            self.queue.put(("log", f"✖ 執行失敗：{e}", "error"))
        self.queue.put(("done", results, self.cancel_event.is_set()))

    def _cancel(self):
        self.cancel_event.set()
        self.status_var.set("取消中…")

    def _set_running(self, running):
        state = DISABLED if running else NORMAL
        self.export_btn.configure(state=state)
        self.cancel_btn.configure(state=NORMAL if running else DISABLED)
        if running:
            self.progress.configure(value=0)
            self.status_var.set("開始匯出…")

    # -- queue / log -------------------------------------------------------
    def _drain_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1], msg[2])
                elif kind == "progress":
                    done, total = msg[1], msg[2]
                    self.progress.configure(maximum=max(total, 1), value=done)
                elif kind == "status":
                    self.status_var.set(msg[1])
                elif kind == "commits":
                    self._on_commits_loaded(msg[1], msg[2])
                elif kind == "dirty":
                    self._set_dirty_text(msg[1])
                elif kind == "done":
                    self._on_done(msg[1], msg[2])
        except queue.Empty:
            pass
        self.after(80, self._drain_queue)

    def _on_commits_loaded(self, rows, err):
        if err:
            self.status_var.set("載入 commit 失敗")
            self._append_log(f"✖ 載入 commit 清單失敗：{err}", "error")
            return
        self.commits = rows
        self._fill_tree(rows)
        self.status_var.set(f"已載入 {len(rows)} 筆 commit")

    def _set_dirty_text(self, text):
        self.dirty_text.configure(state=NORMAL)
        self.dirty_text.delete("1.0", END)
        self.dirty_text.insert("1.0", text)
        self.dirty_text.configure(state=DISABLED)

    def _on_done(self, results, cancelled):
        self._set_running(False)
        files = sum(r["files"] for r in results)
        failed = sum(r["failed"] for r in results)
        if cancelled:
            summary = f"已取消 · 完成 {len(results)} 筆 / {files} 個檔案"
            tag = "warning"
        elif results:
            summary = f"完成 {len(results)} 筆 · 共 {files} 個檔案" + \
                      (f" · 失敗 {failed}" if failed else "")
            tag = "success"
        else:
            summary = "沒有任何輸出"
            tag = "warning"
        self.progress.configure(value=self.progress.cget("maximum") if results else 0)
        self.status_var.set(summary)
        self._append_log(f"═ {summary}", tag)
        if results and self.opt_auto_open.get():
            open_folder(self.out_var.get().strip())

    def _append_log(self, message, tag="info"):
        self.log_text.configure(state=NORMAL)
        self.log_text.insert(END, message + "\n", tag)
        self.log_text.see(END)
        self.log_text.configure(state=DISABLED)

    def _clear_log(self):
        self.log_text.configure(state=NORMAL)
        self.log_text.delete("1.0", END)
        self.log_text.configure(state=DISABLED)
        self.progress.configure(value=0)
        self.status_var.set("就緒")

    # -- config ------------------------------------------------------------
    def _restore_config(self):
        cfg = self.config_data
        self.repo_var.set(cfg.get("git", ""))
        self.out_var.set(cfg.get("out", ""))
        self.sha_text.insert("1.0", cfg.get("sha", ""))
        self.branch_var.set(cfg.get("branch", "HEAD"))
        if cfg.get("limit") in COMMIT_LIMITS:
            self.limit_var.set(cfg["limit"])
        opts = cfg.get("options", {})
        self.opt_overwrite.set(bool(opts.get("overwrite", False)))
        self.opt_patch.set(bool(opts.get("with_patch", True)))
        self.opt_sha_suffix.set(bool(opts.get("name_with_sha", False)))
        self.opt_untracked.set(bool(opts.get("include_untracked", True)))
        self.opt_auto_open.set(bool(opts.get("auto_open", False)))
        if opts.get("merge_mode") in ("separate", "merged"):
            self.merge_mode.set(opts["merge_mode"])
        size = cfg.get("size")
        if isinstance(size, str) and re.fullmatch(r"\d+x\d+", size):
            self.geometry(size)

    def _on_close(self):
        repo_history = push_history(self.repo_history, self.repo_var.get())
        out_history = push_history(self.out_history, self.out_var.get())
        save_config({
            "git": self.repo_var.get().strip(),
            "out": self.out_var.get().strip(),
            "repo_history": repo_history,
            "out_history": out_history,
            "sha": self.sha_text.get("1.0", END).strip(),
            "branch": self.branch_var.get(),
            "limit": self.limit_var.get(),
            "theme": self.style.theme.name,
            "size": f"{self.winfo_width()}x{self.winfo_height()}",
            "options": {
                "overwrite": self.opt_overwrite.get(),
                "with_patch": self.opt_patch.get(),
                "name_with_sha": self.opt_sha_suffix.get(),
                "include_untracked": self.opt_untracked.get(),
                "auto_open": self.opt_auto_open.get(),
                "merge_mode": self.merge_mode.get(),
            },
        })
        self.cancel_event.set()
        self.destroy()


def run_gui():
    GitExportApp().mainloop()


if __name__ == "__main__":
    run_gui()
