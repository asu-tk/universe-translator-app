import streamlit as st
import json
import tempfile
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import deepl

# ── ページ設定 ──
st.set_page_config(page_title="UniVerse — YouTube多言語翻訳アプリ", layout="wide")
st.title("UniVerse — YouTube多言語翻訳アプリ")

# ── OAuth & DeepL の設定 ──
SCOPES          = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRET   = st.secrets["CLIENT_SECRET_JSON"]   # GitHub Secrets に埋め込んでおく
DEEPL_KEY       = st.secrets["DEEPL_API_KEY"]

# ── カテゴリマップ ──
CATEGORY_MAP = {
    "エンターテイメント": "24",
    "ゲーム": "20",
    # …（略）…
    "旅行とイベント": "19"
}

# ── 入力フォーム ──
video_url     = st.text_input("📺 YouTube 動画 URL または ID")
category_name = st.selectbox("🎯 動画のカテゴリを選択", list(CATEGORY_MAP.keys()))
category_id   = CATEGORY_MAP[category_name]

# 認証コードをここにペースト
auth_code = st.text_input("🔑 Google 認証コードをここに貼り付けてください")

if st.button("🚀 翻訳＆アップロード開始"):

    # 入力チェック
    if not video_url:
        st.error("⚠️ 動画 URL または ID を入力してください")
        st.stop()
    if not auth_code:
        st.error("⚠️ まず上の「認証コード」を取得・貼り付けてください")
        st.stop()

    # —— client_secret.json を一時ファイルに出力 ——
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
        fp.write(CLIENT_SECRET)
        fp_path = fp.name

    # —— OAuth フロー手動版 ——
    try:
        flow = InstalledAppFlow.from_client_secrets_file(fp_path, SCOPES)
        # 認証用 URL を取得して表示（１回限り）
        auth_url, _ = flow.authorization_url(prompt="consent")
        st.write("▶️ 以下の URL をコピーしてブラウザで開き、認証コードを取得してください.")
        st.write(auth_url)
        # ペーストされたコードでトークンを取得
        flow.fetch_token(code=auth_code)
        creds  = flow.credentials
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        st.error(f"🚫 Google 認証エラー：{e}")
        st.stop()

    # —— DeepL 認証 ——
    try:
        translator = deepl.Translator(DEEPL_KEY)
    except Exception as e:
        st.error(f"🚫 DeepL 認証エラー：{e}")
        st.stop()

    # —— 元データ取得 ——
    vid  = video_url.split("v=")[-1]
    resp = youtube.videos().list(part="snippet", id=vid).execute()
    if not resp.get("items"):
        st.error("⚠️ 動画が見つかりません。IDを確認してください。")
        st.stop()

    snippet    = resp["items"][0]["snippet"]
    orig_title = snippet.get("title", "")
    orig_desc  = snippet.get("description", "")

    # —— 翻訳 ——
    trans_title = translator.translate_text(orig_title, target_lang="JA").text
    trans_desc  = translator.translate_text(orig_desc,  target_lang="JA").text

    # —— 結果表示 ——
    st.subheader("■ 元タイトル");       st.write(orig_title)
    st.subheader("■ 翻訳後タイトル");   st.write(trans_title)
    st.subheader("■ 翻訳後説明文");     st.write(trans_desc)

    # —— YouTube アップデート ——
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
