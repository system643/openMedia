// « Enregistrements » : les articles mis de côté depuis la languette. On les découvre avant de
// décider : rassembler d'autres sources, suivre le sujet, ou supprimer.

import * as Tooltip from "@radix-ui/react-tooltip";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, ChevronDown, ChevronRight, ExternalLink, Layers, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { FactPanel } from "../components/FactPanel";
import { openLink, SourceChip } from "../components/Facts";
import { Popover } from "../components/Popover";
import { MediaAvatar, OWNER_LABEL, ownerColor } from "../components/MediaAvatar";
import { Logo } from "../components/Logo";
import { Button, Empty, PageHeader, Segmented, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { usePageChrome } from "../lib/chrome";
import { euros, relative, shortDate } from "../lib/format";
import { nav } from "../lib/nav";
import type { DossierPoint, Factcheck, Recording, SourceRef, Topic } from "../lib/types";

type Filter = "enregistre" | "suivi" | "tous";

export function RecordingsView({ id, follow }: { id?: number; follow?: boolean }) {
  const [filter, setFilter] = useState<Filter>("enregistre");
  const [selectedId, setSelectedId] = useState<number | null>(id ?? null);
  const list = useQuery({ queryKey: ["recordings"], queryFn: () => api<Recording[]>("/recordings") });
  usePageChrome("Enregistrements");

  const all = list.data ?? [];
  const rows = all.filter((r) => filter === "tous" || r.status === filter);
  const selected = all.find((r) => r.id === selectedId) ?? rows[0] ?? null;
  useEffect(() => {
    if (id) setSelectedId(id);
  }, [id]);
  // Arrivé depuis la languette (« Voir ») : montrer l'enregistrement même s'il est déjà suivi.
  useEffect(() => {
    if (id && all.some((r) => r.id === id && r.status === "suivi")) setFilter("tous");
  }, [id, list.data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (list.data && all.length === 0)
    return (
      <div className="px-10 pb-24 pt-6">
        <div className="mx-auto max-w-[720px]">
          <PageHeader title="Enregistrements" />
          <Empty icon={<Bookmark size={22} />} title="Garde un article pour plus tard.">
            Quand tu lis un article dans ton navigateur, la languette au bord droit de l'écran prend la couleur d'accent. Survole-la puis clique sur « Enregistrer », ou appuie sur Ctrl + Alt + S. Tu peux aussi y glisser un lien. L'article arrive ici sans être suivi : tu décides ensuite.
          </Empty>
        </div>
      </div>
    );

  return (
    <Tooltip.Provider>
      <div className="px-8 pb-24 pt-6">
        <div className="mx-auto max-w-[1240px]">
          <PageHeader title="Enregistrements" subtitle="Les articles mis de côté depuis ton navigateur. Rassemble d'autres sources pour comprendre le sujet, puis suis-le ou supprime-le." />
          <div className="flex items-start gap-6">
            <section className="w-[360px] shrink-0">
              <div className="mb-3">
                <Segmented<Filter>
                  label="Statut"
                  value={filter}
                  onChange={setFilter}
                  options={[
                    { value: "enregistre", label: `À décider${count(all, "enregistre")}` },
                    { value: "suivi", label: `Suivis${count(all, "suivi")}` },
                    { value: "tous", label: "Tous" },
                  ]}
                />
              </div>
              {list.isLoading && <div className="py-16"><Spinner /></div>}
              {list.data && rows.length === 0 && <p className="py-12 text-center text-[14px] text-ink-2">Rien ici.</p>}
              {rows.length > 0 && (
                <div className="card divide-y divide-line overflow-hidden">
                  {rows.map((r) => (
                    <Row key={r.id} r={r} active={r.id === selected?.id} onSelect={() => setSelectedId(r.id)} />
                  ))}
                </div>
              )}
            </section>
            <section className="min-w-0 flex-1">{selected && <Detail key={`${selected.id}-${follow && selected.id === id ? "suivre" : ""}`} r={selected} follow={!!follow && selected.id === id} onDeleted={() => setSelectedId(null)} />}</section>
          </div>
        </div>
      </div>
    </Tooltip.Provider>
  );
}

function count(all: Recording[], status: Recording["status"]) {
  const n = all.filter((r) => r.status === status).length;
  return n ? ` · ${n}` : "";
}

function Row({ r, active, onSelect }: { r: Recording; active: boolean; onSelect: () => void }) {
  const state = r.dossier.status;
  return (
    <button onClick={onSelect} className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors ${active ? "bg-accent-soft" : "hover:bg-fill/50"}`}>
      <MediaAvatar m={r} />
      <div className="min-w-0 flex-1">
        <p className="line-clamp-2 text-[13.5px] font-medium leading-snug text-ink">{r.title}</p>
        <p className="mt-0.5 flex items-center gap-1.5 text-[12px] text-ink-2">
          <span className="truncate">{r.media}</span>
          <span className="text-ink-3">·</span>
          <span className="shrink-0">{relative(r.created_at)}</span>
          {state === "en_cours" && <span className="shrink-0 text-accent">· sources en cours</span>}
          {state === "ok" && <span className="shrink-0 text-ok">· dossier prêt</span>}
          {r.status === "suivi" && <span className="shrink-0 text-accent">· suivi</span>}
        </p>
      </div>
    </button>
  );
}

function Detail({ r, follow, onDeleted }: { r: Recording; follow: boolean; onDeleted: () => void }) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: ["recordings"] });
  const gather = useMutation({ mutationFn: () => api(`/recordings/${r.id}/gather`, { method: "POST" }), onSuccess: refresh });
  const quick = useMutation({ mutationFn: () => api<Factcheck>(`/recordings/${r.id}/quickcheck${r.quickcheck ? "?force=true" : ""}`, { method: "POST" }), onSuccess: refresh });
  const quickResult = quick.data ?? r.quickcheck;
  const remove = useMutation({ mutationFn: () => api(`/recordings/${r.id}`, { method: "DELETE" }), onSuccess: () => { onDeleted(); void refresh(); } });
  const [confirm, setConfirm] = useState(false);
  const d = r.dossier;
  const running = d.status === "en_cours" || gather.isPending;

  return (
    <article className="card p-6">
      <div className="flex items-start gap-3">
        <MediaAvatar m={r} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-ink">{r.media}</p>
          <p className="text-[12px] text-ink-2">
            {r.owner && r.owner !== r.domain ? `${r.owner}${r.controller ? ` (${r.controller})` : ""}, ` : ""}
            {r.kind === "recherche" ? "recherche" : OWNER_LABEL[r.owner_type] ?? r.owner_type}
          </p>
        </div>
      </div>
      <h2 className="serif mt-4 text-[24px] font-medium leading-snug text-ink">{r.title}</h2>
      <p className="mt-1.5 text-[12.5px] text-ink-2">
        Enregistré {relative(r.created_at)}
        {r.published_at ? ` · publié le ${shortDate(r.published_at)}` : ""}
        {!r.readable ? " · texte non lu (paywall ou page protégée)" : ""}
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button size="sm" icon={<ExternalLink size={13} />} onClick={() => openLink(r.url)}>
          Ouvrir
        </Button>
        <Button size="sm" variant="primary" busy={running} icon={<Layers size={13} />} onClick={() => gather.mutate()}>
          {running ? "Recherche en cours…" : d.status === "ok" ? "Rassembler à nouveau" : "Rassembler des sources"}
        </Button>
        <Button size="sm" busy={quick.isPending} icon={<ShieldCheck size={13} />} onClick={() => quick.mutate()} title="Recoupe les faits de l'article avec d'autres médias, avec Haiku seulement : quelques secondes, moins d'un dixième de centime.">
          {quick.isPending ? "Vérification…" : r.quickcheck ? "Revérifier" : "Vérifier"}
        </Button>
        {r.status === "suivi" && r.topic_id ? <FollowedIn topicId={r.topic_id} /> : <FollowMenu r={r} defaultOpen={follow} />}
        <span className="ml-auto">
          {!confirm ? (
            <Button size="sm" variant="danger" icon={<Trash2 size={13} />} onClick={() => setConfirm(true)}>
              Supprimer
            </Button>
          ) : (
            <span className="inline-flex gap-1.5">
              <Button size="sm" variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
                Confirmer
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirm(false)}>
                Annuler
              </Button>
            </span>
          )}
        </span>
      </div>
      {running && <p className="mt-3 text-[12.5px] text-ink-2">Recherche d'autres médias sur le même sujet, recoupement des faits, puis synthèse : une à trois minutes. Tu peux quitter la page.</p>}
      {gather.error && <p className="mt-3 text-[12.5px] text-deny">{gather.error.message}</p>}
      {quick.error && <p className="mt-3 text-[12.5px] text-deny">{quick.error.message}</p>}
      {quickResult && d.status !== "ok" && (
        <section className="mt-5">
          <h3 className="text-[14px] font-semibold text-ink">Vérification rapide</h3>
          <FactPanel fc={quickResult} />
        </section>
      )}
      {d.status === "erreur" && <p className="mt-3 rounded-lg bg-fill px-3 py-2 text-[13px] text-deny">La recherche a échoué : {d.message}</p>}
      {d.status === "ok" && <DossierView r={r} />}
      {!d.status && !running && !quickResult && (
        <p className="mt-5 flex items-start gap-2.5 rounded-xl bg-fill/60 px-4 py-3 text-[13px] leading-relaxed text-ink-2">
          <Logo size={18} className="mt-0.5 shrink-0" />
          « Rassembler des sources » cherche d'autres médias qui traitent ce sujet. Les faits de l'article sont ensuite recoupés avec la règle des deux sources indépendantes, puis une synthèse neutre est rédigée. De quoi décider si le sujet mérite d'être suivi.
        </p>
      )}
    </article>
  );
}

function DossierView({ r }: { r: Recording }) {
  const d = r.dossier;
  const check = d.check;
  const sources = new Map<string, SourceRef>((check?.sources ?? []).map((s) => [s.ref, s]));
  const coverage = (check?.sources ?? []).filter((s) => s.id !== r.article_id);
  const s = d.synthesis;
  return (
    <div className="mt-6 space-y-7 border-t border-line pt-5">
      <p className="text-[12px] text-ink-3">
        Sources rassemblées {relative(d.gathered_at)}
        {d.cost_usd ? ` · ${euros(d.cost_usd)}` : ""}
      </p>
      {s && (
        <>
          {s.summary && <p className="serif text-[18px] leading-[1.5] text-ink">{s.summary}</p>}
          <Points title="Ce qu'il faut savoir" points={s.points} sources={sources} />
          <Points title="Contexte" points={s.context} sources={sources} />
          {s.open_questions.length > 0 && (
            <section>
              <h3 className="mb-2 text-[14px] font-semibold text-ink">Questions ouvertes</h3>
              <ul className="list-disc space-y-1 pl-5 text-[13.5px] leading-[1.55] text-ink">
                {s.open_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          )}
          {s.next_steps && (
            <section>
              <h3 className="mb-1 text-[14px] font-semibold text-ink">Et ensuite</h3>
              <p className="text-[13.5px] leading-[1.55] text-ink">{s.next_steps}</p>
            </section>
          )}
        </>
      )}
      {!s && <p className="rounded-lg bg-fill px-3 py-2 text-[13px] text-ink-2">Pas de synthèse : aucun texte lisible, ni dans l'article ni chez d'autres médias.</p>}
      {check && check.status === "ok" && (
        <section>
          <h3 className="text-[14px] font-semibold text-ink">Faits de l'article, recoupés</h3>
          <FactPanel fc={check} />
        </section>
      )}
      <section>
        <h3 className="mb-2 text-[14px] font-semibold text-ink">
          Couverture <span className="font-normal text-ink-3">{coverage.length} autre{coverage.length > 1 ? "s" : ""} média{coverage.length > 1 ? "s" : ""}</span>
        </h3>
        {coverage.length === 0 ? (
          <p className="text-[13px] text-ink-2">Aucun autre média trouvé sur ce sujet pour l'instant.</p>
        ) : (
          <ul className="space-y-2">
            {coverage.map((c) => (
              <li key={c.ref} className="flex items-start gap-2.5">
                <span className="mt-[7px] block size-2 shrink-0 rounded-full" style={{ background: ownerColor({ kind: c.kind, owner_type: c.owner_type ?? "inconnu" }) }} aria-hidden />
                <button onClick={() => openLink(c.url)} className="min-w-0 text-left">
                  <span className="block text-[13.5px] leading-snug text-ink hover:text-accent">{c.title}</span>
                  <span className="text-[12px] text-ink-2">
                    {c.name} · {c.country}
                    {c.published_at ? ` · ${shortDate(c.published_at)}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Points({ title, points, sources }: { title: string; points: DossierPoint[]; sources: Map<string, SourceRef> }) {
  if (!points.length) return null;
  return (
    <section>
      <h3 className="mb-2 text-[14px] font-semibold text-ink">{title}</h3>
      <ul className="space-y-3.5">
        {points.map((p, i) => (
          <li key={i}>
            <p className="text-[14px] leading-[1.55] text-ink">{p.text}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {p.refs.slice(0, 5).map((x) => (
                <SourceChip key={x} refId={x} source={sources.get(x)} />
              ))}
              {p.check === "chiffre_non_retrouve" && <span className="text-[12px] text-warn">chiffre introuvable dans les sources citées</span>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function FollowedIn({ topicId }: { topicId: number }) {
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<Topic[]>("/topics") });
  const name = topics.data?.find((t) => t.id === topicId)?.name ?? "un sujet";
  return (
    <Button size="sm" variant="ghost" onClick={() => nav.go({ name: "topic", id: topicId })}>
      Suivi dans « {name} »
    </Button>
  );
}

function FollowMenu({ r, defaultOpen = false }: { r: Recording; defaultOpen?: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(defaultOpen);
  const anchor = useRef<HTMLSpanElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<Topic[]>("/topics"), enabled: open });
  const assign = useMutation({
    mutationFn: (topic_id: number) => api(`/recordings/${r.id}/assign`, { method: "POST", body: { topic_id } }),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["recordings"] });
    },
  });
  const prompt = `Suis l'actualité liée à cet article : « ${r.title} » (${r.media}). Les faits nouveaux, les positions des acteurs et ce qui est attendu ensuite.`;
  return (
    <span ref={anchor} className="inline-flex">
      <Button size="sm" icon={open ? <ChevronDown size={13} /> : <ChevronRight size={13} />} onClick={() => setOpen(!open)}>
        Suivre
      </Button>
      <Popover anchor={anchor} open={open} onClose={close}>
          <button onClick={() => { setOpen(false); nav.openNewTopic({ prompt, name: r.title.slice(0, 60), recordingId: r.id }); }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13.5px] text-ink hover:bg-fill">
            <Plus size={14} /> En faire un nouveau sujet
          </button>
          {!!topics.data?.length && <p className="px-3 pb-1 pt-2 text-[11.5px] font-semibold text-ink-3">Ajouter à un sujet</p>}
          {topics.data?.map((t) => (
            <button key={t.id} onClick={() => assign.mutate(t.id)} className="block w-full truncate rounded-lg px-3 py-1.5 text-left text-[13.5px] text-ink hover:bg-fill">
              {t.name}
            </button>
          ))}
      </Popover>
    </span>
  );
}
