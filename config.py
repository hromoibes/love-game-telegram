import os
from dataclasses import dataclass


class MissingEnvError(RuntimeError):
    """Raised when a required environment variable is absent."""


@dataclass
class Settings:
    telegram_token: str
    ai_api_key: str
    base_url: str
    port: int

    @classmethod
    def load(cls) -> "Settings":
        telegram_token = os.environ.get("TELEGRAM_TOKEN")
        ai_api_key = os.environ.get("AI_API_KEY")
        base_url = os.environ.get("BASE_URL")
        port = int(os.environ.get("PORT", "10000"))

        missing = [name for name, value in (
            ("TELEGRAM_TOKEN", telegram_token),
            ("AI_API_KEY", ai_api_key),
            ("BASE_URL", base_url),
        ) if not value]

        if missing:
            raise MissingEnvError(
                f"Отсутствуют переменные окружения: {', '.join(missing)}. "
                "Проверьте конфигурацию перед запуском."
            )

        return cls(
            telegram_token=telegram_token,
            ai_api_key=ai_api_key,
            base_url=base_url.rstrip("/"),
            port=port,
        )


settings = Settings.load()
