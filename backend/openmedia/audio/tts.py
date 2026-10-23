"""Version audio des fiches et du Brief : un script écrit pour l'oreille, lu par Edge TTS."""

from __future__ import annotations

from ..agents.llm import LLM, RunMeter, get_llm
from ..agents.material import as_json
from ..config import data_dir, load_settings
from ..db import session
from ..models import Brief, Fiche


# Règlement européen sur l'IA, art. 50 : un texte généré par IA le dit, y compris à l'oral.
AI_NOTICE = "Ce texte a été rédigé par une intelligence artificielle, à partir des articles cités dans openMedia."


async def speak(text: str, name: str) -> str:
    import edge_tts  # aiohttp et compagnie : chargés seulement quand on parle

    path = data_dir() / "audio" / f"{name}.mp3"
    await edge_tts.Communicate(text, load_settings().voice, rate="+4%").save(str(path))
    return path.name


async def fiche_audio(fiche_id: int, llm: LLM | None = None) -> str:
    with session() as s:
        fiche = s.get(Fiche, fiche_id)
    if fiche.audio_path:
        return fiche.audio_path
    settings = load_settings()
    llm = llm or get_llm()
    names = {src["ref"]: src["name"] for src in fiche.sources}
    meter = RunMeter()
    script = await llm.text(meter, model=settings.models.topic, task="audio", content=f"<sources>\n{as_json(names)}\n</sources>\n\n<fiche>\n{as_json(fiche.content)}\n</fiche>", effort="low", max_tokens=3000)
    from ..agents.topic_agent import log_run

    log_run("audio", meter, fiche.topic_id)
    name = await speak(f"{AI_NOTICE}\n\n{script}", f"fiche-{fiche.topic_id}-v{fiche.version}")
    with session() as s:
        f = s.get(Fiche, fiche_id)
        f.audio_path = name
        s.add(f)
        s.commit()
    return name


async def brief_audio(brief_id: int) -> str:
    with session() as s:
        brief = s.get(Brief, brief_id)
    if brief.audio_path:
        return brief.audio_path
    name = await speak(f"{AI_NOTICE}\n\n{brief.content.get('audio_script') or brief.content.get('headline', '')}", f"brief-{brief.day}-{brief.id}")
    with session() as s:
        b = s.get(Brief, brief_id)
        b.audio_path = name
        s.add(b)
        s.commit()
    return name
