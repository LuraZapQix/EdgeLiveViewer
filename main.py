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
                           QHeaderView, QComboBox, QMessageBox, QInputDialog, 
                           QMenu, QDialog, QTextEdit)  # QTextEdit を追加
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from thread_fetcher_improved import ThreadFetcher, CommentFetcher, NextThreadFinder
from comment_animation_improved import CommentOverlayWindow
from settings_dialog import SettingsDialog

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('EdgeLiveViewer')

class NGTextDialog(QDialog):
    """NGコメント/名前用のカスタムダイアログ"""
    def __init__(self, initial_text, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)  # 横幅
        
        layout = QVBoxLayout()
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(initial_text)
        self.text_edit.setMinimumHeight(150)  #縦
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
        self.setWindowTitle("エッジ実況ビュアー")
        self.setMinimumSize(800, 600)
        
        # 設定の読み込み
        self.settings = self.load_settings()
        print("main.py の self.settings:", self.settings)
        
        self.overlay_window = None
        self.thread_fetcher = None
        self.comment_fetcher = None
        self.next_thread_finder = None
        
        self.current_thread_id = None
        self.current_thread_title = None
        
        self.init_ui()
        
        app = QApplication.instance()
        app.setProperty("main_window", self)
        
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
        detail_layout = QVBoxLayout(self.detail_tab)
        
        self.thread_title_label = QLabel("接続中のスレッド: 未接続")
        self.thread_title_label.setAlignment(Qt.AlignCenter)
        detail_layout.addWidget(self.thread_title_label)
        
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
        detail_layout.addWidget(self.detail_table)
        
        self.tab_widget.addTab(self.detail_tab, "スレッド詳細")
        
        main_layout.addWidget(self.tab_widget)
        
        button_layout = QHBoxLayout()
        settings_button = QPushButton("設定")
        settings_button.clicked.connect(self.show_settings)
        button_layout.addStretch()
        button_layout.addWidget(settings_button)
        
        main_layout.addLayout(button_layout)
        
        self.statusBar().showMessage("準備完了")

    def show_context_menu(self, pos):
        row = self.detail_table.currentRow()
        if row < 0:
            return
        
        menu = QMenu(self)
        
        ng_id = self.detail_table.item(row, 3).text()  # ID列
        ng_text = self.detail_table.item(row, 1).text().strip()  # 本文列
        ng_name = self.detail_table.item(row, 2).text()  # 名前列
        
        add_id_action = menu.addAction("NG IDに追加する")
        add_comment_action = menu.addAction("NG 本文に追加する")
        add_name_action = menu.addAction("NG 名前を追加する")  # 新規追加
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
        self.comment_fetcher = CommentFetcher(thread_id, thread_title, self.settings["update_interval"], is_past_thread, playback_speed)
        self.comment_fetcher.comments_fetched.connect(self.display_comments)
        self.comment_fetcher.thread_filled.connect(self.handle_thread_filled)
        self.comment_fetcher.error_occurred.connect(self.show_error)
        self.comment_fetcher.thread_over_1000.connect(self.on_thread_over_1000)
        self.comment_fetcher.start()
        
        # スレッド詳細タブを更新
        self.current_thread_id = thread_id
        self.current_thread_title = thread_title
        self.thread_title_label.setText(f"接続中のスレッド: {thread_title}")
        self.detail_table.setRowCount(0)  # 接続時にテーブルをクリア
        logger.info(f"スレッド {thread_id} の監視を開始しました (タイトル: {thread_title}, 過去ログ: {is_past_thread}, 再生速度: {playback_speed}x)")
    
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
        
        if not self.check_thread_exists(thread_id):
            self.show_error(f"スレッド {thread_id} は存在しません（.dat ファイルが見つかりません）。")
            logger.warning(f"スレッド {thread_id} の .dat ファイルが存在しないため、接続を中止します。")
            self.statusBar().showMessage(f"スレッド {thread_id} は存在しません")
            return
        
        is_past_thread = False
        if not thread_title:
            thread_title = self.get_thread_title(thread_id)
            if not thread_title:
                thread_title = f"スレッド {thread_id} (過去ログ)"
                is_past_thread = True
                logger.info(f"スレッド {thread_id} は subject.txt にありません。過去ログとして接続します。")
        
        self.current_thread_id = thread_id
        self.current_thread_title = thread_title
        logger.info(f"スレッド接続 - ID: {thread_id}, タイトル: {thread_title}")
        
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
            logger.info(f"コメントオーバーレイウィンドウを開きました: x={overlay_x}, y={overlay_y}, width={overlay_width}, height={overlay_height}")
        else:
            logger.info("既存のコメントオーバーレイウィンドウを再利用します")
        
        self.start_thread_fetcher(thread_id, thread_title, is_past_thread=is_past_thread)
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
        
        # オーバーレイにコメントを追加
        for comment in comments:
            self.overlay_window.add_comment(comment)
        
        # スレッド詳細タブを更新
        current_row_count = self.detail_table.rowCount()
        for comment in comments:
            name = comment["name"]
            if "</b>(" in name:  # ワッチョイ付き
                base_name, wacchoi = name.split("</b>(")
                wacchoi = wacchoi.rstrip(")<b>")
                formatted_name = f"{base_name}({wacchoi})"
            else:  # ワッチョイなし
                formatted_name = name
            
            self.detail_table.insertRow(current_row_count)
            self.detail_table.setItem(current_row_count, 0, QTableWidgetItem(str(comment["number"])))
            self.detail_table.setItem(current_row_count, 1, QTableWidgetItem(comment["text"]))
            self.detail_table.setItem(current_row_count, 2, QTableWidgetItem(formatted_name))
            self.detail_table.setItem(current_row_count, 3, QTableWidgetItem(comment["id"]))
            current_row_count += 1
        
        # 列幅調整を削除し、スクロールのみ実行
        self.detail_table.scrollToBottom()  # 最新レスに自動スクロール
    
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
            "hide_url_comments": False,
            "spacing": 10,
            "ng_ids": [],  # NGリスト追加
            "ng_names": [],
            "ng_texts": []
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