from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    client_key: str = os.getenv("TIKTOK_CLIENT_KEY", "")
    client_secret: str = os.getenv("TIKTOK_CLIENT_SECRET", "")
    redirect_uri: str = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8000/auth/callback/")
    scopes: str = os.getenv("TIKTOK_SCOPES", "user.info.basic,video.publish,video.upload")
    session_secret: str = os.getenv("SESSION_SECRET", "dev-only-change-me")
    database_path: Path = Path(os.getenv("DATABASE_PATH", "./data/tiktok_local.db"))
    queue_dir: Path = Path(os.getenv("QUEUE_DIR", "./data/queue"))

    def validate_for_oauth(self) -> None:
        missing = []
        if not self.client_key:
            missing.append("TIKTOK_CLIENT_KEY")
        if not self.client_secret:
            missing.append("TIKTOK_CLIENT_SECRET")
        if missing:
            raise RuntimeError("Faltan variables: " + ", ".join(missing))


settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
settings.queue_dir.mkdir(parents=True, exist_ok=True)
