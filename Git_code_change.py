import os, sys, json, threading, UI, Git_lib
from PyQt5 import QtWidgets
from PyQt5.QtWidgets import QApplication, QMessageBox, QFileDialog, QHeaderView, QAbstractItemView


class how_to_use_windows(QtWidgets.QDialog, UI.Ui_Git_code_change_how_to_use.Ui_Howtoused):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

class setting_windows(QtWidgets.QDialog, UI.Ui_Git_code_change_setting.Ui_Setting):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

class select_files_windows(QtWidgets.QDialog, UI.Ui_Git_code_change_select_files.Ui_Selectfiles):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.tableWidget_files_list.horizontalHeader().resizeSection(0, 550) # Set column width
        self.tableWidget_files_list.horizontalHeader().resizeSection(1, 88) # Set column width
        #self.tableWidget_files_list.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch) # Column width auto-sizing feature
        self.tableWidget_files_list.setEditTriggers(QAbstractItemView.NoEditTriggers) # Disable editing
        self.tableWidget_files_list.verticalHeader().setVisible(False) # Hide rows

class main_windows(QtWidgets.QMainWindow, UI.Ui_Git_code_change_main.Ui_GitDiffExportUI):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setup_control()
        self.load_config()
        self.sha1_inputs = [self.SHA1_input]

    # Set up signal connections for UI elements.
    def setup_control(self):
        self.pushButton_repo_browse.clicked.connect(self.repo_browse)
        self.pushButton_output_browse.clicked.connect(self.output_browse)
        self.pushButton_build.clicked.connect(self.open_select_files_windows) # test
        self.SHA1_group.currentIndexChanged.connect(self.change_num_sha1)
        self.actionHow_to_use.triggered.connect(self.open_how_to_use_windows)
        self.actionSetting.triggered.connect(self.open_setting_windows)

    # Show a dialog to select a Git repository, then set the selected path as the repository path.
    def repo_browse(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        repo_path = QFileDialog.getExistingDirectory(self, "Select Git Repository", "", options=options)
        # Check if the .git directory exists in the repo_path
        if not os.path.exists(os.path.join(repo_path, '.git')):
            QMessageBox.information(self, "Error", "Not a valid Git repository.", QMessageBox.Ok)
            return
        self.repo_path_input.setPlainText(repo_path)

    # Show a dialog to select an output directory, then set the selected path as the output path.
    def output_browse(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        output_path = QFileDialog.getExistingDirectory(self, "Select Output Repository", "", options=options)
        # Check if the directory exists
        if not os.path.exists(output_path):
            QMessageBox.information(self, "Error", "This path does not exist.", QMessageBox.Ok)
            return
        self.output_path_input.setPlainText(output_path)

    # Start the process of exporting Git diffs for the specified SHA-1s.
    def start(self):
        repo_path = self.repo_path_input.toPlainText()
        output_path = self.output_path_input.toPlainText()
        sha1_list = [sha1_input.toPlainText() for sha1_input in self.sha1_inputs]
        # Check if all sha1s are valid
        invalid_list = [sha1 for sha1 in sha1_list if not Git_lib.is_valid_sha1(sha1)]
        # If there are any invalid SHA-1s and (the list has more than one element or the first element is not an empty string)
        if invalid_list and (len(sha1_list) > 1 or (len(sha1_list) == 1 and sha1_list[0] != "")):
            QMessageBox.warning(self, "Invalid SHA-1", f"The provided SHA-1s '{invalid_list}' are invalid.")
            return
        # Call the export_diff_files function with each sha1 in the sha1_list
        # Create and start a thread for each SHA-1
        if len(sha1_list) == 1 and sha1_list[0] == "":
            Git_lib.export_uncommitted_changes(repo_path, output_path)
        else:
            threads = [threading.Thread(target=Git_lib.export_diff_files, args=(repo_path, sha1, output_path)) for sha1 in sha1_list]
            for thread in threads:
                thread.start()
            # Wait for all threads to finish
            for thread in threads:
                thread.join()
        # Show the completed dialog
        QMessageBox.information(self, "Operation Completed", "The operation has been completed successfully.", QMessageBox.Ok)

    # Change the number of SHA-1 input fields based on the user's selection.
    def change_num_sha1(self, index):
        # Calculate the number of SHA1 inputs needed based on the selected index
        num_sha1_needed = index + 1
        # If more SHA1 inputs are needed, create them and add them to the layout
        while len(self.sha1_inputs) < num_sha1_needed:
            new_sha1_input = QtWidgets.QPlainTextEdit(self.widget)
            new_sha1_input.setSizePolicy(self.SHA1_input.sizePolicy())
            self.sha1_inputs.append(new_sha1_input)
            self.horizontalLayout_2.insertWidget(len(self.sha1_inputs), new_sha1_input)
        # If fewer SHA1 inputs are needed, remove the extra ones and delete them
        while len(self.sha1_inputs) > num_sha1_needed:
            extra_sha1_input = self.sha1_inputs.pop()
            self.horizontalLayout_2.removeWidget(extra_sha1_input)
            extra_sha1_input.deleteLater()

    # Save the configuration when closing the application.
    def closeEvent(self, event):
        self.save_config()
        event.accept()

    # Save the last repository path to a configuration file.
    def save_config(self):
        config = {
            "last_repo_path": self.repo_path_input.toPlainText(),
            "last_output_path": self.output_path_input.toPlainText()
        }
        with open("config.json", "w") as f:
            json.dump(config, f)

    # Load the last repository path from a configuration file and set it as the repository path.
    def load_config(self):
        if os.path.exists("config.json"):
            with open("config.json", "r") as f:
                config = json.load(f)
            last_repo_path = config.get("last_repo_path", "")
            last_output_path = config.get("last_output_path", "")
            self.repo_path_input.setPlainText(last_repo_path)
            self.output_path_input.setPlainText(last_output_path)

    # Open the "How to Use" window.
    def open_how_to_use_windows(self):
        self.how_to_use_win = how_to_use_windows()
        self.how_to_use_win.show()

    # Open the "Settings" window.
    def open_setting_windows(self):
        self.setting_win = setting_windows()
        self.setting_win.show()

    # Open the "Select files" window.
    def open_select_files_windows(self):
        self.select_files_win = select_files_windows()
        self.select_files_win.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = main_windows()
    window.show()
    sys.exit(app.exec_())