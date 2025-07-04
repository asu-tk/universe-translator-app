import streamlit as st
import os
import json
import tempfile
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import deepl

# ── ページ設定 ──
st.set_page_config(page_title="UniVerse — YouTube多言語翻訳アプリ", layout="wide")
st.title("UniVerse — YouTube多言語翻訳アプリ")

# ── OAuth & DeepL の設定 ──
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
# GitHub Secrets から読み出し
CLIENT_SECRET_JSON = st.secrets["CLIENT_SECRET_JSON"]
DEEPL_KEY          = st.secrets["DEEPL_API_KEY"]

# ── YouTube カテゴリ一覧（日本語名称: ID） ──
CATEGORY_MAP = {
    "エンターテイメント": "24",
    "ゲーム":               "20",
    "コメディ":           "23",
    "スポーツ":           "17",
    "ニュースと政治":     "25",
    "ハウツーとスタイル": "26",
    "ブログ":             "22",
    "ペットと動物":       "15",
    "映画とアニメ":       "1",
    "音楽":               "10",
    "科学と美術":         "28",
    "教育":               "27",
    "自動車と乗り物":     "2",
    "非営利団体と社会活動":"29",
    "旅行とイベント":     "19"
}

# ── ユーザー入力 ──
video_url     = st.text_input("📺 YouTube 動画 URL または ID")
category_name = st.selectbox("🎯 動画のカテゴリを選択", list(CATEGORY_MAP.keys()))
category_id   = CATEGORY_MAP[category_name]

if st.button("🚀 翻訳＆アップロード開始"):
    if not video_url:
        st.error("⚠️ まず動画 URL または ID を入力してください。")
        st.stop()

    # —————— 1) client_secret.json を一時ファイルに書き出し ——————
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
        fp.write(CLIENT_SECRET_JSON)
        secrets_path = fp.name

    # —————— 2) YouTube OAuth 認証 ——————
    try:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
        creds = flow.run_local_server(port=0)
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        st.error(f"🚫 Google 認証エラー：{e}")
        st.stop()

    # —————— 3) DeepL 認証 ——————
    try:
        translator = deepl.Translator(DEEPL_KEY)
    except Exception as e:
        st.error(f"🚫 DeepL 認証エラー：{e}")
        st.stop()

    # —————— 4) 元タイトル＆説明取得 ——————
    vid = video_url.split("v=")[-1] if "v=" in video_url else video_url.strip()
    resp = youtube.videos().list(part="snippet", id=vid).execute()
    if not resp.get("items"):
        st.error("⚠️ 動画が見つかりません。IDを確認してください。")
        st.stop()
    snippet = resp["items"][0]["snippet"]
    orig_title = snippet.get("title", "")
    orig_desc  = snippet.get("description", "")

    # —————— 5) 翻訳 ——————
    trans_title = translator.translate_text(orig_title, target_lang="JA").text
    trans_desc  = translator.translate_text(orig_desc,  target_lang="JA").text

    # —————— 6) 表示 ——————
    st.subheader("■ 元タイトル")
    st.write(orig_title)
    st.subheader("■ 翻訳後タイトル")
    st.write(trans_title)
    st.subheader("■ 翻訳後説明文")
    st.write(trans_desc)

    # —————— 7) YouTube 更新 ——————
    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": category_id,
                    "defaultLanguage": "ja"
                },
                "localizations": {
                    "ja": {"title": trans_title, "description": trans_desc}
                }
            }
        ).execute()
        st.success("✅ YouTube へのアップロードに成功しました！")
    except Exception as e:
        st.error(f"❌ アップロードエラー：{e}")
