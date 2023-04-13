import os
import sys
import json
import re
import threading
import Ui_Git_code_change
from git import Repo
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog, QLineEdit, QFormLayout


def export_diff_files(repo_path, sha1):
    repo = Repo(repo_path)
    commit = repo.commit(sha1)
    parent_commit = commit.parents[0]

    diff = parent_commit.diff(commit, create_patch=True)

    modified_files = list(diff.iter_change_type("M"))
    added_files = list(diff.iter_change_type("A"))
    deleted_files = list(diff.iter_change_type("D"))

    mod_dir = os.path.join(sha1, "mod")
    org_dir = os.path.join(sha1, "org")
    os.makedirs(mod_dir, exist_ok=True)
    os.makedirs(org_dir, exist_ok=True)

    for diff_file in modified_files:
        new_blob = diff_file.b_blob
        old_blob = diff_file.a_blob

        new_file_path = os.path.join(mod_dir, new_blob.path)
        old_file_path = os.path.join(org_dir, old_blob.path)

        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(new_file_path, "wb") as f:
            f.write(new_blob.data_stream.read())
        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())

    for diff_file in added_files:
        new_blob = diff_file.b_blob

        new_file_path = os.path.join(mod_dir, new_blob.path)
        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)

        with open(new_file_path, "wb") as f:
            f.write(new_blob.data_stream.read())

    for diff_file in deleted_files:
        old_blob = diff_file.a_blob

        old_file_path = os.path.join(org_dir, old_blob.path)
        os.makedirs(os.path.dirname(old_file_path), exist_ok=True)

        with open(old_file_path, "wb") as f:
            f.write(old_blob.data_stream.read())


def is_valid_sha1(sha1):
    if len(sha1) != 40:
        return False
    if not re.match(r"[0-9a-fA-F]{40}", sha1):
        return False
    return True


class GitDiffExportApp(QtWidgets.QMainWindow, Ui_Git_code_change.Ui_GitDiffExportUI):
    def __init__(self, parent=None):
        super(GitDiffExportApp, self).__init__(parent)
        self.setupUi(self)
        self.setup_control()
        self.load_config()
        self.form_layout = QFormLayout(self.centralwidget)
        self.setCentralWidget(self.centralwidget)
        self.form_layout.setFormAlignment(QtCore.Qt.AlignLeft)
        self.sha1_inputs = [self.SHA1_input]

    def setup_control(self):
        # Connect the "Start" button, the "Browse" button, and the "SHA1_group" signals to their handlers
        self.pushButton_browse.clicked.connect(self.browse)
        self.pushButton_start.clicked.connect(self.start)
        self.SHA1_group.currentIndexChanged.connect(self.change_num_sha1)

    def browse(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        repo_path = QFileDialog.getExistingDirectory(self, "Select Git Repository", "", options=options)
        self.repo_path_input.setPlainText(repo_path)

    def change_num_sha1(self, index):
        num_sha1 = index + 1

        while len(self.sha1_inputs) < num_sha1:
            new_sha1_input = QLineEdit()
            self.sha1_inputs.append(new_sha1_input)
            self.form_layout.insertRow(len(self.sha1_inputs) + 3, new_sha1_input)

        while len(self.sha1_inputs) > num_sha1:
            sha1_input = self.sha1_inputs.pop()
            self.form_layout.removeWidget(sha1_input)
            sha1_input.deleteLater()

    def start(self):
        repo_path = self.repo_path_input.text()
        sha1_list = [sha1_input.text() for sha1_input in self.sha1_inputs]
        # Check if all sha1s are valid
        for sha1 in sha1_list:
            if not is_valid_sha1(sha1):
                QMessageBox.warning(self, "Invalid SHA-1", f"The provided SHA-1 '{sha1}' is invalid.")
                return
        # Call the export_diff_files function with each sha1 in the sha1_list
        # Create and start a thread for each SHA-1
        threads = []
        for sha1 in sha1_list:
            thread = threading.Thread(target=export_diff_files, args=(repo_path, sha1))
            thread.start()
            threads.append(thread)
        # Wait for all threads to finish
        for thread in threads:
            thread.join()
        # Show the completed dialog
        QMessageBox.information(self, "Operation Completed", "The operation has been completed successfully.", QMessageBox.Ok)

    def closeEvent(self, event):
        self.save_config()
        event.accept()

    def save_config(self):
        config = {"last_repo_path": self.repo_path_input.text()}
        with open("config.json", "w") as f:
            json.dump(config, f)

    def load_config(self):
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
            last_repo_path = config.get("last_repo_path", "")
            self.repo_path_input.setPlainText(last_repo_path)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GitDiffExportApp()
    window.show()
    sys.exit(app.exec_())