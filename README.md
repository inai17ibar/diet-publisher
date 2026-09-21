# Diet Publisher (旧 ChatGPT Diet App)

ダイエット記録の「発信係」APIサーバーです。食事記録の本体である diet-mcp からデータを取得し、ストーリー画像の生成とInstagramへの自動投稿を行います。

※ 以前あったWebフロントエンド（SPA）は2026-08-02に廃止し、APIサーバーのみの構成になりました。

## 主な機能

- ストーリー用サマリ画像の生成（Day数 / kcal / PFC目標比 / 食事タイムライン / AIコーチの一言）
- Instagramストーリーへの自動投稿（公式Graph API・1日6回のcronで状態駆動）
  - **3食（朝・昼・夜）そろった日だけ**を投稿する。朝だけ・朝昼だけの日は見送る
- 1週間の振り返り画像の生成と自動投稿（週のカロリー推移グラフ / 目標との差分 / 100点満点の採点 / 来週の改善ポイント）
- 食事テキストまたは食事写真からのPFC推定・投稿文生成（旧機能のAPI）

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
GET /api/v1/story/next                      # おすすめ: 未生成の直近日を自動選択
GET /api/v1/story/image?date=2026-07-26     # 明示指定（生成済みでも作り直す）
Header: X-API-Key: your-secret-key
```

diet-mcp（食事記録の本体サービス）からサマリを取得し、Instagramストーリー用の1080x1920のJPEG画像を返す。

- `/story/next`: 今日に食事記録があれば**常に最新データで今日の画像**を生成する（日中に記録が増えるため、何度実行しても今日を作り直す）。今日がまだ空の場合のみ、昨日が未生成なら昨日を生成する（作り忘れ救済。一昨日以前へはさかのぼらない）。どちらも無ければエラーではなく案内画像を返す（ショートカットが常に画像を保存できるように）。生成履歴はDBの台帳（`story_image_logs`）に記録
- `/story/image?date=`: 特定日を作り直したいとき用。生成台帳には記録される
- 目標カロリー内ならグリーン、超過ならアンバーの配色に自動切替
- 内容: Day数・日付・合計カロリー・目標との差分バー・PFC内訳・食事リスト
- ストーリーの上下約250px（InstagramのUIと重なる領域）を避けたレイアウト
- レスポンスヘッダー: `X-Story-Date`（対象日）、`X-Story-Status`（generated / none）

### ストーリー自動投稿（Phase 2）

```http
POST /api/v1/story/publish          # 今日の画像を生成してInstagramストーリーに投稿（冪等・1日1回）
POST /api/v1/instagram/token        # 長期アクセストークンの登録・手動更新
GET  /api/v1/public/story/{file}    # Graph APIが画像を取得する公開URL（認証なし・推測不能名）
```

- **3食そろった日だけ投稿する**。朝・昼・夜がすべて記録されていない日（朝だけ、朝昼だけ等）は見送り、レスポンスは `incomplete` になる。見送った日は台帳に残らないので、あとから残りの食事を記録すれば次のcronで投稿される
  - 食事区分は `tags`（"朝食" 等）を優先し、無ければ時刻から判定する（朝 04:00-10:59 / 昼 11:00-15:59 / 夜 16:00-03:59）。間食（`間食`/`おやつ` タグ）は3食に数えない
  - 手動生成の `/story/next`・`/story/image` はこの制限を受けない（自分で確認する用途のため）
- 投稿は**Instagram公式Graph API**（Instagram API with Instagram Login）を使用。非公式ライブラリは使わない
- 画像には**AIコーチの一言**が入る（gpt-4oが当日の実データから生成。過去の一言をプロンプトに渡し、毎日違う切り口になるようにしている）。一言は`/story/next`等の手動生成にも入る
- `.github/workflows/story-publish.yml` が **1日6回（7/10/13/16/19/22時 JST）** `/story/publish` を叩き、サーバー側が記録の状態を見て投稿すべき日を選ぶ: ①21時以降で今日に記録があれば今日を投稿 ②今日が未投稿でも、昨日に記録があり未投稿なら昨日を投稿（翌朝入力パターンの救済）。冪等なので何度呼んでも二重投稿しない。GitHub Secrets に `DIET_PUBLISHER_API_KEY`（= `SECRET_KEY`）が必要。認証情報が未設定の間は `not_configured` を返すだけでcronは失敗しない
- アクセストークンは投稿成功のたびに `refresh_access_token` で更新してDBに保存するため、**毎日投稿が動いている限り失効しない**（60日の期限切れ対策）

### 週次振り返り（Phase 3）

```http
GET  /api/v1/story/weekly-image?date=2026-09-10   # 週の振り返り画像（プレビュー・手動投稿用）
POST /api/v1/story/publish-weekly                 # 週の振り返りをストーリーに投稿（冪等・1週1回）
```

1週間（月曜〜日曜、diet-mcpの週の区切りに合わせる）の記録をまとめた1080x1920の画像を作る。内容:

- **カロリー推移グラフ**: 7日分の棒グラフ。目標超過の日はアンバー、記録の無い日は空バー。目標カロリーは点線で表示
- **目標との差分**: 1日平均カロリーと目標比（±kcal/日）、週合計と週の目標との差
- **100点満点の採点**: 基準35点 + カロリー（±35点）+ タンパク質（0〜30点）。S/A/B/C/Dのグレード付き
  - カロリーは**目標を下回った分が加点、超えた分が減点**。1日平均が目標の20%ぶん下回ると+35、目標ちょうどで±0、20%ぶん超過で−35（その先は頭打ち）。画像では中央から右（グリーン）が加点、左（アンバー）が減点
  - タンパク質は135g達成の日数に応じた加点のみ
  - 記録できたかどうかは採点しない（週が締まったかは投稿の門番で見るため）
  - 配点は `app/services/weekly_review.py` の `BASE_POINTS` / `CALORIE_SWING` / `CALORIE_FULL_SWING_RATIO` / `POINTS_PROTEIN` で調整できる
- **来週の改善ポイント**: gpt-4oが週の実データと採点結果から生成（点数や差分はPython側で決定的に計算し、AIには講評だけ書かせる）

投稿するのは**日曜の3食がそろった週だけ**。日曜まで記録が入ったことを「週が締まった」合図とみなす。そろうまでは `waiting_for_sunday` を返し、日曜に何の食事が足りないかも返す。待たされた週は台帳に残らないので、あとから日曜の記録を足せば次のcronで投稿される（途中の曜日が抜けていても、日曜さえそろえば投稿する）。

投稿タイミングは日次と同じく状態駆動で、`.github/workflows/story-publish.yml` の1日6回のcronに相乗りしている。今週・先週の順に見て、締まっていて未投稿の週があればそれを投稿する。週の途中は日曜がまだ空なので、この門番がフライング投稿も防いでいる。

`/story/weekly-image` はこの制限を受けないので、揃っていない週でも手元で確認できる（記録が1日も無い週だけ404）。

`GET /api/v1/story/weekly-image` は iOSショートカットからも使える（「記録画像を作る」と同じ手順で、URLだけ差し替える）。レスポンスヘッダーに `X-Week-Start` / `X-Week-End` / `X-Week-Score` が入る。

#### セットアップ（Meta側・初回のみ）

1. Instagramアカウントを**プロアカウント（クリエイター）**に切替（アプリの設定 → アカウントの種類とツール）
2. [developers.facebook.com](https://developers.facebook.com) でアプリを作成し、製品「**Instagram**」を追加（Instagram API with Instagram Login構成）
3. 「API setup with Instagram login」の手順で自分のアカウントを接続し、**長期アクセストークン**と**InstagramユーザーID**を取得
4. Railwayの環境変数に `INSTAGRAM_USER_ID` と `INSTAGRAM_ACCESS_TOKEN` を設定（トークンは後から `POST /api/v1/instagram/token` で差し替えも可能）

#### iOSショートカット「記録画像を作る」の作り方

1. 「テキスト」: `https://chatgpt-diet-app-production.up.railway.app/api/v1/story/next` を貼る
2. 「URLの内容を取得」: URLに上のテキスト変数を指定、方法 GET、ヘッダーに `X-API-Key: <SECRET_KEY>` を追加
3. 「写真アルバムに保存」: 直前の「URLの内容」をそのまま保存
4. Instagramのストーリー作成画面で保存した画像を選んで投稿（ここだけ手動）

食事を記録し終えたタイミング（夜）に実行すれば今日の分、翌日に実行すれば前日の分が自動で選ばれる。

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
| `INSTAGRAM_USER_ID` | InstagramのユーザーID（ストーリー自動投稿に必須） | no |
| `INSTAGRAM_ACCESS_TOKEN` | Instagramの長期アクセストークン（初回のみ。以降はDBで自動更新） | no |
| `PUBLIC_BASE_URL` | このアプリの公開URL。デフォルトはRailway本番URL | no |

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

- 日々の食事記録の本体は別リポジトリ `diet-mcp`。本アプリはそこから読み取って発信するだけで、記録の書き込みはしない
- 週次振り返りは diet-mcp の `GET /api/summary/week` を使う。**diet-mcp 側を先にデプロイしてから**本アプリをデプロイすること
