import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useMemo, useState } from "react";
import { CadencePicker } from "../components/CadencePicker";
import { Button, Field, Row, Segmented, Toggle, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { hasContent, useDraftAutosave, type WizardState } from "../lib/drafts";
import { nav, useNav, type NewTopicDraft } from "../lib/nav";
import type { Cadence, Settings, Topic, TopicSpec } from "../lib/types";
import { cadenceLabel, generalCadence } from "../lib/usage";
import { motionProps, scrim, sheet as sheetMotion } from "../lib/motion";

// Des façons d'étudier un sujet, à compléter ou réécrire librement.
const ANGLES = [
  { id: "court", label: "Factuel et court", text: "Donne-moi les faits nouveaux en quelques lignes, sans analyse, avec les chiffres clés et ce qui est attendu ensuite." },
  { id: "fond", label: "Analyse de fond", text: "Explique-moi les enjeux, le contexte et les causes, et distingue clairement les faits établis des analyses d'experts." },
  { id: "chiffres", label: "Suivi chiffré", text: "Suis les chiffres et les indicateurs : leur évolution, leur source et leur méthode, et signale toute révision." },
  { id: "parties", label: "Tous les points de vue", text: "Présente la position de chaque partie prenante, avec ses meilleurs arguments, sans en privilégier aucune." },
];

type Step = 1 | 2 | 3;

export function NewTopicSheet() {
  const { sheet } = useNav();
  return (
    <Dialog.Root open={!!sheet} onOpenChange={(o) => !o && nav.closeSheet()}>
      <AnimatePresence>
        {sheet && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div className="scrim z-40" variants={scrim} {...motionProps} />
            </Dialog.Overlay>
            {/* Un clic à côté ne ferme pas la feuille : la saisie ne se perd pas par accident. */}
            <Dialog.Content asChild aria-describedby={undefined} onPointerDownOutside={(e) => e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
              <motion.div
                className="scroll-area fixed left-1/2 top-10 z-50 max-h-[calc(100vh-5rem)] w-[620px] max-w-[calc(100vw-32px)] -translate-x-1/2 glass rounded-[var(--r-sheet)] p-7 pb-0"
                style={{ transformOrigin: "50% 0%" }}
                variants={sheetMotion}
                {...motionProps}
              >
                <TopicWizard key={sheet.draftId ?? "nouveau"} initial={sheet} />
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

/** L'assistant « Suivre un sujet ». Dans la feuille, il ouvre le sujet créé ; `embedded` (le
 *  tutoriel) le pose dans la page et laisse `onCreated` décider de la suite. */
export function TopicWizard({ initial, embedded, onCreated }: { initial: NewTopicDraft; embedded?: boolean; onCreated?: (topic: Topic) => void }) {
  const qc = useQueryClient();
  const restored = initial.state;
  const [step, setStep] = useState<Step>(restored?.step ?? 1);
  const [subject, setSubject] = useState(restored?.subject ?? initial.prompt ?? "");
  const [angle, setAngle] = useState<string | null>(restored ? restored.angle : initial.prompt ? "libre" : null);
  const [custom, setCustom] = useState(restored?.custom ?? "");
  const [importance, setImportance] = useState(restored?.importance ?? "3");
  const [languages, setLanguages] = useState(restored?.languages ?? "fr+en");
  const [cadence, setCadence] = useState<Cadence | null>(restored?.cadence ?? legacyCadence(restored));
  const [kind, setKind] = useState<"actualite" | "recherche">(restored?.kind ?? "actualite");
  const [fields, setFields] = useState<string[]>(restored?.fields ?? []);
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const general = generalCadence(settings.data);
  const fieldOptions = useQuery({ queryKey: ["research-fields"], queryFn: () => api<{ id: string; label: string }[]>("/research/fields"), staleTime: Infinity });
  const name = restored?.name ?? initial.name;

  const state = useMemo<WizardState>(() => ({ step, subject, angle, custom, importance, languages, cadence, name, kind, fields }), [step, subject, angle, custom, importance, languages, cadence, name, kind, fields]);
  const draft = useDraftAutosave(state, initial.draftId ?? null);
  const fromSuggestion = !!(initial.prompt || restored?.angle === "libre");

  const angleText = angle === "libre" ? custom : ANGLES.find((a) => a.id === angle)?.text ?? "";
  const prompt = fromSuggestion && angle === "libre" && !custom ? subject : `${subject.trim()}\n\n${angleText}`.trim();

  const preview = useMutation({ mutationFn: (p: string) => api<{ spec: TopicSpec; sample: { title: string; source: string }[]; cost_usd: number }>("/topics/preview", { method: "POST", body: { prompt: p } }) });
  // La spécification de l'aperçu sert à la création si la consigne n'a pas changé : un appel de moins.
  const reusable = preview.data && preview.variables === prompt ? preview.data.spec : null;
  const create = useMutation({
    mutationFn: async () => {
      await draft.flush();
      draft.settle();
      return api<Topic>("/topics", { method: "POST", body: { prompt, name, importance: Number(importance), languages: languages.split("+"), run_hours: cadence?.hours ?? [], run_every_days: cadence && !cadence.weekdays.length ? cadence.every : null, run_weekdays: cadence?.weekdays ?? [], draft_id: draft.currentId(), recording_id: initial.recordingId ?? null, kind, research_fields: kind === "recherche" ? fields : [], spec: reusable } });
    },
    onSuccess: (t) => {
      void qc.invalidateQueries({ queryKey: ["topics"] });
      void qc.invalidateQueries({ queryKey: ["today"] });
      void qc.invalidateQueries({ queryKey: ["drafts"] });
      if (initial.recordingId) void qc.invalidateQueries({ queryKey: ["recordings"] });
      if (onCreated) return onCreated(t);
      nav.closeSheet();
      nav.go({ name: "topic", id: t.id });
    },
  });

  async function discard() {
    await draft.discard();
    nav.closeSheet();
  }

  return (
    <div>
      <div className="flex items-baseline justify-between">
        {embedded ? <h3 className="text-[15px] font-semibold text-ink">Ton sujet</h3> : <Dialog.Title className="serif text-[26px] font-medium text-ink">Suivre un sujet</Dialog.Title>}
        <span className="text-[12px] text-ink-3">
          {draft.status === "saving" ? "Enregistrement du brouillon…" : draft.status === "saved" ? "Brouillon enregistré" : draft.status === "error" ? "Brouillon non enregistré, nouvel essai à la prochaine frappe" : ""}
          {draft.status !== "idle" && " · "}Étape {step} sur 3
        </span>
      </div>

      {step === 1 && (
        <div className="mt-5 space-y-4">
          <Segmented
            label="Type de suivi"
            value={kind}
            onChange={setKind}
            options={[
              { value: "actualite", label: "Actualité (presse)" },
              { value: "recherche", label: "Recherche scientifique" },
            ]}
          />
          {kind === "recherche" && (
            <div>
              <p className="mb-2 text-[13px] font-medium text-ink">Domaines</p>
              <div className="flex flex-wrap gap-2">
                {fieldOptions.data?.map((f) => {
                  const on = fields.includes(f.id);
                  return (
                    <button key={f.id} onClick={() => setFields(on ? fields.filter((x) => x !== f.id) : [...fields, f.id])} aria-pressed={on} className={`rounded-full px-3 py-1 text-[13px] transition-colors ${on ? "bg-accent-fill text-white" : "bg-fill text-ink hover:bg-fill-strong"}`}>
                      {f.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-[12px] leading-snug text-ink-2">Sources : arXiv, OpenAlex, PubMed, bioRxiv et medRxiv, HAL. Les papiers sont jugés sur leur titre et leur résumé ; les prépublications sont signalées comme non relues.</p>
            </div>
          )}
          <Field label="Quel sujet ?" hint={kind === "recherche" ? "Une question ou un front de recherche : une méthode, une maladie, un matériau, un type de modèle…" : "Décris-le comme à un journaliste : un événement, une négociation, une technologie, un procès, une entreprise…"}>
            <textarea autoFocus={!embedded} className={`${inputClass} min-h-[110px] resize-y text-[15px] leading-relaxed`} placeholder={kind === "recherche" ? "Les avancées sur le raisonnement des grands modèles de langage" : "Les négociations sur le budget 2027 à l'Assemblée nationale"} value={subject} onChange={(e) => setSubject(e.target.value)} />
          </Field>
        </div>
      )}

      {step === 2 && (
        <div className="mt-5">
          <p className="mb-3 text-[13px] font-medium text-ink">Comment veux-tu l'étudier ?</p>
          <div className="grid grid-cols-2 gap-2">
            {ANGLES.map((a) => (
              <button key={a.id} onClick={() => setAngle(a.id)} className={`rounded-xl border p-3 text-left transition-colors ${angle === a.id ? "border-accent bg-accent-soft" : "border-line-strong hover:bg-paper"}`}>
                <span className="block text-[14px] font-medium text-ink">{a.label}</span>
                <span className="mt-1 block text-[12.5px] leading-snug text-ink-2">{a.text}</span>
              </button>
            ))}
          </div>
          <button onClick={() => setAngle("libre")} className={`mt-2 w-full rounded-xl border p-3 text-left transition-colors ${angle === "libre" ? "border-accent bg-accent-soft" : "border-line-strong hover:bg-paper"}`}>
            <span className="block text-[14px] font-medium text-ink">À ma façon</span>
            <span className="mt-1 block text-[12.5px] text-ink-2">Écris toi-même ce que tu veux savoir et sous quelle forme, sections comprises.</span>
          </button>
          {angle === "libre" && (
            <textarea autoFocus={!embedded} className={`${inputClass} mt-3 min-h-[90px] resize-y`} placeholder="Je veux un point chiffré, les positions de chaque groupe parlementaire et le calendrier des votes." value={custom} onChange={(e) => setCustom(e.target.value)} />
          )}
        </div>
      )}

      {step === 3 && (
        <div className="mt-5 space-y-5">
          <Field label="Importance pour toi" hint="Le Directeur s'en sert pour hiérarchiser ton brief du matin.">
            <Segmented value={importance} onChange={setImportance} options={["1", "2", "3", "4", "5"].map((v) => ({ value: v, label: v }))} />
          </Field>
          <Field label="Langues des sources" hint="Plus de langues, c'est plus de points de vue et moins d'angles morts.">
            <Segmented value={languages} onChange={setLanguages} options={[{ value: "fr+en", label: "Français et anglais" }, { value: "fr", label: "Français" }, { value: "en", label: "Anglais" }]} />
          </Field>
          <div>
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Rythme des passages</span>
            <div className="card overflow-hidden [&>*+*]:border-t [&>*+*]:border-line">
              <Row label="Rythme propre à ce sujet" hint={cadence ? "Les jours d'échéance s'ajoutent d'eux-mêmes." : `Suit le rythme général : ${cadenceLabel(general).toLowerCase()}. Un sujet lent n'a pas besoin d'un passage chaque jour, et moins souvent, c'est moins de tokens.`}>
                <Toggle label="Rythme propre à ce sujet" checked={!!cadence} onChange={(v) => setCadence(v ? general : null)} />
              </Row>
              {cadence && (
                <div className="px-4 py-3.5">
                  <CadencePicker value={cadence} onChange={setCadence} />
                </div>
              )}
            </div>
          </div>
          <div className="rounded-xl bg-paper p-4">
            <p className="text-[12px] font-medium text-ink-2">Ta consigne</p>
            <p className="mt-1 whitespace-pre-line text-[13.5px] leading-relaxed text-ink">{prompt}</p>
            <div className="mt-3 flex items-center gap-3">
              <Button busy={preview.isPending} onClick={() => preview.mutate(prompt)}>
                Aperçu des sources
              </Button>
              {preview.data && <span className="text-[12px] text-ink-3">Recherches : {[...preview.data.spec.queries_fr, ...preview.data.spec.queries_en].join(" ; ")}</span>}
            </div>
            {preview.error && <p className="mt-2 text-[13px] text-deny">{preview.error.message}</p>}
            {preview.data && (
              <ul className="mt-3 max-h-40 space-y-1 overflow-y-auto text-[12.5px] text-ink-2">
                {preview.data.sample.map((s, i) => (
                  <li key={i}>
                    {s.title} <span className="text-ink-3">({s.source})</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}

      {create.error && <p className="mt-4 text-[13px] text-deny">{create.error.message}</p>}

      {/* Les boutons restent visibles quand l'aperçu des sources allonge la feuille. */}
      <div className={embedded ? "mt-5 flex justify-between" : "sticky bottom-0 -mx-7 mt-3 flex justify-between bg-[color-mix(in_srgb,var(--glass-opaque)_88%,transparent)] px-7 pb-7 pt-4 backdrop-blur-xl"}>
        <div className="flex gap-1">
          {(step > 1 || !embedded) && (
            <Button variant="ghost" onClick={() => (step === 1 ? nav.closeSheet() : setStep((step - 1) as Step))}>
              {step > 1 ? "Retour" : hasContent(state) ? "Fermer et garder le brouillon" : "Annuler"}
            </Button>
          )}
          {hasContent(state) && step === 1 && !embedded && (
            <Button variant="danger" onClick={discard}>
              Supprimer le brouillon
            </Button>
          )}
        </div>
        {step < 3 ? (
          <Button variant="primary" disabled={step === 1 ? subject.trim().length < 3 : !angle || (angle === "libre" && !custom.trim() && !initial.prompt)} onClick={() => setStep((step + 1) as Step)}>
            Continuer
          </Button>
        ) : (
          <Button variant="primary" busy={create.isPending} onClick={() => create.mutate()}>
            Suivre ce sujet
          </Button>
        )}
      </div>
    </div>
  );
}

/** Brouillons d'avant les rythmes : une fréquence en jours (« general » : celle des réglages) et une heure. */
function legacyCadence(state: WizardState | undefined): Cadence | null {
  if (!state?.every || state.every === "general") return null;
  return { every: Number(state.every) || 1, weekdays: [], hours: [state.runHour || "06:30"] };
}
