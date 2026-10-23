import * as Switch from "@radix-ui/react-switch";
import { Loader2 } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { chrome } from "../lib/chrome";
import { spring } from "../lib/motion";

type Variant = "primary" | "quiet" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent-fill text-[var(--on-accent)] hover:brightness-110 active:brightness-95",
  // `btn-quiet` : dans la barre d'outils, le bouton passe en verre (voir styles.css).
  quiet: "btn-quiet bg-fill text-ink hover:bg-fill-strong",
  ghost: "text-accent hover:bg-accent-soft",
  danger: "text-deny hover:bg-[color-mix(in_srgb,var(--deny)_12%,transparent)]",
};

export function Button({ variant = "quiet", size = "md", busy, icon, children, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean; icon?: ReactNode }) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-medium transition-[background-color,filter,opacity,scale] duration-150 active:scale-[0.97] disabled:opacity-45 disabled:active:scale-100 ${size === "sm" ? "h-7 px-3 text-[12.5px]" : "h-8 px-3.5 text-[13px]"} ${VARIANTS[variant]} ${className}`}
    >
      {busy ? <Loader2 size={14} className="animate-spin" /> : icon}
      {children}
    </button>
  );
}

export function IconButton({ label, children, className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button {...rest} aria-label={label} title={label} className={`grid size-8 place-items-center rounded-[var(--r-item)] text-ink-2 transition-colors hover:bg-fill hover:text-ink active:bg-fill-strong disabled:opacity-35 disabled:hover:bg-transparent ${className}`}>
      {children}
    </button>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <Loader2 size={size} className="animate-spin text-ink-3" />;
}

/** Titre de section ; `id` en fait une entrée du sommaire de la page. */
export function SectionTitle({ children, aside, id }: { children: ReactNode; aside?: ReactNode; id?: string }) {
  return (
    <div className="mb-3 mt-10 flex items-baseline justify-between gap-4">
      <h2 id={id} data-toc={id ? "" : undefined} className="text-[17px] font-semibold tracking-[-0.015em] text-ink">
        {children}
      </h2>
      {aside}
    </div>
  );
}

/** Le titre de la page : quand il passe sous la barre d'outils, celle-ci affiche sa version compacte. */
export function useCompactTitle() {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const root = el.closest(".scroll-area");
    const obs = new IntersectionObserver(([entry]) => chrome.setCompact(!entry.isIntersecting), { root, threshold: 0, rootMargin: "-60px 0px 0px 0px" });
    obs.observe(el);
    return () => {
      obs.disconnect();
      chrome.setCompact(false);
    };
  }, []);
  return ref;
}

/** Le grand titre d'une page. Quand il sort de l'écran, la barre d'outils affiche sa version compacte. */
export function PageHeader({ title, subtitle, eyebrow, serif, children }: { title: ReactNode; subtitle?: ReactNode; eyebrow?: ReactNode; serif?: boolean; children?: ReactNode }) {
  const ref = useCompactTitle();
  return (
    <header className="mb-8">
      {eyebrow && <p className="mb-1 text-[13px] font-medium text-ink-2">{eyebrow}</p>}
      <h1 ref={ref} className={serif ? "serif text-[38px] font-medium leading-[1.1] tracking-[-0.01em] text-ink" : "title-xl text-ink"}>
        {title}
      </h1>
      {subtitle && <div className="mt-2 text-[14px] text-ink-2">{subtitle}</div>}
      {children}
    </header>
  );
}

/** Conteneur de page : marges et largeur de lecture communes. */
export function Page({ children, wide, aside }: { children: ReactNode; wide?: boolean; aside?: ReactNode }) {
  return (
    <div className="flex justify-center gap-10 px-10 pb-24 pt-6">
      <div className={`min-w-0 flex-1 ${wide ? "max-w-[980px]" : "max-w-[720px]"}`}>{children}</div>
      {aside}
    </div>
  );
}

export function Card({ children, className = "", as: Tag = "div", ...rest }: { children: ReactNode; className?: string; as?: "div" | "section" | "article" } & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag {...rest} className={`card ${className}`}>
      {children}
    </Tag>
  );
}

export function Empty({ title, children, action, icon }: { title: string; children?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      {icon && <div className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-fill text-ink-2">{icon}</div>}
      <p className="title-md text-ink">{title}</p>
      {children && <div className="mt-2 text-[14px] leading-relaxed text-ink-2">{children}</div>}
      {action && <div className="mt-6 flex justify-center">{action}</div>}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[12px] leading-snug text-ink-2">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full rounded-[10px] border-0 bg-fill px-3 py-[7px] text-[14px] text-ink placeholder:text-ink-3 outline-none transition-shadow focus:bg-surface focus:shadow-[var(--focus)]";

/** Contrôle segmenté : la pastille de sélection glisse d'un segment à l'autre (morphose). */
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label?: string }) {
  const id = useId();
  return (
    <div role="radiogroup" aria-label={label} className="segmented inline-flex rounded-full bg-fill p-[3px]">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`relative rounded-full px-3 py-[3px] text-[13px] font-medium transition-colors ${o.value === value ? "text-ink" : "text-ink-2 hover:text-ink"}`}
        >
          {o.value === value && <motion.span layoutId={`seg-${id}`} transition={spring.morph} className="absolute inset-0 rounded-full bg-elevated shadow-[0_1px_3px_rgba(0,0,0,.12),0_0_0_0.5px_rgba(0,0,0,.04)]" />}
          <span className="relative">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <Switch.Root aria-label={label} checked={checked} onCheckedChange={onChange} className="group relative h-[24px] w-[42px] shrink-0 rounded-full bg-fill-strong transition-colors duration-200 data-[state=checked]:bg-ok">
      {/* Comme chez Apple, le curseur s'étire pendant l'appui puis rebondit à sa place. */}
      <Switch.Thumb className="block h-[20px] w-[20px] translate-x-[2px] rounded-full bg-white shadow-[0_2px_4px_rgba(0,0,0,.2)] transition-[translate,width] duration-300 ease-[cubic-bezier(0.2,0.9,0.25,1.15)] group-active:w-[25px] data-[state=checked]:translate-x-[20px] group-active:data-[state=checked]:translate-x-[15px]" />
    </Switch.Root>
  );
}

/** Une ligne de liste groupée : libellé et aide à gauche, contrôle à droite. */
export function Row({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex min-h-[48px] items-center justify-between gap-6 px-4 py-2.5">
      <div className="min-w-0">
        <div className="text-[14px] text-ink">{label}</div>
        {hint && <div className="mt-0.5 text-[12px] leading-snug text-ink-2">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

/** Liste groupée « en encart », avec titre et note de bas facultatifs. */
export function Group({ title, footer, children }: { title?: string; footer?: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-7">
      {title && <h3 className="mb-1.5 px-4 text-[13px] font-semibold text-ink-2">{title}</h3>}
      <div className="card overflow-hidden [&>*+*]:border-t [&>*+*]:border-line">{children}</div>
      {footer && <p className="mt-1.5 px-4 text-[12px] leading-snug text-ink-2">{footer}</p>}
    </section>
  );
}

export const HOURS = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);

/** Heure par pas de 30 minutes (le champ natif `type="time"` rend mal dans WebView2). */
export function TimeSelect({ value, onChange, allowEmpty, emptyLabel = "Par défaut", className = "" }: { value: string | null; onChange: (v: string | null) => void; allowEmpty?: boolean; emptyLabel?: string; className?: string }) {
  const options = value && !HOURS.includes(value) ? [value, ...HOURS] : HOURS;
  return (
    <select className={`${inputClass} ${className}`} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
      {allowEmpty && <option value="">{emptyLabel}</option>}
      {options.map((h) => (
        <option key={h} value={h}>
          {h.replace(":", " h ")}
        </option>
      ))}
    </select>
  );
}
