# エッヂ実況ビュアー

エッヂ掲示板のコメントをニコニコ動画風にリアルタイムで表示するツールです。スレッドのコメントを透過ウィンドウで流し、掲示板の実況を楽しく視聴できます。単一の実行ファイル（EXE）で動作します。

## 主な機能
- **リアルタイムコメント表示**: エッヂ掲示板のスレッドからコメントを取得し、画面上で流れるように表示。
- **スレッド選択**: スレッド一覧から「勢い順」「新着順」でソートして選択可能。URLやIDの直接入力も対応。
- **透過ウィンドウ**: コメントが流れるウィンドウはドラッグで移動、サイズ変更可能。透明度や位置をカスタマイズ可。
- **次スレ自動検出**: スレッドが1000レスに達すると、次のスレッドを自動検索して接続。
- **過去ログ再生**: 過去のスレッドを指定速度（1.0〜2.0倍速）で再生可能。
- **カスタマイズ**: フォント（サイズ、太さ、色、影）、コメント速度、最大表示数などを細かく設定。
- **NG機能**: 特定ID、名前、本文を非表示に設定可能。
- **軽量動作**: Pythonや依存ライブラリをインストールせずに単体で動作。

## 動作環境
- **Windows**: Windows 10/11（推奨）

## インストール
1. [Releasesページ](https://github.com/LuraZapQix/EdgeLiveViewer-Download/releases)から最新版をダウンロード。
   - Windows: `EdgeLiveViewer.exe`
   
2. ファイルを任意の場所に保存。
3. ダブルクリックで起動。

## 使い方
1. **起動**: `EdgeLiveViewer.exe`をダブルクリック。
2. **スレッド接続**:
   - 「スレッド一覧」タブでスレッドをダブルクリック。
   - または、「スレッドURL/ID」欄にURL（例: `https://bbs.eddibb.cc/test/read.cgi/liveedge/1742132339/`）かID（例: `1742132339`）を入力し「接続」をクリック。
3. **コメント表示**: 透過ウィンドウにコメントが流れ始めます。
   - ウィンドウはドラッグで移動、端を引っ張ってサイズ変更。
   - 透過ウィンドウの「-」ボタンで枠が消えます。
4. **設定変更**: 「設定」ボタンからフォントや表示速度などをカスタマイズ。
5. **終了**: メインウィンドウを閉じる。

## 設定のカスタマイズ例
- **フォント**: サイズ（12〜48pt）、太さ、影の有無、色を変更。
- **表示**: コメント速度（2〜15秒）、表示位置（上部/下部）、最大コメント数（10〜100）。
- **透明度**: ウィンドウの透明度を10〜100%で調整。
- **NGリスト**: 迷惑なIDやワードを非表示に。

## トラブルシューティング
- **コメントが流れない**: スレッドID/URLが正しいか、ネット接続を確認。
- **動作が重い**: 設定で最大コメント数を減らすか、影をオフにするか、更新間隔を長くするなど。

## 貢献
バグ報告や機能提案は[Issues](https://github.com/LuraZapQix/EdgeLiveViewer-Download/issues)へ。
