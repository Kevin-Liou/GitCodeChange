import sys
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QLabel

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QVBoxLayout()

        self.top_layout = QHBoxLayout()
        self.label = QLabel("選擇輸入框數量:")
        self.top_layout.addWidget(self.label)

        self.combo_box = QComboBox()
        for i in range(1, 11):
            self.combo_box.addItem(str(i))
        self.top_layout.addWidget(self.combo_box)
        self.layout.addLayout(self.top_layout)

        self.input_layout = QVBoxLayout()
        self.line_edits = []
        self.update_input_boxes(1)
        self.layout.addLayout(self.input_layout)

        self.combo_box.currentIndexChanged.connect(self.on_combobox_changed)
        self.setLayout(self.layout)

    def on_combobox_changed(self, index):
        num_boxes = index + 1
        self.update_input_boxes(num_boxes)

    def update_input_boxes(self, num_boxes):
        for line_edit in self.line_edits:
            self.input_layout.removeWidget(line_edit)
            line_edit.deleteLater()

        self.line_edits = [QLineEdit() for _ in range(num_boxes)]
        for line_edit in self.line_edits:
            self.input_layout.addWidget(line_edit)
        self.adjustSize()  # 在此處添加調整大小的方法

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
