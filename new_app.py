import streamlit as st
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import deepl

# ── ページ設定 ──
st.set_page_config(page_title="UniVerse — YouTube多言語翻訳アプリ", layout="wide")
st.title("UniVerse — YouTube多言語翻訳アプリ")

# ── OAuth & DeepL の設定 ──
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# 1) Secrets から client_secret.json の中身（JSON文字列）を取り出し、
#    json.loads で dict に変換
client_config = json.loads(st.secrets["CLIENT_SECRET_JSON"])

# 2) DeepL APIキーはユーザーに入力してもらう
deepl_key = st.text_input("🔑 DeepL APIキー", type="password")

# ── YouTube カテゴリ一覧（日本語名称: ID） ──
CATEGORY_MAP = {
    "エンターテイメント": "24",
    "ゲーム":         "20",
    "コメディ":       "23",
    "スポーツ":       "17",
    "ニュースと政治": "25",
    "ハウツーとスタイル": "26",
    "ブログ":         "22",
    "ペットと動物":   "15",
    "映画とアニメ":   "1",
    "音楽":           "10",
    "科学と美術":     "28",
    "教育":           "27",
    "自動車と乗り物": "2",
    "非営利団体と社会活動": "29",
    "旅行とイベント": "19"
}

# ── ユーザー入力 ──
video_url     = st.text_input("📺 YouTube 動画 URL または ID")
category_name = st.selectbox("🎯 動画のカテゴリを選択", list(CATEGORY_MAP.keys()))
category_id   = CATEGORY_MAP[category_name]

if st.button("🚀 翻訳＆アップロード開始"):
    # 入力チェック
    if not video_url or not deepl_key:
        st.error("⚠️ 動画 URL と DeepL APIキー は必須です。")
        st.stop()

    # ———— Google OAuth ————
    try:
        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=SCOPES
        )
        creds   = flow.run_local_server(port=0)
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        st.error(f"🚫 Google 認証エラー：{e}")
        st.stop()

    # ———— DeepL 認証 ————
    try:
        translator = deepl.Translator(deepl_key)
    except Exception as e:
        st.error(f"🚫 DeepL 認証エラー：{e}")
        st.stop()

    # ———— 元のタイトル＆説明取得 ————
    vid  = video_url.split("v=")[-1].strip()
    resp = youtube.videos().list(part="snippet", id=vid).execute()
    if not resp.get("items"):
        st.error("⚠️ 動画が見つかりません。IDを確認してください。")
        st.stop()
    snippet    = resp["items"][0]["snippet"]
    orig_title = snippet.get("title", "")
    orig_desc  = snippet.get("description", "")

    # ———— 翻訳 ————
    trans_title = translator.translate_text(orig_title, target_lang="JA").text
    trans_desc  = translator.translate_text(orig_desc,  target_lang="JA").text

    # ———— 結果表示 ————
    st.subheader("■ 元タイトル")
    st.write(orig_title)
    st.subheader("■ 翻訳後タイトル")
    st.write(trans_title)
    st.subheader("■ 翻訳後説明文")
    st.write(trans_desc)

    # ———— YouTube アップロード ————
    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": vid,
                "snippet": {
                    "title":            orig_title,
                    "description":      orig_desc,
                    "categoryId":       category_id,
                    "defaultLanguage":  "ja"
                },
                "localizations": {
                    "ja": {"title": trans_title, "description": trans_desc}
                }
            }
        ).execute()
        st.success("✅ YouTube へのアップロードに成功しました！")
    except Exception as e:
        st.error(f"❌ アップロードエラー：{e}")
