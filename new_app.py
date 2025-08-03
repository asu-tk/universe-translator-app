import streamlit as st
import json
from google_auth_oauthlib.flow import Flow
from urllib.parse import parse_qs
from googleapiclient.discovery import build
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
import deepl

st.set_page_config(page_title="UniVerse — YouTube多言語翻訳アプリ", layout="wide")
st.title("UniVerse — YouTube多言語翻訳アプリ")

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
CLIENT_SECRET_JSON = st.secrets["CLIENT_SECRET_JSON"]

CATEGORY_MAP = {
    "エンターテイメント": "24", "ゲーム": "20", "コメディ": "23", "スポーツ": "17",
    "ニュースと政治": "25", "ハウツーとスタイル": "26", "ブログ": "22",
    "ペットと動物": "15", "映画とアニメ": "1", "音楽": "10", "科学と美術": "28",
    "教育": "27", "自動車と乗り物": "2", "非営利団体と社会活動": "29", "旅行とイベント": "19"
}

# ——— ユーザー入力 ———
deepl_key = st.text_input("🔑 DeepL APIキー", type="password")
video_url = st.text_input("📺 YouTube 動画 URL または ID")
category = st.selectbox("🎯 動画のカテゴリを選択", list(CATEGORY_MAP.keys()))

if st.button("🚀 翻訳＆アップロード開始"):
    if not deepl_key:
        st.error("⚠️ DeepL APIキー を入力してください。")
        st.stop()
    if not video_url:
        st.error("⚠️ YouTube 動画 URL/ID を入力してください。")
        st.stop()

    # ——— Google OAuth認証（Webアプリ用） ———
    CLIENT_SECRET_DICT = json.loads(CLIENT_SECRET_JSON)
    REDIRECT_URI = "https://universe-translator-youtube.streamlit.app/"

    flow = Flow.from_client_config(
        client_config=CLIENT_SECRET_DICT,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    query_params = st.experimental_get_query_params()
    if "code" not in query_params:
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true"
        )
        st.info("① 以下をクリックしてGoogle認証に進んでください")
        st.markdown(f"➡️ [Googleでログイン]({auth_url})")
        st.stop()

    try:
        flow.fetch_token(code=query_params["code"][0])
        creds = flow.credentials
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        st.error(f"🚫 Google 認証エラー：{e}")
        st.stop()

    # ——— DeepL 認証 ———
    try:
        translator = deepl.Translator(deepl_key)
    except Exception as e:
        st.error(f"🚫 DeepL 認証エラー：{e}")
        st.stop()

    # ——— 動画情報取得 ———
    vid = video_url.split("v=")[-1]
    resp = youtube.videos().list(part="snippet", id=vid).execute()
    if not resp.get("items"):
        st.error("⚠️ 動画が見つかりません。IDを確認してください。")
        st.stop()

    snippet = resp["items"][0]["snippet"]
    orig_title = snippet.get("title", "")
    orig_desc = snippet.get("description", "")

    # ——— 多言語翻訳対象言語（DeepL対応） ———
    TARGET_LANGS = [
        "BG", "CS", "DA", "DE", "EL", "EN", "ES", "ET", "FI", "FR", "HU", "ID", "IT",
        "JA", "KO", "LT", "LV", "NB", "NL", "PL", "PT", "RO", "RU", "SK", "SL", "SV",
        "TR", "UK", "ZH"
    ]

    localizations = {}

    for lang in TARGET_LANGS:
        try:
            trans_title = translator.translate_text(orig_title, target_lang=lang).text
            trans_desc = translator.translate_text(orig_desc, target_lang=lang).text
            localizations[lang.lower()] = {
                "title": trans_title,
                "description": trans_desc
            }
        except Exception as e:
            st.warning(f"{lang} の翻訳に失敗しました: {e}")

    # ——— 表示（例：日本語） ———
    st.subheader("■ 元タイトル")
    st.write(orig_title)
    st.subheader("■ 翻訳後タイトル（日本語）")
    st.write(localizations.get("ja", {}).get("title", ""))
    st.subheader("■ 翻訳後説明文（日本語）")
    st.write(localizations.get("ja", {}).get("description", ""))

    # ——— アップロード ———
    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": CATEGORY_MAP[category],
                    "defaultLanguage": "ja"
                },
                "localizations": localizations
            }
        ).execute()
        st.success("✅ 多言語でYouTubeへのアップロードに成功しました！")
    except Exception as e:
        st.error(f"❌ アップロードエラー：{e}")
