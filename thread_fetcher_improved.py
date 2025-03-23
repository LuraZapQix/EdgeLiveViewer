#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import time
import logging
import html
from datetime import datetime
import requests
from concurrent.futures import ThreadPoolExecutor
from PyQt5.QtCore import QThread, pyqtSignal
import difflib  # 類似度計算のために追加

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ThreadFetcher')

class ThreadFetcher(QThread):
    threads_fetched = pyqtSignal(list)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, parent=None, sort_by="momentum"):
        super().__init__(parent)
        self.running = True
        self.sort_by = sort_by
        self.base_url = "https://bbs.eddibb.cc/liveedge"
        
    def run(self):
        try:
            logger.info(f"スレッド一覧の取得を開始します（ソート順: {self.sort_by}）")
            start_time = time.time()
            threads = self.fetch_threads()
            logger.info(f"取得したスレッド数: {len(threads)}, 所要時間: {time.time() - start_time:.2f}秒")
            if self.sort_by == "momentum":
                threads.sort(key=lambda x: int(x.get('momentum', '0').replace(',', '')), reverse=True)
                logger.info("勢い順にソートしました")
            elif self.sort_by == "date":
                threads.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                logger.info("新着順にソートしました")
            self.threads_fetched.emit(threads)
            logger.info("スレッド一覧を送信しました")
        except Exception as e:
            logger.error(f"スレッド一覧の取得に失敗しました: {str(e)}")
            self.error_occurred.emit(f"スレッド一覧の取得に失敗しました: {str(e)}")
    
    def fetch_dat(self, thread_id):
        """個別の .dat ファイルから作成日時を取得"""
        try:
            dat_url = f"{self.base_url}/dat/{thread_id}.dat"
            response = requests.get(dat_url, timeout=0.5)
            response.raise_for_status()
            first_line = response.text.split('\n')[0]
            date_match = re.search(r'(\d{4}/\d{2}/\d{2}).*?(\d{2}:\d{2}:\d{2})', first_line)
            
            timestamp = 0
            date_str = ""
            if date_match:
                date_str = f"{date_match.group(1)} {date_match.group(2)}"
                dt = datetime.strptime(date_str, '%Y/%m/%d %H:%M:%S')
                timestamp = dt.timestamp()
            return timestamp, date_str
        except Exception as e:
            logger.warning(f"スレッド {thread_id} のDAT取得に失敗: {str(e)}")
            return 0, ""
    
    def fetch_threads(self):
        subject_url = f"{self.base_url}/subject.txt"
        subject_response = requests.get(subject_url, timeout=0.5)
        subject_response.raise_for_status()
        
        subject_lines = subject_response.text.splitlines()
        threads = []
        
        for line in subject_lines:
            if not line:
                continue
            try:
                thread_id_dat, title_res = line.split("<>", 1)
                thread_id = thread_id_dat.replace(".dat", "")
                # 修正: 最後の括弧内の数字をレス数として扱うように正規表現を変更
                title_res_match = re.search(r'(.*)\s*\((\d+)\)$', title_res)
                if not title_res_match:
                    continue
                
                title = html.unescape(title_res_match.group(1).strip())  # HTMLエンティティをデコード
                res_count = title_res_match.group(2)
                
                threads.append({
                    'id': thread_id,
                    'title': title,
                    'res_count': res_count
                })
            except Exception as e:
                logger.warning(f"subject.txt の解析に失敗しました: {str(e)}")
                continue
        
        logger.info(f"subject.txt から取得したスレッド数: {len(threads)}")
        
        with ThreadPoolExecutor(max_workers=200) as executor:
            future_to_thread = {executor.submit(self.fetch_dat, thread['id']): thread for thread in threads}
            for future in future_to_thread:
                thread = future_to_thread[future]
                try:
                    timestamp, date_str = future.result()
                    thread['timestamp'] = timestamp
                    thread['date'] = date_str
                    
                    momentum = "0"
                    if timestamp > 0:
                        time_diff = time.time() - timestamp
                        if time_diff > 0:
                            momentum_value = int(float(thread['res_count']) / time_diff * 86400)
                            momentum = f"{momentum_value:,}"
                    thread['momentum'] = momentum
                except Exception as e:
                    logger.warning(f"スレッド {thread['id']} の処理に失敗: {str(e)}")
                    thread['timestamp'] = 0
                    thread['date'] = ""
                    thread['momentum'] = "0"
        
        return threads
    
    def stop(self):
        self.running = False
        self.wait()

from datetime import datetime
import time
import re

class CommentFetcher(QThread):
    comments_fetched = pyqtSignal(list)
    thread_filled = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    thread_over_1000 = pyqtSignal(str)
    
    def __init__(self, thread_id, thread_title="", update_interval=0.5, is_past_thread=False, playback_speed=1.0, comment_delay=0, parent=None):
        super().__init__(parent)
        self.thread_id = thread_id
        self.thread_title = thread_title
        self.update_interval = update_interval
        self.is_past_thread = is_past_thread
        self.playback_speed = max(1.0, min(2.0, playback_speed))
        self.comment_delay = comment_delay  # 修正: 引数として追加し、正しく代入
        self.running = True
        self.last_res_index = -1
        self.max_retries = 3
        self.retry_delay = 2
        self.is_first_fetch = True
        logger.info(f"CommentFetcher 初期化: thread_id={thread_id}, playback_speed={self.playback_speed}, comment_delay={self.comment_delay}")

    def parse_datetime(self, date_str):
        """投稿日時文字列をdatetimeオブジェクトに変換（日本語曜日対応）"""
        try:
            match = re.match(r'(\d{4}/\d{2}/\d{2}\(\S+\) \d{2}:\d{2}:\d{2}\.\d+)', date_str)
            if not match:
                logger.warning(f"日時形式が不正: {date_str}")
                return None
            date_part = match.group(1)
            base, millis = date_part.rsplit('.', 1)
            millis = millis.ljust(6, '0')
            normalized_date = re.sub(r'\(\S+\)', '', f"{base}.{millis}")
            return datetime.strptime(normalized_date, "%Y/%m/%d %H:%M:%S.%f")
        except ValueError as e:
            logger.warning(f"日時解析に失敗: {date_str}, エラー: {str(e)}")
            return None
    
    def safe_sleep(self, duration):
        """中断可能なスリープ"""
        # リアルタイムでは再生速度を適用しない
        adjusted_duration = duration / self.playback_speed if self.is_past_thread else duration
        elapsed = 0
        step = 0.1  # 100msごとにチェック
        while elapsed < adjusted_duration and self.running:
            time.sleep(min(step, adjusted_duration - elapsed))
            elapsed += step
    
    def run(self):
        retry_count = 0
        
        while self.running:
            try:
                url = f"https://bbs.eddibb.cc/liveedge/dat/{self.thread_id}.dat"
                response = requests.get(url)
                response.raise_for_status()
                
                lines = response.text.split('\n')
                new_comments = []
                
                if self.is_first_fetch:
                    if self.is_past_thread:
                        start_index = 0
                    elif len(lines) > 5:
                        start_index = max(0, len(lines) - 5)
                    else:
                        start_index = 0
                else:
                    start_index = self.last_res_index + 1
                
                for i in range(start_index, len(lines)):
                    line = lines[i]
                    if not line.strip():
                        continue
                    
                    parts = line.split('<>')
                    if len(parts) >= 4:
                        name = parts[0]
                        date_id = parts[2]
                        text = parts[3]
                        
                        id_match = re.search(r'ID:([^ ]+)', date_id)
                        user_id = id_match.group(1) if id_match else ""
                        
                        date_match = re.search(r'(\d{4}/\d{2}/\d{2}\(\S+\) \d{2}:\d{2}:\d{2}\.\d+)', date_id)
                        date = date_match.group(1) if date_match else date_id
                        
                        text = text.replace('<br>', ' ')
                        text = re.sub(r'<.*?>', '', text)
                        text = re.sub(r'!metadent:.*?$', '', text, flags=re.MULTILINE)
                        text = html.unescape(text)
                        
                        new_comments.append({
                            'number': i + 1,
                            'name': name,
                            'date': date,
                            'id': user_id,
                            'text': text,
                            'timestamp': self.parse_datetime(date)
                        })
                        self.last_res_index = i
                
                if new_comments:
                    if self.is_past_thread and self.is_first_fetch:
                        # 過去ログの処理
                        base_time = new_comments[0]['timestamp']
                        if not base_time:
                            self.comments_fetched.emit(new_comments)
                        else:
                            prev_time = base_time
                            for comment in new_comments:
                                if not self.running:
                                    break
                                time_diff = (comment['timestamp'] - prev_time).total_seconds()
                                if time_diff > 0:
                                    self.safe_sleep(time_diff)
                                if self.running:
                                    self.comments_fetched.emit([comment])
                                    prev_time = comment['timestamp']
                    else:
                        # リアルタイムの場合、遅延を適用
                        if self.comment_delay > 0:
                            logger.info(f"コメント送信を {self.comment_delay}秒 遅延させます")
                            self.safe_sleep(self.comment_delay)
                        logger.info(f"取得した新コメント数: {len(new_comments)}")
                        self.comments_fetched.emit(new_comments)
                    
                    retry_count = 0
                    if self.is_first_fetch:
                        self.is_first_fetch = False
                
                if len(lines) >= 1000 and not self.is_past_thread:
                    self.thread_filled.emit(self.thread_id, self.thread_title)
                    self.thread_over_1000.emit(f"スレッド： {self.thread_title} が1000レスに到達しました。")
                    break
                
                self.safe_sleep(self.update_interval)
                
            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count >= self.max_retries:
                    self.error_occurred.emit(f"コメントの取得に失敗しました: {str(e)}")
                    retry_count = 0
                self.safe_sleep(self.retry_delay)
            except Exception as e:
                self.error_occurred.emit(f"コメントの取得に失敗しました: {str(e)}")
                self.safe_sleep(self.update_interval)
    
    def stop(self):
        self.running = False
        self.wait()
        logger.info(f"CommentFetcher スレッド {self.thread_id} を停止しました")

class NextThreadFinder(QThread):
    next_thread_found = pyqtSignal(dict)
    search_finished = pyqtSignal(bool)
    
    def __init__(self, thread_id, thread_title, search_duration=180, parent=None):
        super().__init__(parent)
        self.thread_id = thread_id
        self.thread_title = thread_title
        self.search_duration = search_duration
        self.running = True
        
    def run(self):
        start_time = time.time()
        
        while self.running and (time.time() - start_time) < self.search_duration:
            try:
                next_thread = self.find_next_thread()
                if next_thread:
                    logger.info(f"次スレを発見しました: {next_thread['title']} (ID: {next_thread['id']})")
                    self.next_thread_found.emit(next_thread)
                    self.search_finished.emit(True)
                    return
                logger.info("次スレが見つからなかったため、3秒後に再試行します")
                time.sleep(3)
            except Exception as e:
                logger.error(f"次スレ検索中にエラーが発生しました: {str(e)}")
                time.sleep(3)  # エラー時も継続
        
        if self.running:
            logger.info(f"次スレが見つかりませんでした: {self.thread_title}")
            self.search_finished.emit(False)
    
    def find_next_thread(self):
        """次スレを検索するロジック（パターン１とパターン２の両方を考慮）"""
        try:
            url = "https://bbs.eddibb.cc/liveedge/subject.txt"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            lines = response.text.splitlines()
            
            # 現在のタイトルの数字を抽出
            current_number, has_number = self.extract_last_number(self.thread_title)
            logger.info(f"現在のスレッド: {self.thread_title}, 末尾の数字: {current_number if has_number else 'なし'}")
            
            # 候補スレッドを格納するリスト
            candidates = []
            
            for line in lines:
                if not line:
                    continue
                thread_id_dat, title_res = line.split("<>", 1)
                thread_id = thread_id_dat.replace(".dat", "")
                title = html.unescape(title_res.split(" (")[0])  # HTMLエンティティをデコード
                
                if thread_id == self.thread_id:
                    continue
                
                # タイトルの類似度を計算
                similarity = difflib.SequenceMatcher(None, self.thread_title, title).ratio()
                
                # 類似度が0.3以上の場合に候補として検討
                if similarity >= 0.3:
                    next_number, _ = self.extract_last_number(title)
                    candidates.append({
                        "id": thread_id,
                        "title": title,
                        "similarity": similarity,
                        "number": next_number,
                        "is_star": bool(re.search(r'★(\d+)$', title))  # ★付きかどうかを記録
                    })
            
            if not candidates:
                logger.info("類似度0.3以上のスレッドが見つかりませんでした")
                return None
            
            # 次スレの期待される数字を計算
            expected_numbers = []
            if not has_number:
                # 数字がない場合、次スレは「★2」「Part.2」「Part2」を想定
                expected_numbers = [2]
            else:
                # 数字がある場合、+1した値を想定
                expected_numbers = [current_number + 1]
                expected_numbers.append(current_number)  # 元の数字を保持
            
            # 候補から次スレを選択
            valid_candidates = []
            for candidate in candidates:
                next_num = candidate["number"]
                # パターン２: 数字が期待値に一致する場合
                if next_num in expected_numbers:
                    valid_candidates.append(candidate)
                # パターン１: 前スレに数字があっても「★1」「★2」を許容
                elif candidate["is_star"] and next_num in [1, 2]:
                    valid_candidates.append(candidate)
                # 前スレに数字がない場合、「★2」「Part.2」「Part2」を許容
                elif not has_number and next_num == 2:
                    if re.search(r'(★2|Part\.2|Part2)(?:\s+.*)?$', candidate["title"]):
                        valid_candidates.append(candidate)
            
            if not valid_candidates:
                logger.info(f"期待される数字 {expected_numbers} または次スレパターンに一致するスレッドが見つかりませんでした")
                return None
            
            # 最も類似度が高い候補を選択
            best_candidate = max(valid_candidates, key=lambda c: c["similarity"])
            logger.info(f"次スレを発見しました: {best_candidate['title']} (ID: {best_candidate['id']}, 類似度: {best_candidate['similarity']:.2f})")
            return {
                "id": best_candidate["id"],
                "title": best_candidate["title"]
            }
        
        except requests.RequestException as e:
            logger.error(f"subject.txt の取得に失敗しました: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"次スレ検索中にエラーが発生しました: {str(e)}")
            return None
    
    def extract_last_number(self, title):
        """タイトルから末尾に最も近いスレッド進行に関連する数字を抽出"""
        # 「★数字」「Part.数字」「Part数字」を優先的に検索
        star_match = re.search(r'★(\d+)$', title)
        part_dot_match = re.search(r'Part\.(\d+)$', title)
        part_match = re.search(r'Part(\d+)$', title)
        
        if star_match:
            return float(star_match.group(1)), True
        elif part_dot_match:
            return float(part_dot_match.group(1)), True
        elif part_match:
            return float(part_match.group(1)), True
        
        # 上記がない場合、最後の数字を返す
        number_match = re.findall(r'(\d*\.\d+|\d+)', title)
        if number_match:
            return float(number_match[-1]), True
        return 0, False  # 数字がない場合は0とFalseを返す
    
    def stop(self):
        self.running = False
        self.wait()
        logger.info(f"NextThreadFinder が停止しました（スレッドID: {self.thread_id}）")

if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    
    app = QApplication(sys.argv)
    window = QWidget()
    layout = QVBoxLayout()
    label = QLabel("スレッド一覧を取得中...")
    layout.addWidget(label)
    window.setLayout(layout)
    window.show()
    
    def on_threads_fetched(threads):
        text = "取得したスレッド一覧:\n"
        for thread in threads[:10]:
            text += f"{thread['title']} (ID: {thread['id']}, レス数: {thread['res_count']}, 勢い: {thread['momentum']})\n"
        label.setText(text)
    
    fetcher = ThreadFetcher()
    fetcher.threads_fetched.connect(on_threads_fetched)
    fetcher.start()
    
    sys.exit(app.exec_())