import sys
import types

import pytest

from app.config import Settings
from app.services.asr import ASRRequestError, ASRService, _load_faster_whisper_model


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeWhisperModel:
    def __init__(self, model_name: str, device: str, compute_type: str) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, *_args, **_kwargs):
        return iter([FakeSegment("明天上午十点开会")]), {"language": "zh"}


def test_faster_whisper_service_uses_local_model(monkeypatch) -> None:
    _load_faster_whisper_model.cache_clear()
    fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)

    service = ASRService(
        Settings(
            asr_provider="faster-whisper",
            asr_model="base",
            asr_device="cpu",
            asr_compute_type="int8",
        )
    )

    assert service.is_configured() is True
    before = service.health()
    assert before.available is True
    result = service.transcribe(
        filename="voice.wav",
        audio=b"fake-wav-data",
        content_type="audio/wav",
        locale="zh-CN",
    )

    assert result.provider == "faster-whisper"
    assert result.text == "明天上午十点开会"
    after = service.health()
    assert after.ready is True


def test_faster_whisper_service_rejects_empty_audio(monkeypatch) -> None:
    _load_faster_whisper_model.cache_clear()
    fake_module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    service = ASRService(Settings(asr_provider="faster-whisper"))

    with pytest.raises(ASRRequestError):
        service.transcribe(
            filename="voice.wav",
            audio=b"",
            content_type="audio/wav",
        )
