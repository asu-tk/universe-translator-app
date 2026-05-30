import streamlit as st
import json
import re
import os
import base64
import hashlib
import hmac
import stripe
import deepl
from cryptography.fernet import Fernet, InvalidToken
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import create_client

st.set_page_config(page_title="UniVerse — YouTube多言語翻訳アプリ", layout="wide")
st.title("UniVerse — YouTube多言語翻訳アプリ")

MEMBER_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CLIENT_SECRET_JSON = st.secrets["CLIENT_SECRET_JSON"]
STRIPE_SECRET_KEY = st.secrets["STRIPE_SECRET_KEY"]
STRIPE_PRICE_ID = st.secrets["STRIPE_PRICE_ID"]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"]
DEEPL_ENCRYPTION_KEY = st.secrets["DEEPL_ENCRYPTION_KEY"]
ADMIN_EMAILS = {"sukidesuchofu69@gmail.com"}

stripe.api_key = STRIPE_SECRET_KEY
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
fernet = Fernet(DEEPL_ENCRYPTION_KEY.encode("utf-8"))

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
    "ZH-HANS": "zh-Hans",
    "ZH-HANT": "zh-Hant"
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

    return sanitize_text("\n".join(out_lines), YT_DESC_MAX)


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
            st.info("YouTubeチャンネル接続をやり直してください。")
    else:
        st.code(str(error))


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_admin_user(email: str) -> bool:
    return normalize_email(email) in ADMIN_EMAILS


def upsert_universe_user(email: str, subscription_status: str = "unknown", stripe_customer_id: str = None):
    email = normalize_email(email)
    payload = {
        "google_email": email,
        "subscription_status": subscription_status,
        "is_admin": is_admin_user(email),
        "last_login_at": "now()",
    }
    if stripe_customer_id:
        payload["stripe_customer_id"] = stripe_customer_id

    return supabase.table("universe_users").upsert(
        payload,
        on_conflict="google_email",
    ).execute()


def get_subscription_state(email: str) -> tuple[bool, str, str | None]:
    email = normalize_email(email)

    if is_admin_user(email):
        upsert_universe_user(email, "admin", None)
        return True, "admin", None

    customers = stripe.Customer.list(email=email, limit=10)
    last_customer_id = customers.data[0].id if customers.data else None
    best_status = "none"

    for customer in customers.data:
        subscriptions = stripe.Subscription.list(
            customer=customer.id,
            status="all",
            limit=20,
        )

        for subscription in subscriptions.data:
            for item in subscription["items"]["data"]:
                if item["price"]["id"] != STRIPE_PRICE_ID:
                    continue

                best_status = subscription.status
                upsert_universe_user(email, subscription.status, customer.id)
                if subscription.status in ["active", "trialing"]:
                    return True, subscription.status, customer.id

    upsert_universe_user(email, best_status, last_customer_id)
    return False, best_status, last_customer_id


def create_checkout_url(email: str) -> str:
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer_email=normalize_email(email),
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        success_url=_redirect_uri() + "?payment=success",
        cancel_url=_redirect_uri() + "?payment=cancel",
    )
    return session.url


def encrypt_deepl_key(api_key: str) -> str:
    return fernet.encrypt(api_key.encode("utf-8")).decode("utf-8")


def decrypt_deepl_key(encrypted_api_key: str) -> str:
    return fernet.decrypt(encrypted_api_key.encode("utf-8")).decode("utf-8")


def get_saved_deepl_key(email: str) -> str | None:
    resp = supabase.table("universe_deepl_keys").select("encrypted_deepl_api_key").eq(
        "google_email", normalize_email(email)
    ).limit(1).execute()

    if not resp.data:
        return None

    try:
        return decrypt_deepl_key(resp.data[0]["encrypted_deepl_api_key"])
    except InvalidToken:
        st.error("保存済みのDeepL APIキーを復号できません。APIキーを保存し直してください。")
        return None


def has_saved_deepl_key(email: str) -> bool:
    resp = supabase.table("universe_deepl_keys").select("id").eq(
        "google_email", normalize_email(email)
    ).limit(1).execute()
    return bool(resp.data)


def save_deepl_key(email: str, api_key: str):
    supabase.table("universe_deepl_keys").upsert(
        {
            "google_email": normalize_email(email),
            "encrypted_deepl_api_key": encrypt_deepl_key(api_key),
        },
        on_conflict="google_email",
    ).execute()


def delete_deepl_key(email: str):
    supabase.table("universe_deepl_keys").delete().eq(
        "google_email", normalize_email(email)
    ).execute()


def record_youtube_channel(email: str, channel_id: str, channel_title: str):
    supabase.table("universe_youtube_channels").upsert(
        {
            "google_email": normalize_email(email),
            "channel_id": channel_id,
            "channel_title": channel_title,
            "last_connected_at": "now()",
        },
        on_conflict="google_email,channel_id",
    ).execute()


def log_usage(email: str, channel_id: str, channel_title: str, video_id: str, title: str, count: int, status: str, error: str = None):
    supabase.table("universe_usage_logs").insert(
        {
            "google_email": normalize_email(email),
            "youtube_channel_id": channel_id,
            "youtube_channel_title": channel_title,
            "video_id": video_id,
            "original_title": title,
            "localization_count": count,
            "status": status,
            "error_message": error,
        }
    ).execute()


def _client_config_dict() -> dict:
    return json.loads(CLIENT_SECRET_JSON)


def _redirect_uri() -> str:
    return "https://universe-translator-youtube.streamlit.app/"


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def _state_signature(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = STRIPE_SECRET_KEY.encode("utf-8")
    return _b64url(hmac.new(key, raw, hashlib.sha256).digest())


def _encode_state(payload: dict) -> str:
    signed_payload = dict(payload)
    signed_payload["sig"] = _state_signature(payload)
    return _b64url(json.dumps(signed_payload).encode("utf-8"))


def _decode_state(state: str) -> dict:
    payload = json.loads(_b64url_decode(state).decode("utf-8"))
    sig = payload.pop("sig", "")

    expected_sig = _state_signature(payload)
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("認証情報の確認に失敗しました。もう一度ログインしてください。")

    return payload


def _new_code_verifier() -> str:
    return _b64url(os.urandom(64))


def _code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return _b64url(digest)


def _make_flow(scopes) -> Flow:
    return Flow.from_client_config(
        client_config=_client_config_dict(),
        scopes=scopes,
        redirect_uri=_redirect_uri(),
    )


def build_auth_url(purpose: str, scopes, member_email: str = "") -> str:
    flow = _make_flow(scopes)
    verifier = _new_code_verifier()
    challenge = _code_challenge_s256(verifier)

    state_payload = {
        "v": verifier,
        "purpose": purpose,
        "member_email": normalize_email(member_email),
    }
    state = _encode_state(state_payload)

    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        include_granted_scopes="false",
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
    )
    return auth_url


def exchange_code(code: str, state: str):
    payload = _decode_state(state)
    verifier = payload["v"]
    purpose = payload.get("purpose", "youtube")
    scopes = MEMBER_SCOPES if purpose == "member" else YOUTUBE_SCOPES

    flow = _make_flow(scopes)
    flow.code_verifier = verifier
    flow.fetch_token(code=code)

    return purpose, flow.credentials, payload


def get_google_email(creds) -> str:
    oauth2 = build("oauth2", "v2", credentials=creds)
    userinfo = oauth2.userinfo().get().execute()
    return normalize_email(userinfo.get("email", ""))


def clear_query_params():
    try:
        st.query_params.clear()
    except Exception:
        pass


def clear_member_login():
    st.session_state.member_creds_json = None
    st.session_state.member_email = ""
    clear_query_params()


def clear_youtube_login():
    st.session_state.yt_creds_json = None
    clear_query_params()


def extract_video_id(video_url: str) -> str:
    video_url = video_url.strip()
    if "youtu.be/" in video_url:
        return video_url.split("youtu.be/")[-1].split("?")[0].split("/")[0]
    if "v=" in video_url:
        return video_url.split("v=")[-1].split("&")[0]
    return video_url


if "member_creds_json" not in st.session_state:
    st.session_state.member_creds_json = None
if "member_email" not in st.session_state:
    st.session_state.member_email = ""
if "yt_creds_json" not in st.session_state:
    st.session_state.yt_creds_json = None
if "edit_deepl_key" not in st.session_state:
    st.session_state.edit_deepl_key = False

qp = st.query_params
code = qp.get("code")
state = qp.get("state")
payment = qp.get("payment")

if isinstance(code, list):
    code = code[0]
if isinstance(state, list):
    state = state[0]
if isinstance(payment, list):
    payment = payment[0]

if payment == "success":
    st.success("決済ありがとうございます。反映後、会員機能が利用できます。")
elif payment == "cancel":
    st.info("決済はキャンセルされました。")

if code and state:
    try:
        purpose, creds, payload = exchange_code(code, state)

        if purpose == "member":
            st.session_state.member_creds_json = creds.to_json()
            st.session_state.member_email = get_google_email(creds)
            upsert_universe_user(st.session_state.member_email)
            st.success("✅ UniVerse会員ログインOK")
        else:
            member_email_from_state = payload.get("member_email", "")
            if member_email_from_state:
                st.session_state.member_email = normalize_email(member_email_from_state)
            st.session_state.yt_creds_json = creds.to_json()
            st.success("✅ YouTubeチャンネル接続OK")

        clear_query_params()
        st.rerun()

    except Exception as e:
        st.error(f"🚫 Google認証エラー：{e}")
        st.stop()

st.subheader("1) UniVerse会員ログイン")
member_email = st.session_state.member_email

if st.session_state.member_creds_json:
    try:
        from google.oauth2.credentials import Credentials

        info = json.loads(st.session_state.member_creds_json)
        member_creds = Credentials.from_authorized_user_info(info, scopes=MEMBER_SCOPES)

        if not member_email:
            member_email = get_google_email(member_creds)
            st.session_state.member_email = member_email

        upsert_universe_user(member_email)
        st.success("会員ログイン済みです")
        st.info(f"会員メール: {member_email}")

        if st.button("会員ログインをやり直す"):
            clear_member_login()
            clear_youtube_login()
            st.rerun()

    except Exception as e:
        st.warning(f"会員ログイン情報を読み込めませんでした。再ログインしてください: {e}")
        clear_member_login()
        member_email = ""

elif member_email:
    st.success("会員ログイン済みです")
    st.info(f"会員メール: {member_email}")

    if st.button("会員ログインをやり直す"):
        clear_member_login()
        clear_youtube_login()
        st.rerun()
else:
    auth_url = build_auth_url("member", MEMBER_SCOPES)
    st.info("まず、月額会員として登録する本人のGoogleメールでログインしてください。")
    st.link_button("会員としてGoogleログイン", auth_url)
    st.stop()

st.subheader("2) 会員確認")

try:
    if member_email.endswith("@pages.plusgoogle.com"):
        st.error("会員確認にはブランドアカウントではなく、本人のGoogleメールが必要です。")
        st.stop()

    is_member, subscription_status, _ = get_subscription_state(member_email)
    if is_admin_user(member_email):
        st.success("開発者アカウントとして認証されています。")
    elif is_member:
        st.success("月額会員として認証されています。")
    else:
        st.warning("UniVerseは月額会員専用アプリです。")
        if subscription_status not in ["none", "unknown"]:
            st.info(f"現在の契約状態: {subscription_status}")
        checkout_url = create_checkout_url(member_email)
        st.link_button("月額プランに登録する", checkout_url)
        st.stop()

except Exception as e:
    st.error(f"会員確認でエラーが発生しました: {e}")
    st.stop()

st.subheader("3) DeepL APIキー設定")

saved_deepl_key_exists = has_saved_deepl_key(member_email)
if saved_deepl_key_exists and not st.session_state.edit_deepl_key:
    st.success("DeepL APIキーは保存済みです。")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("DeepL APIキーを変更する"):
            st.session_state.edit_deepl_key = True
            st.rerun()
    with col2:
        if st.button("保存済みDeepL APIキーを削除する"):
            delete_deepl_key(member_email)
            st.session_state.edit_deepl_key = False
            st.success("保存済みDeepL APIキーを削除しました。")
            st.rerun()
else:
    if saved_deepl_key_exists:
        st.info("新しいDeepL APIキーを入力すると、保存済みキーを上書きします。")
    else:
        st.info("DeepL APIキーを1回保存すると、次回以降は入力不要になります。キー本体は暗号化して保存されます。")

    new_deepl_key = st.text_input("🔑 DeepL APIキー", type="password", key="new_deepl_key")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("DeepL APIキーを保存する"):
            if not new_deepl_key:
                st.error("DeepL APIキーを入力してください。")
                st.stop()
            try:
                deepl.Translator(new_deepl_key).get_usage()
                save_deepl_key(member_email, new_deepl_key)
                st.session_state.edit_deepl_key = False
                st.success("DeepL APIキーを保存しました。")
                st.rerun()
            except Exception as e:
                st.error(f"DeepL APIキーを確認できませんでした: {e}")
                st.stop()
    with col2:
        if saved_deepl_key_exists and st.button("変更をキャンセル"):
            st.session_state.edit_deepl_key = False
            st.rerun()

if not has_saved_deepl_key(member_email):
    st.stop()

st.subheader("4) YouTubeチャンネル接続")
youtube = None
channel_title = ""
channel_id = ""

if st.session_state.yt_creds_json:
    try:
        from google.oauth2.credentials import Credentials

        info = json.loads(st.session_state.yt_creds_json)
        yt_creds = Credentials.from_authorized_user_info(info, scopes=YOUTUBE_SCOPES)
        youtube = build("youtube", "v3", credentials=yt_creds)

        st.success("YouTubeチャンネル接続済みです")

        if st.button("YouTubeチャンネル接続をやり直す"):
            clear_youtube_login()
            st.rerun()

    except Exception as e:
        st.warning(f"YouTube接続情報を読み込めませんでした。再接続してください: {e}")
        clear_youtube_login()
        youtube = None

if youtube is None:
    auth_url = build_auth_url("youtube", YOUTUBE_SCOPES, member_email)
    st.info("次に、翻訳を反映したいYouTubeチャンネルまたはブランドアカウントを接続してください。")
    st.link_button("YouTubeチャンネルを接続", auth_url)
    st.stop()

try:
    channel_resp = youtube.channels().list(part="snippet", mine=True).execute()
    channels = channel_resp.get("items", [])

    if not channels:
        st.error("認証はできましたが、YouTubeチャンネルが見つかりません。")
        st.info(YOUTUBE_SIGNUP_REQUIRED_HELP)

        if st.button("YouTubeチャンネルを再接続する"):
            clear_youtube_login()
            st.rerun()
        st.stop()

    channel_title = channels[0]["snippet"].get("title", "")
    channel_id = channels[0].get("id", "")
    record_youtube_channel(member_email, channel_id, channel_title)
    st.success(f"接続中のYouTubeチャンネル: {channel_title} / {channel_id}")

except HttpError as e:
    show_youtube_http_error("認証チャンネル情報の取得", e)
    if st.button("YouTubeチャンネルを再接続する"):
        clear_youtube_login()
        st.rerun()
    st.stop()

st.subheader("5) 翻訳＆アップロード")

video_url = st.text_input("📺 YouTube 動画 URL または ID")
category = st.selectbox("🎯 動画のカテゴリを選択", list(CATEGORY_MAP.keys()))

if st.button("🚀 翻訳＆アップロード開始"):
    deepl_key = get_saved_deepl_key(member_email)
    if not deepl_key:
        st.error("DeepL APIキーが保存されていません。")
        st.stop()

    if not video_url:
        st.error("⚠️ YouTube 動画 URL/ID を入力してください。")
        st.stop()

    vid = extract_video_id(video_url)

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
        log_usage(member_email, channel_id, channel_title, vid, "", 0, "deepl_error", str(e))
        st.stop()

    try:
        video_response = youtube.videos().list(
            part="snippet,localizations",
            id=vid,
        ).execute()

        if not video_response.get("items"):
            st.error("⚠️ 動画が見つかりません。IDを確認してください。")
            log_usage(member_email, channel_id, channel_title, vid, "", 0, "video_not_found")
            st.stop()

        snippet = video_response["items"][0]["snippet"]
        orig_title = shorten_title(snippet.get("title", ""))
        orig_desc = sanitize_text(snippet.get("description", ""), YT_DESC_MAX)
        category_id = snippet.get("categoryId", CATEGORY_MAP[category])
        st.success("🎬 動画情報を取得しました")

    except HttpError as e:
        show_youtube_http_error("動画情報の取得", e)
        log_usage(member_email, channel_id, channel_title, vid, "", 0, "youtube_video_error", str(e))
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
                preserve_formatting=True,
            ).text
            translated_desc = translate_preserve_newlines(translator, orig_desc, deepl_lang)

            translated_title = shorten_title(translated_title)
            translated_desc = sanitize_text(translated_desc, YT_DESC_MAX)

            if not translated_title.strip():
                continue

            localizations[yt_lang] = {
                "title": translated_title,
                "description": translated_desc,
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
                    "categoryId": category_id,
                },
            },
        ).execute()
        st.success("✅ snippet更新テスト: 成功")

    except HttpError as e:
        show_youtube_http_error("snippet更新テスト", e)
        log_usage(member_email, channel_id, channel_title, vid, orig_title, len(localizations), "snippet_update_error", str(e))
        st.stop()
    except Exception as e:
        st.error(f"🚫 snippet更新テストで失敗しました: {e}")
        log_usage(member_email, channel_id, channel_title, vid, orig_title, len(localizations), "snippet_update_error", str(e))
        st.stop()

    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": vid,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": category_id,
                },
                "localizations": localizations,
            },
        ).execute()

        log_usage(member_email, channel_id, channel_title, vid, orig_title, len(localizations), "success")
        st.success("✅ YouTubeへの多言語アップロードに成功しました！")

    except HttpError as e:
        show_youtube_http_error("YouTubeへの多言語アップロード", e)
        log_usage(member_email, channel_id, channel_title, vid, orig_title, len(localizations), "localization_update_error", str(e))
        st.stop()
    except Exception as e:
        st.error(f"🚫 アップロードエラー：{e}")
        log_usage(member_email, channel_id, channel_title, vid, orig_title, len(localizations), "localization_update_error", str(e))
        st.stop()
