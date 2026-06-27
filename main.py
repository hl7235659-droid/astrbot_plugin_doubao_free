"""
AstrBot 豆包免费 API 插件
填入 dola.com Cookie 即可使用：聊天、图片识别、文生图、视频生成
"""

import asyncio
import os
import re
import time
from pathlib import Path

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain, Video
from astrbot.api.star import Context, Star, register
from astrbot.core.message.message_event_result import MessageChain

from .dola_client import DolaPool, CreditError

# 临时文件目录
DATA_DIR = Path(os.environ.get("DOUBAO_FREE_DATA_DIR", "/AstrBot/data/doubao_free"))


@register("doubao_free", "豆包免费API", "填入Cookie即可使用豆包聊天/图片识别/文生图/视频生成", "1.0.0")
class Main(Star):
    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self.config = config
        self.pool: DolaPool = None
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    async def initialize(self):
        """AstrBot 加载配置后调用"""
        config = self.config or {}
        # AstrBotConfig 是 dict 子类，但保险起见转一下
        if hasattr(config, "get"):
            cookies = config.get("cookies", [])
        else:
            cookies = config.get("cookies", []) if isinstance(config, dict) else []
        if isinstance(cookies, str):
            cookies = [c.strip() for c in cookies.split("\n") if c.strip()]
        cookies = [c for c in cookies if c and not c.startswith("#")]

        if not cookies:
            logger.warning("[doubao_free] 未配置 Cookie，请在插件配置中填入 dola.com 的 Cookie")
            self.pool = None
            return

        api_base = config.get("api_base", "https://www.dola.com") if hasattr(config, "get") else "https://www.dola.com"
        self.pool = DolaPool(
            cookies,
            api_base=api_base,
            video_timeout=config.get("video_poll_timeout", 300) if hasattr(config, "get") else 300,
            image_timeout=config.get("image_poll_timeout", 120) if hasattr(config, "get") else 120,
            max_retry=config.get("max_retry", 2) if hasattr(config, "get") else 2,
        )
        logger.info(f"[doubao_free] 已加载 {len(self.pool.clients)} 个有效 Cookie")

    # ===== 指令：聊天 =====

    @filter.command("豆包")
    async def chat_cmd(self, event: AstrMessageEvent):
        """直接和豆包聊天（绕过 LLM provider）"""
        if not self._check_ready():
            yield event.plain_result("插件未配置 Cookie，请在 AstrBot 管理面板填写 dola.com 的 Cookie")
            return
        prompt = event.get_message_str().strip()
        prompt = re.sub(r"^/?豆包\s*", "", prompt).strip()
        if not prompt:
            yield event.plain_result("请输入内容，例如：/豆包 你好")
            return
        try:
            reply = await self.pool.chat([{"role": "user", "content": prompt}])
            yield event.plain_result(reply or "(空回复)")
        except Exception as e:
            logger.error(f"[doubao_free] 聊天失败: {e}")
            yield event.plain_result(f"聊天失败: {str(e)[:100]}")

    # ===== 指令：图片识别 =====

    @filter.command("识图")
    async def vision_cmd(self, event: AstrMessageEvent):
        """识别图片内容"""
        if not self._check_ready():
            yield event.plain_result("插件未配置 Cookie，请在 AstrBot 管理面板填写 dola.com 的 Cookie")
            return
        # 从消息中提取图片
        image_url = await self._extract_image(event)
        if not image_url:
            yield event.plain_result("请发送一张图片，或回复图片后发送 /识图 你的问题")
            return
        prompt = re.sub(r"^/?识图\s*", "", event.get_message_str().strip()).strip()
        if not prompt:
            prompt = "请用中文详细描述这张图片的内容"
        yield event.plain_result("正在识别图片，请稍候...")
        try:
            result = await self.pool.vision(image_url, prompt)
            yield event.plain_result(result or "(识别失败)")
        except Exception as e:
            yield event.plain_result(f"图片识别失败: {str(e)[:100]}")

    # ===== 指令：文生图 =====

    @filter.command("生图")
    async def image_cmd(self, event: AstrMessageEvent):
        """文生图"""
        if not self._check_ready():
            yield event.plain_result("插件未配置 Cookie，请在 AstrBot 管理面板填写 dola.com 的 Cookie")
            return
        prompt = re.sub(r"^/?生图\s*", "", event.get_message_str().strip()).strip()
        if not prompt:
            yield event.plain_result("请提供描述，例如：/生图 一只可爱的橘猫")
            return
        yield event.plain_result("正在生成图片，请稍候...")
        try:
            image_url = await self.pool.generate_image(prompt)
            # 下载到本地
            local_path = await self._download_file(image_url, ".jpg")
            if local_path:
                yield event.image_result(local_path)
            else:
                yield event.plain_result(f"图片已生成但下载失败: {image_url}")
        except Exception as e:
            yield event.plain_result(f"生图失败: {str(e)[:100]}")

    # ===== 指令：视频生成 =====

    @filter.command("生成视频")
    async def video_cmd(self, event: AstrMessageEvent):
        """生成视频"""
        if not self._check_ready():
            yield event.plain_result("插件未配置 Cookie，请在 AstrBot 管理面板填写 dola.com 的 Cookie")
            return
        prompt = event.get_message_str().strip()
        prompt = re.sub(r"^/?生成视频\s*", "", prompt).strip()
        if not prompt:
            yield event.plain_result("请提供描述，例如：/生成视频 一只小猫追蝴蝶 16:9 5秒")
            return
        prompt, ratio, duration = self._parse_video_params(prompt)
        if not prompt:
            yield event.plain_result("请提供视频描述内容")
            return
        yield event.plain_result(
            f"收到喵~ 正在生成视频：{prompt}\n比例 {ratio}，时长 {duration}秒，预计 2-4 分钟，请稍候..."
        )
        # 后台异步生成 + 推送
        session_id = event.unified_msg_origin
        asyncio.create_task(self._video_task(prompt, ratio, duration, session_id))

    @filter.command("视频")
    async def video_alias(self, event: AstrMessageEvent):
        """视频生成别名"""
        if not self._check_ready():
            yield event.plain_result("插件未配置 Cookie，请在 AstrBot 管理面板填写 dola.com 的 Cookie")
            return
        prompt = event.get_message_str().strip()
        prompt = re.sub(r"^/?视频\s*", "", prompt).strip()
        if not prompt:
            yield event.plain_result("请提供描述，例如：/视频 一只小猫追蝴蝶 16:9 5秒")
            return
        prompt, ratio, duration = self._parse_video_params(prompt)
        if not prompt:
            yield event.plain_result("请提供视频描述内容")
            return
        yield event.plain_result(
            f"收到喵~ 正在生成视频：{prompt}\n比例 {ratio}，时长 {duration}秒，预计 2-4 分钟，请稍候..."
        )
        session_id = event.unified_msg_origin
        asyncio.create_task(self._video_task(prompt, ratio, duration, session_id))

    async def _video_task(self, prompt: str, ratio: str, duration: int, session_id: str):
        """后台视频生成任务"""
        try:
            video_url = await self.pool.generate_video(prompt, ratio, duration)
            local_path = await self._download_file(video_url, ".mp4")
            if local_path and Path(local_path).exists():
                logger.info(f"[doubao_free] 视频已保存，开始推送: {local_path}")
                await self.context.send_message(
                    session_id,
                    MessageChain([Video.fromFileSystem(local_path)]),
                )
                logger.info(f"[doubao_free] 视频已推送: {local_path}")
            else:
                await self.context.send_message(
                    session_id,
                    MessageChain([Plain("视频已生成但下载失败，请稍后重试")]),
                )
        except CreditError as e:
            await self.context.send_message(
                session_id,
                MessageChain([Plain(f"视频生成失败（所有账号额度不足）: {str(e)[:80]}")]),
            )
        except Exception as e:
            logger.error(f"[doubao_free] 视频任务异常: {e}")
            try:
                await self.context.send_message(
                    session_id,
                    MessageChain([Plain(f"视频生成失败: {str(e)[:100]}")]),
                )
            except Exception:
                pass

    # ===== 工具方法 =====

    def _check_ready(self) -> bool:
        """检查插件是否就绪"""
        if not self.pool or not self.pool.available:
            return False
        return True

    def _parse_video_params(self, raw: str) -> tuple:
        """解析视频参数：比例 + 时长，支持自然语言和 --ratio/--duration"""
        prompt = raw
        ratio = "9:16"
        duration = 5

        # 显式参数
        if "--ratio" in prompt:
            parts = prompt.split("--ratio")
            prompt = parts[0].strip()
            ratio = parts[1].strip().split()[0] if parts[1].strip() else "9:16"
        if "--duration" in prompt:
            parts = prompt.split("--duration")
            prompt = parts[0].strip()
            try:
                duration = int(parts[1].strip().split()[0])
            except (ValueError, IndexError):
                duration = 5

        # 自然语言：比例
        m = re.search(r"\b(1[69]:\d{1,2}|9:1[69]|1:1|4:3|3:4|21:9)\b", prompt)
        if m:
            ratio = m.group(1)
            prompt = (prompt[:m.start()] + prompt[m.end():]).strip()

        # 自然语言：时长
        m = re.search(r"(\d+)\s*(秒|s|S)", prompt)
        if m:
            try:
                duration = int(m.group(1))
            except ValueError:
                duration = 5
            prompt = (prompt[:m.start()] + prompt[m.end():]).strip()

        duration = max(3, min(10, duration))
        return prompt.strip(), ratio, duration

    async def _extract_image(self, event: AstrMessageEvent) -> str:
        """从消息中提取图片 URL 或 base64"""
        for comp in event.get_messages():
            if isinstance(comp, Image):
                url = getattr(comp, "url", "") or getattr(comp, "file", "")
                if url:
                    return url
        return ""

    async def _download_file(self, url: str, ext: str) -> str:
        """下载文件到本地，返回路径"""
        ts = int(time.time())
        local_path = DATA_DIR / f"file_{ts}{ext}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        logger.error(f"[doubao_free] 下载失败 HTTP {resp.status}: {url[:80]}")
                        return None
                    data = await resp.read()
                    with open(local_path, "wb") as f:
                        f.write(data)
                    logger.info(f"[doubao_free] 下载成功: {local_path} ({len(data)} bytes)")
                    return str(local_path)
        except Exception as e:
            logger.error(f"[doubao_free] 下载异常: {e}")
            return None

    async def terminate(self):
        pass
