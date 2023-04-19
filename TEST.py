from PyQt5.QtWidgets import QWidget, QTableWidget, QTableWidgetItem, QVBoxLayout

class select_files_windows(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        # 創建tableWidget物件
        self.tableWidget = QTableWidget()
        self.tableWidget.setRowCount(10)
        self.tableWidget.setColumnCount(5)
        self.tableWidget.setHorizontalHeaderLabels(['Column 1', 'Column 2', 'Column 3', 'Column 4', 'Column 5'])

        # 設定表格列寬自適應
        self.tableWidget.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # 將tableWidget物件添加到垂直佈局中
        layout = QVBoxLayout()
        layout.addWidget(self.tableWidget)
        self.setLayout(layout)