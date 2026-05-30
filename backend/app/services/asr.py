from __future__ import annotations

import audioop
import os
import threading
import wave
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import httpx

from app.config import Settings

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class ASRUnavailableError(RuntimeError):
    pass


class ASRRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class ASRTranscript:
    text: str
    provider: str


@dataclass(frozen=True)
class ASRHealth:
    available: bool
    provider: str | None
    model: str | None
    ready: bool
    warming: bool
    detail: str | None = None


@dataclass
class _WarmupState:
    ready: bool = False
    warming: bool = False
    detail: str | None = None


_WARMUP_LOCK = threading.Lock()
_WARMUP_STATE: dict[tuple[str, str | None, str, str], _WarmupState] = {}

_TRADITIONAL_TO_SIMPLIFIED = str.maketrans(
    {
        "會": "会",
        "議": "议",
        "點": "点",
        "號": "号",
        "鐘": "钟",
        "臺": "台",
        "個": "个",
        "這": "这",
        "裡": "里",
        "說": "说",
        "話": "话",
        "時": "时",
        "間": "间",
        "氣": "气",
        "體": "体",
        "週": "周",
        "為": "为",
        "開": "开",
        "門": "门",
        "辦": "办",
        "網": "网",
        "曆": "历",
        "曉": "晓",
        "覺": "觉",
        "讓": "让",
        "與": "与",
        "後": "后",
        "幫": "帮",
        "麼": "么",
        "見": "见",
        "電": "电",
        "腦": "脑",
        "輸": "输",
        "入": "入",
        "法": "法",
    }
)


def _extract_result_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("text", "transcript", "sentence_info"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, list):
        parts = [_extract_result_text(item) for item in payload]
        return " ".join(part for part in parts if part).strip()
    return ""


def _faster_whisper_is_installed() -> bool:
    try:
        import_module("faster_whisper")
    except ImportError:
        return False
    return True


def _normalize_transcript_text(text: str) -> str:
    normalized = text.translate(_TRADITIONAL_TO_SIMPLIFIED).strip()
    normalized = normalized.replace("幫我", "帮我").replace("提醒一下", "提醒")
    normalized = normalized.replace("行事历", "日历")
    normalized = normalized.replace("曰程", "日程")
    normalized = normalized.replace("几月几号", "几月几号")
    normalized = normalized.replace("有一个会议", "有会议")
    normalized = normalized.replace("有个会议", "有会议")
    normalized = normalized.replace("有一个会", "有会")
    return normalized


def _normalize_wav_audio(audio: bytes, filename: str) -> bytes:
    suffix = Path(filename or "voice.wav").suffix.lower()
    if suffix != ".wav":
        return audio

    try:
        with NamedTemporaryFile(suffix=".wav", delete=False) as input_file:
            input_file.write(audio)
            input_path = input_file.name

        with wave.open(input_path, "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            frame_rate = reader.getframerate()
            frame_count = reader.getnframes()
            frames = reader.readframes(frame_count)
    except Exception:
        if "input_path" in locals() and os.path.exists(input_path):
            os.unlink(input_path)
        return audio
    finally:
        if "input_path" in locals() and os.path.exists(input_path):
            os.unlink(input_path)

    if not frames or sample_width not in (1, 2, 4):
        return audio

    try:
        rms = audioop.rms(frames, sample_width)
        peak = audioop.max(frames, sample_width)
    except Exception:
        return audio

    if rms <= 1 and peak <= 16:
        raise ASRRequestError("录音几乎没有有效人声输入，请检查当前麦克风或远程桌面音频输入。")

    if peak <= 0:
        return audio

    max_value = float((1 << (8 * sample_width - 1)) - 1)
    target_peak = max_value * 0.75
    gain = min(12.0, max(1.0, target_peak / float(peak)))
    if gain <= 1.05:
        return audio

    try:
        boosted = audioop.mul(frames, sample_width, gain)
        with NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = output_file.name
        with wave.open(output_path, "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(sample_width)
            writer.setframerate(frame_rate)
            writer.writeframes(boosted)
        normalized = Path(output_path).read_bytes()
    except Exception:
        if "output_path" in locals() and os.path.exists(output_path):
            os.unlink(output_path)
        return audio
    finally:
        if "output_path" in locals() and os.path.exists(output_path):
            os.unlink(output_path)

    return normalized


def _warmup_key(settings: Settings) -> tuple[str, str | None, str, str]:
    return (
        settings.asr_provider,
        settings.asr_model,
        settings.asr_device,
        settings.asr_compute_type,
    )


def _get_warmup_state(settings: Settings) -> _WarmupState:
    key = _warmup_key(settings)
    with _WARMUP_LOCK:
        return _WARMUP_STATE.setdefault(key, _WarmupState())


@lru_cache(maxsize=4)
def _load_faster_whisper_model(model_name: str, device: str, compute_type: str):
    faster_whisper = import_module("faster_whisper")
    return faster_whisper.WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
    )


class FasterWhisperService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return self.settings.asr_provider == "faster-whisper" and _faster_whisper_is_installed()

    def provider_name(self) -> str:
        return "faster-whisper"

    def health(self) -> ASRHealth:
        configured = self.is_configured()
        state = _get_warmup_state(self.settings)
        detail = state.detail
        if not configured:
            detail = detail or "未安装 faster-whisper 依赖。"
        elif not state.ready and not state.warming:
            detail = detail or "语音模型尚未加载，首次请求会触发加载。"
        return ASRHealth(
            available=configured,
            provider=self.provider_name(),
            model=self.settings.asr_model,
            ready=configured and state.ready,
            warming=configured and state.warming,
            detail=detail,
        )

    def warmup(self) -> None:
        state = _get_warmup_state(self.settings)
        if state.ready or state.warming:
            return
        with _WARMUP_LOCK:
            if state.ready or state.warming:
                return
            state.warming = True
            state.detail = "正在加载语音模型。"
        try:
            if self.settings.asr_provider != "faster-whisper":
                raise ASRUnavailableError("当前未启用 faster-whisper。")
            if not _faster_whisper_is_installed():
                raise ASRUnavailableError("未安装 faster-whisper，请先安装 voice 依赖。")
            _load_faster_whisper_model(
                self.settings.asr_model or "base",
                self.settings.asr_device,
                self.settings.asr_compute_type,
            )
        except Exception as exc:
            with _WARMUP_LOCK:
                state.ready = False
                state.warming = False
                state.detail = f"语音模型加载失败：{exc}"
            raise
        with _WARMUP_LOCK:
            state.ready = True
            state.warming = False
            state.detail = "语音模型已就绪。"

    def transcribe(
        self,
        *,
        filename: str,
        audio: bytes,
        content_type: str,
        locale: str = "zh-CN",
    ) -> ASRTranscript:
        del content_type
        if self.settings.asr_provider != "faster-whisper":
            raise ASRUnavailableError("当前未启用 faster-whisper。")
        if not _faster_whisper_is_installed():
            raise ASRUnavailableError("未安装 faster-whisper，请先安装 voice 依赖。")
        if not audio:
            raise ASRRequestError("音频内容为空。")
        audio = _normalize_wav_audio(audio, filename)

        model_name = self.settings.asr_model or "base"
        suffix = Path(filename or "voice.webm").suffix or ".webm"
        temp_path: str | None = None
        state = _get_warmup_state(self.settings)
        try:
            self.warmup()
            model = _load_faster_whisper_model(
                model_name,
                self.settings.asr_device,
                self.settings.asr_compute_type,
            )
            with NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
                temp_file.write(audio)
                temp_path = temp_file.name
            segments, _ = model.transcribe(
                temp_path,
                language="zh" if locale.startswith("zh") else None,
                task="transcribe",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                condition_on_previous_text=False,
            )
            text = " ".join(
                segment.text.strip()
                for segment in segments
                if getattr(segment, "text", "").strip()
            ).strip()
        except ASRUnavailableError:
            raise
        except Exception as exc:  # pragma: no cover - external runtime failures
            with _WARMUP_LOCK:
                state.detail = f"语音转写失败：{exc}"
            raise ASRRequestError("faster-whisper 转写失败。") from exc
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

        if not text:
            raise ASRRequestError("faster-whisper 未返回文本。")
        with _WARMUP_LOCK:
            state.ready = True
            state.detail = "语音模型已就绪。"
        return ASRTranscript(text=_normalize_transcript_text(text), provider=self.provider_name())


class ThirdPartyASRService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def is_configured(self) -> bool:
        return bool(self.settings.asr_api_url and self.settings.asr_model)

    def provider_name(self) -> str:
        return self.settings.asr_provider

    def health(self) -> ASRHealth:
        configured = self.is_configured()
        detail = None if configured else "后端未配置第三方语音识别服务。"
        return ASRHealth(
            available=configured,
            provider=self.provider_name(),
            model=self.settings.asr_model,
            ready=configured,
            warming=False,
            detail=detail,
        )

    def warmup(self) -> None:
        return

    def transcribe(
        self,
        *,
        filename: str,
        audio: bytes,
        content_type: str,
        locale: str = "zh-CN",
    ) -> ASRTranscript:
        if not self.is_configured():
            raise ASRUnavailableError("后端未配置第三方语音识别服务。")
        if not audio:
            raise ASRRequestError("音频内容为空。")

        headers: dict[str, str] = {}
        if self.settings.asr_api_key:
            headers["Authorization"] = f"Bearer {self.settings.asr_api_key}"

        files = {"file": (filename, audio, content_type or "application/octet-stream")}
        data = {
            "model": self.settings.asr_model or "",
            "language": locale.split("-", 1)[0],
            "response_format": "json",
        }
        try:
            with httpx.Client(timeout=self.settings.asr_timeout_seconds) as client:
                response = client.post(
                    self.settings.asr_api_url,
                    headers=headers,
                    data=data,
                    files=files,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ASRRequestError("第三方语音识别请求失败。") from exc

        payload = response.json()
        text = _extract_result_text(payload)
        if not text:
            raise ASRRequestError("第三方语音识别未返回文本。")
        return ASRTranscript(text=_normalize_transcript_text(text), provider=self.provider_name())


class ASRService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.local = FasterWhisperService(settings)
        self.third_party = ThirdPartyASRService(settings)

    def health(self) -> ASRHealth:
        if self.settings.asr_provider == "faster-whisper":
            return self.local.health()
        return self.third_party.health()

    def is_configured(self) -> bool:
        return self.health().available

    def warmup(self) -> None:
        if self.settings.asr_provider == "faster-whisper":
            self.local.warmup()
            return
        self.third_party.warmup()

    def warmup_async(self) -> None:
        thread = threading.Thread(target=self._safe_warmup, daemon=True, name="voice-asr-warmup")
        thread.start()

    def _safe_warmup(self) -> None:
        try:
            self.warmup()
        except Exception:
            return

    def transcribe(
        self,
        *,
        filename: str,
        audio: bytes,
        content_type: str,
        locale: str = "zh-CN",
    ) -> ASRTranscript:
        if self.settings.asr_provider == "faster-whisper":
            return self.local.transcribe(
                filename=filename,
                audio=audio,
                content_type=content_type,
                locale=locale,
            )
        return self.third_party.transcribe(
            filename=filename,
            audio=audio,
            content_type=content_type,
            locale=locale,
        )
