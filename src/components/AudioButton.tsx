import { Headphones, Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, withToken } from "../lib/api";
import { Button } from "./ui";

/** Écouter : la version audio est générée à la première demande puis mise en cache. */
export function AudioButton({ file, generatePath, label = "Écouter", compact }: { file: string | null; generatePath: string; label?: string; compact?: boolean }) {
  const [name, setName] = useState(file);
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => audio.current?.pause(), []);
  useEffect(() => setName(file), [file]);

  async function toggle() {
    setError(null);
    if (playing) {
      audio.current?.pause();
      return;
    }
    try {
      let n = name;
      if (!n) {
        setBusy(true);
        n = (await api<{ file: string }>(generatePath, { method: "POST" })).file;
        setName(n);
      }
      if (!audio.current) {
        audio.current = new Audio(await withToken(`/audio/${n}`));
        audio.current.onplay = () => setPlaying(true);
        audio.current.onpause = () => setPlaying(false);
        audio.current.onended = () => setPlaying(false);
      }
      await audio.current.play();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="inline-flex items-center gap-2">
      <Button size={compact ? "sm" : "md"} onClick={toggle} busy={busy} title={compact ? label : undefined} icon={playing ? <Pause size={14} /> : name ? <Play size={14} /> : <Headphones size={14} />}>
        {compact ? (busy ? "Audio…" : playing ? "Pause" : "Écouter") : busy ? "Préparation de l'audio" : playing ? "Pause" : label}
      </Button>
      {error && <span className="text-[12px] text-deny">{error}</span>}
    </span>
  );
}
