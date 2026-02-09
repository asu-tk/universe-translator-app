import streamlit as st
import json
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
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

# まずは DeepLターゲット一覧として保持しつつ、
# 実際に YouTubeへ入れる言語コードは後段で「YouTube対応一覧」でフィルタします
DEEPL_TO_YT_LANG_MAP = {
    "BG": "bg", "CS": "cs", "DA": "da", "DE": "de", "EL": "el",
    "EN-US": "en", "EN-GB": "en",
    "ES": "es", "ET": "et", "FI": "fi", "FR": "fr", "HU": "hu",
    "ID": "id", "IT": "it",
    "JA": "ja",
    "KO": "ko", "LT": "lt", "LV": "lv",
    "NB": "no", "NL": "nl", "PL": "pl",
    "PT-BR": "pt", "PT-PT": "pt",
    "RO": "ro", "RU": "ru", "SK": "sk", "SL": "sl", "SV": "sv", "TR": "tr",
    "UK": "uk",
    "ZH": "zh"
}
DEEPL_LANGUAGES = list(DEEPL_TO_YT_LANG_MAP.keys())


def shorten_text(text, max_length=100):
    if len(text) <= max_length:
        return text
    return text[:max_length - 1] + "…"


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

    CLIENT_SECRET_DICT = json.loads(CLIENT_SECRET_JSON)
    REDIRECT_URI = "https://universe-translator-youtube.streamlit.app/"

    flow = Flow.from_client_config(
        client_config=CLIENT_SECRET_DICT,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )

    # Streamlit の新方式
    query_params = st.query_params
    code = query_params.get("code")

    if not code:
        auth_url, _ = flow.authorization_url(
            prompt="consent",
            access_type="offline",
            include_granted_scopes="true"
        )
        st.info("① 以下をクリックしてGoogle認証に進んでください")
        st.markdown(f"➡️ [Googleでログイン]({auth_url})")
        st.stop()

    if isinstance(code, list):
        code = code[0]

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials
        youtube = build("youtube", "v3", credentials=creds)
    except Exception as e:
        st.error(f"🚫 Google 認証エラー：{e}")
        st.stop()

    # ★ YouTubeが受け付ける言語コード一覧を取得（最重要）
    try:
        lang_resp = youtube.i18nLanguages().list(part="snippet").execute()
        YT_SUPPORTED_LANGS = set(item["snippet"]["hl"] for item in lang_resp.get("items", []))
    except Exception as e:
        YT_SUPPORTED_LANGS = set()
        st.warning(f"⚠️ YouTube対応言語コード一覧の取得に失敗（フィルタなしで続行）: {e}")

    try:
        translator = deepl.Translator(deepl_key)
    except Exception as e:
        st.error(f"🚫 DeepL 認証エラー：{e}")
        st.stop()

    if "v=" in video_url:
        vid = video_url.split("v=")[-1].split("&")[0]
    else:
        vid = video_url.strip()

    try:
        video_response = youtube.videos().list(part="snippet", id=vid).execute()
        if not video_response.get("items"):
            st.error("⚠️ 動画が見つかりません。IDを確認してください。")
            st.stop()

        snippet = video_response["items"][0]["snippet"]
        orig_title = snippet.get("title", "")
        orig_desc = snippet.get("description", "")
        st.success("🎬 動画情報を取得しました")

    except HttpError as e:
        st.error(f"🚫 動画情報取得エラー：{e}")
        st.stop()

    localizations = {}
    for deepl_lang in DEEPL_LANGUAGES:
        try:
            yt_lang = DEEPL_TO_YT_LANG_MAP[deepl_lang]

            # defaultLanguage=ja を使うので ja は localizations に入れない（衝突回避）
            if yt_lang == "ja":
                continue

            # YouTubeが受け付けない言語コードは除外
            if YT_SUPPORTED_LANGS and (yt_lang not in YT_SUPPORTED_LANGS):
                st.warning(f"{deepl_lang} → {yt_lang} はYouTube非対応のためスキップ")
                continue

            # 既に同じキーがある場合は上書きしない（en/pt の衝突回避）
            if yt_lang in localizations:
                continue

            translated_title = translator.translate_text(orig_title, target_lang=deepl_lang).text
            translated_title = translated_title.encode("utf-8", errors="ignore").decode("utf-8")
            translated_title = shorten_text(translated_title, 100)

            if not translated_title.strip():
                st.warning(f"{deepl_lang} はタイトルが空になったためスキップ")
                continue

            translated_desc = translator.translate_text(orig_desc, target_lang=deepl_lang).text
            translated_desc = translated_desc.encode("utf-8", errors="ignore").decode("utf-8")

            localizations[yt_lang] = {
                "title": translated_title,
                "description": translated_desc
            }

            st.write(f"{deepl_lang} → {yt_lang}：✅ 翻訳成功")

        except Exception as e:
            st.warning(f"{deepl_lang} 翻訳エラー: {e}")

    st.subheader("■ 元のタイトル")
    st.write(orig_title)
    st.subheader("■ 元の説明文")
    st.write(orig_desc)

    # ★お願い：次の1回だけデバッグ表示（アップロード直前）
    st.write("DEBUG: localizations keys:", list(localizations.keys()))

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
        st.success("✅ YouTubeへの多言語アップロードに成功しました！")
    except Exception as e:
        st.error(f"🚫 アップロードエラー：{e}")
