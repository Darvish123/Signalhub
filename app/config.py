from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    app_env: str = "development"
    database_path: str = "./data/signalhub.db"
    bitunix_futures_base_url: str = "https://fapi.bitunix.com"
    bitunix_spot_base_url: str = "https://www.bitunix.com"
    request_timeout_seconds: float = 12.0
    min_quote_volume_24h: float = 1_000_000
    min_score: int = 70
    min_net_rr: float = 2.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
