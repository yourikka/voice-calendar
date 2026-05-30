from app.api import get_asr_service
from app.main import app
from app.services.asr import ASRHealth, ASRTranscript, ASRUnavailableError


class FakeASRService:
    def is_configured(self) -> bool:
        return True

    def health(self) -> ASRHealth:
        return ASRHealth(
            available=True,
            provider="fake-asr",
            model="fake-model",
            ready=True,
            warming=False,
            detail="语音模型已就绪。",
        )

    def transcribe(self, **_: object) -> ASRTranscript:
        return ASRTranscript(text="明早八点提醒我带身份证", provider="fake-asr")


class FakeUnavailableASRService:
    def is_configured(self) -> bool:
        return False

    def health(self) -> ASRHealth:
        return ASRHealth(
            available=False,
            provider="fake-asr",
            model="fake-model",
            ready=False,
            warming=False,
            detail="后端未配置第三方语音识别服务。",
        )

    def transcribe(self, **_: object) -> ASRTranscript:
        raise ASRUnavailableError("后端未配置第三方语音识别服务。")


def test_voice_capabilities_defaults_to_unconfigured(client) -> None:
    app.dependency_overrides[get_asr_service] = lambda: FakeUnavailableASRService()
    try:
        response = client.get("/api/voice/capabilities")
    finally:
        app.dependency_overrides.pop(get_asr_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["server_asr_available"] is False
    assert body["provider"] == "fake-asr"
    assert body["ready"] is False


def test_voice_command_transcribes_and_executes(client) -> None:
    app.dependency_overrides[get_asr_service] = lambda: FakeASRService()
    try:
        response = client.post(
            "/api/voice/commands",
            data={
                "timezone": "Asia/Shanghai",
                "locale": "zh-CN",
                "now": "2026-05-29T10:00:00+08:00",
            },
            files={"audio": ("voice.webm", b"fake-audio", "audio/webm")},
        )
    finally:
        app.dependency_overrides.pop(get_asr_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["asr_provider"] == "fake-asr"
    assert body["intent"] == "create_reminder"
    assert body["event"]["title"] == "带身份证"
    assert body["transcript"] == "明早八点提醒我带身份证"


def test_voice_command_returns_503_without_asr_config(client) -> None:
    app.dependency_overrides[get_asr_service] = lambda: FakeUnavailableASRService()
    try:
        response = client.post(
            "/api/voice/commands",
            data={"timezone": "Asia/Shanghai", "locale": "zh-CN"},
            files={"audio": ("voice.webm", b"fake-audio", "audio/webm")},
        )
    finally:
        app.dependency_overrides.pop(get_asr_service, None)

    assert response.status_code == 503
