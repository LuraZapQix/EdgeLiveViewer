#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import random
import logging
import time
from PyQt5.QtWidgets import (QWidget, QApplication)
from PyQt5.QtCore import (Qt, QTimer, QRect, QPoint, QSize)
from PyQt5.QtGui import (QFont, QColor, QPainter, QFontMetrics, QPen, QBrush)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', force=True)
logger = logging.getLogger('CommentOverlayWindow')

class CommentOverlayWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.8)
        self.setGeometry(100, 100, 600, 800)

        self.comments = []
        self.max_comments = 40
        self.font_size = 24
        self.font_weight = 75
        self.font_shadow = 2
        self.font_color = QColor("#FFFFFF")
        self.font_family = "MSP Gothic"
        self.font_shadow_direction = "bottom-right"
        self.font_shadow_directions = ["bottom-right"]  # デフォルトをリストに変更
        self.font_shadow_color = QColor("#000000")
        self.comment_speed = 6.0  # デフォルトを6.0秒（浮動小数点数）に変更
        self.display_position = "top"  # デフォルトを "top" に変更
        self.hide_anchor_comments = False  # 新規追加
        self.hide_url_comments = False     # 新規追加
        self.spacing = 20  # 修正: デフォルト値として追加

        # ここで comment_queue を初期化（追加）
        self.comment_queue = []
        self.flow_timer = QTimer(self)
        self.flow_timer.timeout.connect(self.flow_comment)
        self.flow_timer.start(300)  # 300ms間隔で流す

        self.move_area_height = 25
        self.close_button_size = 22
        self.minimize_button_size = 22
        self.button_margin = 2
        self.is_hovering_close = False
        self.is_hovering_minimize = False
        self.is_minimized = False

        self.calculate_comment_rows()
        self.row_usage = {}

        self.dragging = False
        self.resizing = False
        self.drag_position = QPoint()
        self.resize_border = 10
        self.resize_mode = None
        self.minimum_size = QSize(300, 200)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_comments)
        self.timer.start(8)

        self.comment_id_counter = 0

        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        self.main_window = None

        self.ng_ids = []
        self.ng_names = []
        self.ng_texts = []

        self.row_usage = {}  # {row: comment_obj} に変更（以前は {row: end_time}）

    def add_comment_batch(self, comments):
        self.comment_queue.extend(comments)
        logger.debug(f"コメントをキューに追加: 数={len(comments)}, キュー長={len(self.comment_queue)}")

    def flow_comment(self):
        if self.comment_queue:
            comment = self.comment_queue.pop(0)
            self.add_comment(comment)
            logger.debug(f"コメントを流す: text={comment['text']}, 残りキュー={len(self.comment_queue)}")

    def add_system_message(self, message, message_type="generic"):
        """システムメッセージをコメントとして追加"""
        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        font_metrics = QFontMetrics(font)
        
        text_width = font_metrics.width(message)
        
        # メッセージ種別に応じて高さを調整
        if message_type == "thread_over_1000":
            y_position = self.move_area_height + self.height() // 4  # 上部寄り（1/4の高さ）
        elif message_type == "next_thread_connected":
            y_position = self.move_area_height + self.height() // 2  # 中央寄り（1/2の高さ）
        else:
            y_position = self.move_area_height + self.height() // 3  # デフォルト（1/3の高さ）
        
        self.comment_id_counter += 1
        comment_id = f"system_{int(time.time()*1000)}_{self.comment_id_counter}"
        total_distance = self.width() + text_width
        speed = total_distance / self.comment_speed
        
        comment_obj = {
            'id': comment_id,
            'text': message,
            'x': float(self.width()),
            'y': y_position,
            'width': text_width,
            'row': -1,  # 通常のコメントとは異なる位置を示す
            'creation_time': QApplication.instance().property("comment_time") or 0,
            'speed': speed
        }
        
        self.comments.append(comment_obj)
        logger.info(f"システムメッセージ追加: {message}, 種別: {message_type}, ID: {comment_id}, y: {y_position}")
        self.update()

    def calculate_comment_rows(self):
        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        font_metrics = QFontMetrics(font)
        
        line_height = font_metrics.height()
        self.row_height = line_height + self.spacing
        
        self.max_rows = max(1, (self.height() - self.move_area_height - line_height) // self.row_height)
        self.row_usage = {}

    def update_cursor(self, pos):
        if self.is_minimized:
            self.setCursor(Qt.ArrowCursor)
            self.resize_mode = None
            return

        left = pos.x() <= self.resize_border
        right = pos.x() >= self.width() - self.resize_border
        top = pos.y() <= self.resize_border
        bottom = pos.y() >= self.height() - self.resize_border
        in_move_area = pos.y() <= self.move_area_height

        close_button_rect = QRect(
            self.width() - self.close_button_size - self.button_margin,
            self.button_margin,
            self.close_button_size,
            self.close_button_size
        )
        minimize_button_rect = QRect(
            self.width() - self.close_button_size - self.minimize_button_size - self.button_margin * 3,
            self.button_margin,
            self.minimize_button_size,
            self.minimize_button_size
        )

        self.is_hovering_close = close_button_rect.contains(pos)
        self.is_hovering_minimize = minimize_button_rect.contains(pos)
        if self.is_hovering_close:
            self.setCursor(Qt.PointingHandCursor)
            self.resize_mode = None
        elif self.is_hovering_minimize:
            self.setCursor(Qt.PointingHandCursor)
            self.resize_mode = None
        elif in_move_area and not (left or right):
            self.setCursor(Qt.OpenHandCursor)
            self.resize_mode = None
        elif left and top:
            self.setCursor(Qt.SizeFDiagCursor)
            self.resize_mode = "top-left"
        elif right and bottom:
            self.setCursor(Qt.SizeFDiagCursor)
            self.resize_mode = "bottom-right"
        elif left and bottom:
            self.setCursor(Qt.SizeBDiagCursor)
            self.resize_mode = "bottom-left"
        elif right and top:
            self.setCursor(Qt.SizeBDiagCursor)
            self.resize_mode = "top-right"
        elif left:
            self.setCursor(Qt.SizeHorCursor)
            self.resize_mode = "left"
        elif right:
            self.setCursor(Qt.SizeHorCursor)
            self.resize_mode = "right"
        elif top:
            self.setCursor(Qt.SizeVerCursor)
            self.resize_mode = "top"
        elif bottom:
            self.setCursor(Qt.SizeVerCursor)
            self.resize_mode = "bottom"
        else:
            self.setCursor(Qt.ArrowCursor)
            self.resize_mode = None

        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = event.pos()
            self.update_cursor(pos)

            if self.is_minimized:
                return

            close_button_rect = QRect(
                self.width() - self.close_button_size - self.button_margin,
                self.button_margin,
                self.close_button_size,
                self.close_button_size
            )
            minimize_button_rect = QRect(
                self.width() - self.close_button_size - self.minimize_button_size - self.button_margin * 3,
                self.button_margin,
                self.minimize_button_size,
                self.minimize_button_size
            )

            if close_button_rect.contains(pos):
                logger.info("Close button clicked, closing window")
                self.close()
            elif minimize_button_rect.contains(pos):
                logger.info("Minimize button clicked, hiding move area and borders")
                self.is_minimized = True
                self.update()
            elif pos.y() <= self.move_area_height and self.resize_mode is None:
                self.dragging = True
                self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
                logger.info("Move area drag started")
            elif self.resize_mode is not None:
                self.resizing = True
                self.drag_position = event.globalPos()
                logger.info(f"Resize started: mode={self.resize_mode}")

    def mouseMoveEvent(self, event):
        pos = event.pos()
        if self.dragging:
            self.move(event.globalPos() - self.drag_position)
            logger.debug(f"Dragging: new pos=({self.x()}, {self.y()})")
        elif self.resizing:
            self.resize_window(event.globalPos())
            logger.debug(f"Resizing: size=({self.width()}, {self.height()})")
        else:
            self.update_cursor(pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.dragging or self.resizing:
                logger.info("Move or resize ended")
                app = QApplication.instance()
                main_window = app.property("main_window")
                if main_window:
                    main_window.save_window_position(self.pos().x(), self.pos().y(), self.width(), self.height())
            self.dragging = False
            self.resizing = False
            self.update_cursor(event.pos())

    def closeEvent(self, event):
        app = QApplication.instance()
        main_window = app.property("main_window")
        if main_window:
            main_window.save_window_position(self.pos().x(), self.pos().y(), self.width(), self.height())
        event.accept()

    def resize_window(self, global_pos):
        if self.resize_mode is None:
            return

        delta = global_pos - self.drag_position
        geo = self.geometry()
        new_x = geo.x()
        new_y = geo.y()
        new_width = geo.width()
        new_height = geo.height()

        if "left" in self.resize_mode:
            new_x += delta.x()
            new_width -= delta.x()
        elif "right" in self.resize_mode:
            new_width += delta.x()

        if "top" in self.resize_mode:
            new_y += delta.y()
            new_height -= delta.y()
        elif "bottom" in self.resize_mode:
            new_height += delta.y()

        new_width = max(self.minimum_size.width(), new_width)
        new_height = max(self.minimum_size.height(), new_height)

        self.setGeometry(new_x, new_y, new_width, new_height)
        self.drag_position = global_pos

        self.calculate_comment_rows()
        self.update()

    def find_available_row(self, comment_width):
        window_width = self.width()
        available_rows = []
        
        # 新しいコメントの速度を計算
        total_distance_new = window_width + comment_width
        speed_new = total_distance_new / self.comment_speed
        
        for row in range(self.max_rows):
            if row in self.row_usage:
                current_comment = self.row_usage[row]
                right_edge = current_comment['x'] + current_comment['width']
                current_speed = current_comment['speed']
                
                # 現在の隙間
                gap = window_width - right_edge
                
                # 隙間と速度差を考慮
                if gap > 100:  # 最小隙間100px（調整可能）
                    if speed_new > current_speed:  # 新しいコメントが速い場合
                        relative_speed = speed_new - current_speed
                        time_to_catch = gap / relative_speed
                        if time_to_catch >= 2.0:  # 2秒以上のマージン（緩和）
                            available_rows.append(row)
                    else:
                        # 新しいコメントが遅い場合、追い付かないので利用可能
                        available_rows.append(row)
            else:
                available_rows.append(row)
        
        # 利用可能な行から選択
        if available_rows:
            row = min(available_rows)
        else:
            row = min(self.row_usage.keys(), key=lambda k: self.row_usage[k]['x'] + self.row_usage[k]['width'])
        
        # 新しいコメントを仮登録
        self.row_usage[row] = {
            'x': float(window_width),
            'width': comment_width,
            'speed': speed_new,
        }
        
        return row

    def add_comment(self, comment):
        text = comment['text']
        name = comment['name']
        user_id = comment['id']
        
        # NGフィルタリング（変更なし）
        if user_id in self.ng_ids:
            logger.debug(f"NG IDでスキップ: {user_id}, コメント: {text}")
            return
        if any(ng_name in name for ng_name in self.ng_names):
            logger.debug(f"NG 名前でスキップ: {name}, コメント: {text}")
            return
        if any(ng_text in text for ng_text in self.ng_texts):
            logger.debug(f"NG 本文でスキップ: {text}")
            return
        
        # フィルタリング条件（変更なし）
        if self.hide_anchor_comments and ">>" in text:
            logger.debug(f"アンカーコメントをスキップ: {text}")
            return
        if self.hide_url_comments and "http" in text:
            logger.debug(f"URLコメントをスキップ: {text}")
            return
        
        if len(self.comments) >= self.max_comments:
            self.remove_oldest_comment()
        
        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        font_metrics = QFontMetrics(font)
        
        text_width = font_metrics.width(text)
        row = self.find_available_row(text_width)
        
        line_height = font_metrics.height()
        if self.display_position == "top":
            y_position = self.move_area_height + row * self.row_height + line_height
        elif self.display_position == "bottom":
            y_position = self.height() - row * self.row_height - line_height
        
        y_position = max(line_height + self.move_area_height, min(y_position, self.height() - line_height))
        
        self.comment_id_counter += 1
        comment_id = f"comment_{int(time.time()*1000)}_{self.comment_id_counter}"
        total_distance = self.width() + text_width
        speed = total_distance / self.comment_speed
        comment_obj = {
            'id': comment_id,
            'text': text,
            'x': float(self.width()),
            'y': y_position,
            'width': text_width,
            'row': row,
            'creation_time': QApplication.instance().property("comment_time") or 0,
            'speed': speed
        }
        self.comments.append(comment_obj)
        self.row_usage[row] = comment_obj  # 完全なオブジェクトで更新
        logger.info(f"コメント追加: {text}, ID: {comment_id}, y: {y_position}, speed: {speed}")
        self.update()

    def update_comments(self):
        current_time = QApplication.instance().property("comment_time") or 0
        to_remove = []
        
        processed_ids = set()
        for comment in self.comments[:]:
            if comment['id'] in processed_ids:
                continue
            processed_ids.add(comment['id'])
            
            elapsed = current_time - comment['creation_time']
            comment['x'] -= comment['speed'] * (8 / 1000.0)
            if comment['x'] < -comment['width']:
                to_remove.append(comment['id'])
        
        # 削除と row_usage の同期
        for comment_id in to_remove:
            self.comments = [c for c in self.comments if c['id'] != comment_id]
            # row_usage から削除
            for row, comment in list(self.row_usage.items()):
                if comment['id'] == comment_id:
                    del self.row_usage[row]
                    break
        
        self.update()

    def remove_oldest_comment(self):
        if not self.comments:
            return
        
        oldest_comment = min(self.comments, key=lambda c: c['creation_time'])
        logger.info(f"上限超過で削除: ID={oldest_comment['id']}, x={oldest_comment['x']:.1f}, text={oldest_comment['text']}")
        self.comments.remove(oldest_comment)
        if oldest_comment['row'] in self.row_usage:
            self.row_usage.pop(oldest_comment['row'])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        if not self.is_minimized:
            painter.setBrush(QBrush(QColor(50, 50, 50, 100)))
            painter.setPen(QPen(QColor(255, 255, 255, 50), 1))
            painter.drawRect(0, 0, self.width(), self.move_area_height)

            close_button_x = self.width() - self.close_button_size - self.button_margin
            close_button_y = self.button_margin
            if self.is_hovering_close:
                painter.setPen(QPen(QColor(230, 230, 230, 200), 2))
            else:
                painter.setPen(QPen(QColor(230, 230, 230, 150), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(
                close_button_x + 6, close_button_y + 6,
                close_button_x + self.close_button_size - 6, close_button_y + self.close_button_size - 6
            )
            painter.drawLine(
                close_button_x + self.close_button_size - 6, close_button_y + 6,
                close_button_x + 6, close_button_y + self.close_button_size - 6
            )

            minimize_button_x = self.width() - self.close_button_size - self.minimize_button_size - self.button_margin * 5
            minimize_button_y = self.button_margin
            if self.is_hovering_minimize:
                painter.setPen(QPen(QColor(230, 230, 230, 200), 2))
            else:
                painter.setPen(QPen(QColor(230, 230, 230, 150), 2))
            painter.drawLine(
                minimize_button_x + 6, minimize_button_y + self.minimize_button_size // 2,
                minimize_button_x + self.minimize_button_size - 6, minimize_button_y + self.minimize_button_size // 2
            )

            painter.setBrush(QBrush(QColor(0, 0, 0, 1)))
            painter.setPen(Qt.NoPen)
            painter.drawRect(0, 0, self.resize_border, self.height())
            painter.drawRect(self.width() - self.resize_border, 0, self.resize_border, self.height())
            painter.drawRect(0, 0, self.width(), self.resize_border)
            painter.drawRect(0, self.height() - self.resize_border, self.width(), self.resize_border)

            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(100, 100, 100, 150), 1))
            painter.drawRect(0, 0, 1, self.height())
            painter.drawRect(self.width() - 1, 0, 1, self.height())
            painter.drawRect(0, 0, self.width(), 1)
            painter.drawRect(0, self.height() - 1, self.width(), 1)

        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        painter.setFont(font)

        for comment in self.comments:
            if comment['x'] + comment['width'] < 0 or comment['x'] > self.width():
                continue

            if self.font_shadow > 0:
                painter.setPen(self.font_shadow_color)
                offset = self.font_shadow
                # 複数の方向に対応
                for direction in self.font_shadow_directions:
                    if direction == "bottom-right":
                        painter.drawText(int(comment['x']) + offset, int(comment['y']) + offset, comment['text'])
                    elif direction == "top-right":
                        painter.drawText(int(comment['x']) + offset, int(comment['y']) - offset, comment['text'])
                    elif direction == "bottom-left":
                        painter.drawText(int(comment['x']) - offset, int(comment['y']) + offset, comment['text'])
                    elif direction == "top-left":
                        painter.drawText(int(comment['x']) - offset, int(comment['y']) - offset, comment['text'])

            painter.setPen(self.font_color)
            painter.drawText(int(comment['x']), int(comment['y']), comment['text'])

    def update_settings(self, settings):
        self.font_size = settings.get("font_size", self.font_size)
        self.font_weight = settings.get("font_weight", self.font_weight)
        self.font_shadow = settings.get("font_shadow", self.font_shadow)
        self.font_color = QColor(settings.get("font_color", self.font_color.name()))
        self.font_family = settings.get("font_family", self.font_family)
        self.font_shadow_direction = settings.get("font_shadow_direction", self.font_shadow_direction)
        self.font_shadow_directions = settings.get("font_shadow_directions", ["bottom-right"])
        self.font_shadow_color = QColor(settings.get("font_shadow_color", self.font_shadow_color.name()))
        self.comment_speed = settings.get("comment_speed", self.comment_speed)
        self.display_position = settings.get("display_position", "top")
        self.max_comments = settings.get("max_comments", self.max_comments)
        self.hide_anchor_comments = settings.get("hide_anchor_comments", self.hide_anchor_comments)
        self.hide_url_comments = settings.get("hide_url_comments", self.hide_url_comments)
        self.spacing = settings.get("spacing", self.spacing)
        
        self.ng_ids = settings.get("ng_ids", [])
        self.ng_names = settings.get("ng_names", [])
        self.ng_texts = settings.get("ng_texts", [])
        logger.info(f"NG設定を更新: IDs={self.ng_ids}, Names={self.ng_names}, Texts={self.ng_texts}")

        opacity = settings.get("window_opacity", 0.8)
        self.setWindowOpacity(opacity)
        
        self.calculate_comment_rows()
        
        for comment in self.comments:
            total_distance = self.width() + comment['width']
            comment['speed'] = total_distance / self.comment_speed
        
        self.update()

if __name__ == "__main__":
    import time
    
    app = QApplication(sys.argv)
    app.setProperty("comment_time", time.time())
    
    window = CommentOverlayWindow()
    window.show()
    
    test_comments = [
        {"text": "これはテストコメントです"},
        {"text": "透過ウィンドウでコメントが流れます"},
        {"text": "コメント衝突回避アルゴリズムのテスト"},
        {"text": "パフォーマンス最適化されたレンダリング"},
        {"text": "長いコメントもしっかり表示されるかテストします。これは非常に長いコメントです。"},
    ]
    
    def add_test_comment():
        app.setProperty("comment_time", time.time())
        comment = test_comments[len(window.comments) % len(test_comments)]
        window.add_comment(comment)
        if len(window.comments) < 20:
            QTimer.singleShot(1000, add_test_comment)
    
    QTimer.singleShot(1000, add_test_comment)
    
    sys.exit(app.exec_())