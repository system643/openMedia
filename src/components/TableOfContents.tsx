import { useEffect, useState } from "react";

/** « Sur cette page » : les titres de section de la page (marqués `data-toc`), avec la section
 *  visible surlignée. `watch` relance la lecture des titres quand le contenu change. */
export function TableOfContents({ watch }: { watch: unknown }) {
  const [items, setItems] = useState<{ id: string; label: string }[]>([]);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      const heads = [...document.querySelectorAll<HTMLElement>("main [data-toc]")];
      setItems(heads.map((h) => ({ id: h.id, label: h.textContent ?? "" })));
      const root = document.querySelector("main");
      const obs = new IntersectionObserver(
        (entries) => {
          const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
          if (visible) setActive(visible.target.id);
        },
        { root, rootMargin: "0px 0px -70% 0px" },
      );
      heads.forEach((h) => obs.observe(h));
      cleanup = () => obs.disconnect();
    }, 150);
    let cleanup = () => {};
    return () => {
      clearTimeout(t);
      cleanup();
    };
  }, [watch]);

  if (items.length < 3) return null;
  return (
    <nav aria-label="Sur cette page" className="sticky top-[76px] hidden w-[200px] shrink-0 self-start xl:block">
      <p className="mb-2 text-[12px] font-semibold text-ink-3">Sur cette page</p>
      <ul className="space-y-0.5 border-l border-line">
        {items.map((it) => (
          <li key={it.id}>
            <button
              onClick={() => document.getElementById(it.id)?.scrollIntoView({ behavior: "smooth", block: "start" })}
              className={`-ml-px block w-full truncate border-l-2 py-1 pl-3 text-left text-[13px] transition-colors ${active === it.id ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"}`}
            >
              {it.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
