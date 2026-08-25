import hmac

from fastapi import Header, HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict


class LabSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSPILOT_LAB_", extra="ignore")

    token: str = ""


def require_lab_token(
    x_opspilot_lab_token: str | None = Header(default=None),
) -> None:
    expected = LabSettings().token
    if (
        not expected
        or x_opspilot_lab_token is None
        or not hmac.compare_digest(x_opspilot_lab_token, expected)
    ):
        raise HTTPException(status_code=401, detail="invalid lab token")
