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

CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
URL_LINE = re.compile(r"^\s*(https?://\S+)\s*$")

def sanitize_text(text: str, max_len: int) -> str:
    if text is None:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL_CHARS.sub("", text)
    text = text.encode("utf-8", errors="ignore").decode("utf-8")
    if len(text) > max_len:
        text = text[:max_len]
    return text

def shorten_title(text: str) -> str:
    text = sanitize_text(text, YT_TITLE_MAX)
    if len(text) == YT_TITLE_MAX:
        text = text[:-1] + "…"
    return text

def translate_preserve_newlines(translator: deepl.Translator, text: str, target_lang: str) -> str:
    text = sanitize_text(text, YT_DESC_MAX)
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

        t = sanitize_text(t, 2000).replace("\n", " ")
        out_lines.append(t)

    result = "\n".join(out_lines)
    result = sanitize_text(result, YT_DESC_MAX)
    return result

# ---------------------------
# OAuth（PKCE）を壊さない実装
# ---------------------------

def _get_client_config_dict() -> dict:
    # secretsは文字列JSONなのでdict化
    d = json.loads(CLIENT_SECRET_JSON)
    return d

def _get_redirect_uri() -> str:
    # Cloud版のURLは「Google Cloud Consoleの承認済みリダイレクトURI」と完全一致させる
    # 末尾スラッシュが付いている/いないも一致が必要なことがあります
    return "https://universe-translator-youtube.streamlit.app/"

def _ensure_flow():
    if "oauth_flow" not in st.session_state:
        st.session_state.oauth_flow = Flow.from_client_config(
            client_config=_get_client_config_dict(),
            scopes=SCOPES,
            redirect_uri=_get_redirect_uri()
        )

def _start_login():
    _ensure_flow()
    auth_url, state = st.session_state.oauth_flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true"
    )
    st.session_state.oauth_state = state
    return auth_url

def _try_finish_login_from_callback():
    """
    URLに ?code=... が来ていたら token 交換する。
    ここで「認証開始時と同じflow」を使うのがPKCE必須条件。
    """
    qp = st.query_params
    code = qp.get("code")
    if not code:
        return False

    if isinstance(code, list):
        code = code[0]

    _ensure_flow()

    # state を保持しているなら戻す（任意だけど推奨）
    if "oauth_state" in st.session_state:
        st.session_state.oauth_flow.state = st.session_state.oauth_state

    try:
        st.session_state.oauth_flow.fetch_token(code=code)
        creds = st.session_state.oauth_flow.credentials
        st.session_state.yt_creds_json = creds.to_json()

        # codeが残ると再実行でまたfetch_tokenしようとして事故るので消す
        try:
            st.query_params.clear()
        except Exception:
            pass

        st.success("✅ Google認証OK")
        st.rerun()
        return True
    except Exception as e:
        st.error(f"🚫 Google 認証エラー：{e}")
        return False

def _get_youtube_client_or_none():
    if "yt_creds_json" not in st.session_state:
        return None
    # buildは credentials オブジェクトが必要なので flow から復元するのが簡単
    # ここでは flow を再利用して credentials を入れ直す
    _ensure_flow()
    try:
        st.session_state.oauth_flow.credentials = st.session_state.oauth_flow.credentials.from_authorized_user_info(
            json.loads(st.session_state.yt_creds_json),
            scopes=SCOPES
        )
    except Exception:
        # from_authorized_user_info が環境によってコケる場合は、再ログインさせる
        return None

    try:
        youtube = build("youtube", "v3", credentials=st.session_state.oauth_flow.credentials)
        return youtube
    except Exception:
        return None

# まずコールバック処理を先に実行（codeが来てるならここで確定）
_try_finish_login_from_callback()

# UI: ログインセクション
st.subheader("1) Googleログイン")

youtube = _get_youtube_client_or_none()
if youtube is None:
    auth_url = _start_login()
    st.info("下のボタンからGoogle認証に進んでください（認証後、自動でこの画面に戻ります）")
    st.link_button("Googleでログイン", auth_url)
    st.stop()
else:
    st.success("ログイン済みです")

# ここから先はログイン済みで進む
st.subheader("2) 翻訳＆アップロード")

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
        orig_title = shorten_title(snippet.get("title", ""))
        orig_desc = sanitize_text(snippet.get("description", ""), YT_DESC_MAX)

        st.success("🎬 動画情報を取得しました")
    except HttpError as e:
        st.error(f"🚫 動画情報取得エラー：{e}")
        st.stop()

    # 翻訳（Broken pipe対策で出力を減らす）
    localizations = {}
    total = len(DEEPL_LANGUAGES)
    prog = st.progress(0)
    log = st.empty()

    done = 0
    for deepl_lang in DEEPL_LANGUAGES:
        done += 1
        prog.progress(int(done / total * 100))
        try:
            yt_lang = DEEPL_TO_YT_LANG_MAP[deepl_lang]
            if yt_lang == "ja":
                continue
            if YT_SUPPORTED_LANGS and (yt_lang not in YT_SUPPORTED_LANGS):
                continue
            if yt_lang in localizations:
                continue

            translated_title = translator.translate_text(
                orig_title,
                target_lang=deepl_lang,
                preserve_formatting=True
            ).text

            translated_desc = translate_preserve_newlines(translator, orig_desc, deepl_lang)

            translated_title = shorten_title(translated_title)
            translated_desc = sanitize_text(translated_desc, YT_DESC_MAX)

            if not translated_title.strip():
                continue

            localizations[yt_lang] = {"title": translated_title, "description": translated_desc}
            log.write(f"進捗: {deepl_lang} → {yt_lang} OK")
        except Exception as e:
            log.write(f"進捗: {deepl_lang} 失敗: {e}")

    st.subheader("■ 元のタイトル")
    st.write(orig_title)
    st.subheader("■ 元の説明文")
    st.write(orig_desc)

    # snippet更新テスト
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
        st.success("✅ snippet更新テスト: 成功")
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
