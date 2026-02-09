import streamlit as st
import json
import re
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

YT_TITLE_MAX = 100
YT_DESC_MAX = 5000

# 制御文字を除去（改行/タブは残す）
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")

# URLだけの行は翻訳しない（改行崩れ防止＆リンク保持）
URL_LINE = re.compile(r"^\s*(https?://\S+)\s*$")


def sanitize_text(text: str, max_len: int) -> str:
    if text is None:
        return ""
    # 改行コードを統一
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 変な制御文字を消す（改行は残す）
    text = CONTROL_CHARS.sub("", text)
    # 念のためUTF-8化（壊れた文字を落とす）
    text = text.encode("utf-8", errors="ignore").decode("utf-8")
    # 長さ制限
    if len(text) > max_len:
        text = text[:max_len]
    return text


def shorten_title(text: str) -> str:
    text = sanitize_text(text, YT_TITLE_MAX)
    if len(text) == YT_TITLE_MAX:
        text = text[:-1] + "…"
    return text


def translate_preserve_newlines(translator: deepl.Translator, text: str, target_lang: str) -> str:
    """
    改行構造を絶対に壊さない翻訳:
    - 空行は空行のまま
    - URLだけの行は翻訳しない
    - それ以外は1行ずつDeepL翻訳（preserve_formatting=True）
    """
    text = sanitize_text(text, YT_DESC_MAX)  # まず危険文字と改行を整える
    lines = text.split("\n")
    out_lines = []

    for line in lines:
        if line.strip() == "":
            out_lines.append("")
            continue

        if URL_LINE.match(line):
            out_lines.append(line.strip())
            continue

        t = translator.translate_text(
            line,
            target_lang=target_lang,
            preserve_formatting=True
        ).text

        # 1行翻訳した結果にも一応サニタイズをかける（行単位なのでmaxは大きめでOK）
        t = sanitize_text(t, 2000).replace("\n", " ")
        out_lines.append(t)

    # 結合後、最終的に5000文字に収める（YouTube制限）
    result = "\n".join(out_lines)
    result = sanitize_text(result, YT_DESC_MAX)
    return result


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

    # YouTubeが受け付ける言語コード一覧を取得
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

        # 念のためYouTube制限に合わせて整形（改行も統一）
        orig_title = shorten_title(orig_title)
        orig_desc = sanitize_text(orig_desc, YT_DESC_MAX)

        st.success("🎬 動画情報を取得しました")

    except HttpError as e:
        st.error(f"🚫 動画情報取得エラー：{e}")
        st.stop()

    localizations = {}
    for deepl_lang in DEEPL_LANGUAGES:
        try:
            yt_lang = DEEPL_TO_YT_LANG_MAP[deepl_lang]

            # defaultLanguage=ja に任せたいので、ja は localizations に入れない
            if yt_lang == "ja":
                continue

            # YouTubeが受け付けない言語コードは除外
            if YT_SUPPORTED_LANGS and (yt_lang not in YT_SUPPORTED_LANGS):
                st.warning(f"{deepl_lang} → {yt_lang} はYouTube非対応のためスキップ")
                continue

            # 同じキー（en/pt）重複は上書きしない
            if yt_lang in localizations:
                continue

            # タイトルは通常翻訳（フォーマット保持）
            translated_title = translator.translate_text(
                orig_title,
                target_lang=deepl_lang,
                preserve_formatting=True
            ).text

            # 説明文は「改行保持」で翻訳（ここが改行崩れの本命対策）
            translated_desc = translate_preserve_newlines(
                translator,
                orig_desc,
                deepl_lang
            )

            # YouTube制限に合わせて整形
            translated_title = shorten_title(translated_title)
            translated_desc = sanitize_text(translated_desc, YT_DESC_MAX)

            if not translated_title.strip():
                st.warning(f"{deepl_lang} はタイトルが空になったためスキップ")
                continue

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

    # デバッグ（必要なら残してOK）
    st.write("DEBUG: localizations keys:", list(localizations.keys()))

    # まず snippet だけ更新して通るかテスト（原因切り分け）
    try:
        youtube.videos().update(
            part="snippet",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": CATEGORY_MAP[category]
                }
            }
        ).execute()
        st.success("✅ snippet更新テスト: 成功（localizations が原因側の可能性が高い）")
    except Exception as e:
        st.error(f"🚫 snippet更新テストで失敗（localizations以前の問題）: {e}")
        st.stop()

    # 本番：snippet + localizations
    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": CATEGORY_MAP[category]
                },
                "localizations": localizations
            }
        ).execute()
        st.success("✅ YouTubeへの多言語アップロードに成功しました！")
    except Exception as e:
        st.error(f"🚫 アップロードエラー：{e}")
