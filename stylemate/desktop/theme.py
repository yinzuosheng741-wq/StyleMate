"""A neutral desktop workspace with restrained contrast and clear hierarchy."""

STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: #24272b; }
QMainWindow, QDialog { background: #fafafa; }
QFrame#sidebar { background: #f2f2f1; border-right: 1px solid #e7e7e5; }
QLabel { background: transparent; }
QLabel#brandMark { background: #282b2e; color: white; border-radius: 10px; font-size: 15px; font-weight: 700; }
QLabel#brand { font-size: 17px; font-weight: 700; color: #222426; }
QLabel#eyebrow { color: #72777c; font-size: 12px; }
QLabel#title { color: #202226; font-size: 22px; font-weight: 700; }
QLabel#subtitle { color: #6e747a; font-size: 12px; }
QFrame#hero, QFrame#card, QFrame#garmentCard {
    background: #ffffff; border: 1px solid #e9e9e8; border-radius: 12px; }
QFrame#garmentCard:hover { border-color: #c7cbd0; }
QLabel#cardTitle { font-size: 14px; font-weight: 600; }
QPushButton { background: white; border: 1px solid #e0e1e3; border-radius: 8px;
              padding: 8px 14px; color: #393e44; min-height: 18px; }
QPushButton:hover { background: #f4f5f5; border-color: #cbd0d4; }
QPushButton:pressed { background: #e9ebed; }
QPushButton:focus { border: 1px solid #8b949e; }
QPushButton:disabled { color: #a3a5a8; background: #f2f2f2; border-color: #e8e8e8; }
QPushButton#primary { background: #292c30; color: white; border: 1px solid #292c30; }
QPushButton#primary:hover { background: #44494e; }
QPushButton#primary:disabled { background: #b6b9bc; border-color: #b6b9bc; color: #fafafa; }
QPushButton#danger { color: #ae514c; }
QPushButton#nav { background: transparent; color: #62676c; border: 1px solid transparent;
                  text-align: left; padding: 10px 12px; font-size: 13px; }
QPushButton#nav:checked { color: #24272b; background: #e4e5e5; font-weight: 600; border-radius: 8px; }
QPushButton#nav:hover { background: #e9e9e8; }
QPushButton#nav:focus { border-color: #bcc0c3; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QListWidget {
    border: 1px solid #e1e2e3; background: white; border-radius: 8px; padding: 9px;
    selection-background-color: #6f7e8f; selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #9da6ad; }
QComboBox::drop-down { border: none; width: 24px; }
QListWidget::item { padding: 9px 5px; border-radius: 5px; }
QListWidget::item:selected { background: #eaeced; color: #272a2d; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollArea#chatTranscript, QWidget#chatCanvas { background: #fafafa; border: none; }
QFrame#userBubble { background: #eceef0; border: none; border-radius: 16px; }
QLabel#userMessage { color: #25282c; font-size: 13px; }
QLabel#assistantAvatar { background: #2d3135; color: #ffffff; border-radius: 15px; font-size: 15px; }
QLabel#messageAuthor { color: #303438; font-size: 13px; font-weight: 700; }
QLabel#messageMeta { color: #737980; font-size: 11px; }
QLabel#chatWelcome { color: #25282b; font-size: 24px; font-weight: 700; }
QTextBrowser#assistantMessage { background: transparent; border: none; padding: 0; color: #292d31; }
QFrame#chatComposer { background: #ffffff; border: 1px solid #dfe1e3; border-radius: 16px; }
QPlainTextEdit#chatInput, QPlainTextEdit#chatInput:focus { background: transparent; border: none; padding: 4px; }
QPushButton#chatSuggestion { background: transparent; border: 1px solid #e4e5e6; color: #71767d;
                              border-radius: 12px; padding: 4px 11px; font-size: 12px; }
QPushButton#chatSuggestion:hover { background: #f0f1f2; color: #303438; }
QScrollBar:vertical { width: 8px; background: transparent; }
QScrollBar::handle:vertical { background: #d3d5d7; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QStatusBar { background: #fafafa; color: #96999c; font-size: 11px; }
QStatusBar::item { border: none; }
QProgressBar { max-height: 3px; border: none; background: #e9eaeb; }
QProgressBar::chunk { background: #7f8c97; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 10px 23px; margin-right: 7px; color: #85898e; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #303438; border-bottom-color: #505860; }
QTabBar::tab:hover { background: #f0f1f1; }
QMenu { background: white; border: 1px solid #e1e2e3; padding: 5px; }
QMenu::item { padding: 9px 22px; border-radius: 4px; }
QMenu::item:selected { background: #edeff0; color: #24272b; }
QToolTip { background: white; color: #24272b; border: 1px solid #e1e2e3; padding: 6px; }
"""
