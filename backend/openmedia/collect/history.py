"""Lecture locale de l'historique des navigateurs (Chrome, Edge, Brave, Vivaldi, Opera, Firefox).

L'historique est lu sur ce PC, seulement dans les navigateurs que le lecteur a cochés, et
seulement s'il a activé l'option. Seules les pages qui ressemblent à des articles d'actualité
sont retenues ; tout le reste (recherches, messageries, réseaux sociaux, banques…) est ignoré
avant le moindre enregistrement. Des titres ne partent à l'IA que si le lecteur l'a accepté
(sujets de tes lectures, `readings_ai`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

# Navigateurs à moteur Chromium : dossier « User Data » qui contient un dossier par profil.
CHROMIUM = {
    "chrome": ("Google Chrome", ("LOCALAPPDATA", "Google/Chrome/User Data")),
    "chrome_beta": ("Google Chrome Beta", ("LOCALAPPDATA", "Google/Chrome Beta/User Data")),
    "chrome_dev": ("Google Chrome Dev", ("LOCALAPPDATA", "Google/Chrome Dev/User Data")),
    "chrome_canary": ("Google Chrome Canary", ("LOCALAPPDATA", "Google/Chrome SxS/User Data")),
    "edge": ("Microsoft Edge", ("LOCALAPPDATA", "Microsoft/Edge/User Data")),
    "edge_beta": ("Microsoft Edge Beta", ("LOCALAPPDATA", "Microsoft/Edge Beta/User Data")),
    "edge_dev": ("Microsoft Edge Dev", ("LOCALAPPDATA", "Microsoft/Edge Dev/User Data")),
    "edge_canary": ("Microsoft Edge Canary", ("LOCALAPPDATA", "Microsoft/Edge SxS/User Data")),
    "brave": ("Brave", ("LOCALAPPDATA", "BraveSoftware/Brave-Browser/User Data")),
    "brave_beta": ("Brave Beta", ("LOCALAPPDATA", "BraveSoftware/Brave-Browser-Beta/User Data")),
    "brave_nightly": ("Brave Nightly", ("LOCALAPPDATA", "BraveSoftware/Brave-Browser-Nightly/User Data")),
    "vivaldi": ("Vivaldi", ("LOCALAPPDATA", "Vivaldi/User Data")),
    "chromium": ("Chromium", ("LOCALAPPDATA", "Chromium/User Data")),
    "comet": ("Comet (Perplexity)", ("LOCALAPPDATA", "Perplexity/Comet/User Data")),
    "yandex": ("Yandex Browser", ("LOCALAPPDATA", "Yandex/YandexBrowser/User Data")),
    "thorium": ("Thorium", ("LOCALAPPDATA", "Thorium/User Data")),
    "cent": ("Cent Browser", ("LOCALAPPDATA", "CentBrowser/User Data")),
    "epic": ("Epic Privacy Browser", ("LOCALAPPDATA", "Epic Privacy Browser/User Data")),
    "slimjet": ("Slimjet", ("LOCALAPPDATA", "Slimjet/User Data")),
    "coccoc": ("Cốc Cốc", ("LOCALAPPDATA", "CocCoc/Browser/User Data")),
    "maxthon": ("Maxthon", ("LOCALAPPDATA", "Maxthon/Application/User Data")),
    "iridium": ("Iridium", ("LOCALAPPDATA", "Iridium/User Data")),
    "sidekick": ("Sidekick", ("LOCALAPPDATA", "Sidekick/User Data")),
    "wavebox": ("Wavebox", ("LOCALAPPDATA", "WaveboxApp/User Data")),
    "torch": ("Torch", ("LOCALAPPDATA", "Torch/User Data")),
    "360chrome": ("360 Chrome", ("LOCALAPPDATA", "360chrome/Chrome/User Data")),
    "qq": ("QQ Browser", ("LOCALAPPDATA", "Tencent/QQBrowser/User Data")),
}
# Opera range l'historique directement dans le dossier du profil.
OPERA = {
    "opera": ("Opera", ("APPDATA", "Opera Software/Opera Stable")),
    "opera_gx": ("Opera GX", ("APPDATA", "Opera Software/Opera GX Stable")),
    "opera_air": ("Opera Air", ("APPDATA", "Opera Software/Opera Air Stable")),
    "opera_beta": ("Opera Beta", ("APPDATA", "Opera Software/Opera Next")),
    "opera_dev": ("Opera Developer", ("APPDATA", "Opera Software/Opera Developer")),
}
# Navigateurs à moteur Gecko : dossier « Profiles » avec un places.sqlite par profil.
GECKO = {
    "firefox": ("Firefox", ("APPDATA", "Mozilla/Firefox/Profiles")),
    "librewolf": ("LibreWolf", ("APPDATA", "librewolf/Profiles")),
    "waterfox": ("Waterfox", ("APPDATA", "Waterfox/Profiles")),
    "floorp": ("Floorp", ("APPDATA", "Floorp/Profiles")),
    "zen": ("Zen Browser", ("APPDATA", "zen/Profiles")),
    "mullvad": ("Mullvad Browser", ("APPDATA", "Mullvad/MullvadBrowser/Profiles")),
    "palemoon": ("Pale Moon", ("APPDATA", "Moonchild Productions/Pale Moon/Profiles")),
    "seamonkey": ("SeaMonkey", ("APPDATA", "Mozilla/SeaMonkey/Profiles")),
}
CHROME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


@dataclass
class Profile:
    browser: str
    browser_name: str
    profile: str  # identifiant (dossier)
    label: str  # nom affiché
    path: Path  # fichier d'historique
    kind: str  # chromium | firefox

    def as_dict(self) -> dict:
        modified = datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc) if self.path.exists() else None
        return {"browser": self.browser, "browser_name": self.browser_name, "profile": self.profile, "label": self.label, "kind": self.kind, "modified": modified}


@dataclass
class Visit:
    url: str
    title: str
    visits: int
    first_visit: datetime
    last_visit: datetime
    synced: int = 0  # visites venues d'un autre appareil du même compte (téléphone…)


def _base(env_and_rel: tuple[str, str]) -> Path:
    env, rel = env_and_rel
    return Path(os.environ.get(env, "")) / rel


def _chromium_profiles(key: str, name: str, root: Path) -> list[Profile]:
    labels = {}
    try:
        state = json.loads((root / "Local State").read_text(encoding="utf-8"))
        labels = {k: v.get("name", k) for k, v in state.get("profile", {}).get("info_cache", {}).items()}
    except (OSError, ValueError):
        pass
    out = []
    try:
        dirs = sorted(root.iterdir())
    except OSError:
        return out
    for d in dirs:
        if d.is_dir() and (d.name == "Default" or d.name.startswith("Profile ")) and (d / "History").exists():
            out.append(Profile(key, name, d.name, labels.get(d.name, d.name), d / "History", "chromium"))
    return out


def _gecko_profiles(key: str, name: str, root: Path) -> list[Profile]:
    out = []
    try:
        dirs = sorted(root.iterdir())
    except OSError:
        return out
    for d in dirs:
        if (d / "places.sqlite").exists():
            out.append(Profile(key, name, d.name, d.name.split(".", 1)[-1], d / "places.sqlite", "firefox"))
    return out


def _arc_profiles() -> list[Profile]:
    """Arc (The Browser Company) s'installe comme une application du Store, sous Packages."""
    out = []
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Packages"
    if packages.exists():
        for pkg in packages.glob("TheBrowserCompany.Arc*"):
            root = pkg / "LocalCache/Local/Arc/User Data"
            if root.exists():
                out += _chromium_profiles("arc", "Arc", root)
    return out


def detect() -> list[Profile]:
    """Les navigateurs connus présents sur ce PC, et leurs profils. Ne lit pas l'historique.
    Aucune exploration du disque au-delà de cette liste (un client de messagerie ou une
    application qui embarque Chromium n'est pas un navigateur) : un autre navigateur s'ajoute
    à la main, par son fichier d'historique (`profile_from_file`)."""
    found: list[Profile] = []
    for key, (name, where) in CHROMIUM.items():
        root = _base(where)
        if root.exists():
            found += _chromium_profiles(key, name, root)
    for key, (name, where) in OPERA.items():
        root = _base(where)
        if (root / "History").exists():
            found.append(Profile(key, name, "Default", "Profil principal", root / "History", "chromium"))
    for key, (name, where) in GECKO.items():
        root = _base(where)
        if root.exists():
            found += _gecko_profiles(key, name, root)
    found += _arc_profiles()
    return found


def profile_from_file(path: str) -> Profile:
    """Un fichier d'historique choisi à la main (navigateur absent de la liste, copie, autre disque)."""
    f = Path(path.strip().strip('"'))
    if f.is_dir():
        f = f / ("places.sqlite" if (f / "places.sqlite").exists() else "History")
    if not f.exists():
        raise FileNotFoundError(f"Fichier introuvable : {f}")
    kind = "firefox" if f.name == "places.sqlite" else "chromium"
    return Profile(f"fichier:{f}", "Fichier choisi", str(f), f.parent.name, f, kind)


def _open_copy(path: Path) -> tuple[sqlite3.Connection, Path | None]:
    """Copie la base (le navigateur ouvert la verrouille) ; à défaut, lecture seule « immuable »."""
    tmpdir = Path(tempfile.mkdtemp(prefix="openmedia-history-"))
    try:
        target = tmpdir / path.name
        shutil.copy2(path, target)
        for suffix in ("-wal", "-journal"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                try:
                    shutil.copy2(side, tmpdir / side.name)
                except OSError:
                    pass
        return sqlite3.connect(target), tmpdir
    except OSError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True), None


def read_visits(profile: Profile, since: datetime) -> list[Visit]:
    con, tmpdir = _open_copy(profile.path)
    try:
        if profile.kind == "chromium":
            threshold = int((since - CHROME_EPOCH).total_seconds() * 1_000_000)
            # Avec la synchronisation de l'historique, Chrome et Edge rangent aussi les visites faites
            # sur le téléphone : `originator_cache_guid` est alors rempli (appareil d'origine).
            cols = {r[1] for r in con.execute("PRAGMA table_info(visits)")}
            synced = "SUM(CASE WHEN COALESCE(v.originator_cache_guid, '') != '' THEN 1 ELSE 0 END)" if "originator_cache_guid" in cols else "0"
            rows = con.execute(
                f"SELECT u.url, u.title, COUNT(*), MIN(v.visit_time), MAX(v.visit_time), {synced} FROM visits v JOIN urls u ON u.id = v.url "
                "WHERE v.visit_time > ? GROUP BY u.id",
                (threshold,),
            ).fetchall()
            to_dt = lambda t: CHROME_EPOCH + timedelta(microseconds=t)  # noqa: E731
        else:
            threshold = int(since.timestamp() * 1_000_000)
            rows = con.execute(
                "SELECT p.url, p.title, COUNT(*), MIN(h.visit_date), MAX(h.visit_date), 0 FROM moz_historyvisits h JOIN moz_places p ON p.id = h.place_id "
                "WHERE h.visit_date > ? GROUP BY p.id",
                (threshold,),
            ).fetchall()
            to_dt = lambda t: datetime.fromtimestamp(t / 1_000_000, tz=timezone.utc)  # noqa: E731
        return [Visit(url=u, title=(t or "").strip(), visits=n, first_visit=to_dt(a), last_visit=to_dt(b), synced=sy or 0) for u, t, n, a, b, sy in rows if u]
    finally:
        con.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Ce qui est un article d'actualité ────────────────────────────────────────

EXCLUDED_DOMAINS = {
    "google.com", "google.fr", "bing.com", "duckduckgo.com", "qwant.com", "ecosia.org", "yahoo.com", "startpage.com", "perplexity.ai",
    "youtube.com", "youtu.be", "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com", "linkedin.com", "reddit.com", "t.me", "discord.com",
    "whatsapp.com", "messenger.com", "snapchat.com", "pinterest.com", "twitch.tv", "netflix.com", "primevideo.com", "disneyplus.com", "spotify.com", "deezer.com",
    "github.com", "gitlab.com", "stackoverflow.com", "npmjs.com", "pypi.org", "claude.ai", "anthropic.com", "openai.com", "chatgpt.com", "notion.so",
    "amazon.fr", "amazon.com", "leboncoin.fr", "cdiscount.com", "fnac.com", "ebay.fr", "ebay.com", "aliexpress.com", "vinted.fr",
    "live.com", "outlook.com", "office.com", "microsoft.com", "microsoftonline.com", "gmail.com", "proton.me", "icloud.com", "apple.com",
    "wikipedia.org", "wiktionary.org", "doctolib.fr", "ameli.fr", "impots.gouv.fr", "caf.fr", "laposte.net", "orange.fr", "free.fr", "sfr.fr", "bouyguestelecom.fr",
    "paypal.com", "boursorama-banque.com", "credit-agricole.fr", "societegenerale.fr", "bnpparibas", "labanquepostale.fr", "lcl.fr", "revolut.com",
    "crunchyroll.com", "animationdigitalnetwork.fr", "adn.fr", "canalplus.com", "mycanal.fr", "france.tv", "molotov.tv", "arte.tv/fr/videos", "6play.fr", "m6plus.fr", "tf1.fr",
    "steampowered.com", "epicgames.com", "instant-gaming.com", "fandom.com", "allocine.fr", "imdb.com", "booking.com", "airbnb.fr", "tripadvisor.fr",
    "localhost", "deepl.com", "canva.com", "figma.com", "dropbox.com", "wetransfer.com",
}
EXCLUDED_PREFIXES = ("mail.", "accounts.", "login.", "auth.", "docs.", "drive.", "calendar.", "app.", "admin.", "my.", "espace-client.", "console.")
DATE_IN_PATH = re.compile(r"/20\d\d/(0?[1-9]|1[0-2])/|/20\d\d-\d\d-\d\d|/\d{8}/")
LONG_ID = re.compile(r"\d{6,}")
NEWSY_DOMAIN = re.compile(r"news|actu|info|journal|presse|press|gazette|tribune|times|post|herald|monde|matin|soir|depeche|courrier|observ|mag(azine)?|media|radio|tv|telegraph|reporter|daily|hebdo|quotidien")
_IP = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def _slug_words(path: str) -> int:
    last = [p for p in path.split("/") if p]
    if not last:
        return 0
    seg = max(last, key=len)
    return len([w for w in re.split(r"[-_]", seg) if w.isalpha() and len(w) > 1])


def is_news(url: str, title: str, known: dict) -> bool:
    """`known` : registre {domaine: kind}. Une page de rubrique ou d'accueil n'est pas un article."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    host = parts.hostname.lower().removeprefix("www.")
    if _IP.match(host) or host.endswith(".local") or host.startswith(EXCLUDED_PREFIXES):
        return False
    from ..sources.registry import registered_domain  # import local : évite un cycle au chargement

    domain = registered_domain(url)
    if domain in EXCLUDED_DOMAINS or any(domain.startswith(d) for d in ("google.", "amazon.", "bnpparibas")):
        return False
    path = parts.path or "/"
    if any(k in (parts.query or "") for k in ("q=", "query=", "search=")) or "/search" in path:
        return False
    articleish = bool(DATE_IN_PATH.search(path)) or bool(LONG_ID.search(path)) or _slug_words(path) >= 4
    kind = known.get(domain) or known.get(host)
    if kind == "unknown":  # domaine inscrit au registre mais jamais qualifié : reste un inconnu
        kind = None
    if kind == "reseau_social":
        return False
    if kind:  # média connu : il faut encore que la page soit un article, pas une rubrique
        return articleish
    # Site inconnu : il faut un vrai signal de presse (date dans l'adresse, ou un nom de domaine
    # de journal) en plus d'une page d'article ; sinon boutiques, jeux, streaming passeraient.
    pressy = bool(NEWSY_DOMAIN.search(domain))
    return (bool(DATE_IN_PATH.search(path)) or pressy) and _slug_words(path) >= 3 and len(title) >= 25
