from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- control plane ---
    database_url: str = "postgresql+psycopg://avatar:avatar@localhost:5432/avatar_studio"
    s3_endpoint: str = "http://localhost:9000"
    # URL external clients (browser, curl) use to reach S3 for presigned upload/download.
    # Differs from s3_endpoint only in local dev, where the API reaches MinIO via the
    # docker network hostname but the browser/host machine must use localhost instead.
    s3_public_endpoint: str = ""
    s3_bucket: str = "avatar-studio"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "auto"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 30  # 30 days; single-user tool, no refresh flow
    founder_email: str = "founder@example.com"
    worker_token: str = "dev-worker-token-change-me"

    # --- external APIs ---
    elevenlabs_api_key: str = ""
    elevenlabs_tts_model: str = "eleven_v3"
    elevenlabs_fallback_model: str = "eleven_multilingual_v2"
    elevenlabs_default_voice_id: str = ""
    anthropic_api_key: str = ""
    orchestrator_model: str = "claude-sonnet-5"

    @property
    def s3_public_endpoint_or_default(self) -> str:
        return self.s3_public_endpoint or self.s3_endpoint


settings = Settings()
