import streamlit as st
import json
import re
import os
import base64
import hashlib
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

YOUTUBE_SIGNUP_REQUIRED_HELP = """
認証したGoogleアカウントが、YouTubeチャンネルとして利用できない可能性があります。

確認してください。

・認証したGoogleアカウントにYouTubeチャンネルが作成されているか
・目的のYouTubeチャンネルを管理できるGoogleアカウントで認証しているか
・ブランドアカウントの場合、正しいチャンネルに切り替えているか
・再認証ボタンを押して、Google認証をやり直すこと
"""


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


def get_youtube_error_reason(error: HttpError) -> str:
    try:
        payload = json.loads(error.content.decode("utf-8"))
        errors = payload.get("error", {}).get("errors", [])
        if errors:
            return errors[0].get("reason", "")
        return payload.get("error", {}).get("status", "")
    except Exception:
        return ""


def show_youtube_http_error(action: str, error: HttpError):
    status = getattr(error.resp, "status", None)
    reason = get_youtube_error_reason(error)

    st.error(f"🚫 {action} に失敗しました。HTTP {status} / reason: {reason or '不明'}")

    if status == 401:
        st.warning("認証アカウント、YouTubeチャンネル、またはOAuth認証情報に問題がある可能性があります。")

        if reason == "youtubeSignupRequired":
            st.info(YOUTUBE_SIGNUP_REQUIRED_HELP)
        else:
            st.info(
                "Google認証情報が古い、scopeが不足している、または別のGoogleアカウントで"
                "認証している可能性があります。再認証ボタンを押して認証をやり直してください。"
            )
    else:
        st.code(str(error))


# ===========================
# OAuth
# ===========================

def _client_config_dict() -> dict:
    return json.loads(CLIENT_SECRET_JSON)


def _redirect_uri() -> str:
    return "https://universe-translator-youtube.streamlit.app/"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def _new_code_verifier() -> str:
    return _b64url(os.urandom(64))


def _code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _b64url(digest)


def _make_flow() -> Flow:
    return Flow.from_client_config(
        client_config=_client_config_dict(),
        scopes=SCOPES,
        redirect_uri=_redirect_uri()
    )


def build_auth_url() -> str:
    flow = _make_flow()

    verifier = _new_code_verifier()
    challenge = _code_challenge_s256(verifier)

    state_payload = {"v": verifier}
    state = _b64url(json.dumps(state_payload).encode("utf-8"))

    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return auth_url


def exchange_code_for_youtube(code: str, state: str):
    payload = json.loads(_b64url_decode(state).decode("utf-8"))
    verifier = payload["v"]

    flow = _make_flow()
    flow.code_verifier = verifier
    flow.fetch_token(code=code)

    creds = flow.credentials
    youtube = build("youtube", "v3", credentials=creds)
    return youtube, creds


def clear_login():
    st.session_state.yt_creds_json = None
    st.session_state.yt_channel_checked = False
    try:
        st.query_params.clear()
    except Exception:
        pass


# ===========================
# ログイン処理
# ===========================

st.subheader("1) Googleログイン")

qp = st.query_params
code = qp.get("code")
state = qp.get("state")

if isinstance(code, list):
    code = code[0]
if isinstance(state, list):
    state = state[0]

if "yt_creds_json" not in st.session_state:
    st.session_state.yt_creds_json = None

if "yt_channel_checked" not in st.session_state:
    st.session_state.yt_channel_checked = False

if code and state and st.session_state.yt_creds_json is None:
    try:
        youtube, creds = exchange_code_for_youtube(code, state)
        st.session_state.yt_creds_json = creds.to_json()
        st.session_state.yt_channel_checked = False
        st.success("✅ Google認証OK")

        try:
            st.query_params.clear()
        except Exception:
            pass

        st.rerun()
    except Exception as e:
        st.error(f"🚫 Google認証エラー：{e}")
        st.stop()

youtube = None

if st.session_state.yt_creds_json:
    try:
        from google.oauth2.credentials import Credentials

        info = json.loads(st.session_state.yt_creds_json)
        creds = Credentials.from_authorized_user_info(info, scopes=SCOPES)
        youtube = build("youtube", "v3", credentials=creds)

        st.success("ログイン済みです")

        if st.button("Google認証をやり直す"):
            clear_login()
            st.rerun()

    except Exception as e:
        st.warning(f"保存済みのGoogle認証情報を読み込めませんでした。再認証してください: {e}")
        clear_login()
        youtube = None

if youtube is None:
    auth_url = build_auth_url()
    st.info("下のボタンからGoogle認証に進んでください。認証後、自動でこの画面に戻ります。")
    st.link_button("Googleでログイン", auth_url)
    st.stop()


# ===========================
# 認証チャンネル確認
# ===========================

try:
    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
    channels = channel_resp.get("items", [])

    if not channels:
        st.error("認証はできましたが、YouTubeチャンネルが見つかりません。")
        st.info(YOUTUBE_SIGNUP_REQUIRED_HELP)

        if st.button("再認証する"):
            clear_login()
            st.rerun()

        st.stop()

    channel_title = channels[0]["snippet"].get("title", "")
    channel_id = channels[0].get("id", "")
    st.success(f"認証中のYouTubeチャンネル: {channel_title} / {channel_id}")

except HttpError as e:
    show_youtube_http_error("認証チャンネル情報の取得", e)

    if st.button("再認証する"):
        clear_login()
        st.rerun()

    st.stop()


# ===========================
# 翻訳＆アップロード
# ===========================

st.subheader("2) 翻訳＆アップロード")

deepl_key = st.text_input("🔑 DeepL APIキー", type="password")
video_url = st.text_input("📺 YouTube 動画 URL または ID")
category = st.selectbox("🎯 動画のカテゴリを選択", list(CATEGORY_MAP.keys()))

if st.button("🚀 翻訳＆アップロード開始"):
    if not deepl_key:
        st.error("⚠️ DeepL APIキーを入力してください。")
        st.stop()

    if not video_url:
        st.error("⚠️ YouTube 動画 URL/ID を入力してください。")
        st.stop()

    try:
        lang_resp = youtube.i18nLanguages().list(part="snippet").execute()
        YT_SUPPORTED_LANGS = set(item["snippet"]["hl"] for item in lang_resp.get("items", []))
        st.success(f"YouTube対応言語コードを {len(YT_SUPPORTED_LANGS)} 件取得しました。")

    except HttpError as e:
        YT_SUPPORTED_LANGS = set()
        show_youtube_http_error("YouTube対応言語コード一覧の取得", e)
        st.warning("言語コードのフィルタなしで続行します。")

    except Exception as e:
        YT_SUPPORTED_LANGS = set()
        st.warning(f"⚠️ YouTube対応言語コード一覧の取得に失敗しました。フィルタなしで続行します: {e}")

    try:
        translator = deepl.Translator(deepl_key)
    except Exception as e:
        st.error(f"🚫 DeepL認証エラー：{e}")
        st.stop()

    if "v=" in video_url:
        vid = video_url.split("v=")[-1].split("&")[0]
    else:
        vid = video_url.strip()

    try:
        video_response = youtube.videos().list(
            part="snippet,localizations",
            id=vid
        ).execute()

        if not video_response.get("items"):
            st.error("⚠️ 動画が見つかりません。IDを確認してください。")
            st.stop()

        snippet = video_response["items"][0]["snippet"]
        orig_title = shorten_title(snippet.get("title", ""))
        orig_desc = sanitize_text(snippet.get("description", ""), YT_DESC_MAX)
        category_id = snippet.get("categoryId", CATEGORY_MAP[category])

        st.success("🎬 動画情報を取得しました")

    except HttpError as e:
        show_youtube_http_error("動画情報の取得", e)
        st.stop()

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

            translated_desc = translate_preserve_newlines(
                translator,
                orig_desc,
                deepl_lang
            )

            translated_title = shorten_title(translated_title)
            translated_desc = sanitize_text(translated_desc, YT_DESC_MAX)

            if not translated_title.strip():
                continue

            localizations[yt_lang] = {
                "title": translated_title,
                "description": translated_desc
            }

            log.write(f"進捗: {deepl_lang} → {yt_lang} OK")

        except Exception as e:
            log.write(f"進捗: {deepl_lang} 失敗: {e}")

    st.subheader("■ 元のタイトル")
    st.write(orig_title)

    st.subheader("■ 元の説明文")
    st.write(orig_desc)

    st.subheader("■ 作成されたlocalizations")
    st.json(localizations)

    try:
        youtube.videos().update(
            part="snippet",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": category_id
                }
            }
        ).execute()

        st.success("✅ snippet更新テスト: 成功")

    except HttpError as e:
        show_youtube_http_error("snippet更新テスト", e)
        st.stop()

    except Exception as e:
        st.error(f"🚫 snippet更新テストで失敗しました: {e}")
        st.stop()

    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": category_id
                },
                "localizations": localizations
            }
        ).execute()

        st.success("✅ YouTubeへの多言語アップロードに成功しました！")

    except HttpError as e:
        show_youtube_http_error("YouTubeへの多言語アップロード", e)
        st.stop()

    except Exception as e:
        st.error(f"🚫 アップロードエラー：{e}")
        st.stop()
