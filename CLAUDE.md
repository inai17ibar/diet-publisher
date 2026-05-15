# CLAUDE.md

このファイルは、エージェントがこのリポジトリを扱う際の補助メモです。

## プロジェクト概要

ChatGPT Diet App - ダイエット記録用のPFC計算、投稿文、投稿用画像を作るWebアプリ。

## 技術スタック

- バックエンド: FastAPI (Python 3.11+)
- フロントエンド: Vanilla JS + Chart.js
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
├── services/
│   ├── day_counter.py
│   ├── image_editor.py
│   ├── meal_processor.py
│   └── openai_service.py
└── static/index.html
```

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

## クロスプラットフォーム方針

- パスは `pathlib` で扱う
- ローカルDBと画像保存先はプロジェクト基準で解決する
- ローカル起動は `python -m uvicorn app.main:app ...` を基本にする
- OS固有の手順差分はREADMEへ明記する
