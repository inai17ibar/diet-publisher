# CLAUDE.md

このファイルは、エージェントがこのリポジトリを扱う際の補助メモです。

## プロジェクト概要

Diet Publisher（旧 ChatGPT Diet App）- ダイエット記録用のPFC計算、投稿文、投稿用画像を作るWebアプリ。
記録データの「発信係」（共有画像生成・SNS投稿）を担う位置づけ。

## 関連システム（重要）

日々の食事記録の本体は別リポジトリ `~/src/diet-mcp`（Fly.io: https://diet-mcp.fly.dev）。
ChatGPTコネクタ（MCP）で記録され、iOSショートカットがApple ヘルスケアへ同期する。
本アプリのRailway本番DBに日々の記録は入っていない（2026-07-26時点で0件）。
全体像は diet-mcp の README「周辺システムとの関係」を参照。

## 技術スタック

- バックエンド: FastAPI (Python 3.11+)
- フロントエンド: なし（2026-08-02にSPAを廃止。APIサーバーのみ）
- データベース: SQLite + SQLAlchemy async
- AI: OpenAI API

## よく使うコマンド

```bash
python -m pip install -e .
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m pytest -q
docker compose up --build
```

## プロジェクト構造

```text
app/
├── main.py
├── config.py
├── api/routes.py
├── models/
└── services/
    ├── day_counter.py
    ├── diet_mcp_client.py   # diet-mcpの読み取りAPI（日次 / 週次）
    ├── image_editor.py
    ├── instagram_story.py
    ├── meal_processor.py
    ├── meal_slots.py        # 朝/昼/夜の判定（3食そろった日だけ投稿する門番）
    ├── openai_service.py
    ├── story_image.py       # 日次のストーリー画像
    ├── weekly_image.py      # 週次振り返りの画像
    └── weekly_review.py     # 週次の採点（点数はAIでなくPythonで決定的に計算）
```

## 投稿まわりの前提（変更時に壊さないこと）

- 自動投稿は**冪等**。cronが1日に何度も叩く前提で、投稿済みは台帳（`story_post_logs` / `weekly_post_logs`）で判定する。回数はコスト都合で増減しうるので、回数に依存した実装にしないこと
- 日次の自動投稿は**3食そろった日だけ**、週次の自動投稿は**日曜の3食がそろった週だけ**（日曜まで記録が入ったことを週が締まった合図とみなす）。判定は `app/services/meal_slots.py` と `weekly_review.is_week_ready`。手動生成（`/story/next`・`/story/image`・`/story/weekly-image`）はこの制限を受けない
- 週次の点数は「基準点 + カロリーの増減 + タンパク質の加点」。カロリーは目標を下回れば加点・超えれば減点で、記録の有無は採点しない
- 認証情報が未設定でもcronを失敗させない（`not_configured` を200で返す）
- 点数・差分などの数値はPython側で計算し、AIには文章だけ書かせる

## デプロイ

- プラットフォーム: Railway
- Public URL: https://chatgpt-diet-app-production.up.railway.app/
- Private URL: chatgpt-diet-app.railway.internal
- デプロイ方式: `main` ブランチへの push で自動デプロイ
- 永続化: Railway Volume を `/data` にマウント
- DB保存先: `/data/diet_app.db`

## 環境変数

| 変数名 | 説明 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI APIキー |
| `SECRET_KEY` | API認証キー |
| `HOST` | サーバーホスト |
| `PORT` | サーバーポート |
| `DATABASE_URL` | 外部DBを使う場合のみ |
| `DIET_MCP_URL` | diet-mcpのURL（省略時 https://diet-mcp.fly.dev） |
| `DIET_MCP_API_KEY` | diet-mcpのAPIキー。`GET /api/v1/story/image`（ストーリー画像生成）に必須 |
| `INSTAGRAM_USER_ID` | ストーリー自動投稿（`POST /story/publish`）に必須 |
| `INSTAGRAM_ACCESS_TOKEN` | Instagram長期トークン（初回のみ。以降DBで自動refresh） |

## クロスプラットフォーム方針

- パスは `pathlib` で扱う
- ローカルDBと画像保存先はプロジェクト基準で解決する
- ローカル起動は `python -m uvicorn app.main:app ...` を基本にする
- OS固有の手順差分はREADMEへ明記する
