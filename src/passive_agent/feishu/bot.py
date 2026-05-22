from __future__ import annotations

import asyncio
import json
import os

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
    CallBackToast,
)

from passive_agent.feishu.callbacks import CallbackHandler
from passive_agent.feishu.cards import CardBuilder
from passive_agent.feishu.commands import CommandHandler
from passive_agent.integrations.deepseek import DeepSeekClient
from passive_agent.storage.database import Database
from passive_agent.storage.models import EnrichedItem
from passive_agent.utils.config import AppConfig
from passive_agent.utils.logger import log


def _run_async(coro):
    """Run async coroutine safely - handles case where event loop may already be running."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result(timeout=60)


class FeishuBot:
    """飞书 Bot - 长连接模式"""

    def __init__(self, config: AppConfig, db: Database, llm: DeepSeekClient | None = None):
        self.config = config
        self.db = db
        self.llm = llm

        self.app_id = os.environ.get("FEISHU_APP_ID", "")
        self.app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        self.chat_id = os.environ.get("FEISHU_CHAT_ID", "")

        if not self.app_id or not self.app_secret:
            raise ValueError("FEISHU_APP_ID and FEISHU_APP_SECRET must be set")

        self.client = lark.Client.builder() \
            .app_id(self.app_id) \
            .app_secret(self.app_secret) \
            .log_level(lark.LogLevel.WARNING) \
            .build()

        self.callback_handler = CallbackHandler(config, db, llm)
        self.command_handler = CommandHandler(db)

    def start(self):
        """启动飞书长连接 WebSocket 服务"""
        event_handler = lark.EventDispatcherHandler.builder(
            "", ""
        ).register_p2_im_message_receive_v1(
            self._on_message
        ).register_p2_card_action_trigger(
            self._on_card_action
        ).build()

        ws_client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO,
        )

        log.info("Feishu Bot starting (WebSocket long connection)...")
        ws_client.start()

    def _on_message(self, data):
        """处理收到的文本消息 (P2ImMessageReceiveV1)"""
        try:
            msg = data.event.message
            chat_id = msg.chat_id
            content = json.loads(msg.content)
            text = content.get("text", "").strip()

            # @机器人的消息会包含 @mention 标记，去除它
            if msg.mentions:
                for mention in msg.mentions:
                    text = text.replace(f"@_{mention.key}", "").strip()

            if not self.chat_id:
                self.chat_id = chat_id
                log.info(f"Auto-detected chat_id: {chat_id} (set FEISHU_CHAT_ID to persist)")

            if not text:
                return

            log.info(f"Received message from {chat_id}: {text}")
            response = _run_async(self.command_handler.handle(text))

            if response:
                self._reply_text(chat_id, response)
        except Exception as e:
            log.error(f"Error handling message: {e}")

    def _on_card_action(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse | None:
        """处理卡片按钮回调（通过 EventDispatcher 注册）"""
        try:
            action_value = data.event.action.value
            open_chat_id = data.event.context.open_chat_id if data.event.context else None
            log.info(f"Card action: {action_value}")

            result = _run_async(self.callback_handler.handle(action_value))

            if result is None:
                return None

            if result["type"] == "toast":
                return self._toast(result["text"])
            elif result["type"] == "new_message":
                chat_id = open_chat_id or self.chat_id
                if chat_id:
                    self._send_card(chat_id, result["card"])
                return None

        except Exception as e:
            log.error(f"Error handling card action: {e}")
            return self._toast(f"处理失败：{e}", toast_type="error")

    def send_daily_card(self, items: list[EnrichedItem]) -> bool:
        """发送每日推荐卡片"""
        if not self.chat_id:
            log.warning("FEISHU_CHAT_ID not set, skipping push")
            return False

        if self.command_handler.is_paused:
            log.info("Push is paused, skipping")
            return False

        card = CardBuilder.build_daily_card(items)
        if self._send_card(self.chat_id, card):
            log.info(f"Daily card sent to chat {self.chat_id}")
            return True
        return False

    def send_weekend_card(self, items: list[EnrichedItem]) -> bool:
        """发送周末阅读推荐卡片"""
        if not self.chat_id:
            log.warning("FEISHU_CHAT_ID not set, skipping weekend push")
            return False

        card = CardBuilder.build_weekend_card(items)
        if self._send_card(self.chat_id, card):
            log.info(f"Weekend card sent to chat {self.chat_id} ({len(items)} items)")
            return True
        return False

    def send_error_notification(self, error: str):
        """发送错误通知"""
        if not self.chat_id:
            return

        card = CardBuilder.build_result_card(
            "⚠ 今日处理失败",
            f"**原因：** {error}\n**处理：** 明日将补推今日内容",
            success=False,
        )
        self._send_card(self.chat_id, card)

    def _send_card(self, chat_id: str, card: dict) -> bool:
        """发送卡片消息"""
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(json.dumps(card, ensure_ascii=False))
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)
        if not response.success():
            log.error(f"Failed to send card: {response.code} - {response.msg}")
            return False
        return True

    def _reply_text(self, chat_id: str, text: str):
        """回复文本消息"""
        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            ).build()

        response = self.client.im.v1.message.create(request)
        if not response.success():
            log.error(f"Failed to reply: {response.code} - {response.msg}")

    def _toast(self, text: str, toast_type: str = "info") -> P2CardActionTriggerResponse:
        resp = P2CardActionTriggerResponse()
        resp.toast = CallBackToast()
        resp.toast.type = toast_type
        resp.toast.content = text
        return resp
