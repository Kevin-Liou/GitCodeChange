import os
import json
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, scrolledtext
from git import Repo, InvalidGitRepositoryError
from datetime import datetime
import ttkbootstrap as ttk
from ttkbootstrap.dialogs import Messagebox

CONFIG_FILE = os.path.expanduser("~/.git_export_tool_config.json")

def sanitize_filename(name, max_length=50):
    name = re.sub(r'[\\/*?:"<>| \n\r\t]', '_', name.strip())
    return name[:max_length]

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f)

def log(msg, log_widget):
    log_widget.configure(state="normal")
    log_widget.insert(tk.END, msg + "\n")
    log_widget.see(tk.END)
    log_widget.configure(state="disabled")

def open_output_folder(path):
    if os.path.exists(path):
        if os.name == 'nt':
            os.startfile(path)
        elif os.name == 'posix':
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', path])

def extract_commit(repo_path, commit_hash, output_base, log_widget):
    try:
        repo = Repo(repo_path)
        commit = repo.commit(commit_hash)
        parent = commit.parents[0] if commit.parents else None
    except InvalidGitRepositoryError:
        log("❌ 選擇的資料夾不是 Git 倉庫", log_widget)
        return
    except Exception as e:
        log(f"❌ 無法讀取 commit: {e}", log_widget)
        return

    commit_date = datetime.fromtimestamp(commit.committed_date).strftime('%Y-%m-%d')
    message_first_line = commit.message.strip().splitlines()[0]
    folder_name = f"{commit_date}_{sanitize_filename(message_first_line)}"
    output_dir = os.path.join(output_base, folder_name)

    if os.path.exists(output_dir):
        log(f"⚠️ 已存在：{folder_name}，跳過", log_widget)
        return

    os.makedirs(os.path.join(output_dir, "MOD"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "ORG"), exist_ok=True)

    with open(os.path.join(output_dir, "commit_message.txt"), "w", encoding="utf-8") as f:
        f.write(f"Commit:  {commit.hexsha}\n")
        f.write(f"Author:  {commit.author.name} <{commit.author.email}>\n")
        f.write(f"Date:    {datetime.fromtimestamp(commit.committed_date).isoformat()}\n\n")
        f.write("Message:\n")
        f.write(commit.message.strip())

    if not parent:
        log(f"⚠️ 此 commit 無父節點，無法產生 diff。", log_widget)
        return

    diff = parent.diff(commit, create_patch=False)

    for change in diff:
        if change.renamed:
            log(f"[RENAMED] {change.rename_from} → {change.rename_to}", log_widget)
        elif change.deleted_file:
            log(f"[DELETED] {change.a_path}", log_widget)
        elif change.new_file:
            log(f"[ADDED] {change.b_path}", log_widget)
        else:
            log(f"[CHANGED] {change.a_path}", log_widget)

        try:
            if change.a_blob:
                org_file = os.path.join(output_dir, "ORG", change.a_path)
                os.makedirs(os.path.dirname(org_file), exist_ok=True)
                with open(org_file, "wb") as f:
                    f.write(change.a_blob.data_stream.read())
            if change.b_blob:
                mod_file = os.path.join(output_dir, "MOD", change.b_path)
                os.makedirs(os.path.dirname(mod_file), exist_ok=True)
                with open(mod_file, "wb") as f:
                    f.write(change.b_blob.data_stream.read())
        except Exception as e:
            log(f"❌ 無法處理檔案: {e}", log_widget)

    log(f"✅ 完成輸出：{output_dir}", log_widget)

def run_gui():
    config = load_config()

    app = ttk.Window(title="Git Commit Extractor", themename="darkly", size=(800, 500))

    ttk.Label(app, text="Git 資料夾：").grid(row=0, column=0, sticky="w", padx=10, pady=5)
    git_entry = ttk.Entry(app, width=80)
    git_entry.grid(row=0, column=1, padx=5)
    ttk.Button(app, text="Browse", command=lambda: [git_entry.delete(0, tk.END), git_entry.insert(0, filedialog.askdirectory())]).grid(row=0, column=2)

    ttk.Label(app, text="Commit SHA（可多筆，用逗號或換行）：").grid(row=1, column=0, sticky="w", padx=10, pady=5)
    sha_entry = scrolledtext.ScrolledText(app, height=4)
    sha_entry.grid(row=1, column=1, columnspan=2, padx=5)

    ttk.Label(app, text="輸出資料夾：").grid(row=2, column=0, sticky="w", padx=10, pady=5)
    out_entry = ttk.Entry(app, width=80)
    out_entry.grid(row=2, column=1, padx=5)
    ttk.Button(app, text="Browse", command=lambda: [out_entry.delete(0, tk.END), out_entry.insert(0, filedialog.askdirectory())]).grid(row=2, column=2)

    log_text = scrolledtext.ScrolledText(app, height=15, state="disabled")
    log_text.grid(row=4, column=0, columnspan=3, padx=10, pady=10, sticky="nsew")

    app.grid_rowconfigure(4, weight=1)
    app.grid_columnconfigure(1, weight=1)

    def on_extract():
        git_dir = git_entry.get().strip()
        sha_input = sha_entry.get("1.0", tk.END).strip()
        out_dir = out_entry.get().strip()

        if not (git_dir and sha_input and out_dir):
            Messagebox.show_error("請填寫所有欄位", title="錯誤")
            return

        save_config({"git": git_dir, "sha": sha_input, "out": out_dir})
        sha_list = re.split(r'[\s,]+', sha_input.strip())

        for sha in sha_list:
            if sha:
                log(f"\n🚀 處理 commit: {sha}", log_text)
                extract_commit(git_dir, sha, out_dir, log_text)

    def on_open_output():
        out_dir = out_entry.get().strip()
        open_output_folder(out_dir)

    ttk.Button(app, text="Extract", bootstyle="success", command=on_extract).grid(row=3, column=1, pady=10, sticky="e")
    ttk.Button(app, text="開啟輸出資料夾", bootstyle="info", command=on_open_output).grid(row=3, column=2, pady=10, sticky="w")

    git_entry.insert(0, config.get("git", ""))
    sha_entry.insert("1.0", config.get("sha", ""))
    out_entry.insert(0, config.get("out", ""))

    app.mainloop()

if __name__ == "__main__":
    run_gui()
