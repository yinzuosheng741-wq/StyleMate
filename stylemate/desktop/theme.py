"""A quiet light theme with one restrained accent for primary actions."""

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #273b35; }
QMainWindow, QDialog { background: #fafbf9; }
QFrame#sidebar { background: #f0f3ef; border-right: 1px solid #e3e8e2; }
QLabel { background: transparent; }
QLabel#brand { font-size: 22px; font-weight: 700; color: #244d3e; }
QLabel#eyebrow { color: #7b8880; font-size: 12px; }
QLabel#title { font-size: 25px; font-weight: 700; }
QLabel#subtitle { color: #748078; font-size: 12px; }
QFrame#hero, QFrame#card, QFrame#garmentCard {
    background: #ffffff; border: 1px solid #e4e9e2; border-radius: 12px; }
QFrame#garmentCard:hover { border-color: #acc4b4; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; }
QPushButton { background: white; border: 1px solid #dce4dc; border-radius: 7px;
              padding: 8px 14px; color: #345746; min-height: 18px; }
QPushButton:hover { background: #edf4ee; border-color: #b4caba; }
QPushButton:pressed { background: #e0ece2; }
QPushButton:focus { border: 1px solid #508467; }
QPushButton:disabled { color: #9ba69e; background: #f0f3ee; border-color: #e5eae3; }
QPushButton#primary { background: #356b50; color: white; border: 1px solid #356b50; }
QPushButton#primary:hover { background: #28583f; }
QPushButton#primary:disabled { background: #a7baad; border-color: #a7baad; color: #f7faf7; }
QPushButton#danger { color: #b24d40; }
QPushButton#nav { background: transparent; color: #64766b; border: 1px solid transparent;
                  text-align: left; padding: 11px 14px; font-size: 14px; }
QPushButton#nav:checked { color: #254f3b; background: #dfeade; font-weight: 600; border-radius: 8px; }
QPushButton#nav:hover { background: #e6ece3; }
QPushButton#nav:focus { border-color: #9fbba7; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QListWidget {
    border: 1px solid #dfe5de; background: white; border-radius: 8px; padding: 9px;
    selection-background-color: #356b50; selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #81a38b; }
QTextBrowser#chatTranscript { background: #ffffff; border: 1px solid #edf0eb; border-radius: 12px; padding: 0; }
QFrame#chatComposer { background: #ffffff; border: 1px solid #d8e3d9; border-radius: 14px; }
QPlainTextEdit#chatInput, QPlainTextEdit#chatInput:focus { background: transparent; border: none; padding: 4px; }
QComboBox::drop-down { border: none; width: 24px; }
QListWidget::item { padding: 9px 5px; border-radius: 5px; }
QListWidget::item:selected { background: #e5efe3; color: #254f3b; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #d3dcd2; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #fafbf9; color: #859087; font-size: 11px; }
QStatusBar::item { border: none; }
QProgressBar { max-height: 3px; border: none; background: #e6ece2; }
QProgressBar::chunk { background: #709b79; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 10px 23px; margin-right: 7px; color: #748078; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #2e6147; border-bottom-color: #356b50; }
QTabBar::tab:hover { background: #edf3e9; }
QMenu { background: white; border: 1px solid #dfe5de; padding: 5px; }
QMenu::item { padding: 9px 22px; border-radius: 4px; }
QMenu::item:selected { background: #e5efe3; color: #254f3b; }
QToolTip { background: #ffffff; color: #273b35; border: 1px solid #dfe5de; padding: 6px; }
"""
