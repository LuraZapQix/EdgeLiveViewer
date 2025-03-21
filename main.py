#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
エッジ実況ビュアー
エッヂ掲示板のコメントをニコニコ動画風に表示するアプリケーション
"""

import os
import sys
import time
import json
import re
import requests
import logging
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QPushButton, QLineEdit, 
                           QTabWidget, QTableWidget, QTableWidgetItem, 
                           QHeaderView, QComboBox, QMessageBox, QInputDialog)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from thread_fetcher_improved import ThreadFetcher, CommentFetcher, NextThreadFinder
from comment_animation_improved import CommentOverlayWindow
from settings_dialog import SettingsDialog

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('EdgeLiveViewer')

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("エッジ実況ビュアー")
        self.setMinimumSize(800, 600)
        
        # 設定の読み込み
        self.settings = self.load_settings()
        print("main.py の self.settings:", self.settings)  # デバッグ追加
        
        # overlay_window は初期化しない（接続時に作成）
        self.overlay_window = None  # 初期値として None を設定
        
        self.thread_fetcher = None
        self.comment_fetcher = None
        self.next_thread_finder = None
        
        self.current_thread_id = None
        self.current_thread_title = None
        
        # UIの初期化
        self.init_ui()
        
        # アプリケーション全体のプロパティ設定
        app = QApplication.instance()
        app.setProperty("main_window", self)
        
        # 初期スレッド一覧の取得開始
        self.start_thread_fetcher_initial()
        self.show_tutorial_if_first_launch()
    
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
        
        playback_tab = QWidget()
        playback_layout = QVBoxLayout(playback_tab)
        
        playback_controls = QHBoxLayout()
        self.playback_speed_combo = QComboBox()
        self.playback_speed_combo.addItem("0.5倍速", 0.5)
        self.playback_speed_combo.addItem("1.0倍速", 1.0)
        self.playback_speed_combo.addItem("1.5倍速", 1.5)
        self.playback_speed_combo.addItem("2.0倍速", 2.0)
        self.playback_speed_combo.setCurrentIndex(1)
        
        self.play_button = QPushButton("再生")
        self.play_button.clicked.connect(self.toggle_playback)
        self.play_button.setEnabled(False)
        
        playback_controls.addWidget(QLabel("再生速度:"))
        playback_controls.addWidget(self.playback_speed_combo)
        playback_controls.addWidget(self.play_button)
        playback_controls.addStretch()
        
        playback_layout.addLayout(playback_controls)
        playback_layout.addStretch()
        
        self.tab_widget.addTab(playback_tab, "過去ログ再生")
        
        main_layout.addWidget(self.tab_widget)
        
        button_layout = QHBoxLayout()
        settings_button = QPushButton("設定")
        settings_button.clicked.connect(self.show_settings)
        button_layout.addStretch()
        button_layout.addWidget(settings_button)
        
        main_layout.addLayout(button_layout)
        
        self.statusBar().showMessage("準備完了")
    
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
    
    def start_thread_fetcher(self, thread_id, thread_title):
        if self.comment_fetcher and self.comment_fetcher.isRunning():
            self.comment_fetcher.stop()
        
        self.comment_fetcher = CommentFetcher(thread_id, thread_title, self.settings["update_interval"])
        self.comment_fetcher.comments_fetched.connect(self.display_comments)
        self.comment_fetcher.thread_filled.connect(self.handle_thread_filled)
        self.comment_fetcher.error_occurred.connect(self.show_error)
        self.comment_fetcher.thread_over_1000.connect(self.on_thread_over_1000)  # 1000超えのシグナル接続
        self.comment_fetcher.start()
        logger.info(f"スレッド {thread_id} の監視を開始しました (タイトル: {thread_title})")
    
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
            
            self.connect_to_thread_by_id(thread_id, thread_title)
    
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
        if self.comment_fetcher is not None:
            self.comment_fetcher.stop()
        
        self.current_thread_id = thread_id
        
        if not thread_title:
            thread_title = self.get_thread_title(thread_id)
            if not thread_title:
                thread_title, ok = QInputDialog.getText(self, "スレッドタイトル入力", 
                                                    f"スレッド {thread_id} のタイトルが見つかりませんでした。\nタイトルを入力してください（例: 【何か】スレタイ★1）:")
                if not ok or not thread_title:
                    thread_title = f"スレッド {thread_id}"
        
        self.current_thread_title = thread_title
        logger.info(f"スレッド接続 - ID: {thread_id}, タイトル: {thread_title}")
        
        # overlay_window が存在しないか閉じている場合に作成して表示
        if not self.overlay_window or not self.overlay_window.isVisible():
            self.overlay_window = CommentOverlayWindow(None)  # 親なしで作成
            self.overlay_window.update_settings(self.settings)
            self.overlay_window.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
            self.overlay_window.setAttribute(Qt.WA_TranslucentBackground, True)
            overlay_x = self.settings.get("overlay_x", 100)
            overlay_y = self.settings.get("overlay_y", 100)
            overlay_width = self.settings.get("overlay_width", 600)
            overlay_height = self.settings.get("overlay_height", 800)
            self.overlay_window.setGeometry(overlay_x, overlay_y, overlay_width, overlay_height)
            self.overlay_window.show()
            logger.info(f"コメントオーバーレイウィンドウを開きました: x={overlay_x}, y={overlay_y}, width={overlay_width}, height={overlay_height}")
        else:
            logger.info("既存のコメントオーバーレイウィンドウを再利用します")
        
        self.start_thread_fetcher(thread_id, thread_title)
        
        self.play_button.setEnabled(True)
        self.statusBar().showMessage(f"スレッド {thread_id} - {thread_title} に接続しました")
    
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
        
        for comment in comments:
            self.overlay_window.add_comment(comment)
    
    def handle_thread_filled(self, thread_id, thread_title):
        logger.info(f"スレッド {thread_id} が埋まりました。次スレを検索します")
        
        search_duration = self.settings.get("next_thread_search_duration", 180)
        
        if self.next_thread_finder is not None:
            self.next_thread_finder.stop()
        
        self.next_thread_finder = NextThreadFinder(thread_id, thread_title, search_duration)
        self.next_thread_finder.next_thread_found.connect(self.on_next_thread_found)
        self.next_thread_finder.search_finished.connect(self.on_search_finished)
        self.next_thread_finder.start()
        logger.info(f"次スレ検索を開始しました（検索時間: {search_duration}秒）")
        self.statusBar().showMessage(f"スレッド {thread_id} が埋まりました。次スレを検索中...")
    
    def on_next_thread_found(self, next_thread):
        next_thread_id = next_thread["id"]
        next_thread_title = next_thread["title"]
        logger.info(f"次スレが見つかりました: {next_thread_id} - {next_thread_title}")
        
        self.connect_to_thread_by_id(next_thread_id, next_thread_title)
        self.overlay_window.add_system_message(f"[{next_thread_title}] に接続しました", message_type="next_thread_connected")
        self.statusBar().showMessage(f"次スレ {next_thread_id} - {next_thread_title} に接続しました")
    
    def on_search_finished(self, success):
        if not success:
            logger.warning("次スレが見つかりませんでした")
            self.show_error("次スレが見つかりませんでした")
            self.statusBar().showMessage("次スレが見つかりませんでした")
        
        self.next_thread_finder = None
    
    def on_thread_over_1000(self, message):
        """スレッドが1000を超えたときにメッセージを表示"""
        self.overlay_window.add_system_message(message, message_type="thread_over_1000")
    
    def get_next_part(self, thread_title):
        part_match = re.search(r'★(\d+)$', thread_title)
        return int(part_match.group(1)) + 1 if part_match else 2
    
    def toggle_playback(self):
        logger.info("過去ログ再生機能は未実装です")
    
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
            "font_shadow_direction": "bottom-right",
            "font_shadow_color": "#000000",
            "comment_speed": 6.0,
            "display_position": "center",
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
            "hide_url_comments": False
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
            QMessageBox.information(self, "エッジ実況ビュアーへようこそ",
                                  "エッジ実況ビュアーへようこそ！\n\n"
                                  "このアプリケーションは、エッヂ掲示板のコメントをニコニコ動画風に表示します。\n\n"
                                  "使い方：\n"
                                  "1. スレッド一覧からスレッドを選択するか、スレッドURLまたはIDを入力して接続します。\n"
                                  "2. 透過ウィンドウが表示され、コメントが流れ始めます。\n"
                                  "3. 設定ボタンから、フォントサイズや色などをカスタマイズできます。\n\n"
                                  "それでは、お楽しみください！")
            
            self.settings["first_launch"] = False
            
            try:
                settings_dir = os.path.expanduser("~/.edge_live_viewer")
                os.makedirs(settings_dir, exist_ok=True)
                
                settings_file = os.path.join(settings_dir, "settings.json")
                with open(settings_file, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=4)
            except Exception as e:
                logger.error(f"設定の保存に失敗しました: {str(e)}")
    
    def show_error(self, message):
        logger.error(message)
        QMessageBox.critical(self, "エラー", message)
    
    def closeEvent(self, event):
        if self.thread_fetcher is not None:
            self.thread_fetcher.stop()
        
        if self.comment_fetcher is not None:
            self.comment_fetcher.stop()
        
        if self.next_thread_finder is not None:
            self.next_thread_finder.stop()
        
        if self.overlay_window is not None and self.overlay_window.isVisible():
            self.overlay_window.close()
        
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setProperty("comment_time", time.time())
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())