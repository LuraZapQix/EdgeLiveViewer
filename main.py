#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
エッヂ実況ビュアー
エッヂ掲示板のコメントをニコニコ動画風に表示するアプリケーション
"""

import os
import sys
import time
import json
import re
import requests
import logging
import zstandard as zstd
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                             QTabWidget, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QComboBox, QMessageBox, QInputDialog, 
                             QMenu, QDialog, QTextEdit, QFormLayout, QGroupBox, QDockWidget,
                             QCheckBox)
from PyQt5.QtCore import Qt, QTimer, QUrl, QPoint, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QDesktopServices

from thread_fetcher_improved import ThreadFetcher, CommentFetcher, NextThreadFinder, MainstreamWatcher
from comment_animation_improved import CommentOverlayWindow
from settings_dialog import SettingsDialog

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('EdgeLiveViewer')

class PostCommentWorker(QThread):
    """コメント投稿を非同期で実行するワーカースレッド"""
    finished = pyqtSignal(bool, str, str, str, str)  # success, response, name, mail, comment
    
    def __init__(self, main_window, thread_id, name, mail, comment, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.thread_id = thread_id
        self.name = name
        self.mail = mail
        self.comment = comment
        
    def run(self):
        """別スレッドでHTTPリクエストを実行"""
        success, response = self._send_post_request()
        self.finished.emit(success, response, self.name, self.mail, self.comment)
    
    def _send_post_request(self):
        """エッヂに書き込みリクエストを送信（スレッドセーフ）"""
        url = "https://bbs.eddibb.cc/test/bbs.cgi"
        headers = {
            "User-Agent": "EdgeLiveViewer/1.0",
            "Referer": f"https://bbs.eddibb.cc/liveedge/{self.thread_id}",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Content-Type": "application/x-www-form-urlencoded; charset=Shift_JIS",
            "Origin": "https://bbs.eddibb.cc",
        }

        def to_shift_jis(text):
            try:
                return text.encode("shift_jis")
            except UnicodeEncodeError:
                result = ""
                for char in text:
                    try:
                        result += char.encode("shift_jis").decode("shift_jis")
                    except UnicodeEncodeError:
                        result += f"&#{ord(char)};"
                return result.encode("shift_jis")

        data = {
            "bbs": "liveedge",
            "key": self.thread_id,
            "FROM": to_shift_jis(self.name),
            "mail": to_shift_jis(self.mail) if self.mail else b"",
            "MESSAGE": to_shift_jis(self.comment),
            "submit": "書き込む".encode("shift_jis"),
        }
        
        # メインウィンドウから設定を取得（スレッドセーフに注意）
        auth_token = self.main_window.auth_token
        tinker_token = self.main_window.settings.get("tinker_token", "")
        
        if auth_token:
            data["mail"] = to_shift_jis(f"#{auth_token}")
            logger.info(f"認証トークンを適用: {auth_token}")

        session = requests.Session()
        try:
            if auth_token:
                session.cookies.set("edge-token", auth_token, domain="bbs.eddibb.cc")
            if tinker_token:
                session.cookies.set("tinker-token", tinker_token, domain="bbs.eddibb.cc")

            pre_response = session.get(
                f"https://bbs.eddibb.cc/liveedge/{self.thread_id}",
                headers=headers,
                timeout=5
            )
            logger.info(f"事前リクエスト: ステータス={pre_response.status_code}")

            logger.info(f"送信データ: {data}")
            logger.info(f"送信クッキー: {session.cookies.get_dict()}")
            response = session.post(url, headers=headers, data=data, timeout=10)

            try:
                response_text = response.content.decode("shift_jis")
            except UnicodeDecodeError:
                response_text = response.content.decode("utf-8", errors="replace")
                logger.warning("Shift_JISデコード失敗、UTF-8で代替")

            logger.info(f"レスポンスステータス: {response.status_code}")
            logger.info(f"レスポンス本文: {response_text[:500]}...")

            if response.status_code == 200 and "<title>書きこみました</title>" in response_text:
                # トークン更新はメインスレッドで行う必要があるため、レスポンスに含める
                new_tinker = session.cookies.get("tinker-token")
                new_edge = session.cookies.get("edge-token")
                # 新しいトークン情報をレスポンスに追加
                token_info = f"__TOKENS__:{new_tinker or ''}:{new_edge or ''}"
                logger.info("書き込みが正常に完了しました")
                return True, response_text + token_info

            auth_code_match = re.search(r"^\d{6}$", response_text.strip()) or re.search(
                r'<input[^>]*name="auth-code"[^>]*value="([^"]+)"[^>]*>|認証コード[\'""](\d{6})[\'""]',
                response_text
            )
            if auth_code_match:
                auth_code = auth_code_match.group(0) if auth_code_match.group(0).isdigit() else (auth_code_match.group(1) or auth_code_match.group(2))
                logger.info(f"認証コードを受信: {auth_code}")
                return False, auth_code

            logger.error("書き込み失敗: 成功条件を満たしていません")
            return False, response_text
        except requests.RequestException as e:
            logger.error(f"書き込みリクエストに失敗: {str(e)}")
            return False, str(e)

class WriteWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("書き込み")
        self.setMinimumWidth(400)
        self._dragging = False
        self._offset = QPoint()
        # MainWindowへの参照を保持
        self.main_window = parent if isinstance(parent, MainWindow) else None
        self.setup_ui()
        
        self.hide_on_detach = self.main_window.settings.get("hide_name_mail_on_detach", False) if self.main_window else False
        self.hide_checkbox.setChecked(self.hide_on_detach)

        # 透過度の初期設定
        if self.main_window:
            opacity = self.main_window.settings.get("write_window_opacity", 1.0)
            self.setWindowOpacity(opacity)
            logger.info(f"WriteWidget 初期化時に透過度を設定: {opacity*100}%")
    
    def setup_ui(self):
        write_layout = QVBoxLayout()
        # レイアウトのマージンとスペーシングを縮める
        write_layout.setContentsMargins(2, 2, 2, 2)  # 上下左右のマージンを5pxに
        write_layout.setSpacing(4)  # 内部の間隔を2pxに縮小
        
        # 名前、メール、チェックボックスを同じ行に配置
        self.name_mail_layout = QHBoxLayout()
        self.name_mail_layout.setSpacing(4)  # 水平間隔も縮小
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("エッヂの名無し")
        self.name_input.setFixedWidth(200)
        self.name_mail_layout.addWidget(QLabel("名前:"))
        self.name_mail_layout.addWidget(self.name_input)
        
        self.mail_input = QLineEdit()
        self.mail_input.setPlaceholderText("sage または空欄")
        self.mail_input.setFixedWidth(150)
        self.name_mail_layout.addWidget(QLabel("メール:"))
        self.name_mail_layout.addWidget(self.mail_input)
        
        self.hide_checkbox = QCheckBox("分離時に非表示")
        self.hide_checkbox.stateChanged.connect(self.update_hide_setting)
        self.name_mail_layout.addWidget(self.hide_checkbox)
        
        self.name_mail_layout.addStretch()
        write_layout.addLayout(self.name_mail_layout)
        
        # コメントとボタンのレイアウト
        comment_button_layout = QHBoxLayout()
        comment_button_layout.setSpacing(4)  # 水平間隔も縮小
        self.comment_input = QLineEdit()
        self.comment_input.setPlaceholderText("コメントを入力")
        comment_button_layout.addWidget(QLabel("本文:"))
        comment_button_layout.addWidget(self.comment_input)
        
        self.post_button = QPushButton("書き込む")
        self.post_button.setFixedWidth(100)
        comment_button_layout.addWidget(self.post_button)
        
        self.toggle_button = QPushButton("分離")
        self.toggle_button.setFixedWidth(100)
        comment_button_layout.addWidget(self.toggle_button)
        
        write_layout.addLayout(comment_button_layout)
        self.setLayout(write_layout)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.parent() is None:
            self._dragging = True
            self._offset = event.pos()
            event.accept()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        if self._dragging and self.parent() is None:
            self.move(self.mapToGlobal(event.pos() - self._offset))
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()

    def update_hide_setting(self, state):
        """チェックボックスの状態を更新し、設定に保存"""
        self.hide_on_detach = (state == Qt.Checked)
        if self.parent() and isinstance(self.parent(), MainWindow):
            self.parent().settings["hide_name_mail_on_detach"] = self.hide_on_detach
            self.parent().save_settings()
            logger.info(f"分離時に非表示設定を更新: {self.hide_on_detach}")

    def set_name_mail_visible(self, visible):
        """名前とメール欄の表示/非表示を切り替え"""
        self.name_input.setVisible(visible)
        self.mail_input.setVisible(visible)
        for i in range(self.name_mail_layout.count()):
            item = self.name_mail_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), QLabel):
                item.widget().setVisible(visible)
        if visible:
            self.hide_checkbox.setVisible(True)  # ドッキング時は常に表示
        else:
            self.hide_checkbox.setVisible(not self.hide_on_detach)  # 分離時: チェック済みなら非表示
        logger.info(f"名前とメール欄の表示状態を変更: {visible}, チェックボックス: {self.hide_checkbox.isVisible()}")

    def closeEvent(self, event):
        if not self.parent():  # 分離状態の場合
            if self.main_window and isinstance(self.main_window, MainWindow):
                # ドッキング処理を直接呼び出し
                self.main_window.toggle_write_widget()
                # ウィンドウが閉じないようにイベントを無視（ドッキング後に親ウィンドウが管理）
                event.ignore()
                logger.info("分離状態の書き込みウィンドウをドッキング状態に戻しました")
            else:
                # メインウィンドウが見つからない場合（異常系）は閉じる
                event.accept()
                logger.warning("メインウィンドウが見つからなかったため、書き込みウィンドウを閉じました")
        else:
            # ドッキング状態では通常通り閉じる
            event.accept()
            logger.info("ドッキング状態の書き込みウィンドウを閉じました")

    def adjust_height(self):
        """チェック状態に応じたウィンドウの高さを計算して設定"""
        # ベース高さ（入力欄とボタンのみ、マージンを最小化）
        base_height = self.comment_input.height() + self.post_button.height() + 5  # マージンを10→5に縮小
        if not self.hide_on_detach or self.parent():  # チェックなし or ドッキング時
            # フル高さ（名前欄を追加、マージンを最小化）
            full_height = base_height + self.name_input.height() + 2  # マージンを5→2に縮小
            self.setFixedHeight(full_height)
            logger.info(f"ウィンドウ高さをフルサイズに設定: {full_height}, コメント: {self.comment_input.height()}, ボタン: {self.post_button.height()}, 名前: {self.name_input.height()}")
        else:  # チェック済みで分離時
            self.setFixedHeight(base_height)
            logger.info(f"ウィンドウ高さを縮小サイズに設定: {base_height}, コメント: {self.comment_input.height()}, ボタン: {self.post_button.height()}")
            
class RetryDialog(QDialog):
    def __init__(self, error_message, retry_callback, parent=None):
        super().__init__(parent)
        self.setWindowTitle("書き込みエラー")
        self.error_message = error_message
        self.retry_callback = retry_callback
        self.remaining_time = 5
        self.setup_ui()
        self.start_countdown()

    def setup_ui(self):
        layout = QVBoxLayout()
        
        # エラーメッセージ
        error_label = QLabel(self.error_message)
        error_label.setWordWrap(True)
        layout.addWidget(error_label)
        
        # ボタンレイアウト
        button_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.retry_button = QPushButton(f"リトライ ({self.remaining_time})")
        self.retry_button.clicked.connect(self.accept)
        button_layout.addWidget(self.retry_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def start_countdown(self):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)  # 1秒ごとに更新

    def update_countdown(self):
        self.remaining_time -= 1
        self.retry_button.setText(f"リトライ ({self.remaining_time})")
        if self.remaining_time <= 0:
            self.timer.stop()
            self.accept()  # 5秒経過で自動リトライ

class AuthDialog(QDialog):
    def __init__(self, auth_code, parent=None):
        super().__init__(parent)
        self.setWindowTitle("認証が必要です")
        self.auth_code = auth_code
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        
        # 各ラベルを個別に追加して間隔を調整
        label1 = QLabel("初回書き込みまたはトークン無効化のため認証が必要です。")
        label2 = QLabel(f"認証コード: <b>{self.auth_code}</b>")
        label2.setTextFormat(Qt.RichText)
        label3 = QLabel("以下のURLにアクセスし、認証を行ってください:")
        url_label = QLabel('<a href="https://bbs.eddibb.cc/auth-code">https://bbs.eddibb.cc/auth-code</a>')
        url_label.setTextFormat(Qt.RichText)
        url_label.setOpenExternalLinks(True)
        label4 = QLabel("認証成功後、32文字のトークン（例: #xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx）を入力してください。")
        
        layout.addWidget(label1)
        layout.addSpacing(10)  # 10pxの余白
        layout.addWidget(label2)
        layout.addSpacing(10)
        layout.addWidget(label3)
        layout.addWidget(url_label)
        layout.addSpacing(10)
        layout.addWidget(label4)
        
        ok_button = QPushButton("OK")
        ok_button.setFixedWidth(100)
        ok_button.clicked.connect(self.accept)
        layout.addWidget(ok_button, alignment=Qt.AlignCenter)
        
        self.setLayout(layout)

class NGTextDialog(QDialog):
    """NGコメント/名前用のカスタムダイアログ"""
    def __init__(self, initial_text, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        
        layout = QVBoxLayout()
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setMinimumHeight(150)
        layout.addWidget(self.text_edit)
        
        button_layout = QHBoxLayout()
        self.ok_button = QPushButton("追加")
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def get_text(self):
        return self.text_edit.toPlainText().strip()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("エッヂ実況ビュアー")
        self.setMinimumSize(800, 600)
        
        QApplication.instance().setProperty("main_window", self)
        self.settings = self.load_settings()
        self.overlay_window = None
        self.thread_fetcher = None
        self.comment_fetcher = None
        self.next_thread_finder = None
        # ### 機能追加: MainstreamWatcher と元スレタイトルのプロパティを追加 ###
        self.mainstream_watcher = None
        self.original_thread_title_for_watcher = None

        self.current_thread_id = None
        self.current_thread_title = None
        self.is_past_thread = False
        self.auth_token = None
        self.load_auth_token()
        self.write_widget = None
        self.is_docked = True
        self.refresh_timer = QTimer(self)
        self.init_ui()
        
        app = QApplication.instance()
        app.setProperty("main_window", self)
        
        self.start_thread_fetcher_initial()
        self.show_tutorial_if_first_launch()
        
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_fetcher_health)
        self.health_timer.start(30000)
        self.last_post_time = 0
        self.my_comments = {}  
        self.current_thread_id = None
        self.is_thread_finished = False  # 1000レス到達で正常停止した場合はTrue
        self.detail_table.doubleClicked.connect(self.start_playback_from_comment)

        # --- 追加: タイマーの設定と開始 ---
        self.refresh_timer.timeout.connect(self.refresh_thread_list)
        if self.auto_refresh_check.isChecked():
            self.refresh_timer.start(30000)  # 30秒 = 30000ミリ秒
        # --- 追加ここまで ---

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        input_layout = QHBoxLayout()
        self.thread_input = QLineEdit()
        self.thread_input.setPlaceholderText("スレッドURLまたはID（例: https://bbs.eddibb.cc/test/read.cgi/liveedge/1742132339/ または 1742132339）")
        self.thread_input.returnPressed.connect(self.connect_to_thread)
        connect_button = QPushButton("接続")
        connect_button.clicked.connect(self.connect_to_thread)
        input_layout.addWidget(QLabel("スレッドURL/ID:"))
        input_layout.addWidget(self.thread_input)
        input_layout.addWidget(connect_button)
        main_layout.addLayout(input_layout)
        
        self.tab_widget = QTabWidget()
        
        # スレッド一覧タブ
        thread_tab = QWidget()
        thread_layout = QVBoxLayout(thread_tab)
        sort_layout = QHBoxLayout()
        sort_layout.addWidget(QLabel("並び替え:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("勢い順", "momentum")
        self.sort_combo.addItem("新着順", "date")
        self.sort_combo.currentIndexChanged.connect(self.change_sort_order)
        sort_layout.addWidget(self.sort_combo)
        
        # --- ここからレイアウトの修正 ---
        
        # 更新ボタンを先に定義しておく
        refresh_button = QPushButton("更新")
        refresh_button.clicked.connect(self.refresh_thread_list)
        
        # スペーサー（addStretch）を先に追加して、これ以降のウィジェットを右詰にする
        sort_layout.addStretch()
        
        # 自動更新チェックボックスを作成し、スペーサーの後に追加する
        self.auto_refresh_check = QCheckBox("自動更新 (30秒)")
        self.auto_refresh_check.setChecked(True) # デフォルトでON
        self.auto_refresh_check.stateChanged.connect(self.toggle_auto_refresh)
        sort_layout.addWidget(self.auto_refresh_check)
        
        # 最後に更新ボタンを配置する
        sort_layout.addWidget(refresh_button)

        # --- 修正ここまで ---
        thread_layout.addLayout(sort_layout)
        
        self.thread_table = QTableWidget(0, 4)
        self.thread_table.setHorizontalHeaderLabels(["スレッドタイトル", "レス数", "勢い", "作成日時"])
        self.thread_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.thread_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.thread_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.thread_table.doubleClicked.connect(self.thread_selected)
        
        self.thread_table.setColumnWidth(1, 60)
        self.thread_table.setColumnWidth(2, 60)
        self.thread_table.setColumnWidth(3, 80)
        
        thread_layout.addWidget(self.thread_table)
        self.tab_widget.addTab(thread_tab, "スレッド一覧")
        
        # スレッド詳細タブ
        self.detail_tab = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_tab)
        
        self.thread_title_label = QLabel("接続中のスレッド: 未接続")
        self.thread_title_label.setAlignment(Qt.AlignCenter)
        self.detail_layout.addWidget(self.thread_title_label)
        
        self.detail_table = QTableWidget(0, 5)
        self.detail_table.setHorizontalHeaderLabels(["番号", "本文", "名前", "ID", "投稿日時"])
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setColumnWidth(0, 40)
        self.detail_table.setColumnWidth(2, 80)
        self.detail_table.setColumnWidth(3, 80)
        self.detail_table.setColumnWidth(4, 100)
        self.detail_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail_table.customContextMenuRequested.connect(self.show_context_menu)
        self.detail_layout.addWidget(self.detail_table)
        
        self.write_widget = WriteWidget(self)
        self.write_widget.post_button.clicked.connect(self.post_comment)
        self.write_widget.comment_input.returnPressed.connect(self.post_comment)
        self.write_widget.toggle_button.clicked.connect(self.toggle_write_widget)
        self.detail_layout.addWidget(self.write_widget)
        
        self.tab_widget.addTab(self.detail_tab, "スレッド詳細")
        
        main_layout.addWidget(self.tab_widget)
        
        button_layout = QHBoxLayout()
        settings_button = QPushButton("設定")
        settings_button.clicked.connect(self.show_settings)
        button_layout.addStretch()
        button_layout.addWidget(settings_button)
        
        main_layout.addLayout(button_layout)
        
        self.statusBar().showMessage("準備完了")

    # --- 追加: 自動更新のON/OFFを切り替えるメソッド ---
    def toggle_auto_refresh(self, state):
        if state == Qt.Checked:
            self.refresh_timer.start(30000)
            self.statusBar().showMessage("スレッド一覧の自動更新を開始しました。")
            logger.info("スレッド一覧の自動更新を開始しました。")
        else:
            self.refresh_timer.stop()
            self.statusBar().showMessage("スレッド一覧の自動更新を停止しました。")
            logger.info("スレッド一覧の自動更新を停止しました。")
    # --- 追加ここまで ---

    def update_thread_list(self, threads):
        # 以前の修正を反映したバージョン
        self.thread_table.setRowCount(0)
        
        for thread in threads:
            row = self.thread_table.rowCount()
            self.thread_table.insertRow(row)
            
            self.thread_table.setItem(row, 0, QTableWidgetItem(thread["title"]))
            self.thread_table.setItem(row, 1, QTableWidgetItem(thread["res_count"]))
            
            momentum_str = f"{thread['momentum']:,}"
            self.thread_table.setItem(row, 2, QTableWidgetItem(momentum_str))
            
            self.thread_table.setItem(row, 3, QTableWidgetItem(thread["date"]))
            
            self.thread_table.item(row, 0).setData(Qt.UserRole, thread["id"])
        
        # 自動更新時にはステータスメッセージを上書きしないように配慮
        if not self.refresh_timer.isActive() or not self.auto_refresh_check.isChecked():
             self.statusBar().showMessage(f"スレッド一覧を更新しました（{len(threads)}件）")

    def start_playback_from_comment(self):
        """スレッド詳細画面のレスをダブルクリックして再生開始"""
        if not self.is_past_thread:
            return

        selected_row = self.detail_table.currentRow()
        if selected_row < 0:
            logger.warning("選択された行がありません")
            return

        comment_number = int(self.detail_table.item(selected_row, 0).text())
        logger.info(f"ダブルクリックで選択されたコメント番号: {comment_number}")

        # 現在のCommentFetcherを停止
        if self.comment_fetcher and self.comment_fetcher.isRunning():
            self.comment_fetcher.stop()
            logger.info("既存のCommentFetcherを停止しました")

        # CommentOverlayWindowをリセット
        if self.overlay_window:
            self.overlay_window.comments.clear()
            self.overlay_window.comment_queue.clear()
            self.overlay_window.row_usage.clear()
            if self.overlay_window.flow_timer.isActive():
                self.overlay_window.flow_timer.stop()
            logger.info("CommentOverlayWindowをリセットしました")

        # 新しいCommentFetcherを開始（指定位置から）
        self.start_thread_fetcher_from_position(
            self.current_thread_id,
            self.current_thread_title,
            start_number=comment_number
        )
        self.statusBar().showMessage(f"コメント番号 {comment_number} から再生を開始しました")

    def start_thread_fetcher_from_position(self, thread_id, thread_title, start_number=None):
        """指定された番号からCommentFetcherを開始"""
        if self.comment_fetcher and self.comment_fetcher.isRunning():
            self.comment_fetcher.stop()

        playback_speed = self.settings.get("playback_speed", 1.0)
        comment_delay = 0  # 過去ログではデフォルトで遅延なし
        self.comment_fetcher = CommentFetcher(
            thread_id=thread_id,
            thread_title=thread_title,
            update_interval=self.settings["update_interval"],
            is_past_thread=True,  # 過去ログモードを強制
            playback_speed=playback_speed,
            comment_delay=comment_delay,
            start_number=start_number,  # 新しい引数を追加
            parent=self
        )
        self.comment_fetcher.comments_fetched.connect(self.display_comments)
        self.comment_fetcher.thread_filled.connect(self.handle_thread_filled)
        self.comment_fetcher.error_occurred.connect(self.show_error)
        self.comment_fetcher.thread_over_1000.connect(self.on_thread_over_1000)
        self.comment_fetcher.start()

        self.current_thread_id = thread_id
        self.current_thread_title = thread_title
        self.thread_title_label.setText(f"接続中のスレッド: {thread_title}")
        logger.info(f"スレッド {thread_id} の再生を番号 {start_number} から開始しました (タイトル: {thread_title}, 再生速度: {playback_speed}x)")

    def toggle_write_widget(self):
        if self.write_widget is None:
            logger.error("書き込みウィジェットが初期化されていません")
            return
        
        if self.is_docked:
            # 分離
            docked_pos = self.write_widget.mapToGlobal(QPoint(0, 0))
            self.write_widget.setParent(None)
            self.write_widget.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.write_widget.hide()
            if self.write_widget.hide_on_detach:
                self.write_widget.set_name_mail_visible(False)
            else:
                self.write_widget.set_name_mail_visible(True)
            self.write_widget.adjust_height()
            # 透過度の適用
            opacity = self.settings.get("write_window_opacity", 1.0)
            self.write_widget.setWindowOpacity(opacity)  # 再起動後も確実に適用
            logger.info(f"分離時に透過度を設定: {opacity*100}%")
            new_x = docked_pos.x() - 50
            new_y = docked_pos.y() - 30
            self.write_widget.move(new_x, new_y)
            self.write_widget.show()
            self.write_widget.toggle_button.setText("ドッキング")
            self.is_docked = False
            logger.info(f"書き込み欄を分離しました（位置: x={new_x}, y={new_y}）")
        else:
            # ドッキング
            self.write_widget.setParent(self)
            self.write_widget.setWindowFlags(Qt.Widget)
            self.detail_layout.addWidget(self.write_widget)
            self.write_widget.set_name_mail_visible(True)
            self.write_widget.adjust_height()
            self.write_widget.show()
            self.write_widget.toggle_button.setText("分離")
            self.is_docked = True
            logger.info("書き込み欄をドッキングしました")

    def closeEvent(self, event):
        if self.thread_fetcher is not None:
            self.thread_fetcher.stop()
        
        if self.comment_fetcher is not None:
            self.comment_fetcher.stop()
        
        if self.next_thread_finder is not None:
            self.next_thread_finder.stop()
        
        # ### 機能追加: MainstreamWatcher も停止させる ###
        if self.mainstream_watcher is not None:
            self.mainstream_watcher.stop()
        
        if self.overlay_window is not None and self.overlay_window.isVisible():
            self.overlay_window.close()
        
        # 分離状態の WriteWidget を閉じる
        if not self.is_docked and self.write_widget is not None:
            self.write_widget.close()
            logger.info("分離状態の書き込みウィジェットを閉じました")
        
        event.accept()
    
    def check_fetcher_health(self):
        # 1000レス到達で正常停止した場合は再起動しない
        if self.is_thread_finished:
            logger.debug("check_fetcher_health: スレッドは正常に完了したため、再起動しません")
            return
        
        if self.comment_fetcher and not self.comment_fetcher.isRunning():
            logger.warning("CommentFetcher が停止している可能性があります。再起動します")
            self.start_thread_fetcher(self.current_thread_id, self.current_thread_title)
    
    def show_context_menu(self, pos):
        row = self.detail_table.currentRow()
        if row < 0:
            return
        
        menu = QMenu(self)
        
        ng_id = self.detail_table.item(row, 3).text()
        ng_text = self.detail_table.item(row, 1).text().strip()
        ng_name = self.detail_table.item(row, 2).text()
        
        add_id_action = menu.addAction("NG IDに追加する")
        add_comment_action = menu.addAction("NG 本文に追加する")
        add_name_action = menu.addAction("NG 名前を追加する")
        open_settings_action = menu.addAction("NG設定")
        
        add_id_action.triggered.connect(lambda: self.add_ng_id(ng_id))
        add_comment_action.triggered.connect(lambda: self.add_ng_comment(ng_text))
        add_name_action.triggered.connect(lambda: self.add_ng_name(ng_name))
        open_settings_action.triggered.connect(self.open_ng_settings)
        
        menu.exec_(self.detail_table.mapToGlobal(pos))
    
    def add_ng_id(self, ng_id):
        if ng_id and ng_id not in self.settings["ng_ids"]:
            self.settings["ng_ids"].append(ng_id)
            self.save_settings()
            if self.overlay_window:
                self.overlay_window.update_settings(self.settings)
            logger.info(f"NG IDに追加: {ng_id}")
            self.statusBar().showMessage(f"NG ID '{ng_id}' を追加しました")
    
    def add_ng_comment(self, initial_text):
        dialog = NGTextDialog(initial_text, "NG 本文の追加", self)
        if dialog.exec_():
            text = dialog.get_text()
            if text and text not in self.settings["ng_texts"]:
                self.settings["ng_texts"].append(text)
                self.save_settings()
                if self.overlay_window:
                    self.overlay_window.update_settings(self.settings)
                logger.info(f"NG 本文に追加: {text}")
                self.statusBar().showMessage(f"NG 本文 '{text}' を追加しました")
    
    def add_ng_name(self, initial_text):
        dialog = NGTextDialog(initial_text, "NG 名前の追加", self)
        if dialog.exec_():
            text = dialog.get_text()
            if text and text not in self.settings["ng_names"]:
                self.settings["ng_names"].append(text)
                self.save_settings()
                if self.overlay_window:
                    self.overlay_window.update_settings(self.settings)
                logger.info(f"NG 名前を追加: {text}")
                self.statusBar().showMessage(f"NG 名前 '{text}' を追加しました")
    
    def open_ng_settings(self):
        dialog = SettingsDialog(self)
        dialog.tab_widget.setCurrentIndex(2)
        if dialog.exec_():
            self.settings = dialog.get_settings()
            if self.overlay_window:
                self.overlay_window.update_settings(self.settings)
            logger.info("設定を更新しました")
            print("現在の self.settings:", self.settings)
    
    def load_auth_token(self):
        """設定ファイルから認証トークンを読み込む"""
        try:
            if "auth_token" in self.settings:
                self.auth_token = self.settings["auth_token"]
                logger.info(f"認証トークンを読み込みました: {self.auth_token}")
        except Exception as e:
            logger.error(f"認証トークンの読み込みに失敗: {str(e)}")
    
    def save_auth_token(self, token):
        """認証トークンを設定ファイルに保存"""
        self.auth_token = token
        self.settings["auth_token"] = token
        self.save_settings()
        logger.info(f"認証トークンを保存しました: {token}")
    
    def send_post_request(self, thread_id, name, mail, comment):
        """エッヂに書き込みリクエストを送信"""
        url = "https://bbs.eddibb.cc/test/bbs.cgi"
        headers = {
            "User-Agent": "EdgeLiveViewer/1.0",
            "Referer": f"https://bbs.eddibb.cc/liveedge/{thread_id}",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Content-Type": "application/x-www-form-urlencoded; charset=Shift_JIS",
            "Origin": "https://bbs.eddibb.cc",
        }

        def to_shift_jis(text):
            try:
                return text.encode("shift_jis")
            except UnicodeEncodeError:
                result = ""
                for char in text:
                    try:
                        result += char.encode("shift_jis").decode("shift_jis")
                    except UnicodeEncodeError:
                        result += f"&#{ord(char)};"
                return result.encode("shift_jis")

        data = {
            "bbs": "liveedge",
            "key": thread_id,
            "FROM": to_shift_jis(name),
            "mail": to_shift_jis(mail) if mail else b"",
            "MESSAGE": to_shift_jis(comment),
            "submit": "書き込む".encode("shift_jis"),
        }
        if self.auth_token:
            data["mail"] = to_shift_jis(f"#{self.auth_token}")
            logger.info(f"認証トークンを適用: {self.auth_token}")

        session = requests.Session()
        try:
            if self.auth_token:
                session.cookies.set("edge-token", self.auth_token, domain="bbs.eddibb.cc")
            tinker_token = self.settings.get("tinker_token", "")
            if tinker_token:
                session.cookies.set("tinker-token", tinker_token, domain="bbs.eddibb.cc")

            pre_response = session.get(
                f"https://bbs.eddibb.cc/liveedge/{thread_id}",
                headers=headers,
                timeout=5
            )
            logger.info(f"事前リクエスト: ステータス={pre_response.status_code}")

            logger.info(f"送信データ: {data}")
            logger.info(f"送信クッキー: {session.cookies.get_dict()}")
            response = session.post(url, headers=headers, data=data, timeout=10)

            try:
                response_text = response.content.decode("shift_jis")
            except UnicodeDecodeError:
                response_text = response.content.decode("utf-8", errors="replace")
                logger.warning("Shift_JISデコード失敗、UTF-8で代替")

            logger.info(f"レスポンスステータス: {response.status_code}")
            logger.info(f"レスポンス本文: {response_text[:500]}...")

            if response.status_code == 200 and "<title>書きこみました</title>" in response_text:
                new_tinker = session.cookies.get("tinker-token")
                if new_tinker and new_tinker != tinker_token:
                    self.settings["tinker_token"] = new_tinker
                    self.save_settings()
                    logger.info(f"tinker-tokenを更新: {new_tinker}")
                new_edge = session.cookies.get("edge-token")
                if new_edge and new_edge != self.auth_token:
                    self.auth_token = new_edge
                    self.save_auth_token(new_edge)
                    logger.info(f"edge-tokenを更新: {new_edge}")
                logger.info("書き込みが正常に完了しました")
                return True, response_text

            auth_code_match = re.search(r"^\d{6}$", response_text.strip()) or re.search(
                r'<input[^>]*name="auth-code"[^>]*value="([^"]+)"[^>]*>|認証コード[\'"](\d{6})[\'"]',
                response_text
            )
            if auth_code_match:
                auth_code = auth_code_match.group(0) if auth_code_match.group(0).isdigit() else (auth_code_match.group(1) or auth_code_match.group(2))
                logger.info(f"認証コードを受信: {auth_code}")
                return False, auth_code

            logger.error("書き込み失敗: 成功条件を満たしていません")
            return False, response_text
        except requests.RequestException as e:
            logger.error(f"書き込みリクエストに失敗: {str(e)}")
            return False, str(e)

    def post_comment(self):
        """コメントをエッジに投稿する（非同期版）"""
        if not self.current_thread_id:
            QMessageBox.warning(self, "エラー", "スレッドに接続してください。")
            return
        
        if self.is_past_thread:
            QMessageBox.critical(self, "書き込みエラー", "過去ログには書き込みできません。")
            return
        
        name = self.write_widget.name_input.text().strip() or "エッヂの名無し"
        mail = self.write_widget.mail_input.text().strip()
        comment = self.write_widget.comment_input.text().strip()
        
        if not comment:
            return
        
        current_time = time.time()
        if current_time - self.last_post_time < 5:
            remaining = 5 - (current_time - self.last_post_time)
            QMessageBox.warning(self, "投稿制限", f"5秒以内の連続投稿はできません。あと {remaining:.1f}秒 お待ちください。")
            return
        
        # 非同期でコメント投稿を実行（UIをブロックしない）
        self.post_worker = PostCommentWorker(
            self, self.current_thread_id, name, mail, comment
        )
        self.post_worker.finished.connect(self._on_post_finished)
        self.post_worker.start()
        
        # 投稿中の状態を表示
        self.statusBar().showMessage("書き込み中...")
        self.write_widget.post_button.setEnabled(False)
        logger.info("コメント投稿を開始（非同期）")
    
    def _on_post_finished(self, success, response, name, mail, comment):
        """コメント投稿完了時の処理"""
        self.write_widget.post_button.setEnabled(True)
        
        if success:
            self.last_post_time = time.time()
            current_time = time.time()
            comment_key = f"{current_time}_{comment}"
            self.my_comments[comment_key] = {
                "text": comment,
                "number": None,
                "thread_id": self.current_thread_id
            }
            self.write_widget.comment_input.clear()
            self.statusBar().showMessage("書き込みが完了しました。")
            logger.info("コメント投稿が成功しました（非同期）")
            
            # トークン更新処理
            if "__TOKENS__:" in response:
                token_part = response.split("__TOKENS__:")[1]
                tokens = token_part.split(":")
                if len(tokens) >= 2:
                    new_tinker, new_edge = tokens[0], tokens[1]
                    tinker_token = self.settings.get("tinker_token", "")
                    if new_tinker and new_tinker != tinker_token:
                        self.settings["tinker_token"] = new_tinker
                        self.save_settings()
                        logger.info(f"tinker-tokenを更新: {new_tinker}")
                    if new_edge and new_edge != self.auth_token:
                        self.auth_token = new_edge
                        self.save_auth_token(new_edge)
                        logger.info(f"edge-tokenを更新: {new_edge}")
        else:
            if isinstance(response, str) and re.match(r"^\d{6}$", response):
                # サーバーから返された6桁の認証コードをダイアログに渡す
                self.show_auth_dialog(response)
            else:
                self.handle_post_error(response, name, mail, comment)

    def show_auth_dialog(self, auth_code):
        """カスタム認証ダイアログを表示"""
        dialog = AuthDialog(auth_code, self)
        dialog.exec_()
        
        # 認証後にトークンを入力
        token, ok = QInputDialog.getText(
            self, "トークン入力", "認証後に表示されたトークン（#を含む）を入力:",
            QLineEdit.Normal, "#"
        )
        if ok and token and re.match(r"#[a-f0-9]{32}", token):
            self.auth_token = token[1:]  # #を除去
            self.save_auth_token(self.auth_token)
            QMessageBox.information(self, "認証成功", "トークンを保存しました。再度書き込みを試してください。")
            # 認証成功後、即座に再投稿を試みる
            self.post_comment()
        elif ok:
            QMessageBox.warning(self, "入力エラー", "トークンは#で始まる32文字の英数字である必要があります。")

    def save_settings(self):
        try:
            settings_dir = os.path.expanduser("~/.edge_live_viewer")
            os.makedirs(settings_dir, exist_ok=True)
            settings_file = os.path.join(settings_dir, "settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logger.error(f"設定の保存に失敗しました: {str(e)}")
            self.show_error(f"設定の保存に失敗しました: {str(e)}")

    def display_comments(self, comments):
        if self.overlay_window is None:
            return
        
        QApplication.instance().setProperty("comment_time", time.time())
        logger.info(f"表示対象のコメント数: {len(comments)}")
        
        # 自分のコメントの番号を確定
        for comment in comments:
            comment_text = comment["text"].strip()
            comment_number = comment["number"]
            for key, my_comment in list(self.my_comments.items()):
                my_comment_text = my_comment["text"].strip()
                if (my_comment["number"] is None and 
                    my_comment_text == comment_text and 
                    my_comment["thread_id"] == self.current_thread_id):
                    self.my_comments[key]["number"] = comment_number
                    if self.overlay_window:
                        self.overlay_window.add_my_comment(comment_number, comment_text)
                    break
        
        self.overlay_window.add_comment_batch(comments)
        
        # リアルタイムモードの場合のみ、テーブルに逐次追加
        if not self.is_past_thread:
            current_row_count = self.detail_table.rowCount()
            for comment in comments:
                name = comment["name"]
                if "</b>(" in name:
                    base_name, wacchoi = name.split("</b>(")
                    wacchoi = wacchoi.rstrip(")<b>")
                    formatted_name = f"{base_name}({wacchoi})"
                else:
                    formatted_name = name
                
                self.detail_table.insertRow(current_row_count)
                self.detail_table.setItem(current_row_count, 0, QTableWidgetItem(str(comment["number"])))
                self.detail_table.setItem(current_row_count, 1, QTableWidgetItem(comment["text"]))
                self.detail_table.setItem(current_row_count, 2, QTableWidgetItem(formatted_name))
                self.detail_table.setItem(current_row_count, 3, QTableWidgetItem(comment["id"]))
                self.detail_table.setItem(current_row_count, 4, QTableWidgetItem(comment.get("date", "不明")))
                current_row_count += 1
            
            scrollbar = self.detail_table.verticalScrollBar()
            is_at_bottom = scrollbar.value() >= scrollbar.maximum()
            if is_at_bottom:
                self.detail_table.scrollToBottom()

    def handle_post_error(self, response_text, name, mail, comment):
        """書き込みエラーの処理"""
        logger.info(f"エラーレスポンス全文: {response_text}")
        error_msg = re.search(r"ＥＲＲＯＲ.*?エラー！([^<]+)", response_text)
        error_detail = error_msg.group(1).strip() if error_msg else f"不明なエラー: {response_text[:200]}"
        
        if "短期間に書き込みすぎです" in error_detail:
            dialog = RetryDialog(error_detail, lambda: self.retry_post(name, mail, comment), self)
            if dialog.exec_() == QDialog.Accepted:
                self.retry_post(name, mail, comment)
        elif "対象の'スレッド'が見つかりません" in error_detail and self.is_past_thread:
            QMessageBox.critical(self, "書き込みエラー", "過去ログには書き込みできません。")
        else:
            QMessageBox.critical(self, "書き込みエラー", f"書き込みに失敗しました。\n理由: {error_detail}")

    def retry_post(self, name, mail, comment):
        """リトライ時の投稿処理"""
        success, response = self.send_post_request(self.current_thread_id, name, mail, comment)
        if success:
            self.last_post_time = time.time()
            self.write_widget.comment_input.clear()  # 修正
            self.statusBar().showMessage("書き込みが完了しました。")
        else:
            if isinstance(response, str) and re.match(r"^\d{6}$", response):
                self.show_auth_dialog(response)
            else:
                self.handle_post_error(response, name, mail, comment)
    
    def start_thread_fetcher_initial(self):
        if self.thread_fetcher is not None:
            self.thread_fetcher.stop()
        
        sort_by = self.sort_combo.currentData()
        self.thread_fetcher = ThreadFetcher(sort_by=sort_by)
        self.thread_fetcher.threads_fetched.connect(self.update_thread_list)
        self.thread_fetcher.error_occurred.connect(self.show_error)
        self.thread_fetcher.start()
        logger.info("スレッド一覧の取得を開始しました")
    
    def refresh_thread_list(self):
        if self.thread_fetcher is not None:
            self.thread_fetcher.stop()
        
        sort_by = self.sort_combo.currentData()
        self.thread_fetcher = ThreadFetcher(sort_by=sort_by)
        self.thread_fetcher.threads_fetched.connect(self.update_thread_list)
        self.thread_fetcher.error_occurred.connect(self.show_error)
        self.thread_fetcher.start()
        logger.info("スレッド一覧を更新しました")
    
    def start_thread_fetcher(self, thread_id, thread_title, is_past_thread=False, start_number=None):
        if self.comment_fetcher and self.comment_fetcher.isRunning():
            self.comment_fetcher.stop()
        
        playback_speed = self.settings.get("playback_speed", 1.0)
        comment_delay = self.settings.get("comment_delay", 0) if not is_past_thread else 0
        self.comment_fetcher = CommentFetcher(
            thread_id=thread_id,
            thread_title=thread_title,
            update_interval=self.settings["update_interval"],
            is_past_thread=is_past_thread,
            playback_speed=playback_speed,
            comment_delay=comment_delay,
            start_number=start_number,
            parent=self
        )
        self.comment_fetcher.comments_fetched.connect(self.display_comments)
        self.comment_fetcher.all_comments_fetched.connect(self.display_all_comments)
        self.comment_fetcher.thread_filled.connect(self.handle_thread_filled)
        self.comment_fetcher.error_occurred.connect(self.show_error)
        self.comment_fetcher.thread_over_1000.connect(self.on_thread_over_1000)
        self.comment_fetcher.playback_finished.connect(self.on_playback_finished)  # 新しいシグナルを接続
        self.comment_fetcher.start()
        
        self.current_thread_id = thread_id
        self.current_thread_title = thread_title
        self.thread_title_label.setText(f"接続中のスレッド: {thread_title}")
        self.detail_table.setRowCount(0)  # 初期化
        logger.info(f"スレッド {thread_id} の監視を開始しました (タイトル: {thread_title}, 過去ログ: {is_past_thread})")

    def on_playback_finished(self):
        """再生終了時の処理"""
        self.statusBar().showMessage(f"スレッド {self.current_thread_id} の再生が終了しました")
        logger.info(f"スレッド {self.current_thread_id} の再生が終了しました")

    def display_all_comments(self, comments):
        """過去ログの全コメントをスレッド詳細画面に表示"""
        if not self.is_past_thread:
            return  # 過去ログ以外では何もしない
        
        self.detail_table.setRowCount(0)  # テーブルをクリア
        current_row_count = 0
        
        for comment in comments:
            name = comment["name"]
            if "</b>(" in name:
                base_name, wacchoi = name.split("</b>(")
                wacchoi = wacchoi.rstrip(")<b>")
                formatted_name = f"{base_name}({wacchoi})"
            else:
                formatted_name = name
            
            self.detail_table.insertRow(current_row_count)
            self.detail_table.setItem(current_row_count, 0, QTableWidgetItem(str(comment["number"])))
            self.detail_table.setItem(current_row_count, 1, QTableWidgetItem(comment["text"]))
            self.detail_table.setItem(current_row_count, 2, QTableWidgetItem(formatted_name))
            self.detail_table.setItem(current_row_count, 3, QTableWidgetItem(comment["id"]))
            self.detail_table.setItem(current_row_count, 4, QTableWidgetItem(comment.get("date", "不明")))
            current_row_count += 1
        
        logger.info(f"過去ログの全コメントを表示しました: {len(comments)}件")
        self.statusBar().showMessage(f"過去ログ {self.current_thread_id} の全コメント（{len(comments)}件）を表示しました")
    
    def change_sort_order(self):
        if self.thread_fetcher is not None:
            self.thread_fetcher.stop()
        
        sort_by = self.sort_combo.currentData()
        self.thread_fetcher = ThreadFetcher(sort_by=sort_by)
        self.thread_fetcher.threads_fetched.connect(self.update_thread_list)
        self.thread_fetcher.error_occurred.connect(self.show_error)
        self.thread_fetcher.start()
        logger.info(f"ソート順を {sort_by} に変更しました")
    
    def thread_selected(self):
        selected_row = self.thread_table.currentRow()
        if selected_row >= 0:
            thread_id = self.thread_table.item(selected_row, 0).data(Qt.UserRole)
            thread_title = self.thread_table.item(selected_row, 0).text()
            
            if self.next_thread_finder is not None and self.next_thread_finder.isRunning():
                self.next_thread_finder.stop()
                self.next_thread_finder.wait(3000)  # 最大3秒待機
                logger.info(f"次スレ検索を停止しました（スレッド一覧から選択: {thread_id}）")
                self.next_thread_finder = None
            
            self.connect_to_thread_by_id(thread_id, thread_title)
            self.tab_widget.setCurrentIndex(1)  # スレッド詳細タブに切り替え
            logger.info(f"スレッド {thread_id} を選択し、スレッド詳細タブに切り替えました")
    
    def connect_to_thread(self):
        """スレッドURL/IDの手動入力による接続処理"""
        input_text = self.thread_input.text().strip()
        
        # 入力が空の場合、ユーザーに通知して終了
        if not input_text:
            QMessageBox.warning(self, "エラー", "スレッドURLまたはIDを入力してください。")
            logger.info("スレッドURL/IDが入力されていません")
            return
        
        # URLまたはIDからスレッドIDを抽出
        thread_id_match = re.search(r'(\d{10,})', input_text)
        if not thread_id_match:
            QMessageBox.warning(self, "エラー", "有効なスレッドURLまたはIDを入力してください（例: https://bbs.eddibb.cc/test/read.cgi/liveedge/1742132339/ または 1742132339）。")
            logger.info(f"無効なスレッドURL/IDが入力されました: {input_text}")
            return
        
        thread_id = thread_id_match.group(1)
        
        # 既存の接続と同じ場合は何もしない
        if thread_id == self.current_thread_id:
            logger.info(f"既にスレッド {thread_id} に接続済みです")
            self.statusBar().showMessage(f"既にスレッド {thread_id} に接続済みです")
            return
        
        # 状態を更新
        self.current_thread_id = thread_id
        self.is_past_thread = False
        self.last_post_time = 0
        logger.info(f"スレッドに接続を開始しました: {thread_id}")
        
        # コメント番号をリセットし、自分のコメントを復元
        if self.overlay_window:
            self.overlay_window.reset_my_comments()
            for key, my_comment in self.my_comments.items():
                if my_comment["thread_id"] == self.current_thread_id and my_comment["number"] is not None:
                    self.overlay_window.add_my_comment(my_comment["number"], my_comment["text"])
                    logger.info(f"スレッド {thread_id} の自分のコメントを復元: 番号={my_comment['number']}, テキスト={my_comment['text']}")
        
        # スレッドに接続
        self.connect_to_thread_by_id(thread_id)
    
    def connect_to_thread_by_id(self, thread_id, thread_title=None):


        # 新しいスレッドに接続するため、完走フラグをリセット
        self.is_thread_finished = False
        
        # ### 機能追加: 既存のウォッチャーを停止させる処理を追加 ###
        if self.mainstream_watcher and self.mainstream_watcher.isRunning():
            self.mainstream_watcher.stop()
            self.mainstream_watcher.wait(3000)  # 最大3秒待機
            logger.info("本流スレ監視を停止しました（新しいスレッド接続）")
            self.mainstream_watcher = None
        
        if self.next_thread_finder is not None and self.next_thread_finder.isRunning():
            self.next_thread_finder.stop()
            self.next_thread_finder.wait(3000)  # 最大3秒待機
            logger.info(f"次スレ検索を停止しました（新しいスレッド接続: {thread_id}）")
            self.next_thread_finder = None
        
        if self.comment_fetcher is not None:
            self.comment_fetcher.stop()
            if not self.comment_fetcher.isFinished():
                logger.warning(f"既存の CommentFetcher {self.current_thread_id} が終了していない可能性があります")
        
        if self.overlay_window:
            self.overlay_window.comment_queue.clear()
            if self.overlay_window.flow_timer.isActive():
                self.overlay_window.flow_timer.stop()
        
        if not self.check_thread_exists(thread_id):
            self.show_error(f"スレッド {thread_id} は存在しません（.dat ファイルが見つかりません）。")
            self.statusBar().showMessage(f"スレッド {thread_id} は存在しません")
            return
        
        self.is_past_thread = False
        if not thread_title:
            thread_title = self.get_thread_title(thread_id)
            if not thread_title:
                thread_title = f"スレッド {thread_id} (過去ログ)"
                self.is_past_thread = True
                logger.info(f"スレッド {thread_id} は subject.txt にありません。過去ログとして接続します。")
        
        # スレッド切り替え時にmy_comment_numbersをリセット
        if self.overlay_window:
            self.overlay_window.reset_my_comments()
            for key, my_comment in self.my_comments.items():
                if my_comment["thread_id"] == thread_id and my_comment["number"] is not None:
                    self.overlay_window.add_my_comment(my_comment["number"], my_comment["text"])
                    logger.info(f"スレッド {thread_id} の自分のコメントを復元: 番号={my_comment['number']}, テキスト={my_comment['text']}")

        self.current_thread_id = thread_id
        self.current_thread_title = thread_title
        logger.info(f"スレッド接続 - ID: {thread_id}, タイトル: {thread_title}, 過去ログ: {self.is_past_thread}")
        
        if not self.overlay_window or not self.overlay_window.isVisible():
            self.overlay_window = CommentOverlayWindow(None)
            self.overlay_window.update_settings(self.settings)
            self.overlay_window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
            self.overlay_window.setAttribute(Qt.WA_TranslucentBackground, True)
            overlay_x = self.settings.get("overlay_x", 100)
            overlay_y = self.settings.get("overlay_y", 100)
            overlay_width = self.settings.get("overlay_width", 600)
            overlay_height = self.settings.get("overlay_height", 800)
            self.overlay_window.setGeometry(overlay_x, overlay_y, overlay_width, overlay_height)
            
            # 最大化状態を復元
            if self.settings.get("overlay_is_maximized", False):
                self.overlay_window.is_maximized = True
                # 通常時のジオメトリを復元
                from PyQt5.QtCore import QRect
                normal_x = self.settings.get("overlay_normal_x", 100)
                normal_y = self.settings.get("overlay_normal_y", 100)
                normal_width = self.settings.get("overlay_normal_width", 600)
                normal_height = self.settings.get("overlay_normal_height", 800)
                self.overlay_window._normal_geometry = QRect(normal_x, normal_y, normal_width, normal_height)
                logger.info(f"最大化状態を復元: normal_geometry={self.overlay_window._normal_geometry}")
            
            self.overlay_window.show()
            logger.info(f"コメントオーバーレイウィンドウを開きました: x={overlay_x}, y={overlay_y}, width={overlay_width}, height={overlay_height}, is_maximized={self.overlay_window.is_maximized}")
        else:
            self.overlay_window.comments.clear()
            self.overlay_window.row_usage.clear()
            logger.info("既存のコメントオーバーレイウィンドウを再利用します")
        
        self.start_thread_fetcher(thread_id, thread_title, is_past_thread=self.is_past_thread)
        self.statusBar().showMessage(f"スレッド {thread_id} - {thread_title} に接続しました")

        # スレッド詳細タブに切り替え
        self.tab_widget.setCurrentIndex(1)
        logger.info(f"スレッド {thread_id} に接続し、スレッド詳細タブに切り替えました")
    
    def check_thread_exists(self, thread_id):
        try:
            url = f"https://bbs.eddibb.cc/liveedge/dat/{thread_id}.dat"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_thread_title(self, thread_id):
        try:
            url = "https://bbs.eddibb.cc/liveedge/subject.txt"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            lines = response.text.splitlines()
            for line in lines:
                if not line:
                    continue
                thread_id_dat, title_res = line.split("<>", 1)
                if thread_id_dat == f"{thread_id}.dat":
                    title = title_res.split(" (")[0]
                    logger.info(f"スレッドタイトル取得成功: {title}")
                    return title
            logger.warning(f"スレッド {thread_id} のタイトルが見つかりませんでした")
            return None
        except Exception as e:
            logger.error(f"スレッドタイトル取得に失敗しました: {str(e)}")
            return None
    
    def handle_thread_filled(self, thread_id, thread_title):
        logger.info(f"スレッド {thread_id} が埋まりました。")
        
        # 1000レス到達を記録（再起動を防止）
        self.is_thread_finished = True
        
        if self.settings.get("auto_next_thread", True):
            logger.info("次スレを検索します")
            search_duration = self.settings.get("next_thread_search_duration", 180)
            
            if self.next_thread_finder is not None:
                self.next_thread_finder.stop()
                self.next_thread_finder.wait(3000)  # 最大3秒待機
            
            self.next_thread_finder = NextThreadFinder(thread_id, thread_title, search_duration)
            self.next_thread_finder.next_thread_found.connect(self.on_next_thread_found)
            self.next_thread_finder.search_finished.connect(self.on_search_finished)
            self.next_thread_finder.start()
            logger.info(f"次スレ検索を開始しました（検索時間: {search_duration}秒）")
            self.statusBar().showMessage(f"スレッド {thread_id} が埋まりました。次スレを検索中...")
        else:
            logger.info("次スレの自動検索が無効化されています")
            self.statusBar().showMessage(f"スレッド {thread_id} が埋まりました。次スレ検索は無効です")
            if self.overlay_window:
                self.overlay_window.add_system_message("次スレ検索は設定で無効化されています", message_type="auto_next_disabled")
    
    def on_next_thread_found(self, next_thread):
        next_thread_id = next_thread["id"]
        next_thread_title = next_thread["title"]
        logger.info(f"次スレが見つかりました: {next_thread_id} - {next_thread_title}")
        
        # ### 修正箇所: 監視用に「埋まったスレのID」も保存 ###
        original_thread_id_for_watcher = self.current_thread_id
        original_title_for_watcher = self.current_thread_title

        # まずは次スレに接続
        self.connect_to_thread_by_id(next_thread_id, next_thread_title)
        self.overlay_window.add_system_message(f"次スレ： {next_thread_title} に接続しました。", message_type="next_thread_connected")

        # ### 機能追加: 設定が有効なら本流スレッドの監視を開始 ###
        if self.settings.get("watch_mainstream_thread", True):
            # ### 修正箇所: 新しい設定値 `watch_delay` を読み込む ###
            watch_delay = self.settings.get("watch_delay", 15)
            watch_duration = self.settings.get("watch_duration", 60)
            momentum_ratio = self.settings.get("momentum_ratio", 1.5)
            
            if self.mainstream_watcher and self.mainstream_watcher.isRunning():
                self.mainstream_watcher.stop()
                self.mainstream_watcher.wait(3000)  # 最大3秒待機

            self.mainstream_watcher = MainstreamWatcher(
                original_title=original_title_for_watcher,
                original_thread_id=original_thread_id_for_watcher,
                current_thread_id=next_thread_id,
                watch_duration=watch_duration,
                momentum_ratio=momentum_ratio,
                grace_period=watch_delay, # ### `watch_delay` を `grace_period` として渡す ###
                parent=self
            )
            self.mainstream_watcher.mainstream_thread_found.connect(self.on_mainstream_thread_found)
            self.mainstream_watcher.search_finished.connect(self.on_mainstream_watch_finished)
            self.mainstream_watcher.start()
            # ### 修正箇所: ステータスバーのメッセージを分かりやすく ###
            self.statusBar().showMessage(f"次スレに接続。{watch_delay}秒後から{watch_duration}秒間、本流スレを監視します...")
        else:
            self.statusBar().showMessage(f"次スレ {next_thread_id} - {next_thread_title} に接続しました")
    
    def on_search_finished(self, success):
        if not success:
            logger.warning("次スレが見つかりませんでした")
            self.show_error("次スレが見つかりませんでした")
            self.statusBar().showMessage("次スレが見つかりませんでした")
        
        self.next_thread_finder = None
    
    # ### 機能追加: 本流スレッドが見つかった時と監視終了時の処理を追加 ###
    def on_mainstream_thread_found(self, thread_info):
        mainstream_id = thread_info["id"]
        mainstream_title = thread_info["title"]
        
        if self.current_thread_id == mainstream_id:
            logger.info("発見された本流スレッドは現在接続中のスレッドと同じため、切り替えません。")
            return

        logger.info(f"本流スレッドに切り替えます: {mainstream_title} (ID: {mainstream_id})")
        self.connect_to_thread_by_id(mainstream_id, mainstream_title)
        
        if self.overlay_window:
            self.overlay_window.add_system_message(f"勢いの高い本流スレッド『{mainstream_title}』に切り替えました。", message_type="mainstream_switched")
        self.statusBar().showMessage(f"本流スレッド『{mainstream_title}』に切り替えました。")

    def on_mainstream_watch_finished(self):
        # メインスレッドが見つからずに正常終了した場合
        if self.mainstream_watcher:
             self.statusBar().showMessage("本流スレッドの監視が終了しました。")
        self.mainstream_watcher = None

    def on_thread_over_1000(self, message):
        self.overlay_window.add_system_message(message, message_type="thread_over_1000")
    
    def get_next_part(self, thread_title):
        part_match = re.search(r'★(\d+)$', thread_title)
        return int(part_match.group(1)) + 1 if part_match else 2
    
    def show_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec_():
            self.settings = dialog.get_settings()
            
            if self.overlay_window is not None:
                self.overlay_window.update_settings(self.settings)
            
            if self.comment_fetcher is not None:
                self.comment_fetcher.update_interval = self.settings["update_interval"]
            
            # 分離状態の書き込みウィジェットに透明度を反映
            if self.write_widget is not None and not self.is_docked:
                opacity = self.settings.get("write_window_opacity", 1.0)
                self.write_widget.setWindowOpacity(opacity)
                logger.info(f"分離ウィンドウの透明度を更新: {opacity*100}%")
            
            logger.info("設定を更新しました")
            print("現在の self.settings:", self.settings)
    
    def load_settings(self):
        default_settings = {
            "font_size": 31, "font_weight": 75, "font_shadow": 2, "font_color": "#FFFFFF", "font_family": "MS PGothic",
            "font_shadow_directions": ["bottom-right"], "font_shadow_color": "#000000", "comment_speed": 6.0,
            "comment_delay": 0, "display_position": "top", "max_comments": 80, "window_opacity": 0.8, "update_interval": 5,
            "playback_speed": 1.0, "auto_next_thread": True, "next_thread_search_duration": 180, "first_launch": True,
            "overlay_x": 100, "overlay_y": 100, "overlay_width": 600, "overlay_height": 800,
            "hide_anchor_comments": False, "hide_url_comments": False, "spacing": 30, "ng_ids": [], "ng_names": [], "ng_texts": [],
            "auth_token": None, "tinker_token": None, "hide_name_mail_on_detach": False, "display_images": True, "hide_image_urls": True,
            # ### 機能追加: 本流スレ監視設定のデフォルト値を追加 ###
            "watch_mainstream_thread": True,
            "watch_duration": 60,
            "watch_delay": 15,
            "momentum_ratio": 1.5,
        }
        
        try:
            settings_file = os.path.expanduser("~/.edge_live_viewer/settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                for key, value in loaded_settings.items():
                    if key in default_settings:
                        default_settings[key] = value
        except Exception as e:
            logger.error(f"設定の読み込みに失敗しました: {str(e)}")
        return default_settings
    
    def save_window_position(self, x, y, width, height, is_maximized=None, normal_geometry=None):
        self.settings["overlay_x"] = x
        self.settings["overlay_y"] = y
        self.settings["overlay_width"] = width
        self.settings["overlay_height"] = height
        
        # 最大化状態を保存
        if is_maximized is not None:
            self.settings["overlay_is_maximized"] = is_maximized
        
        # 通常時のジオメトリを保存（最大化状態から元に戻すために必要）
        if normal_geometry is not None:
            self.settings["overlay_normal_x"] = normal_geometry.x()
            self.settings["overlay_normal_y"] = normal_geometry.y()
            self.settings["overlay_normal_width"] = normal_geometry.width()
            self.settings["overlay_normal_height"] = normal_geometry.height()
        
        try:
            settings_dir = os.path.expanduser("~/.edge_live_viewer")
            os.makedirs(settings_dir, exist_ok=True)
            settings_file = os.path.join(settings_dir, "settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            logger.info(f"ウィンドウ位置とサイズを保存しました: x={x}, y={y}, width={width}, height={height}, is_maximized={is_maximized}")
        except Exception as e:
            logger.error(f"ウィンドウ位置とサイズの保存に失敗しました: {str(e)}")
    
    def show_tutorial_if_first_launch(self):
        if self.settings.get("first_launch", True):
            QMessageBox.information(self, "エッヂ実況ビュアーへようこそ",
                                  "エッヂ実況ビュアーへようこそ！\n\n"
                                  "このアプリケーションは、エッヂ掲示板のコメントをニコニコ動画風に表示します。\n\n"
                                  "使い方：\n"
                                  "1. スレッド一覧からスレッドを選択するか、スレッドURLまたはIDを入力して接続します。\n"
                                  "2. 透過ウィンドウが表示され、コメントが流れ始めます。\n"
                                  "3. 設定ボタンから、フォントサイズや色などをカスタマイズできます。\n"
                                  "4. スレッド詳細タブからコメントを書き込めます（初回は認証が必要）。\n\n"
                                  "それでは、お楽しみください！")
            
            self.settings["first_launch"] = False
            self.save_settings()
    
    def show_error(self, message):
        logger.error(message)
        self.statusBar().showMessage(f"エラー: {message[:50]}...")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setProperty("comment_time", time.time())
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())