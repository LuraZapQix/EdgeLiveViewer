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
from PyQt5.QtCore import Qt, QTimer, QUrl, QPoint
from PyQt5.QtGui import QFont, QColor, QDesktopServices

from thread_fetcher_improved import ThreadFetcher, CommentFetcher, NextThreadFinder
from comment_animation_improved import CommentOverlayWindow
from settings_dialog import SettingsDialog

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('EdgeLiveViewer')

class WriteWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("書き込み")
        self.setMinimumWidth(400)
        self._dragging = False
        self._offset = QPoint()
        self._force_close = False
        self.setup_ui()
        
        main_window = parent if isinstance(parent, MainWindow) else None
        self.hide_on_detach = main_window.settings.get("hide_name_mail_on_detach", False) if main_window else False
        self.hide_checkbox.setChecked(self.hide_on_detach)
    
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
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._offset = event.pos()
            event.accept()
    
    def mouseMoveEvent(self, event):
        if self._dragging:
            self.move(self.mapToGlobal(event.pos() - self._offset))
            event.accept()
    
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

    def force_close(self):
        self._force_close = True
        self.close()

    def closeEvent(self, event):
        if not self.parent() and not self.isHidden() and not self._force_close:
            event.ignore()
            logger.info("書き込みウィンドウの閉じる操作を無効化しました。ドッキングで戻してください。")
        else:
            event.accept()
            logger.info("書き込みウィンドウを閉じました")

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
        
        self.settings = self.load_settings()
        self.overlay_window = None
        self.thread_fetcher = None
        self.comment_fetcher = None
        self.next_thread_finder = None
        self.current_thread_id = None
        self.current_thread_title = None
        self.is_past_thread = False
        self.auth_token = None
        self.load_auth_token()
        self.write_widget = None
        self.is_docked = True
        
        self.init_ui()
        
        app = QApplication.instance()
        app.setProperty("main_window", self)
        
        self.start_thread_fetcher_initial()
        self.show_tutorial_if_first_launch()
        
        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self.check_fetcher_health)
        self.health_timer.start(30000)
        self.last_post_time = 0

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        input_layout = QHBoxLayout()
        self.thread_input = QLineEdit()
        self.thread_input.setPlaceholderText("スレッドURLまたはID（例: https://bbs.eddibb.cc/test/read.cgi/liveedge/1742132339/ または 1742132339）")
        connect_button = QPushButton("接続")
        connect_button.clicked.connect(self.connect_to_thread)
        input_layout.addWidget(QLabel("スレッドURL/ID:"))
        input_layout.addWidget(self.thread_input)
        input_layout.addWidget(connect_button)
        main_layout.addLayout(input_layout)
        
        self.tab_widget = QTabWidget()
        
        # スレッド一覧タブ（変更なし）
        thread_tab = QWidget()
        thread_layout = QVBoxLayout(thread_tab)
        sort_layout = QHBoxLayout()
        sort_layout.addWidget(QLabel("並び替え:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("勢い順", "momentum")
        self.sort_combo.addItem("新着順", "date")
        self.sort_combo.currentIndexChanged.connect(self.change_sort_order)
        sort_layout.addWidget(self.sort_combo)
        refresh_button = QPushButton("更新")
        refresh_button.clicked.connect(self.refresh_thread_list)
        sort_layout.addStretch()
        sort_layout.addWidget(refresh_button)
        thread_layout.addLayout(sort_layout)
        self.thread_table = QTableWidget(0, 4)
        self.thread_table.setHorizontalHeaderLabels(["スレッドタイトル", "レス数", "勢い", "作成日時"])
        self.thread_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.thread_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.thread_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.thread_table.doubleClicked.connect(self.thread_selected)
        thread_layout.addWidget(self.thread_table)
        self.tab_widget.addTab(thread_tab, "スレッド一覧")
        
        # スレッド詳細タブ
        self.detail_tab = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_tab)
        
        self.thread_title_label = QLabel("接続中のスレッド: 未接続")
        self.thread_title_label.setAlignment(Qt.AlignCenter)
        self.detail_layout.addWidget(self.thread_title_label)
        
        self.detail_table = QTableWidget(0, 4)
        self.detail_table.setHorizontalHeaderLabels(["番号", "本文", "名前", "ID"])
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.verticalHeader().setVisible(False)
        self.detail_table.setColumnWidth(0, 40)
        self.detail_table.setColumnWidth(2, 120)
        self.detail_table.setColumnWidth(3, 100)
        self.detail_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.detail_table.customContextMenuRequested.connect(self.show_context_menu)
        self.detail_layout.addWidget(self.detail_table)
        
        # 書き込みウィジェット
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

    def toggle_write_widget(self):
        if self.write_widget is None:
            logger.error("書き込みウィジェットが初期化されていません")
            return
        
        if self.is_docked:
            # 分離
            self.write_widget.setParent(None)
            self.write_widget.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
            self.write_widget.hide()
            if self.write_widget.hide_on_detach:
                self.write_widget.set_name_mail_visible(False)
            else:
                self.write_widget.set_name_mail_visible(True)
            self.write_widget.adjust_height()  # 高さを調整
            self.write_widget.show()
            self.write_widget.move(self.pos().x() + 50, self.pos().y() + 50)
            self.write_widget.toggle_button.setText("ドッキング")
            self.is_docked = False
            logger.info("書き込み欄を分離しました（フレームレス＋最前面）")
        else:
            # ドッキング
            self.detail_layout.addWidget(self.write_widget)
            self.write_widget.setWindowFlags(Qt.Widget)
            self.write_widget.set_name_mail_visible(True)
            self.write_widget.adjust_height()  # ドッキング時も高さを調整
            self.write_widget.show()
            self.write_widget.toggle_button.setText("分離")
            self.is_docked = True
            logger.info("書き込み欄をドッキングしました")
    
    def check_fetcher_health(self):
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
        # 汎用的なUser-Agent（必要最低限）
        headers = {
            "User-Agent": "EdgeLiveViewer/1.0",  # カスタムアプリ名に変更
            "Referer": f"https://bbs.eddibb.cc/liveedge/{thread_id}",
            "Accept": "*/*",
            "Accept-Encoding": "identity",  # zstd回避
            "Content-Type": "application/x-www-form-urlencoded; charset=Shift_JIS",
            "Origin": "https://bbs.eddibb.cc",
        }
        data = {
            "bbs": "liveedge",
            "key": thread_id,
            "FROM": name.encode("shift_jis"),
            "mail": mail.encode("shift_jis") if mail else b"",
            "MESSAGE": comment.encode("shift_jis"),
            "submit": "書き込む".encode("shift_jis"),
        }
        if self.auth_token:
            data["mail"] = f"#{self.auth_token}".encode("shift_jis")
        
        session = requests.Session()
        try:
            if self.auth_token:
                session.cookies.set("edge-token", self.auth_token, domain="bbs.eddibb.cc")
            tinker_token = self.settings.get("tinker_token", "")
            if tinker_token:
                session.cookies.set("tinker-token", tinker_token, domain="bbs.eddibb.cc")
            
            session.get(f"https://bbs.eddibb.cc/liveedge/{thread_id}", headers=headers, timeout=5)
            
            logger.info(f"送信データ: {data}")
            logger.info(f"送信クッキー: {session.cookies.get_dict()}")
            response = session.post(url, headers=headers, data=data, timeout=10)
            
            logger.info(f"レスポンスステータス: {response.status_code}")
            logger.info(f"レスポンスヘッダー: {dict(response.headers)}")
            
            response_text = response.content.decode("shift_jis", errors="replace")
            logger.info(f"レスポンス本文: {response_text[:500]}")
            
            if response.status_code == 200 and "<title>書きこみました</title>" in response_text:
                new_tinker = session.cookies.get("tinker-token")
                if new_tinker:
                    self.settings["tinker_token"] = new_tinker
                    self.save_settings()
                    logger.info(f"tinker-tokenを更新: {new_tinker}")
                new_edge = session.cookies.get("edge-token")
                if new_edge and new_edge != self.auth_token:
                    self.auth_token = new_edge
                    self.save_auth_token(new_edge)
                    logger.info(f"edge-tokenを更新: {new_edge}")
                return True, response_text
            
            auth_code_match = re.search(r'<input[^>]*name="auth-code"[^>]*value="([^"]+)"[^>]*>|認証コード[\'"](\d{6})[\'"]', response_text)
            if auth_code_match:
                auth_code = auth_code_match.group(1) or auth_code_match.group(2)
                new_edge = session.cookies.get("edge-token")
                if new_edge and new_edge != self.auth_token:
                    logger.info(f"認証コードレスポンスにedge-tokenが含まれていますが無視: {new_edge}")
                return False, auth_code
            return False, response_text
        except requests.RequestException as e:
            logger.error(f"書き込みリクエストに失敗: {str(e)}")
            return False, str(e)

    def post_comment(self):
        """コメントをエッヂに投稿する"""
        if not self.current_thread_id:
            QMessageBox.warning(self, "エラー", "スレッドに接続してください。")
            return
        
        if self.is_past_thread:
            QMessageBox.critical(self, "書き込みエラー", "過去ログには書き込みできません。")
            return
        
        name = self.write_widget.name_input.text().strip() or "エッヂの名無し"  # 修正
        mail = self.write_widget.mail_input.text().strip()  # 修正
        comment = self.write_widget.comment_input.text().strip()  # 修正
        
        if not comment:
            QMessageBox.warning(self, "エラー", "コメントを入力してください。")
            return
        
        # 5秒以内の投稿チェック
        current_time = time.time()
        if current_time - self.last_post_time < 5:
            remaining = 5 - (current_time - self.last_post_time)
            QMessageBox.warning(self, "投稿制限", f"5秒以内の連続投稿はできません。あと {remaining:.1f}秒 お待ちください。")
            return
        
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
    
    def show_auth_dialog(self, auth_code):
        """カスタム認証ダイアログを表示"""
        dialog = AuthDialog(auth_code, self)
        dialog.exec_()
        
        token, ok = QInputDialog.getText(
            self, "トークン入力", "認証後に表示されたトークン（#を含む）を入力:",
            QLineEdit.Normal, "#"
        )
        if ok and token and re.match(r"#[a-f0-9]{32}", token):
            self.auth_token = token[1:]  # #を除去
            self.save_auth_token(self.auth_token)
            QMessageBox.information(self, "認証成功", "トークンを保存しました。再度書き込みを試してください。")
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
    
    def start_thread_fetcher(self, thread_id, thread_title, is_past_thread=False):
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
        self.detail_table.setRowCount(0)
        logger.info(f"スレッド {thread_id} の監視を開始しました (タイトル: {thread_title}, 過去ログ: {is_past_thread}, 再生速度: {playback_speed}x, 遅延: {comment_delay}秒)")
    
    def update_thread_list(self, threads):
        self.thread_table.setRowCount(0)
        
        for thread in threads:
            row = self.thread_table.rowCount()
            self.thread_table.insertRow(row)
            
            self.thread_table.setItem(row, 0, QTableWidgetItem(thread["title"]))
            self.thread_table.setItem(row, 1, QTableWidgetItem(thread["res_count"]))
            self.thread_table.setItem(row, 2, QTableWidgetItem(thread["momentum"]))
            self.thread_table.setItem(row, 3, QTableWidgetItem(thread["date"]))
            
            self.thread_table.item(row, 0).setData(Qt.UserRole, thread["id"])
        
        self.statusBar().showMessage(f"スレッド一覧を更新しました（{len(threads)}件）")
    
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
                logger.info(f"次スレ検索を停止しました（スレッド一覧から選択: {thread_id}）")
                self.next_thread_finder = None
            
            self.connect_to_thread_by_id(thread_id, thread_title)
            self.tab_widget.setCurrentIndex(1)  # スレッド詳細タブに切り替え
            logger.info(f"スレッド {thread_id} を選択し、スレッド詳細タブに切り替えました")
    
    def connect_to_thread(self):
        input_text = self.thread_input.text().strip()
        if not input_text:
            QMessageBox.warning(self, "エラー", "スレッドURLまたはIDを入力してください。")
            return
        
        thread_id = input_text
        url_match = re.search(r'/liveedge/(\d+)', input_text)
        if url_match:
            thread_id = url_match.group(1)
        
        if not thread_id.isdigit():
            QMessageBox.warning(self, "エラー", "無効なスレッドURLまたはIDです。")
            return
        
        self.connect_to_thread_by_id(thread_id)
    
    def connect_to_thread_by_id(self, thread_id, thread_title=None):
        if self.next_thread_finder is not None and self.next_thread_finder.isRunning():
            self.next_thread_finder.stop()
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
            self.overlay_window.show()
            logger.info(f"コメントオーバーレイウィンドウを開きました: x={overlay_x}, y={overlay_y}, width={overlay_width}, height={overlay_height}")  # height を overlay_height に修正
        else:
            self.overlay_window.comments.clear()
            self.overlay_window.row_usage.clear()
            logger.info("既存のコメントオーバーレイウィンドウを再利用します")
        
        self.start_thread_fetcher(thread_id, thread_title, is_past_thread=self.is_past_thread)
        self.statusBar().showMessage(f"スレッド {thread_id} - {thread_title} に接続しました")
    
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
    
    def display_comments(self, comments):
        if self.overlay_window is None:
            return
        
        QApplication.instance().setProperty("comment_time", time.time())
        logger.info(f"表示対象のコメント数: {len(comments)}")
        
        self.overlay_window.add_comment_batch(comments)
        
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
            current_row_count += 1
        
        self.detail_table.scrollToBottom()
    
    def handle_thread_filled(self, thread_id, thread_title):
        logger.info(f"スレッド {thread_id} が埋まりました。")
        
        if self.settings.get("auto_next_thread", True):
            logger.info("次スレを検索します")
            search_duration = self.settings.get("next_thread_search_duration", 180)
            
            if self.next_thread_finder is not None:
                self.next_thread_finder.stop()
            
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
        
        self.connect_to_thread_by_id(next_thread_id, next_thread_title)
        self.overlay_window.add_system_message(f"次スレ： {next_thread_title} に接続しました。", message_type="next_thread_connected")
        self.statusBar().showMessage(f"次スレ {next_thread_id} - {next_thread_title} に接続しました")
    
    def on_search_finished(self, success):
        if not success:
            logger.warning("次スレが見つかりませんでした")
            self.show_error("次スレが見つかりませんでした")
            self.statusBar().showMessage("次スレが見つかりませんでした")
        
        self.next_thread_finder = None
    
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
            logger.info("設定を更新しました")
            print("現在の self.settings:", self.settings)
    
    def load_settings(self):
        default_settings = {
            "font_size": 24,
            "font_weight": 75,
            "font_shadow": 2,
            "font_color": "#FFFFFF",
            "font_family": "MSP Gothic",
            "font_shadow_directions": ["bottom-right"],
            "font_shadow_color": "#000000",
            "comment_speed": 6.0,
            "comment_delay": 0,
            "display_position": "top",
            "max_comments": 40,
            "window_opacity": 0.8,
            "update_interval": 5,
            "playback_speed": 1.0,
            "auto_next_thread": True,
            "next_thread_search_duration": 180,
            "first_launch": True,
            "overlay_x": 100,
            "overlay_y": 100,
            "overlay_width": 600,
            "overlay_height": 800,
            "hide_anchor_comments": False,
            "hide_url_comments": False,
            "spacing": 10,
            "ng_ids": [],
            "ng_names": [],
            "ng_texts": [],
            "auth_token": None,
            "tinker_token": None,
            "hide_name_mail_on_detach": False  # 新しい設定項目
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
    
    def save_window_position(self, x, y, width, height):
        self.settings["overlay_x"] = x
        self.settings["overlay_y"] = y
        self.settings["overlay_width"] = width
        self.settings["overlay_height"] = height
        try:
            settings_dir = os.path.expanduser("~/.edge_live_viewer")
            os.makedirs(settings_dir, exist_ok=True)
            settings_file = os.path.join(settings_dir, "settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            logger.info(f"ウィンドウ位置とサイズを保存しました: x={x}, y={y}, width={width}, height={height}")
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
    
    def closeEvent(self, event):
        if self.thread_fetcher is not None:
            self.thread_fetcher.stop()
        
        if self.comment_fetcher is not None:
            self.comment_fetcher.stop()
        
        if self.next_thread_finder is not None:
            self.next_thread_finder.stop()
        
        if self.overlay_window is not None and self.overlay_window.isVisible():
            self.overlay_window.close()
        
        # 分離状態の書き込みウィンドウを閉じる
        if self.write_widget is not None:
            if not self.is_docked:  # 分離状態の場合
                self.write_widget.force_close()  # 強制終了メソッドを呼び出し
                logger.info("分離状態の書き込みウィンドウを閉じました")
            # ドッキング状態の場合は親（MainWindow）の終了で自動的に閉じる
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setProperty("comment_time", time.time())
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())