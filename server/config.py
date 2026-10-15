import base64
import contextvars
import json
import os
from functools import lru_cache

from databricks.sdk import WorkspaceClient

IS_DATABRICKS_APP = bool(os.environ.get("DATABRICKS_APP_NAME"))
UC_CATALOG = os.environ.get("UC_CATALOG", "lanl")
UC_SCHEMA = os.environ.get("UC_SCHEMA", "dol_ui")
SECRET_SCOPE = os.environ.get("SECRET_SCOPE", "dol_ui")

DEFAULT_PERSONA = "investigator"
PERSONAS = {
    "investigator": {
        "label": "Federal investigator",
        "role": "All states · PII cleared",
        "identity": "App service principal",
    },
    "federal_analyst": {
        "label": "Federal analyst",
        "role": "All states · PII masked",
        "identity": "dol-ui-persona-federal-analyst",
        "env": "PERSONA_FEDERAL_ANALYST",
        "secret": "persona_federal_analyst",
    },
    "ca_analyst": {
        "label": "CA EDD state analyst",
        "role": "California only · PII masked",
        "identity": "dol-ui-persona-ca-state-analyst",
        "env": "PERSONA_CA_ANALYST",
        "secret": "persona_ca_analyst",
    },
}
persona_var: contextvars.ContextVar[str] = contextvars.ContextVar("persona", default=DEFAULT_PERSONA)


class PersonaUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_workspace_client() -> WorkspaceClient:
    if IS_DATABRICKS_APP:
        return WorkspaceClient()
    profile = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")
    return WorkspaceClient(profile=profile)


def persona_credentials(name: str) -> dict | None:
    spec = PERSONAS.get(name) or {}
    if "env" not in spec:
        return None
    raw = os.environ.get(spec["env"])
    if not raw:
        try:
            raw = base64.b64decode(get_workspace_client().secrets.get_secret(SECRET_SCOPE, spec["secret"]).value).decode()
        except Exception:  # noqa: BLE001
            return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


@lru_cache(maxsize=8)
def persona_client(name: str) -> WorkspaceClient:
    if name not in PERSONAS or name == DEFAULT_PERSONA:
        return get_workspace_client()
    creds = persona_credentials(name)
    if not creds:
        raise PersonaUnavailable(f"Credentials for persona {name} are not configured")
    return WorkspaceClient(host=get_workspace_host(), client_id=creds["client_id"], client_secret=creds["client_secret"], auth_type="oauth-m2m")


def current_persona() -> str:
    name = persona_var.get()
    return name if name in PERSONAS else DEFAULT_PERSONA


def get_oauth_token() -> str:
    client = get_workspace_client()
    headers = client.config.authenticate()
    auth = headers.get("Authorization", "")
    return auth.replace("Bearer ", "")


def get_workspace_host() -> str:
    if IS_DATABRICKS_APP:
        host = os.environ.get("DATABRICKS_HOST", "")
        if host and not host.startswith("http"):
            host = f"https://{host}"
        return host
    return get_workspace_client().config.host


def fq(table: str) -> str:
    return f"{UC_CATALOG}.{UC_SCHEMA}.{table}"
