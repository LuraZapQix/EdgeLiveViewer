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
                # 修正: 'momentum'キーは既に数値なので、int()変換は不要
                threads.sort(key=lambda x: x.get('momentum', 0), reverse=True)
                logger.info("勢い順にソートしました")
            elif self.sort_by == "date":
                threads.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
                logger.info("新着順にソートしました")
            self.threads_fetched.emit(threads)
            logger.info("スレッド一覧を送信しました")
        except Exception as e:
            logger.error(f"スレッド一覧の取得に失敗しました: {str(e)}")
            self.error_occurred.emit(f"スレッド一覧の取得に失敗しました: {str(e)}")
    
    # 削除: このメソッドは不要になりました
    # def fetch_dat(self, thread_id):
    #     ...

    def fetch_threads(self):
        subject_url = f"{self.base_url}/subject.txt"
        subject_response = requests.get(subject_url, timeout=5) # タイムアウトを少し延長
        subject_response.raise_for_status()
        
        subject_lines = subject_response.text.splitlines()
        threads = []
        
        current_timestamp = time.time()

        for line in subject_lines:
            if not line:
                continue
            try:
                thread_id_dat, title_res = line.split("<>", 1)
                thread_id = thread_id_dat.replace(".dat", "")
                
                title_res_match = re.search(r'(.*)\s*\((\d+)\)$', title_res)
                if not title_res_match:
                    continue
                
                title = html.unescape(title_res_match.group(1).strip())
                res_count_str = title_res_match.group(2)
                res_count = int(res_count_str)
                
                # --- ここからが修正箇所 ---
                
                # 1. スレッドIDをUNIXタイムスタンプとして直接利用
                timestamp = int(thread_id)
                
                # 2. タイムスタンプから表示用の日付文字列を生成
                dt_object = datetime.fromtimestamp(timestamp)
                date_str = dt_object.strftime('%Y/%m/%d %H:%M:%S')
                
                # 3. 勢いを計算
                time_diff = current_timestamp - timestamp
                momentum = 0
                if time_diff > 0:
                    momentum = int(res_count / time_diff * 86400)

                threads.append({
                    'id': thread_id,
                    'title': title,
                    'res_count': res_count_str,
                    'timestamp': timestamp,
                    'date': date_str,
                    # 修正: 勢いは数値で保持し、表示時にカンマ区切りにする
                    'momentum': momentum
                })
                # --- 修正ここまで ---

            except Exception as e:
                logger.warning(f"subject.txt の解析に失敗しました: {str(e)} - Line: {line}")
                continue
        
        logger.info(f"subject.txt から取得したスレッド数: {len(threads)}")
        
        # 削除: ThreadPoolExecutorを使った個別datファイルの取得処理はすべて不要
        # with ThreadPoolExecutor(max_workers=200) as executor:
        #     ...
        
        return threads
    
    def stop(self):
        logger.info("ThreadFetcher の停止をリクエスト")
        self.running = False
        
from datetime import datetime
import time
import re

class CommentFetcher(QThread):
    comments_fetched = pyqtSignal(list)
    all_comments_fetched = pyqtSignal(list)  # 新しいシグナルを追加
    thread_filled = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    thread_over_1000 = pyqtSignal(str)
    playback_finished = pyqtSignal()  # 新しいシグナルを追加
    
    def __init__(self, thread_id, thread_title="", update_interval=0.5, is_past_thread=False, playback_speed=1.0, comment_delay=0, start_number=None, parent=None):
        super().__init__(parent)
        self.thread_id = thread_id
        self.thread_title = thread_title
        self.update_interval = update_interval
        self.is_past_thread = is_past_thread
        self.playback_speed = max(1.0, min(2.0, playback_speed))
        self.comment_delay = comment_delay  # 修正: 引数として追加し、正しく代入
        self.start_number = start_number  # 開始位置を追加
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
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                
                lines = response.text.split('\n')
                new_comments = []
                
                # 全コメントをパース
                for i in range(len(lines)):
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
                        
                        comment = {
                            'number': i + 1,
                            'name': name,
                            'date': date,
                            'id': user_id,
                            'text': text,
                            'timestamp': self.parse_datetime(date)
                        }
                        new_comments.append(comment)
                
                # 過去ログの場合
                if self.is_past_thread and self.is_first_fetch:
                    # 全コメントを即座に送信（スレッド詳細画面用）
                    self.all_comments_fetched.emit(new_comments)
                    
                    # 再生開始位置を決定
                    start_index = max(0, (self.start_number - 1) if self.start_number else 0)
                    playback_comments = new_comments[start_index:]  # start_number以降のコメント
                    
                    # 時間差再生
                    if playback_comments:
                        base_time = playback_comments[0]['timestamp']
                        if not base_time:
                            self.comments_fetched.emit(playback_comments)
                        else:
                            prev_time = base_time
                            for comment in playback_comments:
                                if not self.running:
                                    break
                                time_diff = (comment['timestamp'] - prev_time).total_seconds()
                                if time_diff > 0:
                                    self.safe_sleep(time_diff)
                                if self.running:
                                    self.comments_fetched.emit([comment])
                                    prev_time = comment['timestamp']
                    
                    # 再生終了後にシグナルを発行してループを終了
                    self.playback_finished.emit()
                    break  # 過去ログ再生後はループを抜ける
                
                else:
                    # リアルタイムモードまたは2回目以降
                    start_index = self.last_res_index + 1 if not self.is_first_fetch else max(0, len(lines) - 5)
                    batch_comments = [c for c in new_comments if c['number'] > start_index]
                    if batch_comments:
                        # 遅延処理を削除し、取得後すぐに通知する
                        self.comments_fetched.emit(batch_comments)
                        self.last_res_index = batch_comments[-1]['number'] - 1
                
                retry_count = 0
                if self.is_first_fetch:
                    self.is_first_fetch = False
                
                # 1000レス到達チェック
                if len(lines) >= 1000 and not self.is_past_thread:
                    self.thread_filled.emit(self.thread_id, self.thread_title)
                    self.thread_over_1000.emit(f"スレッド： {self.thread_title} が1000レスに到達しました。")
                    break
                
                self.safe_sleep(self.update_interval)
                
            except requests.exceptions.RequestException as e:
                retry_count += 1
                logger.warning(f"コメント取得失敗 ({retry_count}/{self.max_retries}): {str(e)}")
                if retry_count >= self.max_retries:
                    self.error_occurred.emit(f"コメントの取得に繰り返し失敗しました: {str(e)}")
                    break
                self.safe_sleep(self.retry_delay)
            except Exception as e:
                self.error_occurred.emit(f"コメントの取得に失敗しました: {str(e)}")
                self.safe_sleep(self.update_interval)
    
    def stop(self):
        self.running = False
        logger.info(f"CommentFetcher {self.thread_id} の停止をリクエスト")
        if not self.wait(5000):  # 5秒待機
            logger.warning(f"CommentFetcher {self.thread_id} がタイムアウトしました。強制終了を試みます")
            self.terminate()
            self.wait(1000)
            if not self.isFinished():
                logger.error(f"CommentFetcher {self.thread_id} の終了に失敗")
            else:
                logger.info(f"CommentFetcher {self.thread_id} を強制終了しました")
        else:
            logger.info(f"CommentFetcher {self.thread_id} を正常に停止しました")


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
        """次スレを検索するロジック（●→通常ルール→反省会ルールの順で検索）"""
        try:
            url = "https://bbs.eddibb.cc/liveedge/subject.txt"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            lines = response.text.splitlines()
            
            starts_with_mark = self.thread_title.startswith('●')
            logger.info(f"現在のスレッド: {self.thread_title}, 前スレが「●」で始まるか: {starts_with_mark}")
            
            # ★★★ 変更点1: 最初にすべての候補をレス数付きでリストアップする ★★★
            all_candidates = []
            for line in lines:
                if not line: continue
                try:
                    thread_id_dat, title_res = line.split("<>", 1)
                    
                    title_res_match = re.search(r'(.*)\s*\((\d+)\)$', title_res)
                    if not title_res_match: continue
                    
                    thread_id = thread_id_dat.replace(".dat", "")
                    title = html.unescape(title_res_match.group(1).strip())
                    res_count = int(title_res_match.group(2))
                    
                    if thread_id == self.thread_id: continue

                    # 1000レス未満の候補のみをリストに追加する
                    if res_count < 1000:
                        all_candidates.append({
                            "id": thread_id,
                            "title": title,
                            "res_count": res_count
                        })
                except Exception as e:
                    logger.warning(f"subject.txtの行解析エラー: {line}, {e}")

            if not all_candidates:
                logger.info("1000レス未満の次スレ候補が見つかりませんでした")
                return None
            logger.info(f"次スレ候補を{len(all_candidates)}件に絞り込みました（1000レス未満のスレッドのみ）")

            # --- ここから下のロジックは、絞り込まれた `all_candidates` に対して実行 ---
            
            if starts_with_mark:
                # ●ルール: 絞り込まれた候補の中で、最もID(時刻)が新しいものを選択
                mark_candidates = [c for c in all_candidates if c['title'].startswith('●')]
                if mark_candidates:
                    best_candidate = max(mark_candidates, key=lambda c: int(c['id']))
                    logger.info(f"次スレを発見しました（●ルール）: {best_candidate['title']} (ID: {best_candidate['id']})")
                    return best_candidate # 辞書のキーを合わせて返す
            
            # 通常ルール
            else:
                # ★★★ 変更点2: 候補リストに類似度や番号情報を追加していく ★★★
                candidates_with_info = []
                for candidate in all_candidates:
                    similarity = difflib.SequenceMatcher(None, self.thread_title, candidate['title']).ratio()
                    if similarity >= 0.3:
                        next_number, _ = self.extract_last_number(candidate['title'])
                        candidate['similarity'] = similarity
                        candidate['number'] = next_number
                        candidate['is_star'] = bool(re.search(r'★(\d+)$', candidate['title']))
                        candidates_with_info.append(candidate)
                
                current_number, has_number = self.extract_last_number(self.thread_title)
                
                if has_number:
                    LOWER_BOUND_OFFSET = 2
                    UPPER_BOUND_OFFSET = 3
                    start_num = max(1, int(current_number) - LOWER_BOUND_OFFSET)
                    end_num = int(current_number) + UPPER_BOUND_OFFSET
                    expected_numbers = list(range(start_num, end_num + 1))
                else:
                    expected_numbers = [1, 2]

                valid_candidates = []
                for candidate in candidates_with_info:
                    next_num = candidate["number"]
                    if next_num in expected_numbers or \
                       (candidate["is_star"] and next_num in [1, 2]) or \
                       (not has_number and next_num == 2 and re.search(r'(★2|Part\.2|Part2)', candidate["title"])):
                        valid_candidates.append(candidate)
                
                if valid_candidates:
                    best_candidate = max(valid_candidates, key=lambda c: c["similarity"])
                    logger.info(f"次スレを発見しました（通常ルール）: {best_candidate['title']} (ID: {best_candidate['id']}, 類似度: {best_candidate['similarity']:.2f})")
                    return {"id": best_candidate["id"], "title": best_candidate["title"]}

            # 反省会ルール (フォールバック)
            logger.info("通常の次スレが見つからなかったため、『反省会』スレッドのフォールバック検索を実行します。")
            
            reflection_candidates = []
            # all_candidatesではなく、情報が付与されたcandidates_with_infoを使う
            for candidate in candidates_with_info: 
                if "反省会" in candidate["title"]:
                    if candidate.get("similarity", 0) >= 0.6: # 類似度情報がなければ0として扱う
                        reflection_candidates.append(candidate)
                        logger.debug(f"反省会候補: {candidate['title']} (類似度: {candidate.get('similarity', 0):.2f})")

            if reflection_candidates:
                best_reflection_candidate = max(reflection_candidates, key=lambda c: c.get('similarity', 0))
                logger.info(f"次スレを発見しました（反省会ルール）: {best_reflection_candidate['title']}")
                return {
                    "id": best_reflection_candidate["id"],
                    "title": best_reflection_candidate["title"]
                }
            
            logger.info("すべての検索ルールで次スレを見つけることができませんでした。")
            return None
        
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
        logger.info(f"NextThreadFinder {self.thread_id} の停止をリクエスト")
        self.running = False

# ### 機能追加: 本流スレッドを監視する MainstreamWatcher クラスを追加 ###
class MainstreamWatcher(QThread):
    """次スレ接続後、さらに勢いの高い本流スレッドがないか監視するクラス"""
    mainstream_thread_found = pyqtSignal(dict)
    search_finished = pyqtSignal()

    # ### 修正箇所: grace_period (猶予期間) をコンストラクタに追加 ###
    def __init__(self, original_title, original_thread_id, current_thread_id, 
                 watch_duration=60, momentum_ratio=1.5, min_res=10, 
                 grace_period=15, parent=None):
        super().__init__(parent)
        self.original_title = original_title
        self.original_thread_id = original_thread_id
        self.current_thread_id = current_thread_id
        self.watch_duration = watch_duration
        self.momentum_ratio = momentum_ratio
        self.min_res = min_res
        self.grace_period = grace_period # 猶予期間をプロパティとして保持
        self.running = True
        self.base_url = "https://bbs.eddibb.cc/liveedge"

    def run(self):
        start_time = time.time()
        # ### 修正箇所: ログメッセージを分かりやすく ###
        logger.info(f"本流スレッドの監視を開始します。{self.grace_period}秒後に比較を開始し、その後{self.watch_duration}秒間監視します。")

        # ### 修正箇所: 監視ループの条件を変更 ###
        # ループ全体の時間は「猶予期間＋監視時間」になる
        total_watch_time = self.grace_period + self.watch_duration
        
        while self.running and (time.time() - start_time) < total_watch_time:
            try:
                # ### 猶予期間（Grace Period）のロジック ###
                elapsed_time = time.time() - start_time
                if elapsed_time < self.grace_period:
                    logger.info(f"監視開始まで待機中... 残り約{self.grace_period - elapsed_time:.0f}秒")
                    time.sleep(5)  # 5秒待機して次のチェックへ
                    continue # ループの先頭に戻る

                # --- ここから下は猶予期間が終了した後の処理 ---
                logger.info(f"勢いの比較を開始しました。監視終了まで残り約{total_watch_time - elapsed_time:.0f}秒")
                
                # 1. subject.txt から全スレッドの基本情報を取得
                all_threads = self.fetch_threads_basic_info()
                if not all_threads or not self.running: break

                # 2. 現在接続中のスレッド情報を取得
                current_thread = next((t for t in all_threads if t['id'] == self.current_thread_id), None)
                if not current_thread:
                    logger.warning(f"現在接続中のスレッド {self.current_thread_id} が一覧に見つかりません。監視を中止します。")
                    break
                
                # 3. 事前フィルタリングで候補を高速に絞り込む
                candidate_threads = self.filter_candidates(all_threads)

                # 4. 絞り込んだ候補と現在スレッドの勢いを計算
                threads_to_fetch_momentum = [current_thread] + candidate_threads
                self.calculate_momentum_for_list(threads_to_fetch_momentum)
                
                current_momentum = int(current_thread.get('momentum', '0').replace(',', ''))
                if current_momentum == 0: 
                    time.sleep(5)
                    continue

                # 5. 最終比較と判断
                for thread in candidate_threads:
                    if int(thread.get('momentum', '0').replace(',', '')) > current_momentum * self.momentum_ratio:
                        logger.info(f"本流スレッドを発見しました: {thread['title']} (勢い: {thread['momentum']})")
                        if self.running: self.mainstream_thread_found.emit(thread)
                        self.running = False
                        break
                
                if not self.running: break
            except Exception as e:
                logger.error(f"本流スレッド監視中にエラーが発生しました: {e}")

            time.sleep(5)

        logger.info("本流スレッドの監視を終了します。")
        if self.running: self.search_finished.emit()

    def fetch_threads_basic_info(self):
        """subject.txt のみからスレッド情報を取得する軽量メソッド"""
        try:
            subject_url = f"{self.base_url}/subject.txt"
            response = requests.get(subject_url, timeout=2)
            response.raise_for_status()
            threads = []
            for line in response.text.splitlines():
                if not line: continue
                try:
                    thread_id_dat, title_res = line.split("<>", 1)
                    title_res_match = re.search(r'(.*)\s*\((\d+)\)$', title_res)
                    if not title_res_match: continue
                    threads.append({
                        'id': thread_id_dat.replace(".dat", ""),
                        'title': html.unescape(title_res_match.group(1).strip()),
                        'res_count': title_res_match.group(2)
                    })
                except Exception: continue
            return threads
        except Exception:
            return []

    # ### 修正箇所3: filter_candidatesメソッドをNextThreadFinderのロジックで全面刷新 ###
    def filter_candidates(self, all_threads):
        """
        NextThreadFinderの判定ロジックを完全に模倣し、本流の可能性がある候補を絞り込む
        """
        # 1. ●ルールのチェック
        starts_with_mark = self.original_title.startswith('●')
        
        if starts_with_mark:
            logger.debug("本流監視: ●ルールを適用します")
            candidates = []
            for thread in all_threads:
                if thread['id'] == self.current_thread_id or thread['id'] == self.original_thread_id:
                    continue
                if thread['title'].startswith('●'):
                    candidates.append(thread)
            return candidates

        # 2. 通常ルールの適用
        # a. 期待される次スレの番号を計算
        current_number, has_number = self.extract_last_number(self.original_title)
        expected_numbers = []
        if not has_number:
            expected_numbers = [2]
        else:
            expected_numbers = [current_number + 1, current_number]
        
        logger.debug(f"本流監視: 元スレ='{self.original_title}', 期待される番号={expected_numbers}")

        # b. 候補の選別
        valid_candidates = []
        for thread in all_threads:
            # 基本的な除外条件
            if thread['id'] == self.current_thread_id: continue
            if thread['id'] == self.original_thread_id: continue
            if int(thread['res_count']) >= 1000: continue
            if int(thread['res_count']) < self.min_res: continue

            # タイトル類似度が低すぎるものは、番号チェックの前に除外
            similarity = difflib.SequenceMatcher(None, self.original_title, thread['title']).ratio()
            if similarity < 0.3:
                continue

            # 候補スレの番号が期待値と一致するかチェック
            next_num, _ = self.extract_last_number(thread['title'])
            is_star = bool(re.search(r'★(\d+)$', thread['title']))

            if next_num in expected_numbers:
                valid_candidates.append(thread)
            elif is_star and next_num in [1, 2]:
                valid_candidates.append(thread)
            elif not has_number and next_num == 2:
                if re.search(r'(★2|Part\.2|Part2)(?:\s+.*)?$', thread['title']):
                    valid_candidates.append(thread)
        
        if valid_candidates:
            logger.debug(f"本流監視: {len(valid_candidates)}件の候補を発見しました")
        
        return valid_candidates
        
    # ### 追加4: NextThreadFinderからロジックを移植 ###
    def extract_last_number(self, title):
        """タイトルから末尾に最も近いスレッド進行に関連する数字を抽出"""
        star_match = re.search(r'★(\d+)$', title)
        part_dot_match = re.search(r'Part\.(\d+)$', title)
        part_match = re.search(r'Part(\d+)$', title)
        
        if star_match:
            return float(star_match.group(1)), True
        elif part_dot_match:
            return float(part_dot_match.group(1)), True
        elif part_match:
            return float(part_match.group(1)), True
        
        number_match = re.findall(r'(\d*\.\d+|\d+)', title)
        if number_match:
            return float(number_match[-1]), True
        return 0, False

    def calculate_momentum_for_list(self, thread_list):
        """指定されたスレッドのリストに対してのみ、勢いを計算する"""
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_thread = {executor.submit(self.fetch_dat_timestamp, thread['id']): thread for thread in thread_list}
            for future in future_to_thread:
                if not self.running: break
                thread = future_to_thread[future]
                try:
                    timestamp = future.result()
                    momentum = "0"
                    if timestamp > 0:
                        time_diff = time.time() - timestamp
                        if time_diff > 0:
                            momentum = f"{int(float(thread['res_count']) / time_diff * 86400):,}"
                    thread['momentum'] = momentum
                except Exception:
                    thread['momentum'] = "0"

    def fetch_dat_timestamp(self, thread_id):
        try:
            dat_url = f"{self.base_url}/dat/{thread_id}.dat"
            response = requests.get(dat_url, timeout=0.5)
            response.raise_for_status()
            date_match = re.search(r'(\d{4}/\d{2}/\d{2}).*?(\d{2}:\d{2}:\d{2})', response.text.split('\n', 1)[0])
            if date_match:
                return datetime.strptime(f"{date_match.group(1)} {date_match.group(2)}", '%Y/%m/%d %H:%M:%S').timestamp()
            return 0
        except Exception:
            return 0
    
    def stop(self):
        logger.info(f"MainstreamWatcher {self.original_title} の停止をリクエスト")
        self.running = False
    
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