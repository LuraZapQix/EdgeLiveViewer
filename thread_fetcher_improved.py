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
                title_res_match = re.search(r'(.*?)\s*\((\d+)\)', title_res)
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

class CommentFetcher(QThread):
    comments_fetched = pyqtSignal(list)
    thread_filled = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    
    def __init__(self, thread_id, thread_title="", update_interval=0.5, parent=None):
        super().__init__(parent)
        self.thread_id = thread_id
        self.thread_title = thread_title
        self.update_interval = update_interval
        self.running = True
        self.last_res_index = -1  # 最後に処理したインデックス（0始まり）
        self.max_retries = 3
        self.retry_delay = 2
        self.is_first_fetch = True
        
    def run(self):
        retry_count = 0
        
        while self.running:
            try:
                url = f"https://bbs.eddibb.cc/liveedge/dat/{self.thread_id}.dat"
                response = requests.get(url)
                response.raise_for_status()
                
                lines = response.text.split('\n')
                new_comments = []
                
                if self.is_first_fetch and len(lines) > 5:
                    start_index = max(0, len(lines) - 5)
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
                        
                        # デバッグ用に生データをログ出力
                        logger.debug(f"生コメントテキスト: {text}")
                        
                        # まず <br> をスペースに変換（タグ除去より前）
                        text = text.replace('<br>', ' ')
                        # その後に他のタグを除去
                        text = re.sub(r'<.*?>', '', text)
                        text = re.sub(r'!metadent:.*?$', '', text, flags=re.MULTILINE)
                        # HTMLエンティティをデコード
                        text = html.unescape(text)
                        
                        # 処理後テキストをログ出力
                        logger.debug(f"処理後コメントテキスト: {text}")
                        
                        new_comments.append({
                            'number': i + 1,
                            'name': name,
                            'date': date,
                            'id': user_id,
                            'text': text
                        })
                        self.last_res_index = i
                
                if new_comments:
                    logger.info(f"取得した新コメント数: {len(new_comments)}, 開始インデックス: {start_index}, 総コメント数: {len(lines)}")
                    self.comments_fetched.emit(new_comments)
                    retry_count = 0
                    if self.is_first_fetch:
                        self.is_first_fetch = False
                
                if len(lines) >= 1000:
                    logger.info(f"スレッド {self.thread_id} が1000レスに到達しました。次スレを探します。")
                    self.thread_filled.emit(self.thread_id, self.thread_title)
                    break
                
                time.sleep(self.update_interval)
                
            except requests.exceptions.RequestException as e:
                retry_count += 1
                logger.warning(f"コメントの取得に失敗しました（リトライ {retry_count}/{self.max_retries}）: {str(e)}")
                if retry_count >= self.max_retries:
                    self.error_occurred.emit(f"コメントの取得に失敗しました: {str(e)}")
                    retry_count = 0
                time.sleep(self.retry_delay)
                
            except Exception as e:
                logger.error(f"コメントの取得中に予期しないエラーが発生しました: {str(e)}")
                self.error_occurred.emit(f"コメントの取得に失敗しました: {str(e)}")
                time.sleep(self.update_interval)
    
    def stop(self):
        self.running = False
        self.wait()

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
            next_thread = self.find_next_thread()
            if next_thread:
                logger.info(f"次スレを発見しました: {next_thread['title']} (ID: {next_thread['id']})")
                self.next_thread_found.emit(next_thread)
                self.search_finished.emit(True)
                return
            logger.info("次スレが見つからなかったため、3秒後に再試行します")
            time.sleep(3)  # 3秒間隔で再検索
        
        if self.running:
            logger.info(f"次スレが見つかりませんでした: {self.thread_title}")
            self.search_finished.emit(False)
    
    def find_next_thread(self):
        """次スレを検索するロジック（Chmateの次スレ作成ロジックを参考）"""
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
                
                # 類似度が0.5以上の場合に候補として検討
                if similarity >= 0.5:
                    next_number, _ = self.extract_last_number(title)
                    candidates.append({
                        "id": thread_id,
                        "title": title,
                        "similarity": similarity,
                        "number": next_number
                    })
            
            if not candidates:
                logger.info("類似度0.5以上のスレッドが見つかりませんでした")
                return None
            
            # 次スレの期待される数字を計算
            expected_numbers = []
            if not has_number:
                # 数字がない場合、次スレは「★2」「Part.2」「Part2」を想定
                expected_numbers = [2]
            else:
                # 数字がある場合、+1した値と「元の数字 + ★2」を想定
                expected_numbers = [current_number + 1]
                # ユーザー修正パターン（例: 27 → 27 ★2）
                star_suffix_match = re.search(r'★(\d+)$', self.thread_title)
                if not star_suffix_match:
                    expected_numbers.append(current_number)  # 元の数字を保持して★2を後でチェック
            
            # 候補から次スレを選択
            valid_candidates = []
            for candidate in candidates:
                next_num = candidate["number"]
                if next_num in expected_numbers:
                    valid_candidates.append(candidate)
                elif not has_number and next_num == 2:
                    # 数字がない場合、★2, Part.2, Part2 を許容
                    if re.search(r'(★2|Part\.2|Part2)(?:\s+.*)?$', candidate["title"]):
                        valid_candidates.append(candidate)
                elif has_number and not star_suffix_match:
                    # ユーザー修正パターン: 元の数字 + ★2
                    star_match = re.search(r'★(\d+)$', candidate["title"])
                    if star_match and int(star_match.group(1)) == 2 and re.search(str(current_number), candidate["title"]):
                        valid_candidates.append(candidate)
            
            if not valid_candidates:
                logger.info(f"期待される数字 {expected_numbers} に一致するスレッドが見つかりませんでした")
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
        """タイトルから末尾に最も近い数字を抽出"""
        # 末尾に近い整数または小数を検索
        number_match = re.findall(r'(\d*\.\d+|\d+)', title)
        if number_match:
            # 最後の数字を取得し、浮動小数点数として変換
            last_number = float(number_match[-1])
            return last_number, True
        return 0, False  # 数字がない場合は0とFalseを返す
    
    def stop(self):
        self.running = False
        self.wait()

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