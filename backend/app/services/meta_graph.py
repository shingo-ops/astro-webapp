from __future__ import annotations

"""
Meta Graph API クライアント（Phase 1-D Sprint 2）。

OAuth code → 短期/長期 User Access Token 交換、Page 一覧取得、
subscribed_apps 登録/解除、Instagram Business Account 取得など、
Phase 1-D で必要な Graph API 呼び出しを薄いラッパとして提供する。

たとえ話:
  「Meta というお役所の窓口に書類を出しに行く受付係」。
  各受付窓口（endpoint）でフォーマットが違うので、各専用関数を用意して
  我々のアプリ側からは統一した戻り値・例外で扱えるようにする。

設計判断:
  - httpx (async) を直接使用。リトライなし（Sprint 5 で再考）
  - timeout=10 秒、Meta 側遅延を許容しつつ FastAPI worker を縛らない
  - 例外階層:
      MetaGraphError                      … 全 Graph API 例外の基底
        ├─ MetaGraphAPIError              … Meta から返ったエラー（type/code/message を保持）
        ├─ MetaGraphTimeoutError          … タイムアウト
        └─ MetaGraphTransportError        … ネットワーク / 5xx / JSON parse 失敗
  - "happy path" は dict / 構造体 (TypedDict 風 dict) で返却
  - Page Access Token などの secret 値は **str のまま** 返却。呼び出し側で
    暗号化・ロギング除外を行う責務を持つ
  - `META_GRAPH_API_VERSION` 環境変数（既定 `v19.0`）でバージョンをスイッチ

参考:
  spec §6-3 トークン交換シーケンス
  https://developers.facebook.com/docs/messenger-platform/reference/send-api
  https://developers.facebook.com/docs/graph-api/reference/page/subscribed_apps/
"""

import logging
import os
from typing import Any, Optional

import httpx


logger = logging.getLogger(__name__)


_DEFAULT_TIMEOUT_SECONDS = 10.0
_GRAPH_BASE_URL = "https://graph.facebook.com"
_DEFAULT_SUBSCRIBED_FIELDS = (
    "messages",
    "messaging_postbacks",
    "message_deliveries",
    "message_reads",
    "messaging_referrals",
    "message_reactions",  # Instagram DM リアクションを受け取るために追加（hotfix 2026-05-14）
)

# NOTE: `/{ig-user-id}/subscribed_apps` は IG Business Account では使用不可（#100 エラー）。
# Instagram DM は Page-level subscription（上記 _DEFAULT_SUBSCRIBED_FIELDS）のみで受信できる。
# 以下の定数は互換性のために残すが、実際には使用しない。
_DEFAULT_INSTAGRAM_SUBSCRIBED_FIELDS = (
    "messages",
    "messaging_postbacks",
    "message_reactions",
)

# subscribed_fields JSONB に Instagram 側のフィールドを保存する際の prefix。
# Page 側の `messages` と Instagram 側の `messages` を区別するために付ける。
INSTAGRAM_FIELD_PREFIX = "instagram:"


# ---------------------------------------------------------------------------
# 例外階層
# ---------------------------------------------------------------------------


class MetaGraphError(Exception):
    """Meta Graph API クライアントの基底例外。"""


class MetaGraphAPIError(MetaGraphError):
    """Meta から返却されたエラーレスポンス（4xx 系で `error` フィールドを持つもの）。

    Attributes:
        status_code: HTTP ステータスコード
        error_type: Meta `error.type`（例: `OAuthException`, `GraphMethodException`）
        error_code: Meta `error.code`（数値、例: 100, 190）
        error_subcode: Meta `error.error_subcode`
        message: Meta `error.message`（PII を含み得るのでログ前に sanitize すること）
        fbtrace_id: Meta のトレース ID（サポート問い合わせ用）
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_type: Optional[str] = None,
        error_code: Optional[int] = None,
        error_subcode: Optional[int] = None,
        fbtrace_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.message = message
        self.fbtrace_id = fbtrace_id

    def to_audit_dict(self) -> dict[str, Any]:
        """audit_logs に書く際の安全な dict（PII を最小化）。"""
        return {
            "status_code": self.status_code,
            "error_type": self.error_type,
            "error_code": self.error_code,
            "error_subcode": self.error_subcode,
            "fbtrace_id": self.fbtrace_id,
        }


class MetaGraphRateLimitError(MetaGraphAPIError):
    """Meta Graph API のレート制限エラー（429 相当）。

    Meta はレート制限を HTTP 429 または error.code 4 / 32 / 613 で返す。
    通常の MetaGraphAPIError と区別することで、呼び出し元が 429 を正しく返せる。

    Attributes:
        retry_after: Retry-After ヘッダー値（秒）。不明時は None。
    """

    # Meta のレート制限を示す error.code 一覧
    RATE_LIMIT_CODES = frozenset({4, 32, 613, 17})

    def __init__(self, message: str, *, status_code: int, retry_after: Optional[int] = None, **kwargs) -> None:
        super().__init__(message, status_code=status_code, **kwargs)
        self.retry_after = retry_after


class MetaGraphTimeoutError(MetaGraphError):
    """Meta Graph API がタイムアウトした。"""


class MetaGraphTransportError(MetaGraphError):
    """ネットワーク失敗 / 5xx / JSON parse 失敗 など、Meta が形式上のエラーを返さなかったケース。"""


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------


def graph_api_version() -> str:
    """環境変数 `META_GRAPH_API_VERSION`（既定 `v19.0`）。"""
    return os.getenv("META_GRAPH_API_VERSION", "v19.0")


def graph_base_url() -> str:
    """`https://graph.facebook.com/v19.0` を返す。"""
    return f"{_GRAPH_BASE_URL}/{graph_api_version()}"


def _app_id() -> str:
    value = os.getenv("META_APP_ID", "")
    if not value:
        raise MetaGraphError("環境変数 META_APP_ID が未設定です")
    return value


def _app_secret() -> str:
    value = os.getenv("META_APP_SECRET", "")
    if not value:
        raise MetaGraphError("環境変数 META_APP_SECRET が未設定です")
    return value


# ---------------------------------------------------------------------------
# 内部 HTTP ラッパ
# ---------------------------------------------------------------------------


async def _request(
    method: str,
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """共通の HTTP 呼び出しラッパ。

    - 4xx で `{"error": {...}}` を返したら `MetaGraphAPIError`
    - timeout は `MetaGraphTimeoutError`
    - その他のネットワーク失敗 / JSON parse 失敗は `MetaGraphTransportError`
    - 2xx かつ JSON object なら dict を返す（list を返す API は MVP では使わない）

    `client` 引数を受け取るのはテスト時に MockTransport を差し込むため。
    本番経路では新規 AsyncClient を `with` 文で開閉する。
    """
    own_client = client is None
    try:
        if own_client:
            client = httpx.AsyncClient(timeout=timeout)
        try:
            response = await client.request(method, url, params=params, data=data)
        finally:
            if own_client:
                await client.aclose()
    except httpx.TimeoutException as e:
        raise MetaGraphTimeoutError(f"Meta Graph API timeout: {method} {url}") from e
    except httpx.HTTPError as e:
        raise MetaGraphTransportError(
            f"Meta Graph API transport error: {method} {url}: {e}"
        ) from e

    # JSON parse
    try:
        body = response.json()
    except ValueError as e:
        raise MetaGraphTransportError(
            f"Meta Graph API returned non-JSON body (status={response.status_code})"
        ) from e

    # Meta のエラー応答は status >= 400 もしくは body に "error" キーを含む
    if isinstance(body, dict) and "error" in body:
        err = body["error"] or {}
        error_code = err.get("code")
        common_kwargs = dict(
            status_code=response.status_code,
            error_type=err.get("type"),
            error_code=error_code,
            error_subcode=err.get("error_subcode"),
            fbtrace_id=err.get("fbtrace_id"),
        )
        message = err.get("message") or "Meta Graph API error (no message)"
        # レート制限コード（4=Application rate limit, 32=Page rate limit,
        # 613=Calls to this API have exceeded the rate limit, 17=User rate limit）
        # または HTTP 429 の場合は MetaGraphRateLimitError を raise する
        if response.status_code == 429 or error_code in MetaGraphRateLimitError.RATE_LIMIT_CODES:
            raise MetaGraphRateLimitError(message, **common_kwargs)
        raise MetaGraphAPIError(message, **common_kwargs)

    if response.status_code >= 400:
        raise MetaGraphTransportError(
            f"Meta Graph API HTTP {response.status_code} (no error payload)"
        )

    if not isinstance(body, dict):
        raise MetaGraphTransportError(
            f"Meta Graph API returned non-dict JSON ({type(body).__name__})"
        )

    return body


# ---------------------------------------------------------------------------
# 公開関数（Sprint 2 で実装するもののみ）
# ---------------------------------------------------------------------------


async def exchange_code_for_short_token(
    code: str,
    redirect_uri: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """OAuth 認可コードを短期 User Access Token に交換する。

    Returns:
        短期 User Access Token 文字列
    """
    if not code:
        raise ValueError("code is required")
    if not redirect_uri:
        raise ValueError("redirect_uri is required")

    url = f"{graph_base_url()}/oauth/access_token"
    body = await _request(
        "GET",
        url,
        params={
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "redirect_uri": redirect_uri,
            "code": code,
        },
        client=client,
    )
    token = body.get("access_token")
    if not token or not isinstance(token, str):
        raise MetaGraphTransportError(
            "Meta /oauth/access_token did not return access_token"
        )
    return token


async def exchange_short_token_for_long_token(
    short_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """短期 User Access Token を長期トークン（約 60 日）に交換する。

    Returns:
        {
            "access_token": "<long-token>",
            "expires_in": 5183944,   # 残秒数（おおよそ 60 日）
            "token_type": "bearer",  # ある場合のみ
        }
    """
    if not short_token:
        raise ValueError("short_token is required")
    url = f"{graph_base_url()}/oauth/access_token"
    body = await _request(
        "GET",
        url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "fb_exchange_token": short_token,
        },
        client=client,
    )
    token = body.get("access_token")
    if not token or not isinstance(token, str):
        raise MetaGraphTransportError(
            "Meta /oauth/access_token (fb_exchange_token) did not return access_token"
        )
    expires_in = body.get("expires_in")
    return {
        "access_token": token,
        "expires_in": expires_in if isinstance(expires_in, int) else None,
        "token_type": body.get("token_type"),
    }


async def refresh_page_access_token(
    current_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """既存の長期 Page Access Token を再延長する（Phase 1-E F1-S2）。

    Meta の Graph API では `grant_type=fb_exchange_token` を使うことで、
    まだ有効な長期トークンをもう一度長期化（≒ 60 日延長）できる。仕組みとしては
    `exchange_short_token_for_long_token` と同じエンドポイントを叩くが、用途が
    「短期 → 長期」ではなく「長期 → 長期（再延長）」である点だけが違う。

    呼び出し側（`app.tasks.refresh_meta_tokens`）の責務:
      - DB から Fernet 復号した平文 token を渡す
      - 戻り値の `access_token` を再び Fernet 暗号化して保存する
      - `expires_in` から `page_token_expires_at` を計算して保存する
      - 失敗時の audit_logs 記録 / is_active 制御

    Returns:
        {
            "access_token": "<refreshed-long-token>",
            "expires_in": 5183944 | None,
            "token_type": "bearer" | None,
        }

    Raises:
        ValueError: current_token が空
        MetaGraphError サブクラス: Meta 側エラー（呼び出し側で audit すること）
    """
    if not current_token:
        raise ValueError("current_token is required")
    url = f"{graph_base_url()}/oauth/access_token"
    body = await _request(
        "GET",
        url,
        params={
            "grant_type": "fb_exchange_token",
            "client_id": _app_id(),
            "client_secret": _app_secret(),
            "fb_exchange_token": current_token,
        },
        client=client,
    )
    token = body.get("access_token")
    if not token or not isinstance(token, str):
        raise MetaGraphTransportError(
            "Meta /oauth/access_token (refresh) did not return access_token"
        )
    expires_in = body.get("expires_in")
    return {
        "access_token": token,
        "expires_in": expires_in if isinstance(expires_in, int) else None,
        "token_type": body.get("token_type"),
    }


async def list_user_pages(
    user_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """接続ユーザーが管理する Page 一覧を取得する（ADR-041: Business Manager 対応）。

    試行する経路:
        1. `/me/accounts`（個人保有 Page）
        2. `/me/businesses` → 各 business に対して以下の 2 経路:
           - `/{business-id}/owned_pages`（business が所有する Page）
           - `/{business-id}/client_pages`（business が代理管理する Page）

    各経路は独立してエラーハンドリングする。**全経路が失敗した場合のみ**
    `MetaGraphAPIError` を集約して raise する（部分失敗は警告ログのみで継続）。

    ### 合成契約（ADR-041 §2.1）

    - 戻り値: ユニーク化済 `list[Page]`（同一 `page.id` は先勝ち）
    - access_token 優先順位: `/me/accounts` > `owned_pages` > `client_pages`
    - rate limit 配慮: `/me/businesses` が 0 件なら `owned_pages`/`client_pages` をスキップ

    Returns:
        list of {"id", "name", "access_token", "instagram_business_account": {...} or None}

    `access_token` は **Page Access Token**。User の長期化を経ているため
    Meta の仕様により Page Token も実質長期となる（公式: User token 長期化 → Page token 長期化）。

    Raises:
        MetaGraphAPIError: 全経路が Meta から API エラーで返ってきた場合のみ。
        MetaGraphTransportError: 全経路が transport error の場合のみ。
    """
    if not user_access_token:
        raise ValueError("user_access_token is required")

    # 集約用バケット。先勝ち dedupe のため list ではなく dict (page_id -> page) で持つ
    aggregated: dict[str, dict[str, Any]] = {}
    errors: list[tuple[str, MetaGraphError]] = []  # (経路名, 例外)
    successes: list[str] = []

    # --- 経路 1: /me/accounts ---
    try:
        me_accounts = await _list_pages_from_me_accounts(user_access_token, client=client)
        successes.append("me_accounts")
        for page in me_accounts:
            pid = page.get("id")
            if pid and pid not in aggregated:
                aggregated[pid] = page
    except MetaGraphError as e:
        logger.warning("list_user_pages: /me/accounts failed: %s", e)
        errors.append(("me_accounts", e))

    # --- 経路 2: /me/businesses → 各 business の owned_pages / client_pages ---
    businesses: list[dict[str, Any]] = []
    try:
        businesses = await _list_user_businesses(user_access_token, client=client)
        successes.append("me_businesses")
    except MetaGraphError as e:
        logger.warning("list_user_pages: /me/businesses failed: %s", e)
        errors.append(("me_businesses", e))

    # rate limit 配慮: businesses が空なら owned/client_pages はスキップ
    if businesses:
        for biz in businesses:
            biz_id = biz.get("id")
            if not biz_id:
                continue

            # owned_pages（owned_pages > client_pages の優先順位なので先に処理）
            try:
                owned = await _list_business_pages(
                    biz_id, "owned_pages", user_access_token, client=client
                )
                successes.append(f"owned_pages:{biz_id}")
                for page in owned:
                    pid = page.get("id")
                    if pid and pid not in aggregated:
                        aggregated[pid] = page
            except MetaGraphError as e:
                logger.warning(
                    "list_user_pages: /%s/owned_pages failed: %s", biz_id, e
                )
                errors.append((f"owned_pages:{biz_id}", e))

            # client_pages
            try:
                client_pages = await _list_business_pages(
                    biz_id, "client_pages", user_access_token, client=client
                )
                successes.append(f"client_pages:{biz_id}")
                for page in client_pages:
                    pid = page.get("id")
                    if pid and pid not in aggregated:
                        aggregated[pid] = page
            except MetaGraphError as e:
                logger.warning(
                    "list_user_pages: /%s/client_pages failed: %s", biz_id, e
                )
                errors.append((f"client_pages:{biz_id}", e))

    # 全経路エラー: 最初の API エラーを raise、無ければ transport error を raise
    if not successes and errors:
        first_api_error = next(
            (e for _, e in errors if isinstance(e, MetaGraphAPIError)), None
        )
        if first_api_error is not None:
            raise first_api_error
        # API エラーが 1 件も無い → transport error
        raise errors[0][1]

    return list(aggregated.values())


async def _list_pages_from_me_accounts(
    user_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """`/me/accounts` から Page 一覧を取り、共通フォーマットで返す（内部 helper）。"""
    url = f"{graph_base_url()}/me/accounts"
    body = await _request(
        "GET",
        url,
        params={
            "fields": "id,name,access_token,instagram_business_account",
            "access_token": user_access_token,
        },
        client=client,
    )
    data = body.get("data", [])
    if not isinstance(data, list):
        raise MetaGraphTransportError("Meta /me/accounts did not return a list")
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "access_token": item.get("access_token"),
                "instagram_business_account": item.get("instagram_business_account"),
            }
        )
    return out


async def _list_user_businesses(
    user_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """`/me/businesses` から Business Manager 一覧を取得する（内部 helper）。"""
    url = f"{graph_base_url()}/me/businesses"
    body = await _request(
        "GET",
        url,
        params={
            "fields": "id,name",
            "access_token": user_access_token,
        },
        client=client,
    )
    data = body.get("data", [])
    if not isinstance(data, list):
        raise MetaGraphTransportError("Meta /me/businesses did not return a list")
    return [item for item in data if isinstance(item, dict) and item.get("id")]


async def _list_business_pages(
    business_id: str,
    edge: str,
    user_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """`/{business-id}/owned_pages` または `/{business-id}/client_pages` から Page 一覧を取得する。

    Args:
        business_id: Business Manager の ID
        edge: "owned_pages" または "client_pages"

    Returns:
        list of {"id", "name", "access_token", "instagram_business_account"}
    """
    if edge not in ("owned_pages", "client_pages"):
        raise ValueError(f"invalid edge: {edge}")
    url = f"{graph_base_url()}/{business_id}/{edge}"
    body = await _request(
        "GET",
        url,
        params={
            "fields": "id,name,access_token,instagram_business_account",
            "access_token": user_access_token,
        },
        client=client,
    )
    data = body.get("data", [])
    if not isinstance(data, list):
        raise MetaGraphTransportError(
            f"Meta /{business_id}/{edge} did not return a list"
        )
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "access_token": item.get("access_token"),
                "instagram_business_account": item.get("instagram_business_account"),
            }
        )
    return out


async def get_instagram_business_account(
    page_id: str,
    page_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict[str, Any]]:
    """Page に紐づく Instagram Business Account を取得する。

    紐付けがなければ None を返す。

    Returns:
        {"id": "<ig-business-id>", "username": "<ig-username>"} or None
    """
    if not page_id:
        raise ValueError("page_id is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    url = f"{graph_base_url()}/{page_id}"
    body = await _request(
        "GET",
        url,
        params={
            "fields": "instagram_business_account{id,username}",
            "access_token": page_access_token,
        },
        client=client,
    )
    iba = body.get("instagram_business_account")
    if not iba or not isinstance(iba, dict):
        return None
    return {"id": iba.get("id"), "username": iba.get("username")}


async def get_user_name(
    psid: str,
    page_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[str]:
    """Page Scoped User ID（PSID / IGSID）から表示名を取得する。

    Phase 1-E F15-S6: Webhook 受信時に新規作成された lead の customer_name を
    実名で埋めるために使用。`pages_messaging` 権限のもとで取得可能。

    エラー時（権限不足、無効な ID、タイムアウト等）は MetaGraph* 例外が伝播するため、
    呼び出し側で握りつぶすこと（webhook 全体を落とさない）。

    Returns:
        ユーザー表示名（取得不能なら None）
    """
    if not psid:
        raise ValueError("psid is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    body = await _request(
        "GET",
        f"{graph_base_url()}/{psid}",
        params={"fields": "name", "access_token": page_access_token},
        client=client,
    )
    name = body.get("name")
    if not name or not isinstance(name, str):
        return None
    return name


async def subscribe_page_to_app(
    page_id: str,
    page_access_token: str,
    *,
    subscribed_fields: Optional[tuple[str, ...]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """Page を本 App の subscribed_apps に登録する（webhook 受信開始）。

    Returns:
        登録した subscribed_fields のリスト
    """
    if not page_id:
        raise ValueError("page_id is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    fields = tuple(subscribed_fields) if subscribed_fields else _DEFAULT_SUBSCRIBED_FIELDS
    url = f"{graph_base_url()}/{page_id}/subscribed_apps"
    body = await _request(
        "POST",
        url,
        params={"access_token": page_access_token},
        data={"subscribed_fields": ",".join(fields)},
        client=client,
    )
    if not body.get("success", False):
        raise MetaGraphTransportError(
            f"Meta /{page_id}/subscribed_apps did not return success=true"
        )
    return list(fields)


async def send_messenger_message(
    *,
    page_access_token: str,
    recipient_id: str,
    text: str,
    messaging_type: str = "RESPONSE",
    tag: Optional[str] = None,
    page_id: str = "me",
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Messenger Send API でテキストメッセージを送信する（spec §3-3 / §5-5）。

    `POST /v19.0/{page_id}/messages?access_token=...`
    body:
        recipient: {"id": <PSID>}
        message:   {"text": <text>}
        messaging_type: 'RESPONSE' | 'MESSAGE_TAG' | 'UPDATE'
        tag:        'HUMAN_AGENT' 等（messaging_type=MESSAGE_TAG のときのみ）

    Returns:
        {"recipient_id": "<PSID>", "message_id": "mid-xxx"}

    Page Access Token は **str のまま受け取る**（呼び出し側で復号済み前提）。
    """
    if not page_access_token:
        raise ValueError("page_access_token is required")
    if not recipient_id:
        raise ValueError("recipient_id is required")
    if not text:
        raise ValueError("text is required")
    if messaging_type not in ("RESPONSE", "MESSAGE_TAG", "UPDATE"):
        raise ValueError(f"invalid messaging_type: {messaging_type}")

    pid = page_id or "me"
    url = f"{graph_base_url()}/{pid}/messages"
    body: dict[str, Any] = {
        "messaging_type": messaging_type,
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    if tag:
        body["tag"] = tag

    # Send API は application/json を期待するため、専用の JSON ヘルパを使う。
    # 内部 `_request` は data を form-encoded で送るのでここでは使わない。
    response = await _send_messages_json(
        url=url,
        access_token=page_access_token,
        body=body,
        client=client,
    )
    return {
        "recipient_id": response.get("recipient_id") or recipient_id,
        "message_id": response.get("message_id"),
    }


async def send_instagram_message(
    *,
    page_access_token: str,
    page_id: str,
    recipient_id: str,
    text: str,
    messaging_type: str = "RESPONSE",
    tag: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Instagram Messaging API でテキストメッセージを送信する（ADR-018）。

    `POST /v19.0/{page_id}/messages?access_token=<page_access_token>`

    Facebook Login for Business 経由のアプリは Messenger Platform の endpoint を使う。
    recipient.id に IGSID を渡すと Meta が Instagram DM としてディスパッチする。
    Messenger 送信（PSID）と同一 endpoint・同一トークンで動作する。
    """
    if not page_id:
        raise ValueError("page_id is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    if not recipient_id:
        raise ValueError("recipient_id is required")
    if not text:
        raise ValueError("text is required")
    if messaging_type not in ("RESPONSE", "MESSAGE_TAG", "UPDATE"):
        raise ValueError(f"invalid messaging_type: {messaging_type}")

    url = f"{graph_base_url()}/{page_id}/messages"
    body: dict[str, Any] = {
        "messaging_type": messaging_type,
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    if tag:
        body["tag"] = tag

    response = await _send_messages_json(
        url=url,
        access_token=page_access_token,
        body=body,
        client=client,
    )
    return {
        "recipient_id": response.get("recipient_id") or recipient_id,
        "message_id": response.get("message_id"),
    }


async def _send_messages_json(
    *,
    url: str,
    access_token: str,
    body: dict[str, Any],
    client: Optional[httpx.AsyncClient],
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Send API 専用の JSON body POST 実装。

    `_request` は `data=` を form-encoded で送るが、Send API は `application/json`
    を期待するためこちらを使う。例外階層は `_request` と同等。
    """
    own_client = client is None
    try:
        if own_client:
            client = httpx.AsyncClient(timeout=timeout)
        try:
            response = await client.request(
                "POST",
                url,
                params={"access_token": access_token},
                json=body,
            )
        finally:
            if own_client:
                await client.aclose()
    except httpx.TimeoutException as e:
        raise MetaGraphTimeoutError(f"Meta Send API timeout: POST {url}") from e
    except httpx.HTTPError as e:
        raise MetaGraphTransportError(
            f"Meta Send API transport error: POST {url}: {e}"
        ) from e

    try:
        rbody = response.json()
    except ValueError as e:
        raise MetaGraphTransportError(
            f"Meta Send API returned non-JSON body (status={response.status_code})"
        ) from e

    if isinstance(rbody, dict) and "error" in rbody:
        err = rbody["error"] or {}
        raise MetaGraphAPIError(
            err.get("message") or "Meta Send API error (no message)",
            status_code=response.status_code,
            error_type=err.get("type"),
            error_code=err.get("code"),
            error_subcode=err.get("error_subcode"),
            fbtrace_id=err.get("fbtrace_id"),
        )

    if response.status_code >= 400:
        raise MetaGraphTransportError(
            f"Meta Send API HTTP {response.status_code} (no error payload)"
        )

    if not isinstance(rbody, dict):
        raise MetaGraphTransportError(
            f"Meta Send API returned non-dict JSON ({type(rbody).__name__})"
        )

    return rbody


async def unsubscribe_page_from_app(
    page_id: str,
    page_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """Page を本 App の subscribed_apps から解除する。

    Returns:
        success=true なら True
    """
    if not page_id:
        raise ValueError("page_id is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    url = f"{graph_base_url()}/{page_id}/subscribed_apps"
    body = await _request(
        "DELETE",
        url,
        params={"access_token": page_access_token},
        client=client,
    )
    return bool(body.get("success", False))


async def subscribe_ig_user_to_app(
    ig_user_id: str,
    page_access_token: str,
    *,
    subscribed_fields: Optional[tuple[str, ...]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """Instagram Business Account を本 App の subscribed_apps に登録する（ADR-024）。

    Page-level subscription と並行して、Instagram Login for Business 経由で
    届く DM/Reaction/Postback を受け取るために IG 側にも明示的に登録する。

    Returns:
        登録した subscribed_fields のリスト
    """
    if not ig_user_id:
        raise ValueError("ig_user_id is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    fields = (
        tuple(subscribed_fields)
        if subscribed_fields
        else _DEFAULT_INSTAGRAM_SUBSCRIBED_FIELDS
    )
    url = f"{graph_base_url()}/{ig_user_id}/subscribed_apps"
    body = await _request(
        "POST",
        url,
        params={"access_token": page_access_token},
        data={"subscribed_fields": ",".join(fields)},
        client=client,
    )
    if not body.get("success", False):
        raise MetaGraphTransportError(
            f"Meta /{ig_user_id}/subscribed_apps did not return success=true"
        )
    return list(fields)


async def get_page_subscribed_apps(
    page_id: str,
    page_access_token: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Page に登録されている subscribed_apps の一覧を取得する（ADR-024 検証用）。

    `GET /{page-id}/subscribed_apps` の戻り値:
        {"data": [{"id": "<app-id>", "name": "<app-name>",
                    "subscribed_fields": ["messages", ...]}, ...]}

    Returns:
        list of {"id", "name", "subscribed_fields"}（順序は Meta 側の返却順）
    """
    if not page_id:
        raise ValueError("page_id is required")
    if not page_access_token:
        raise ValueError("page_access_token is required")
    url = f"{graph_base_url()}/{page_id}/subscribed_apps"
    body = await _request(
        "GET",
        url,
        params={"access_token": page_access_token},
        client=client,
    )
    data = body.get("data", [])
    if not isinstance(data, list):
        raise MetaGraphTransportError(
            f"Meta /{page_id}/subscribed_apps did not return a data list"
        )
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "subscribed_fields": item.get("subscribed_fields") or [],
            }
        )
    return out


__all__ = [
    "MetaGraphError",
    "MetaGraphAPIError",
    "MetaGraphTimeoutError",
    "MetaGraphTransportError",
    "INSTAGRAM_FIELD_PREFIX",
    "graph_api_version",
    "graph_base_url",
    "exchange_code_for_short_token",
    "exchange_short_token_for_long_token",
    "refresh_page_access_token",
    "list_user_pages",
    "get_instagram_business_account",
    "subscribe_page_to_app",
    "subscribe_ig_user_to_app",
    "get_page_subscribed_apps",
    "unsubscribe_page_from_app",
    "send_messenger_message",
    "send_instagram_message",
]
