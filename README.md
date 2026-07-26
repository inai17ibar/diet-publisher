# Diet Publisher (旧 ChatGPT Diet App)

写真と食事内容から、ダイエット記録用の `PFC / カロリー`、投稿文、投稿用画像を作るWebアプリです。  
投稿用画像は、アップロードした代表写真に `日付 / Day数 / kcal / PFC` を重ねて生成します。

## 主な機能

- 食事テキストまたは食事写真からPFCとカロリーを推定
- 投稿用の代表写真を別アップロードし、記録用画像を生成
- 投稿文の生成
- 継続日数の表示
- 食事履歴、カレンダー、日別集計、グラフ表示

## 前提

- Python 3.11 以上
- OpenAI APIキー
- Docker Desktop は任意

## 環境変数

`.env.example` を `.env` にコピーして編集します。

### macOS / Linux

```bash
cp .env.example .env
```

### Windows PowerShell

```powershell
Copy-Item .env.example .env
```

### Windows Git Bash

```bash
cp .env.example .env
```

設定例:

```env
OPENAI_API_KEY=sk-your-openai-api-key
SECRET_KEY=your-secret-api-key
HOST=0.0.0.0
PORT=8000
IMAGES_DIR=./images
```

`OPENAI_API_KEY` が未設定でも画面表示はできますが、AI分析と投稿文生成は使えません。

## ローカル起動

### Docker

```bash
docker compose up --build
```

起動後:

```text
http://127.0.0.1:8000
```

Compose では以下を永続化します。

- `./images` -> `/app/images`
- `./data` -> `/data`

### Python 直接起動

#### macOS / Linux

```bash
python3 -m pip install -e .
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

#### Windows PowerShell

```powershell
python -m pip install -e .
$env:OPENAI_API_KEY="your-key"
$env:SECRET_KEY="your-secret"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

#### Windows Git Bash

```bash
cd /c/Users/<USER>/path/to/chatgpt-diet-app
python -m pip install -e .
export OPENAI_API_KEY="your-key"
export SECRET_KEY="your-secret"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Git Bash では `C:\...` 形式ではなく `/c/...` 形式のパスを使ってください。

## データ保存

- ローカル実行時:
  - 画像: `images/`
  - DB: `diet_app.db`
- `/data` が存在する環境:
  - DB: `/data/diet_app.db`
- `DATABASE_URL` が設定されている場合:
  - その値を優先

画像保存先とDB保存先は、起動したカレントディレクトリではなくプロジェクト基準で解決します。

## API

### ヘルスチェック

```http
GET /api/v1/health
```

### 現在または指定日のDay数

```http
GET /api/v1/meal/day-number
GET /api/v1/meal/day-number?date=2026-05-14
```

### 1日分の記録作成

```http
POST /api/v1/meal/post
Header: X-API-Key: your-secret-key
Content-Type: application/json
```

```json
{
  "date": "2026-05-15T00:00:00",
  "share_image_base64": "...",
  "meals": [
    {
      "meal_type": "lunch",
      "description": "サラダチキンとおにぎり",
      "image_base64": "..."
    }
  ]
}
```

- `share_image_base64`: 投稿用に編集する代表写真
- `meals[].image_base64`: 栄養推定用の食事写真

### ストーリー画像（Phase 1・半自動）

```http
GET /api/v1/story/image
GET /api/v1/story/image?date=2026-07-26
Header: X-API-Key: your-secret-key
```

diet-mcp（食事記録の本体サービス）から当日のサマリを取得し、Instagramストーリー用の1080x1920のJPEG画像を返す。日付省略時はJSTの今日。記録が1件もない日は404。

- 目標カロリー内ならグリーン、超過ならアンバーの配色に自動切替
- 内容: Day数・日付・合計カロリー・目標との差分バー・PFC内訳・食事リスト
- ストーリーの上下約250px（InstagramのUIと重なる領域）を避けたレイアウト

#### iOSショートカット「今日の記録画像」の作り方

1. 「URLの内容を取得」: `GET https://chatgpt-diet-app-production.up.railway.app/api/v1/story/image`、ヘッダーに `X-API-Key: <SECRET_KEY>` を追加
2. 「写真アルバムに保存」: 直前の「URLの内容」をそのまま保存
3. Instagramのストーリー作成画面で保存した画像を選んで投稿（ここだけ手動）

## デプロイ

現在の Railway 設定:

- Public URL: `https://chatgpt-diet-app-production.up.railway.app/`
- Private URL: `chatgpt-diet-app.railway.internal`
- デプロイ方式: GitHub連携で `main` ブランチ push 時に自動デプロイ
- 永続化: Railway Volume を `/data` にマウント
- DB保存先: `/data/diet_app.db`

### Railwayで必要な設定

| 変数名 | 説明 | 必須 |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI APIキー | yes |
| `SECRET_KEY` | API認証キー | yes |
| `HOST` | 通常は `0.0.0.0` | no |
| `PORT` | Railway 側で注入される値を利用 | no |
| `DATABASE_URL` | 外部DBを使う場合のみ | no |
| `IMAGES_DIR` | 画像保存先。Railwayでは `/data/images` 推奨 | no |
| `DIET_MCP_URL` | diet-mcpのURL。デフォルト `https://diet-mcp.fly.dev` | no |
| `DIET_MCP_API_KEY` | diet-mcpのAPIキー（ストーリー画像生成に必須） | yes |

### Railwayでの永続化

1. Railway ダッシュボードで対象サービスを開く
2. Volume を追加
3. Mount Path を `/data` にする
4. `IMAGES_DIR=/data/images` を設定する
5. 再デプロイする

### どちらのOSからでもデプロイするために

デプロイ操作自体はOSに依存しません。  
MacでもWindowsでも、同じGitHubリポジトリへ push すれば、接続済みのデプロイ先側で自動デプロイが走ります。

```bash
git push origin main
```

ローカル差異を減らすには、以下を推奨します。

- 本番確認は Docker でも一度行う
- `.env` は各環境で個別管理し、Gitに含めない
- Windows と macOS の両方で `python -m pytest -q` を通す
- Railway の不要変数は削除して、環境差分を減らす

## テスト

```bash
python -m pytest -q
```

## 補足

- このアプリは現在、Instagramへの自動投稿は行いません
- 目的は、ダイエット記録を続けるための画像・数値・投稿文の作成です
