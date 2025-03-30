#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import random
import logging
import time
import re  # ここを追加
from PyQt5.QtWidgets import (QWidget, QApplication)
from PyQt5.QtCore import (Qt, QTimer, QRect, QPoint, QSize, QThread, pyqtSignal, QBuffer, QByteArray)
from PyQt5.QtGui import (QFont, QColor, QPainter, QFontMetrics, QPen, QBrush, QImage, QMovie)
import requests
from io import BytesIO
import threading
from queue import Queue, Empty

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', force=True)
logger = logging.getLogger('CommentOverlayWindow')

class ImageLoaderThread(QThread):
    """画像読み込み用のスレッド"""
    image_loaded = pyqtSignal(str, QImage, str)  # コメントIDを追加

    def __init__(self, url_queue):
        super().__init__()
        self.url_queue = url_queue
        self.running = True
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def run(self):
        while self.running:
            try:
                # キューからURLとコメントIDを取得
                url_data = self.url_queue.get(timeout=1)
                url, comment_id = url_data if isinstance(url_data, tuple) else (url_data, None)
                try:
                    logger.info(f"画像の読み込みを開始: {url}, comment_id={comment_id}")
                    
                    # リトライ処理の設定
                    max_retries = 3
                    retry_delay = 2  # 初期待機時間（秒）
                    
                    for attempt in range(max_retries):
                        try:
                            response = requests.get(url, headers=self.headers, timeout=5)
                            if response.status_code == 200:
                                image_data = BytesIO(response.content)
                                image = QImage()
                                if image.loadFromData(image_data.getvalue()):
                                    logger.info(f"画像の読み込み成功: {url}")
                                    self.image_loaded.emit(url, image, comment_id)  # コメントIDを送信
                                    break  # 成功したらループを抜ける
                                else:
                                    logger.error(f"画像データの読み込みに失敗: {url}")
                            elif response.status_code == 429:
                                if attempt < max_retries - 1:
                                    wait_time = retry_delay * (2 ** attempt)  # 指数バックオフ
                                    logger.warning(f"レート制限に引っかかりました。{wait_time}秒後にリトライします。(試行回数: {attempt + 1}/{max_retries})")
                                    time.sleep(wait_time)
                                    continue
                                else:
                                    logger.error(f"最大リトライ回数に達しました: {url}")
                            else:
                                logger.error(f"画像のダウンロードに失敗: HTTP {response.status_code}")
                                break
                        except requests.exceptions.RequestException as e:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (2 ** attempt)
                                logger.warning(f"リクエストエラー: {str(e)}。{wait_time}秒後にリトライします。")
                                time.sleep(wait_time)
                                continue
                            else:
                                logger.error(f"最大リトライ回数に達しました: {str(e)}")
                                break
                except Exception as e:
                    logger.error(f"画像の読み込みに失敗: {str(e)}")
            except Empty:
                continue  # キューが空の場合は次のループへ
            except Exception as e:
                logger.error(f"予期せぬエラー: {str(e)}")
                continue

    def stop(self):
        self.running = False

class CommentOverlayWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(0.8)
        self.setGeometry(100, 100, 600, 800)

        # デフォルト設定を初期化
        self.settings = {
            "font_size": 31,
            "font_weight": 75,
            "font_shadow": 2,
            "font_color": "#FFFFFF",
            "font_family": "MS PGothic",
            "font_shadow_directions": ["bottom-right"],
            "font_shadow_color": "#000000",
            "comment_speed": 6.0,
            "display_position": "top",
            "max_comments": 80,
            "window_opacity": 0.8,
            "spacing": 30,
            "ng_ids": [],
            "ng_names": [],
            "ng_texts": [],
            "hide_anchor_comments": False,
            "hide_url_comments": False,
            "display_images": True,
            "hide_image_urls": True  # 新しい設定項目（デフォルトで非表示）
        }

        self.comments = []
        self.max_comments = 80
        self.font_size = 31
        self.font_weight = 75
        self.font_shadow = 2
        self.font_color = QColor("#FFFFFF")
        self.font_family = "MS PGothic"
        self.font_shadow_directions = ["bottom-right"]
        self.font_shadow_color = QColor("#000000")
        self.comment_speed = 6.0
        self.display_position = "top"
        self.hide_anchor_comments = False
        self.hide_url_comments = False
        self.spacing = 30
        self.comment_queue = []
        self.comment_queue_max_size = 100  # キューサイズの制限を追加

        self.flow_timer = QTimer(self)
        self.flow_timer.timeout.connect(self.flow_comment)
        self.flow_timer.start(200)

        self.current_batch_size = 0
        self.current_update_interval = 1.0

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
        self.row_usage = {}
        self.my_comment_numbers = set()  # 自分のコメントの番号を保持

        self.images = {}  # 画像を保持する辞書
        self.image_positions = {}  # 画像の位置を保持する辞書
        self.movies = {}  # GIFアニメーションを保持する辞書
        self.max_images = 5  # 表示する最大画像数
        self.image_height = 300  # 画像の高さ
        self.image_spacing = 40  # 画像間の間隔を40pxに変更
        self.image_queue = []  # 画像をキューに入れるためのリスト
        self.image_queue_timer = QTimer(self)  # 画像キューを処理するためのタイマー
        self.image_queue_timer.timeout.connect(self.process_image_queue)
        self.image_queue_timer.start(100)  # 100ミリ秒ごとにキューをチェック

        self.image_cache = {}  # 画像のキャッシュを保持する辞書
        self.max_cache_size = 20  # キャッシュの最大サイズ
        self.image_loader_thread = None
        self.image_url_queue = Queue()
        self.pending_images = set()  # 読み込み中の画像URLを保持

        # 画像読み込みスレッドを開始
        self.start_image_loader()

    def add_my_comment(self, number, text):
        """自分のコメントを登録"""
        self.my_comment_numbers.add(number)
        logger.info(f"自分のコメントを登録: 番号={number}, テキスト={text}")
    
    def reset_my_comments(self):
        """スレッド切り替え時に自分のコメント番号をリセット"""
        self.my_comment_numbers.clear()
        logger.info("自分のコメント番号をリセットしました")

    def add_comment_batch(self, comments):
        """コメントバッチを追加し、流れを開始"""
        batch_size = len(comments)
        self.current_batch_size = batch_size
        app = QApplication.instance()
        main_window = app.property("main_window")
        if main_window:
            self.current_update_interval = main_window.settings.get("update_interval", 1.0)
        else:
            self.current_update_interval = 1.0

        # キューサイズを制限
        if len(self.comment_queue) + batch_size > self.comment_queue_max_size:
            excess = len(self.comment_queue) + batch_size - self.comment_queue_max_size
            self.comment_queue = self.comment_queue[excess:]
            logger.warning(f"コメントキューが上限 {self.comment_queue_max_size} を超えたため、古いコメントを削除しました")

        self.comment_queue.extend(comments)
        logger.debug(f"コメントをキューに追加: 数={batch_size}, キュー長={len(self.comment_queue)}")

        if self.flow_timer.isActive():
            self.flow_timer.stop()
        self.schedule_next_comment()

    def schedule_next_comment(self):
        """次のコメントをスケジュール"""
        if self.comment_queue:
            # 間隔を計算
            interval = self.calculate_flow_interval()
            QTimer.singleShot(interval, self.flow_comment)
            logger.debug(f"次のコメントを {interval}ms 後にスケジュール")

    def calculate_flow_interval(self):
        """コメント間の間隔を計算"""
        if self.current_batch_size == 0 or self.current_update_interval <= 0:
            return 200  # デフォルト

        # 1秒あたりのコメント数
        comments_per_sec = self.current_batch_size / self.current_update_interval
        # 基本間隔（ミリ秒）
        base_interval = int((self.current_update_interval * 1000) / self.current_batch_size)

        if comments_per_sec <= 2.0:
            # コメントが少ない場合、300～500msでランダム
            return random.randint(300, 500)
        else:
            # コメントが多い場合、ベース間隔に±20%の揺らぎ
            variance = int(base_interval * 0.2)
            lower_bound = max(50, base_interval - variance)
            upper_bound = min(500, base_interval + variance)
            # 範囲が逆転しないように調整
            start = min(lower_bound, upper_bound)
            end = max(lower_bound, upper_bound)
            logger.debug(f"Flow interval: base={base_interval}, variance={variance}, range=({start}, {end})")
            return random.randint(start, end)

    def adjust_flow_timer(self):
        """更新間隔とコメント数に基づいてflow_timer間隔を動的に調整"""
        if self.current_batch_size == 0 or self.current_update_interval <= 0:
            self.flow_timer.setInterval(200)  # デフォルト
            return

        # 1秒あたりのコメント数
        comments_per_sec = self.current_batch_size / self.current_update_interval

        # 基本間隔: 更新間隔内でバッチを消化
        interval = int((self.current_update_interval * 1000) / self.current_batch_size)

        # コメント数が少ない場合（1秒あたり2件以下）にランダム性を持たせる
        if comments_per_sec <= 2.0:
            interval = random.randint(300, 500)
        else:
            # 50ms～500msに制限
            interval = max(50, min(500, interval))

        self.flow_timer.setInterval(interval)
        logger.info(f"flow_timer間隔を調整: {interval}ms (update_interval={self.current_update_interval}s, batch_size={self.current_batch_size})")

    def flow_comment(self):
        if self.comment_queue:
            comment = self.comment_queue.pop(0)
            self.add_comment(comment)
            logger.debug(f"コメントを流す: text={comment['text']}, 残りキュー={len(self.comment_queue)}")
            # 次のコメントをスケジュール
            self.schedule_next_comment()
        else:
            logger.info("キューが空に。次のバッチを待機")

    def add_system_message(self, message, message_type="generic"):
        """システムメッセージをコメントとして追加（通常コメントと同じロジックで流す）"""
        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        font_metrics = QFontMetrics(font)
        
        text_width = font_metrics.width(message)
        row = self.find_available_row(text_width)  # 通常の行判定を使用
        
        line_height = font_metrics.height()
        if self.display_position == "top":
            y_position = self.move_area_height + row * self.row_height + line_height
        elif self.display_position == "bottom":
            y_position = self.height() - row * self.row_height - line_height
        
        y_position = max(line_height + self.move_area_height, min(y_position, self.height() - line_height))
        
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
            'row': row,
            'creation_time': QApplication.instance().property("comment_time") or 0,
            'speed': speed,
            'is_system': True  # システムメッセージフラグ
        }
        
        self.comments.append(comment_obj)
        self.row_usage[row] = comment_obj  # 通常コメントと同じく row_usage に登録
        logger.info(f"システムメッセージ追加: {message}, 種別: {message_type}, ID: {comment_id}, row: {row}, y: {y_position}")
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
        # GIFアニメーションを停止
        for movie in self.movies.values():
            movie.stop()
        self.stop_image_loader()
        self.image_queue_timer.stop()  # 画像キュー処理タイマーを停止
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

    def extract_image_url(self, text):
        """テキストから画像URLを抽出"""
        # 画像ファイルの拡張子パターン
        image_extensions = r'\.(jpg|jpeg|png|gif|webp)'
        
        # imgurのURLパターン
        imgur_pattern = r'https?://(?:i\.)?imgur\.com/([a-zA-Z0-9]+)(?:\.[a-zA-Z]+)?'
        imgur_matches = re.findall(imgur_pattern, text)
        if imgur_matches:
            # imgurのURLを構築（最大5枚まで）
            urls = []
            for image_id in imgur_matches[:5]:
                # 元のURLから拡張子を取得
                original_url = next((url for url in re.findall(r'https?://[^\s<>"]+', text) 
                                   if image_id in url), None)
                if original_url and re.search(image_extensions, original_url, re.IGNORECASE):
                    # 元の拡張子を使用
                    urls.append(original_url)
                else:
                    # 拡張子が見つからない場合は.jpgを使用
                    urls.append(f"https://i.imgur.com/{image_id}.jpg")
                logger.info(f"imgur URLを検出: {urls[-1]}")
            return urls
        
        # その他の画像URLパターン（完全なURLを取得）
        # URLのパターンを修正
        url_pattern = r'https?://[^\s<>"]+'
        urls = re.findall(url_pattern, text)
        
        # 各URLが画像URLかどうかをチェック（最大5枚まで）
        image_urls = []
        for url in urls:
            if re.search(image_extensions, url, re.IGNORECASE):
                image_urls.append(url)
                logger.info(f"画像URLを検出: {url}")
                if len(image_urls) >= 5:
                    break
        
        return image_urls if image_urls else None

    def start_image_loader(self):
        """画像読み込みスレッドを開始"""
        if not self.image_loader_thread:
            logger.info("画像読み込みスレッドを開始します")
            self.image_loader_thread = ImageLoaderThread(self.image_url_queue)
            self.image_loader_thread.image_loaded.connect(self.handle_loaded_image)
            self.image_loader_thread.start()
            logger.info("画像読み込みスレッドが開始されました")

    def stop_image_loader(self):
        """画像読み込みスレッドを停止"""
        if self.image_loader_thread:
            self.image_loader_thread.stop()
            self.image_loader_thread.wait()
            self.image_loader_thread = None

    def handle_loaded_image(self, url, image, comment_id):
        """読み込んだ画像を処理"""
        logger.info(f"画像の読み込み完了を検知: URL={url}")
        if url in self.pending_images:
            self.pending_images.remove(url)
            if image:
                logger.info(f"画像の処理を開始: URL={url}, サイズ={image.width()}x{image.height()}")
                
                # GIFファイルかどうかをチェック
                if url.lower().endswith('.gif'):
                    logger.debug(f"GIFファイルを検出: {url}")
                    # GIFアニメーションとして処理
                    try:
                        # URLから直接GIFデータを取得
                        response = requests.get(url, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        })
                        if response.status_code == 200:
                            # GIFデータをQBufferに設定
                            buffer = QBuffer()
                            buffer.setData(QByteArray(response.content))
                            buffer.open(QBuffer.ReadOnly)
                            
                            # GIFデータを直接QMovieに渡す
                            movie = QMovie()
                            movie.setDevice(buffer)
                            
                            # サイズ設定前の状態をログ
                            logger.debug(f"GIFサイズ設定前: width={movie.scaledSize().width()}, height={movie.scaledSize().height()}")
                            
                            movie.setScaledSize(QSize(
                                int(self.image_height * (image.width() / image.height())),
                                self.image_height
                            ))
                            logger.debug(f"GIFサイズ設定後: width={movie.scaledSize().width()}, height={movie.scaledSize().height()}")
                            
                            # アニメーション開始前にフレームを取得
                            if not movie.isValid():
                                logger.error(f"GIFアニメーションが無効: {url}")
                                return
                                
                            movie.start()
                            logger.debug(f"GIFアニメーション開始: {url}")
                            
                            # バッファをムービーのプロパティとして保持
                            movie.buffer = buffer
                            
                            # キャッシュに保存
                            self.image_cache[url] = movie
                            if len(self.image_cache) > self.max_cache_size:
                                oldest_url = next(iter(self.image_cache))
                                del self.image_cache[oldest_url]
                                logger.debug(f"キャッシュから古い画像を削除: {oldest_url}")

                            # 画像をキューに追加
                            image_id = f"img_{int(time.time()*1000)}_{len(self.images)}"
                            self.image_queue.append((image_id, movie, comment_id))
                            logger.info(f"GIFアニメーションをキューに追加: ID={image_id}, URL={url}")
                        else:
                            logger.error(f"GIFデータの取得に失敗: HTTP {response.status_code}")
                    except Exception as e:
                        logger.error(f"GIFアニメーションの処理中にエラー: {str(e)}")
                else:
                    scaled_width = int(self.image_height * (image.width() / image.height()))
                    scaled_image = image.scaled(scaled_width, self.image_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.image_cache[url] = scaled_image
                    if len(self.image_cache) > self.max_cache_size:
                        oldest_url = next(iter(self.image_cache))
                        del self.image_cache[oldest_url]
                    image_id = f"img_{int(time.time()*1000)}_{len(self.images)}"
                    self.image_queue.append((image_id, scaled_image, comment_id))
                    logger.info(f"画像をキューに追加: ID={image_id}, URL={url}")
            else:
                logger.error(f"画像の読み込みに失敗: URL={url}")
        else:
            logger.warning(f"待機中の画像リストにURLが見つかりません: {url}")

    def process_image_queue(self):
        """画像キューを処理し、重ならないように画像を表示"""
        if not self.image_queue:
            return

        window_width = self.width()
        logger.debug(f"画像キュー処理開始: キューサイズ={len(self.image_queue)}, ウィンドウ幅={window_width}")

        processed_ids = set()
        for image_data in self.image_queue[:]:
            if len(image_data) != 3:
                continue  # 古い形式のデータはスキップ
            image_id, image, comment_id = image_data
            if image_id in processed_ids or image_id in self.image_positions:
                continue
            processed_ids.add(image_id)

            if image:
                logger.debug(f"画像処理開始: ID={image_id}, comment_id={comment_id}, タイプ={type(image)}")
                if isinstance(image, QMovie):
                    scaled_width = image.scaledSize().width()
                    self.movies[image_id] = image
                else:
                    scaled_width = int(self.image_height * (image.width() / image.height()))
                    self.images[image_id] = image

                # 同一コメント内の前の画像の現在の位置を確認
                start_x = window_width
                min_gap = 100  # 画像間の最小間隔

                # self.image_positions から同一 comment_id の画像を取得
                prev_images = [pos for img_id, pos in self.image_positions.items() if pos.get('comment_id') == comment_id]
                if prev_images:
                    # 最も右にある画像を選択
                    prev_pos = max(prev_images, key=lambda p: p['x'] + p['width'])
                    prev_x = prev_pos['x']
                    prev_width = prev_pos['width']
                    logger.debug(f"前の画像検出: prev_x={prev_x}, prev_width={prev_width}, comment_id={comment_id}")
                    # 前の画像がまだ右端に近い場合、遅延を適用
                    if prev_x + prev_width + min_gap > window_width:
                        start_x = prev_x + prev_width + min_gap
                        logger.debug(f"次の画像の開始位置を調整: start_x={start_x}")
                        if start_x >= window_width:
                            logger.debug(f"画面外のため保留: start_x={start_x}")
                            continue  # 画面外なら次の周期まで保留

                # 画像の位置を設定
                self.image_positions[image_id] = {
                    'x': start_x,
                    'y': self.height() - self.image_height - 10,
                    'width': scaled_width,
                    'height': self.image_height,
                    'speed': (window_width + scaled_width) / self.comment_speed,
                    'comment_id': comment_id
                }
                logger.info(f"画像を表示: ID={image_id}, x={start_x}, comment_id={comment_id}")
                self.image_queue.remove(image_data)
                self.update()

        # 画像が多すぎる場合は古いものを削除
        while len(self.images) + len(self.movies) > self.max_images:
            oldest_id = min(self.images.keys() if self.images else self.movies.keys())
            if oldest_id in self.images:
                del self.images[oldest_id]
            if oldest_id in self.movies:
                self.movies[oldest_id].stop()
                del self.movies[oldest_id]
            if oldest_id in self.image_positions:
                del self.image_positions[oldest_id]
            logger.info(f"古い画像を削除: ID={oldest_id}")

    def load_image(self, url, comment_id=None):
        """URLから画像を読み込む（非同期）"""
        if url in self.image_cache:
            logger.info(f"キャッシュから画像を読み込み: {url}")
            image = self.image_cache[url]
            image_id = f"img_{int(time.time()*1000)}_{len(self.images)}"
            self.image_queue.append((image_id, image, comment_id))  # comment_idを追加
            logger.info(f"キャッシュから画像をキューに追加: ID={image_id}")
            return image

        if url in self.pending_images:
            return None

        self.pending_images.add(url)
        self.image_url_queue.put((url, comment_id))  # URLとcomment_idをタプルでキューに追加
        return None

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

        # 画像の位置を更新
        to_remove_images = []
        for image_id, pos in self.image_positions.items():
            pos['x'] -= pos['speed'] * (8 / 1000.0)
            if pos['x'] + pos['width'] < 0:
                to_remove_images.append(image_id)

        # 画面外に出た画像を削除
        for image_id in to_remove_images:
            if image_id in self.images:
                del self.images[image_id]
            if image_id in self.movies:
                self.movies[image_id].stop()
                del self.movies[image_id]
            if image_id in self.image_positions:
                del self.image_positions[image_id]
        
        self.update()

    def add_comment(self, comment):
        text = comment['text']
        name = comment['name']
        user_id = comment['id']
        
        # デバッグ: 現在の設定値を確認
        logger.debug(f"add_comment 開始 - display_images: {self.settings.get('display_images', True)}, hide_image_urls: {self.settings.get('hide_image_urls', True)}")

        # NGフィルタリング
        if user_id in self.ng_ids:
            logger.debug(f"NG IDでスキップ: {user_id}, コメント: {text}")
            return
        if any(ng_name in name for ng_name in self.ng_names):
            logger.debug(f"NG 名前でスキップ: {name}, コメント: {text}")
            return
        if any(ng_text in text for ng_text in self.ng_texts):
            logger.debug(f"NG 本文でスキップ: {text}")
            return
        
        # アンカーコメントの非表示
        if self.hide_anchor_comments and ">>" in text:
            logger.debug(f"アンカーコメントをスキップ: {text}")
            return
        
        # 画像URLを検出し、必要に応じて表示用テキストから削除
        display_text = text
        image_urls = self.extract_image_url(text)
        if image_urls and self.settings.get("hide_image_urls", True):
            logger.info(f"コメントから画像URLを検出: {len(image_urls)}枚")
            for url in image_urls:
                display_text = display_text.replace(url, "").strip()
            if display_text:
                display_text = f"[📷] {display_text}"  # 画像がある場合、先頭にアイコンを追加
            else:
                display_text = ""  # 空文字の場合はスキップ
        
        # URLコメントの非表示
        if self.hide_url_comments and "http" in display_text :
            logger.debug(f"URLコメントをスキップ: {display_text}")
            return

        # 画像の表示設定を確認
        if self.settings.get("display_images", True) and image_urls:
            self.comment_id_counter += 1
            comment_id = f"comment_{int(time.time()*1000)}_{self.comment_id_counter}"
            for image_url in image_urls:
                self.load_image(image_url, comment_id)
        else:
            if image_urls:
                logger.debug(f"画像表示が無効化されています: {text}")
        
        # display_text が空文字の場合、コメントを追加しない
        if not display_text:
            logger.debug(f"表示テキストが空のためコメントをスキップ: 元テキスト={text}")
            return

        # コメント数が上限を超えた場合、古いコメントを削除
        if len(self.comments) >= self.max_comments:
            self.remove_oldest_comment()
        
        # フォント設定とメトリクスの計算
        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        font_metrics = QFontMetrics(font)
        
        text_width = font_metrics.width(display_text)
        row = self.find_available_row(text_width)
        
        line_height = font_metrics.height()
        if self.display_position == "top":
            y_position = self.move_area_height + row * self.row_height + line_height
        elif self.display_position == "bottom":
            y_position = self.height() - row * self.row_height - line_height
        else:  # center の場合
            y_position = (self.height() - line_height) // 2 + row * self.row_height
        
        y_position = max(line_height + self.move_area_height, min(y_position, self.height() - line_height))
        
        # コメントオブジェクトの作成
        self.comment_id_counter += 1
        comment_id = f"comment_{int(time.time()*1000)}_{self.comment_id_counter}"
        total_distance = self.width() + text_width
        speed = total_distance / self.comment_speed
        comment_obj = {
            'id': comment_id,
            'text': display_text,
            'x': float(self.width()),
            'y': y_position,
            'width': text_width,
            'row': row,
            'creation_time': QApplication.instance().property("comment_time") or 0,
            'speed': speed,
            'number': comment.get('number', 0)
        }
        self.comments.append(comment_obj)
        self.row_usage[row] = comment_obj
        logger.info(f"コメント追加: 番号={comment_obj['number']}, テキスト={display_text}, 元テキスト={text}, ID={comment_id}")
        self.update()

    def update_settings(self, settings):
        self.settings = settings.copy()
        self.font_size = self.settings.get("font_size", self.font_size)
        self.font_weight = self.settings.get("font_weight", self.font_weight)
        self.font_shadow = self.settings.get("font_shadow", self.font_shadow)
        self.font_color = QColor(self.settings.get("font_color", self.font_color.name()))
        self.font_family = self.settings.get("font_family", self.font_family)
        self.font_shadow_directions = self.settings.get("font_shadow_directions", ["bottom-right"])
        self.font_shadow_color = QColor(self.settings.get("font_shadow_color", self.font_shadow_color.name()))
        self.comment_speed = self.settings.get("comment_speed", self.comment_speed)
        self.display_position = self.settings.get("display_position", "top")
        self.max_comments = self.settings.get("max_comments", self.max_comments)
        self.hide_anchor_comments = self.settings.get("hide_anchor_comments", self.hide_anchor_comments)
        self.hide_url_comments = self.settings.get("hide_url_comments", self.hide_url_comments)
        self.spacing = self.settings.get("spacing", self.spacing)
        self.ng_ids = self.settings.get("ng_ids", [])
        self.ng_names = self.settings.get("ng_names", [])
        self.ng_texts = self.settings.get("ng_texts", [])
        self.current_update_interval = self.settings.get("update_interval", 1.0)
        # hide_image_urls は self.settings に含まれるため追加処理不要
        
        opacity = self.settings.get("window_opacity", 0.8)
        self.setWindowOpacity(opacity)
        
        self.calculate_comment_rows()
        for comment in self.comments:
            total_distance = self.width() + comment['width']
            comment['speed'] = total_distance / self.comment_speed
        
        for image_id, pos in self.image_positions.items():
            total_distance = self.width() + pos['width']
            pos['speed'] = total_distance / self.comment_speed
        
        logger.debug(f"update_settings 実行後 - display_images: {self.settings.get('display_images', True)}, hide_image_urls: {self.settings.get('hide_image_urls', True)}")
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

        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        painter.setFont(font)
        font_metrics = QFontMetrics(font)

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

        # まず画像を描画
        logger.debug(f"画像描画開始: 通常画像={len(self.images)}, GIFアニメーション={len(self.movies)}")
        for image_id, image in self.images.items():
            if image_id in self.image_positions:
                pos = self.image_positions[image_id]
                if not image.isNull():
                    painter.drawImage(
                        int(pos['x']),
                        int(pos['y']),
                        image
                    )
                    logger.debug(f"通常画像を描画: ID={image_id}, x={pos['x']}, y={pos['y']}")

        # GIFアニメーションを描画
        for image_id, movie in self.movies.items():
            if image_id in self.image_positions:
                pos = self.image_positions[image_id]
                if movie.isValid():
                    current_image = movie.currentImage()
                    if not current_image.isNull():
                        painter.drawImage(
                            int(pos['x']),
                            int(pos['y']),
                            current_image
                        )
                        logger.debug(f"GIFアニメーションを描画: ID={image_id}, x={pos['x']}, y={pos['y']}")
                    else:
                        logger.warning(f"GIFアニメーションの現在フレームが無効: ID={image_id}")
                else:
                    logger.warning(f"GIFアニメーションが無効: ID={image_id}")

        # 次にコメントを描画
        font = QFont(self.font_family)
        font.setPointSize(self.font_size)
        font.setWeight(self.font_weight)
        painter.setFont(font)

        logger.debug(f"現在の自分のコメント番号: {self.my_comment_numbers}")
        for comment in self.comments:
            if comment['x'] + comment['width'] < 0 or comment['x'] > self.width():
                continue

            # システムメッセージか通常コメントかを判定
            is_system = comment.get('is_system', False)
            is_my_comment = False
            is_anchored_to_my_comment = False

            if not is_system and 'number' in comment:
                is_my_comment = comment['number'] in self.my_comment_numbers
                if not is_my_comment:
                    anchor_matches = re.findall(r'>>([0-9]+)', comment['text'])
                    for anchor in anchor_matches:
                        if int(anchor) in self.my_comment_numbers:
                            is_anchored_to_my_comment = True
                            break

            # 背景と枠線の設定
            if is_system:
                painter.setBrush(QBrush(QColor(255, 255, 0, 70)))
                painter.setPen(Qt.NoPen)
                logger.debug(f"システムメッセージ描画: {comment['text']}")
            elif is_my_comment:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 0, 255), 3))
                logger.debug(f"自分のコメント描画: 番号={comment['number']}, テキスト={comment['text']}")
            elif is_anchored_to_my_comment:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 0, 0, 255), 3))
                logger.debug(f"アンカー付きコメント描画: 番号={comment['number']}, テキスト={comment['text']}, アンカー={anchor_matches}")
            else:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(Qt.NoPen)

            if painter.brush() != Qt.NoBrush or painter.pen() != Qt.NoPen:
                painter.drawRect(int(comment['x']) - 5, int(comment['y']) - font_metrics.ascent() - 5,
                                comment['width'] + 10, font_metrics.height() + 10)

            # 影の描画
            if self.font_shadow > 0:
                painter.setPen(self.font_shadow_color)
                offset = self.font_shadow
                for direction in self.font_shadow_directions:
                    if direction == "bottom-right":
                        painter.drawText(int(comment['x']) + offset, int(comment['y']) + offset, comment['text'])
                    elif direction == "top-right":
                        painter.drawText(int(comment['x']) + offset, int(comment['y']) - offset, comment['text'])
                    elif direction == "bottom-left":
                        painter.drawText(int(comment['x']) - offset, int(comment['y']) + offset, comment['text'])
                    elif direction == "top-left":
                        painter.drawText(int(comment['x']) - offset, int(comment['y']) - offset, comment['text'])

            # テキスト描画
            painter.setPen(self.font_color)
            painter.drawText(int(comment['x']), int(comment['y']), comment['text'])

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