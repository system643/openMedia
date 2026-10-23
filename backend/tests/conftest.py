import os
import tempfile

# Base de données jetable : à fixer avant tout import d'openmedia.
os.environ["OPENMEDIA_DATA"] = tempfile.mkdtemp(prefix="openmedia-tests-")
# Le jeu ouvert de notation n'est pas dans le dépôt : un petit jeu synthétique le remplace.
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

shutil.copy(Path(__file__).parent / "fixtures" / "domain_quality_sample.csv", Path(os.environ["OPENMEDIA_DATA"]) / "domain_quality.csv")
os.environ["OPENMEDIA_NO_SCHEDULER"] = "1"
os.environ["OPENMEDIA_EXTRA_HOSTS"] = "testserver"  # nom d'hôte du TestClient
os.environ.pop("ANTHROPIC_API_KEY", None)
for _var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "KIMI_API_KEY", "ZAI_API_KEY", "ZHIPU_API_KEY", "DASHSCOPE_API_KEY", "QWEN_API_KEY", "XAI_API_KEY", "OPENMEDIA_COMPATIBLE_KEY"):
    os.environ.pop(_var, None)

# Les clés ne touchent jamais le Gestionnaire d'identifiants réel pendant les tests.
import keyring  # noqa: E402
from keyring.backend import KeyringBackend  # noqa: E402


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


keyring.set_keyring(MemoryKeyring())


# Les tests supposent les conditions de fonctionnement acceptées (le tutoriel est passé) ;
# ceux qui vérifient le consentement l'effacent eux-mêmes.
from openmedia.config import update_settings  # noqa: E402

update_settings({"consent_at": "2026-01-01T00:00:00+00:00"})
