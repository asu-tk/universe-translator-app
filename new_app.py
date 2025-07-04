import streamlit as st
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import deepl
from dotenv import load_dotenv

# ── ページ設定 ──
st.set_page_config(page_title="UniVerse－YouTube多言語翻訳アプリ", layout="wide")

# ── タイトル表示 ──
st.title("UniVerse－YouTube多言語翻訳アプリ")

# ── 初期設定 ──
load_dotenv()
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

# ── YouTube カテゴリ一覧（日本語名称: ID） ──
CATEGORY_MAP = {
    "エンターテイメント": "24", "ゲーム": "20", "コメディ": "23", "スポーツ": "17",
    "ニュースと政治": "25", "ハウツーとスタイル": "26", "ブログ": "22", "ペットと動物": "15",
    "映画とアニメ": "1",  "音楽": "10", "科学と美術": "28", "教育": "27",
    "自動車と乗り物": "2", "非営利団体と社会活動": "29", "旅行とイベント": "19"
}

# ── ユーザー入力フォーム ──
youtube_secrets = st.text_input(
    "client_secret.json のパス",
    value=os.getenv("YOUTUBE_CLIENT_SECRETS", "client_secret.json")
)
deepl_key = st.text_input("DeepL APIキー", type="password")
video_url  = st.text_input("YouTube 動画URLまたはID")

# ── カテゴリ選択 ──
category_name = st.selectbox(
    "動画のカテゴリを選択",
    list(CATEGORY_MAP.keys()),
    index=0
)
category_id = CATEGORY_MAP[category_name]

if st.button("翻訳＆アップロード開始"):
    # 入力チェック
    if not youtube_secrets or not deepl_key or not video_url:
        st.error("⚠️ すべての項目を埋めてください。")
        st.stop()

    # 動画ID抽出
    video_id = video_url.split("v=")[-1] if "v=" in video_url else video_url.strip()

    # Google OAuth 認証
    try:
        flow = InstalledAppFlow.from_client_secrets_file(youtube_secrets, SCOPES)
        creds = flow.run_local_server(port=0)
        youtube = build("youtube", "v3", credentials=creds)
        st.success("✅ Google 認証 成功")
    except Exception as e:
        st.error(f"🚫 Google 認証エラー: {e}")
        st.stop()

    # DeepL 認証
    try:
        translator = deepl.Translator(deepl_key)
        st.success("✅ DeepL 認証 成功")
    except Exception as e:
        st.error(f"🚫 DeepL 認証エラー: {e}")
        st.stop()

    # 元タイトル・説明取得
    resp = youtube.videos().list(part="snippet", id=video_id).execute()
    if not resp.get("items"):
        st.error("⚠️ 動画が見つかりません。IDを確認してください。")
        st.stop()
    snippet = resp["items"][0]["snippet"]
    orig_title = snippet.get("title", "")
    orig_desc  = snippet.get("description", "")

    st.subheader("■ 元のタイトル／説明")
    st.write(orig_title)
    st.write(orig_desc)

    # 他言語ローカライズ構築
    st.subheader("■ 翻訳ステータス")
    localizations = {}
    DEEPL_TO_YT = {
        "BG":"bg","CS":"cs","DA":"da","DE":"de","EL":"el",
        "EN-US":"en","EN-GB":"en","ES":"es","ET":"et","FI":"fi",
        "FR":"fr","HU":"hu","ID":"id","IT":"it","KO":"ko",
        "LT":"lt","LV":"lv","NB":"no","NL":"nl","PL":"pl",
        "PT-BR":"pt","PT-PT":"pt","RO":"ro","RU":"ru","SK":"sk",
        "SL":"sl","SV":"sv","TR":"tr","UK":"uk","ZH":"zh"
    }
    for dl_code, yt_code in DEEPL_TO_YT.items():
        try:
            t_title = translator.translate_text(orig_title, target_lang=dl_code).text
            t_desc  = translator.translate_text(orig_desc, target_lang=dl_code).text
            localizations[yt_code] = {"title": t_title, "description": t_desc}
            st.write(f"- {dl_code} → {yt_code}: 翻訳OK")
        except Exception as e:
            st.write(f"- {dl_code}: エラー ({e})")

    # ── YouTube 更新 ──
    try:
        youtube.videos().update(
            part="snippet,localizations",
            body={
                "id": video_id,
                "snippet": {
                    "title": orig_title,
                    "description": orig_desc,
                    "categoryId": category_id,
                    "defaultLanguage": "ja"
                },
                "localizations": localizations
            }
        ).execute()
        st.success("🚀 アップロード完了！")
    except Exception as e:
        st.error(f"❌ アップロードエラー: {e}")