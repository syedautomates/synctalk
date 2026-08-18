from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- control plane ---
    database_url: str = "postgresql+psycopg://avatar:avatar@localhost:5432/avatar_studio"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "avatar-studio"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    jwt_secret: str = "dev-secret-change-me"
    founder_email: str = "founder@example.com"
    worker_token: str = "dev-worker-token-change-me"

    # --- external APIs ---
    elevenlabs_api_key: str = ""
    elevenlabs_tts_model: str = "eleven_v3"
    elevenlabs_fallback_model: str = "eleven_multilingual_v2"
    elevenlabs_default_voice_id: str = ""
    anthropic_api_key: str = ""
    orchestrator_model: str = "claude-sonnet-5"


settings = Settings()
