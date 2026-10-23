import * as Dialog from "@radix-ui/react-dialog";
import { nav, useNav } from "../lib/nav";
import { SHORTCUTS } from "../lib/shortcuts";
import { Button } from "./ui";

export function ShortcutsSheet() {
  const { shortcuts } = useNav();
  return (
    <Dialog.Root open={shortcuts} onOpenChange={nav.setShortcuts}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim anim-scrim z-50" />
        <Dialog.Content aria-describedby={undefined} className="scroll-area anim-sheet fixed left-1/2 top-[16vh] z-50 max-h-[76vh] w-[440px] max-w-[calc(100vw-32px)] -translate-x-1/2 glass rounded-[var(--r-sheet)] p-6">
          <Dialog.Title className="title-md text-ink">Raccourcis clavier</Dialog.Title>
          <ul className="mt-4 divide-y divide-line">
            {SHORTCUTS.map((s) => (
              <li key={s.keys} className="flex items-center justify-between gap-4 py-2 text-[13.5px]">
                <span className="text-ink">{s.label}</span>
                <kbd className="shrink-0 rounded-md bg-fill px-2 py-0.5 text-[12px] font-medium text-ink-2">{s.keys}</kbd>
              </li>
            ))}
          </ul>
          <div className="mt-5 flex justify-end">
            <Dialog.Close asChild>
              <Button variant="primary">OK</Button>
            </Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
