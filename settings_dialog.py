#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
設定ダイアログ
ユーザーがフォントサイズ、色、速度などの設定を変更できるダイアログ
"""

import os
import json
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                           QSlider, QComboBox, QPushButton, QColorDialog,
                           QGroupBox, QFormLayout, QSpinBox, QCheckBox,
                           QTabWidget, QWidget, QFileDialog, QMessageBox)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QColor, QFont

class SettingsDialog(QDialog):
    """
    設定ダイアログ
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setMinimumWidth(500)
        
        # 親から渡された設定を使用、なければデフォルト
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
            "hide_anchor_comments": False,  # 新規追加
            "hide_url_comments": False      # 新規追加
        }
        
        self.load_settings()
        self.init_ui()
    
    def init_ui(self):
        print("現在の self.settings:", self.settings)  # デバッグ用

        layout = QVBoxLayout()
        
        tab_widget = QTabWidget()
        
        # 表示設定タブ
        display_tab = QWidget()
        display_layout = QVBoxLayout()
        
        # フォント設定グループ
        font_group = QGroupBox("フォント設定")
        font_layout = QFormLayout()
        
        # フォントファミリー
        self.font_family_combo = QComboBox()
        font_options = [
            ("MSP Gothic", "MSP Gothic"),
            ("Meiryo", "Meiryo"),
            ("Yu Gothic", "Yu Gothic"),
            ("Segoe UI Emoji", "Segoe UI Emoji"),
            ("Noto Sans JP", "Noto Sans JP"),
        ]
        for display_name, font_name in font_options:
            self.font_family_combo.addItem(display_name, font_name)
        index = self.font_family_combo.findData(self.settings["font_family"])
        if index >= 0:
            self.font_family_combo.setCurrentIndex(index)
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
        
        # フォントの太さ
        self.font_weight_combo = QComboBox()
        self.font_weight_combo.addItem("標準", 50)
        self.font_weight_combo.addItem("太字", 75)
        self.font_weight_combo.addItem("最太", 87)
        self.font_weight_combo.addItem("超太字", 99)
        index = self.font_weight_combo.findData(self.settings["font_weight"])
        if index >= 0:
            self.font_weight_combo.setCurrentIndex(index)
        font_layout.addRow("フォントの太さ:", self.font_weight_combo)
        
        # 影の距離
        self.font_shadow_slider = QSlider(Qt.Horizontal)
        self.font_shadow_slider.setRange(0, 5)
        self.font_shadow_slider.setValue(self.settings["font_shadow"])
        self.font_shadow_slider.setTickPosition(QSlider.TicksBelow)
        self.font_shadow_slider.setTickInterval(1)
        self.font_shadow_label = QLabel(f"{self.settings['font_shadow']}px")
        self.font_shadow_slider.valueChanged.connect(self.update_font_shadow_label)
        font_layout.addRow("フォントの影:", self.font_shadow_slider)
        font_layout.addRow("", self.font_shadow_label)
        
        # 影の方向
        self.font_shadow_direction_combo = QComboBox()
        self.font_shadow_direction_combo.addItem("右下", "bottom-right")
        self.font_shadow_direction_combo.addItem("右上", "top-right")
        self.font_shadow_direction_combo.addItem("左下", "bottom-left")
        self.font_shadow_direction_combo.addItem("左上", "top-left")
        shadow_direction = self.settings.get("font_shadow_direction", "bottom-right")
        index = self.font_shadow_direction_combo.findData(shadow_direction)
        if index >= 0:
            self.font_shadow_direction_combo.setCurrentIndex(index)
        else:
            print(f"影の方向: {shadow_direction} が見つかりませんでした。デフォルト 'bottom-right' を使用")
            self.font_shadow_direction_combo.setCurrentIndex(0)  # "右下" に設定
        font_layout.addRow("影の方向:", self.font_shadow_direction_combo)
        
        # 影の色
        self.font_shadow_color_button = QPushButton()
        self.font_shadow_color_button.setAutoFillBackground(True)
        shadow_color = self.settings.get("font_shadow_color", "#000000")
        self.update_shadow_color_button(shadow_color)  # 保存された値を反映
        self.font_shadow_color_button.clicked.connect(self.select_font_shadow_color)
        font_layout.addRow("影の色:", self.font_shadow_color_button)
        
        # フォント色
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
        
        # コメント速度（2.0〜15.0秒、0.1秒刻み）
        self.comment_speed_slider = QSlider(Qt.Horizontal)
        self.comment_speed_slider.setRange(20, 150)  # 2.0〜15.0秒を10倍した値（整数で扱う）
        self.comment_speed_slider.setValue(int(self.settings["comment_speed"] * 10))  # 現在の値を10倍して設定
        self.comment_speed_slider.setTickPosition(QSlider.TicksBelow)
        self.comment_speed_slider.setTickInterval(5)  # 0.5秒刻み
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
        
        # 新しいチェックボックスを追加
        self.hide_anchor_checkbox = QCheckBox("アンカー（>>）を含むコメントを表示しない")
        self.hide_anchor_checkbox.setChecked(self.settings.get("hide_anchor_comments", False))
        display_form.addRow("", self.hide_anchor_checkbox)
        
        self.hide_url_checkbox = QCheckBox("URL（http）を含むコメントを表示しない")
        self.hide_url_checkbox.setChecked(self.settings.get("hide_url_comments", False))
        display_form.addRow("", self.hide_url_checkbox)
        
        display_group.setLayout(display_form)
        display_layout.addWidget(display_group)
        
        display_tab.setLayout(display_layout)
        tab_widget.addTab(display_tab, "表示設定")
        
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
        self.playback_speed_combo.addItem("0.5倍速", 0.5)
        self.playback_speed_combo.addItem("1.0倍速", 1.0)
        self.playback_speed_combo.addItem("1.5倍速", 1.5)
        self.playback_speed_combo.addItem("2.0倍速", 2.0)
        index = 1
        for i in range(self.playback_speed_combo.count()):
            if abs(self.playback_speed_combo.itemData(i) - self.settings["playback_speed"]) < 0.01:
                index = i
                break
        self.playback_speed_combo.setCurrentIndex(index)
        playback_form.addRow("再生速度:", self.playback_speed_combo)
        
        playback_group.setLayout(playback_form)
        network_layout.addWidget(playback_group)
        
        network_tab.setLayout(network_layout)
        tab_widget.addTab(network_tab, "通信・再生設定")
        
        layout.addWidget(tab_widget)
        
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
    
    def update_font_size_label(self, value):
        self.font_size_label.setText(f"{value}pt")
    
    def update_font_shadow_label(self, value):
        self.font_shadow_label.setText(f"{value}px")
    
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
        self.comment_speed_label.setText(f"{value / 10.0:.1f}秒")  # 10で割って小数点以下1桁で表示
    
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
    
    def save_settings(self):
        self.settings["font_size"] = self.font_size_slider.value()
        self.settings["font_weight"] = self.font_weight_combo.currentData()
        self.settings["font_shadow"] = self.font_shadow_slider.value()
        self.settings["font_color"] = self.font_color_button.text()  # QColor.name() から直接取得
        self.settings["font_family"] = self.font_family_combo.currentData()  # フォントファミリーを保存
        self.settings["comment_speed"] = self.comment_speed_slider.value() / 10.0  # 浮動小数点数として保存
        self.settings["display_position"] = self.display_position_combo.currentData()
        self.settings["max_comments"] = self.max_comments_spin.value()
        self.settings["window_opacity"] = self.window_opacity_slider.value() / 100.0
        self.settings["update_interval"] = self.update_interval_slider.value()
        self.settings["playback_speed"] = self.playback_speed_combo.currentData()
        self.settings["auto_next_thread"] = self.auto_next_thread_check.isChecked()
        self.settings["next_thread_search_duration"] = self.next_thread_search_duration_spin.value()
        self.settings["font_shadow_direction"] = self.font_shadow_direction_combo.currentData()
        self.settings["font_shadow_color"] = self.font_shadow_color_button.text()
        # 新しい設定を保存
        self.settings["hide_anchor_comments"] = self.hide_anchor_checkbox.isChecked()
        self.settings["hide_url_comments"] = self.hide_url_checkbox.isChecked()
        
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
                # 既存の self.settings にマージ
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
                "font_shadow_color": "#000000",
                "comment_speed": 6,
                "display_position": "center",
                "max_comments": 40,
                "window_opacity": 0.8,
                "update_interval": 5,
                "playback_speed": 1.0,
                "auto_next_thread": True,
                "next_thread_search_duration": 180,
                "hide_anchor_comments": False,  # 新規追加
                "hide_url_comments": False      # 新規追加
            }
            
            self.font_size_slider.setValue(self.settings["font_size"])
            index = self.font_weight_combo.findData(self.settings["font_weight"])
            if index >= 0:
                self.font_weight_combo.setCurrentIndex(index)
            self.font_shadow_slider.setValue(self.settings["font_shadow"])
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