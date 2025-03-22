#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                           QSlider, QComboBox, QPushButton, QColorDialog,
                           QGroupBox, QFormLayout, QSpinBox, QCheckBox,
                           QTabWidget, QWidget, QFileDialog, QMessageBox,
                           QListWidget, QLineEdit)  # 追加
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QColor, QFont, QFontDatabase

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(500)
        hint = self.sizeHint()
        print(f"推奨サイズ: 幅={hint.width()}, 高さ={hint.height()}")
        self.resize(500, hint.height())  # 幅は500、高さは推奨値に
        
        self.settings = parent.settings if parent is not None else {
            "font_size": 24,
            "font_weight": 75,
            "font_shadow": 2,
            "font_color": "#FFFFFF",
            "font_family": "MSP Gothic",
            "font_shadow_direction": "bottom-right",
            "font_shadow_color": "#000000",
            "comment_speed": 6,
            "display_position": "center",
            "max_comments": 40,
            "window_opacity": 0.8,
            "update_interval": 5,
            "playback_speed": 1.0,
            "auto_next_thread": True,
            "next_thread_search_duration": 180,
            "hide_anchor_comments": False,
            "hide_url_comments": False,
            "spacing": 10,
            "ng_ids": [],  # NGリスト追加
            "ng_names": [],
            "ng_texts": []
        }
        
        self.load_settings()
        self.init_ui()
    
    def init_ui(self):
        print("現在の self.settings:", self.settings)

        layout = QVBoxLayout()
        self.tab_widget = QTabWidget()  # self を付けてインスタンス変数に
        
        # 表示設定タブ
        display_tab = QWidget()
        display_layout = QVBoxLayout()
        
        # フォント設定グループ
        font_group = QGroupBox("フォント設定")
        font_layout = QFormLayout()
        
        # フォント種類（動的取得）
        self.font_family_combo = QComboBox()
        font_db = QFontDatabase()
        font_families = font_db.families()  # システムの全フォントを取得
        for family in font_families:
            self.font_family_combo.addItem(family, family)
        index = self.font_family_combo.findData(self.settings["font_family"])
        if index >= 0:
            self.font_family_combo.setCurrentIndex(index)
        else:
            self.font_family_combo.setCurrentIndex(0)  # 見つからない場合は先頭を選択
        font_layout.addRow("フォント:", self.font_family_combo)
        
        # フォントサイズ
        self.font_size_slider = QSlider(Qt.Horizontal)
        self.font_size_slider.setRange(12, 48)
        self.font_size_slider.setValue(self.settings["font_size"])
        self.font_size_slider.setTickPosition(QSlider.TicksBelow)
        self.font_size_slider.setTickInterval(4)
        self.font_size_label = QLabel(f"{self.settings['font_size']}pt")
        self.font_size_slider.valueChanged.connect(self.update_font_size_label)
        font_layout.addRow("フォントサイズ:", self.font_size_slider)
        font_layout.addRow("", self.font_size_label)
        
        # フォントの太さ（スライダーに変更）
        self.font_weight_slider = QSlider(Qt.Horizontal)
        self.font_weight_slider.setRange(1, 99)  # QFont の weight は 1-99
        self.font_weight_slider.setValue(self.settings["font_weight"])
        self.font_weight_slider.setTickPosition(QSlider.TicksBelow)
        self.font_weight_slider.setTickInterval(10)
        self.font_weight_label = QLabel(f"{self.settings['font_weight']}")
        self.font_weight_slider.valueChanged.connect(self.update_font_weight_label)
        font_layout.addRow("フォントの太さ:", self.font_weight_slider)
        font_layout.addRow("", self.font_weight_label)
        
        # フォントの影
        self.font_shadow_slider = QSlider(Qt.Horizontal)
        self.font_shadow_slider.setRange(0, 5)
        self.font_shadow_slider.setValue(self.settings["font_shadow"])
        self.font_shadow_slider.setTickPosition(QSlider.TicksBelow)
        self.font_shadow_slider.setTickInterval(1)
        self.font_shadow_label = QLabel(f"{self.settings['font_shadow']}px")
        self.font_shadow_slider.valueChanged.connect(self.update_font_shadow_label)
        font_layout.addRow("フォントの影:", self.font_shadow_slider)
        font_layout.addRow("", self.font_shadow_label)
        
        # 影の方向グループを追加
        shadow_direction_group = QGroupBox("影の方向")
        shadow_direction_layout = QHBoxLayout()  # QVBoxLayout を QHBoxLayout に変更

        # チェックボックスの定義
        self.shadow_top_left = QCheckBox("左上")
        self.shadow_bottom_left = QCheckBox("左下")
        self.shadow_top_right = QCheckBox("右上")
        self.shadow_bottom_right = QCheckBox("右下")

        # 初期状態を設定（リスト形式で管理）
        shadow_directions = self.settings.get("font_shadow_directions", ["bottom-right"])
        self.shadow_top_left.setChecked("top-left" in shadow_directions)
        self.shadow_bottom_left.setChecked("bottom-left" in shadow_directions)
        self.shadow_top_right.setChecked("top-right" in shadow_directions)
        self.shadow_bottom_right.setChecked("bottom-right" in shadow_directions)

        # レイアウトに追加（左上→左下→右上→右下の順）
        shadow_direction_layout.addWidget(self.shadow_top_left)
        shadow_direction_layout.addWidget(self.shadow_bottom_left)
        shadow_direction_layout.addWidget(self.shadow_top_right)
        shadow_direction_layout.addWidget(self.shadow_bottom_right)
        shadow_direction_group.setLayout(shadow_direction_layout)
        font_layout.addRow("影の方向:", shadow_direction_group)
        
        self.font_shadow_color_button = QPushButton()
        self.font_shadow_color_button.setAutoFillBackground(True)
        shadow_color = self.settings.get("font_shadow_color", "#000000")
        self.update_shadow_color_button(shadow_color)
        self.font_shadow_color_button.clicked.connect(self.select_font_shadow_color)
        font_layout.addRow("影の色:", self.font_shadow_color_button)
        
        self.font_color_button = QPushButton()
        self.font_color_button.setAutoFillBackground(True)
        self.update_color_button(self.settings["font_color"])
        self.font_color_button.clicked.connect(self.select_font_color)
        font_layout.addRow("フォント色:", self.font_color_button)
        
        font_group.setLayout(font_layout)
        display_layout.addWidget(font_group)
        
        # 表示設定グループ
        display_group = QGroupBox("表示設定")
        display_form = QFormLayout()
        
        self.comment_speed_slider = QSlider(Qt.Horizontal)
        self.comment_speed_slider.setRange(20, 150)
        self.comment_speed_slider.setValue(int(self.settings["comment_speed"] * 10))
        self.comment_speed_slider.setTickPosition(QSlider.TicksBelow)
        self.comment_speed_slider.setTickInterval(5)
        self.comment_speed_label = QLabel(f"{self.settings['comment_speed']:.1f}秒")
        self.comment_speed_slider.valueChanged.connect(self.update_comment_speed_label)
        display_form.addRow("コメント速度:", self.comment_speed_slider)
        display_form.addRow("", self.comment_speed_label)
        
        self.display_position_combo = QComboBox()
        self.display_position_combo.addItem("上部", "top")
        self.display_position_combo.addItem("中央", "center")
        self.display_position_combo.addItem("下部", "bottom")
        index = self.display_position_combo.findData(self.settings["display_position"])
        if index >= 0:
            self.display_position_combo.setCurrentIndex(index)
        display_form.addRow("表示位置:", self.display_position_combo)
        
        self.max_comments_spin = QSpinBox()
        self.max_comments_spin.setRange(10, 100)
        self.max_comments_spin.setValue(self.settings["max_comments"])
        display_form.addRow("最大コメント数:", self.max_comments_spin)
        
        self.window_opacity_slider = QSlider(Qt.Horizontal)
        self.window_opacity_slider.setRange(10, 100)
        self.window_opacity_slider.setValue(int(self.settings["window_opacity"] * 100))
        self.window_opacity_slider.setTickPosition(QSlider.TicksBelow)
        self.window_opacity_slider.setTickInterval(10)
        self.window_opacity_label = QLabel(f"{int(self.settings['window_opacity'] * 100)}%")
        self.window_opacity_slider.valueChanged.connect(self.update_window_opacity_label)
        display_form.addRow("ウィンドウ透明度:", self.window_opacity_slider)
        display_form.addRow("", self.window_opacity_label)
        
        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(0, 40)
        self.spacing_spin.setValue(self.settings["spacing"])
        self.spacing_spin.setSuffix("px")
        display_form.addRow("コメント行間:", self.spacing_spin)
        
        self.hide_anchor_checkbox = QCheckBox("アンカー（>>）を含むコメントを表示しない")
        self.hide_anchor_checkbox.setChecked(self.settings.get("hide_anchor_comments", False))
        display_form.addRow("", self.hide_anchor_checkbox)
        
        self.hide_url_checkbox = QCheckBox("URL（http）を含むコメントを表示しない")
        self.hide_url_checkbox.setChecked(self.settings.get("hide_url_comments", False))
        display_form.addRow("", self.hide_url_checkbox)
        
        display_group.setLayout(display_form)
        display_layout.addWidget(display_group)
        
        display_tab.setLayout(display_layout)
        self.tab_widget.addTab(display_tab, "表示設定")
        
        # 通信設定タブ
        network_tab = QWidget()
        network_layout = QVBoxLayout()
        
        network_group = QGroupBox("通信設定")
        network_form = QFormLayout()
        
        self.update_interval_slider = QSlider(Qt.Horizontal)
        self.update_interval_slider.setRange(1, 10)
        self.update_interval_slider.setValue(self.settings["update_interval"])
        self.update_interval_slider.setTickPosition(QSlider.TicksBelow)
        self.update_interval_slider.setTickInterval(1)
        self.update_interval_label = QLabel(f"{self.settings['update_interval']}秒")
        self.update_interval_slider.valueChanged.connect(self.update_interval_label_text)
        network_form.addRow("更新間隔:", self.update_interval_slider)
        network_form.addRow("", self.update_interval_label)
        
        self.auto_next_thread_check = QCheckBox("自動的に次スレを検出する")
        self.auto_next_thread_check.setChecked(self.settings["auto_next_thread"])
        network_form.addRow("", self.auto_next_thread_check)
        
        self.next_thread_search_duration_spin = QSpinBox()
        self.next_thread_search_duration_spin.setRange(60, 600)
        self.next_thread_search_duration_spin.setValue(self.settings["next_thread_search_duration"])
        self.next_thread_search_duration_spin.setSuffix("秒")
        network_form.addRow("次スレ検索時間:", self.next_thread_search_duration_spin)
        
        network_group.setLayout(network_form)
        network_layout.addWidget(network_group)
        
        playback_group = QGroupBox("過去ログ再生設定")
        playback_form = QFormLayout()
        
        self.playback_speed_combo = QComboBox()
        # 新しい選択肢: 1.0～2.0 を 0.05刻みで生成
        speed_options = [round(1.0 + i * 0.05, 2) for i in range(21)]  # [1.0, 1.05, ..., 2.0]
        for speed in speed_options:
            self.playback_speed_combo.addItem(f"{speed}倍速", speed)
        # 現在の設定値を選択
        current_speed = self.settings.get("playback_speed", 1.0)
        index = 0
        for i in range(self.playback_speed_combo.count()):
            if abs(self.playback_speed_combo.itemData(i) - current_speed) < 0.01:
                index = i
                break
        self.playback_speed_combo.setCurrentIndex(index)
        playback_form.addRow("再生速度:", self.playback_speed_combo)
        
        playback_group.setLayout(playback_form)
        network_layout.addWidget(playback_group)
        
        network_tab.setLayout(network_layout)
        self.tab_widget.addTab(network_tab, "通信・再生設定")



# NG設定タブ（新規）
        ng_tab = QWidget()
        ng_layout = QVBoxLayout()
        
        # NG ID
        ng_id_group = QGroupBox("NG ID")
        ng_id_layout = QVBoxLayout()
        self.ng_id_list = QListWidget()
        for ng_id in self.settings["ng_ids"]:
            self.ng_id_list.addItem(ng_id)
        ng_id_layout.addWidget(self.ng_id_list)
        ng_id_input_layout = QHBoxLayout()
        self.ng_id_input = QLineEdit()
        self.ng_id_input.setPlaceholderText("NGにしたいIDを入力")
        ng_id_add_button = QPushButton("追加")
        ng_id_add_button.clicked.connect(self.add_ng_id)
        ng_id_remove_button = QPushButton("削除")
        ng_id_remove_button.clicked.connect(self.remove_ng_id)
        ng_id_input_layout.addWidget(self.ng_id_input)
        ng_id_input_layout.addWidget(ng_id_add_button)
        ng_id_input_layout.addWidget(ng_id_remove_button)
        ng_id_layout.addLayout(ng_id_input_layout)
        ng_id_group.setLayout(ng_id_layout)
        ng_layout.addWidget(ng_id_group)
        
        # NG 名前
        ng_name_group = QGroupBox("NG 名前")
        ng_name_layout = QVBoxLayout()
        self.ng_name_list = QListWidget()
        for ng_name in self.settings["ng_names"]:
            self.ng_name_list.addItem(ng_name)
        ng_name_layout.addWidget(self.ng_name_list)
        ng_name_input_layout = QHBoxLayout()
        self.ng_name_input = QLineEdit()
        self.ng_name_input.setPlaceholderText("NGにしたい名前を入力")
        ng_name_add_button = QPushButton("追加")
        ng_name_add_button.clicked.connect(self.add_ng_name)
        ng_name_remove_button = QPushButton("削除")
        ng_name_remove_button.clicked.connect(self.remove_ng_name)
        ng_name_input_layout.addWidget(self.ng_name_input)
        ng_name_input_layout.addWidget(ng_name_add_button)
        ng_name_input_layout.addWidget(ng_name_remove_button)
        ng_name_layout.addLayout(ng_name_input_layout)
        ng_name_group.setLayout(ng_name_layout)
        ng_layout.addWidget(ng_name_group)
        
        # NG 本文
        ng_text_group = QGroupBox("NG 本文")
        ng_text_layout = QVBoxLayout()
        self.ng_text_list = QListWidget()
        for ng_text in self.settings["ng_texts"]:
            self.ng_text_list.addItem(ng_text)
        ng_text_layout.addWidget(self.ng_text_list)
        ng_text_input_layout = QHBoxLayout()
        self.ng_text_input = QLineEdit()
        self.ng_text_input.setPlaceholderText("NGにしたい文字列を入力")
        ng_text_add_button = QPushButton("追加")
        ng_text_add_button.clicked.connect(self.add_ng_text)
        ng_text_remove_button = QPushButton("削除")
        ng_text_remove_button.clicked.connect(self.remove_ng_text)
        ng_text_input_layout.addWidget(self.ng_text_input)
        ng_text_input_layout.addWidget(ng_text_add_button)
        ng_text_input_layout.addWidget(ng_text_remove_button)
        ng_text_layout.addLayout(ng_text_input_layout)
        ng_text_group.setLayout(ng_text_layout)
        ng_layout.addWidget(ng_text_group)
        
        ng_tab.setLayout(ng_layout)
        self.tab_widget.addTab(ng_tab, "NG設定")
        
        layout.addWidget(self.tab_widget)
        
        # ボタンレイアウト（既存、変更なし）
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save_settings)
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button = QPushButton("初期設定に戻す")
        self.reset_button.clicked.connect(self.reset_settings)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)

    # NG追加メソッド
    def add_ng_id(self):
        text = self.ng_id_input.text().strip()
        if text and text not in self.settings["ng_ids"]:
            self.settings["ng_ids"].append(text)
            self.ng_id_list.addItem(text)
            self.ng_id_input.clear()
    
    def add_ng_name(self):
        text = self.ng_name_input.text().strip()
        if text and text not in self.settings["ng_names"]:
            self.settings["ng_names"].append(text)
            self.ng_name_list.addItem(text)
            self.ng_name_input.clear()
    
    def add_ng_text(self):
        text = self.ng_text_input.text().strip()
        if text and text not in self.settings["ng_texts"]:
            self.settings["ng_texts"].append(text)
            self.ng_text_list.addItem(text)
            self.ng_text_input.clear()
    
    # NG削除メソッド
    def remove_ng_id(self):
        selected = self.ng_id_list.currentItem()
        if selected:
            text = selected.text()
            self.settings["ng_ids"].remove(text)
            self.ng_id_list.takeItem(self.ng_id_list.row(selected))
    
    def remove_ng_name(self):
        selected = self.ng_name_list.currentItem()
        if selected:
            text = selected.text()
            self.settings["ng_names"].remove(text)
            self.ng_name_list.takeItem(self.ng_name_list.row(selected))
    
    def remove_ng_text(self):
        selected = self.ng_text_list.currentItem()
        if selected:
            text = selected.text()
            self.settings["ng_texts"].remove(text)
            self.ng_text_list.takeItem(self.ng_text_list.row(selected))

    def update_font_size_label(self, value):
        self.font_size_label.setText(f"{value}pt")
    
    def update_font_shadow_label(self, value):
        self.font_shadow_label.setText(f"{value}px")
    
    def update_font_weight_label(self, value):  # 新規追加
        self.font_weight_label.setText(f"{value}")
    
    def select_font_shadow_color(self):
        current_color = QColor(self.settings["font_shadow_color"])
        color = QColorDialog.getColor(current_color, self, "影の色を選択")
        if color.isValid():
            self.update_shadow_color_button(color.name())

    def update_shadow_color_button(self, color_name):
        self.settings["font_shadow_color"] = color_name
        self.font_shadow_color_button.setStyleSheet(f"background-color: {color_name}; color: {'#000000' if QColor(color_name).lightness() > 128 else '#FFFFFF'};")
        self.font_shadow_color_button.setText(color_name)

    def update_comment_speed_label(self, value):
        self.comment_speed_label.setText(f"{value / 10.0:.1f}秒")
    
    def update_window_opacity_label(self, value):
        self.window_opacity_label.setText(f"{value}%")
    
    def update_interval_label_text(self, value):
        self.update_interval_label.setText(f"{value}秒")
    
    def select_font_color(self):
        current_color = QColor(self.settings["font_color"])
        color = QColorDialog.getColor(current_color, self, "フォント色を選択")
        if color.isValid():
            self.update_color_button(color.name())
    
    def update_color_button(self, color_name):
        self.settings["font_color"] = color_name
        self.font_color_button.setStyleSheet(f"background-color: {color_name}; color: {'#000000' if QColor(color_name).lightness() > 128 else '#FFFFFF'};")
        self.font_color_button.setText(color_name)
    
    def get_settings(self):
        return self.settings
    
    # 保存メソッドの修正
    def save_settings(self):
        self.settings["font_size"] = self.font_size_slider.value()
        self.settings["font_weight"] = self.font_weight_slider.value()
        self.settings["font_shadow"] = self.font_shadow_slider.value()
        self.settings["font_color"] = self.font_color_button.text()
        self.settings["font_family"] = self.font_family_combo.currentData()
        self.settings["comment_speed"] = self.comment_speed_slider.value() / 10.0
        self.settings["display_position"] = self.display_position_combo.currentData()
        self.settings["max_comments"] = self.max_comments_spin.value()
        self.settings["window_opacity"] = self.window_opacity_slider.value() / 100.0
        self.settings["update_interval"] = self.update_interval_slider.value()
        self.settings["playback_speed"] = self.playback_speed_combo.currentData()
        self.settings["auto_next_thread"] = self.auto_next_thread_check.isChecked()
        self.settings["next_thread_search_duration"] = self.next_thread_search_duration_spin.value()
        self.settings["font_shadow_color"] = self.font_shadow_color_button.text()
        self.settings["hide_anchor_comments"] = self.hide_anchor_checkbox.isChecked()
        self.settings["hide_url_comments"] = self.hide_url_checkbox.isChecked()
        self.settings["spacing"] = self.spacing_spin.value()

        # 影の方向をリストとして保存
        shadow_directions = []
        if self.shadow_bottom_right.isChecked():
            shadow_directions.append("bottom-right")
        if self.shadow_top_right.isChecked():
            shadow_directions.append("top-right")
        if self.shadow_bottom_left.isChecked():
            shadow_directions.append("bottom-left")
        if self.shadow_top_left.isChecked():
            shadow_directions.append("top-left")
        self.settings["font_shadow_directions"] = shadow_directions

        try:
            settings_dir = os.path.expanduser("~/.edge_live_viewer")
            os.makedirs(settings_dir, exist_ok=True)
            settings_file = os.path.join(settings_dir, "settings.json")
            with open(settings_file, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=4)
            QMessageBox.information(self, "設定保存", "設定を保存しました。")
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "エラー", f"設定の保存に失敗しました: {str(e)}")
    
    def load_settings(self):
        try:
            settings_file = os.path.expanduser("~/.edge_live_viewer/settings.json")
            if os.path.exists(settings_file):
                with open(settings_file, "r", encoding="utf-8") as f:
                    loaded_settings = json.load(f)
                self.settings.update(loaded_settings)
        except Exception as e:
            print(f"設定の読み込みに失敗しました: {str(e)}")
    
    def reset_settings(self):
        if QMessageBox.question(self, "設定リセット", "設定を初期値に戻しますか？",
                              QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.settings = {
                "font_size": 24,
                "font_weight": 75,
                "font_shadow": 2,
                "font_color": "#FFFFFF",
                "font_family": "MSP Gothic",
                "font_shadow_direction": "bottom-right",
                "font_shadow_directions": ["bottom-right"],  # リスト形式でデフォルトは "bottom-right" のみ
                "font_shadow_color": "#000000",
                "comment_speed": 6,
                "display_position": "center",
                "max_comments": 40,
                "window_opacity": 0.8,
                "update_interval": 5,
                "playback_speed": 1.0,
                "auto_next_thread": True,
                "next_thread_search_duration": 180,
                "hide_anchor_comments": False,
                "hide_url_comments": False,
                "spacing": 10,
                "ng_ids": [],
                "ng_names": [],
                "ng_texts": []
            }
            self.font_size_slider.setValue(self.settings["font_size"])
            self.font_weight_slider.setValue(self.settings["font_weight"])  # 修正: スライダーにリセット
            self.font_shadow_slider.setValue(self.settings["font_shadow"])
            self.shadow_bottom_right.setChecked(True)
            self.shadow_top_right.setChecked(False)
            self.shadow_bottom_left.setChecked(False)
            self.shadow_top_left.setChecked(False)
            self.update_color_button(self.settings["font_color"])
            self.comment_speed_slider.setValue(self.settings["comment_speed"])
            index = self.display_position_combo.findData(self.settings["display_position"])
            if index >= 0:
                self.display_position_combo.setCurrentIndex(index)
            self.max_comments_spin.setValue(self.settings["max_comments"])
            self.window_opacity_slider.setValue(int(self.settings["window_opacity"] * 100))
            self.update_interval_slider.setValue(self.settings["update_interval"])
            index = 1
            for i in range(self.playback_speed_combo.count()):
                if abs(self.playback_speed_combo.itemData(i) - self.settings["playback_speed"]) < 0.01:
                    index = i
                    break
            self.playback_speed_combo.setCurrentIndex(index)
            self.auto_next_thread_check.setChecked(self.settings["auto_next_thread"])
            self.next_thread_search_duration_spin.setValue(self.settings["next_thread_search_duration"])
            index = self.font_family_combo.findData(self.settings["font_family"])
            if index >= 0:
                self.font_family_combo.setCurrentIndex(index)
            self.hide_anchor_checkbox.setChecked(self.settings["hide_anchor_comments"])
            self.hide_url_checkbox.setChecked(self.settings["hide_url_comments"])
            self.spacing_spin.setValue(self.settings["spacing"])
            self.ng_id_list.clear()
            self.ng_name_list.clear()
            self.ng_text_list.clear()
            

if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dialog = SettingsDialog()
    if dialog.exec_() == QDialog.Accepted:
        print("設定が保存されました:")
        for key, value in dialog.get_settings().items():
            print(f"{key}: {value}")
    sys.exit(0)