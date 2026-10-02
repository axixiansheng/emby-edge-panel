import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    db_file: str
    panel_password: str
    cf_token: str
    cf_zone: str
    base_domain: str
    panel_name: str
    panel_domain: str
    secret: str
    cert_dir: str

    @classmethod
    def load(cls):
        values = {}
        path = Path(os.environ.get("EMBY_ENV_FILE", "/opt/emby_panel/.env"))
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines():
                if raw.strip() and not raw.lstrip().startswith("#") and "=" in raw:
                    key, value = raw.split("=", 1)
                    values[key.strip()] = value.strip().strip("\"'")
        values.update(os.environ)
        required = ("PANEL_PASSWORD", "CF_API_TOKEN", "CF_ZONE_ID", "BASE_DOMAIN", "GLOBAL_SECRET_KEY")
        # docker run --env-file retains quotes, unlike Compose's default env parser.
        for key in required + ("PANEL_NAME", "PANEL_DOMAIN"):
            if key in values:
                values[key] = values[key].strip().strip("\"'")
        missing = [key for key in required if not values.get(key)]
        if missing:
            raise RuntimeError("Missing configuration: " + ", ".join(missing))
        return cls(
            values.get("EMBY_DB_FILE", "/opt/emby_panel/db/panel.db"),
            values["PANEL_PASSWORD"], values["CF_API_TOKEN"], values["CF_ZONE_ID"],
            values["BASE_DOMAIN"].lower(), values.get("PANEL_NAME", "Emby Edge"),
            values.get("PANEL_DOMAIN", "").lower(), values["GLOBAL_SECRET_KEY"],
            values.get("EMBY_CERT_DIR", "/etc/letsencrypt/live/emby-edge-wildcard"),
        )
