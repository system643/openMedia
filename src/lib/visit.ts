// « Nouveau depuis ta dernière visite » : la visite précédente est lue une fois au lancement,
// puis la visite en cours est enregistrée.

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { parse } from "./format";

export function usePreviousVisit(): Date | null {
  const q = useQuery({
    queryKey: ["visit"],
    queryFn: () => api<{ previous_visit_at: string | null }>("/visit", { method: "POST" }),
    staleTime: Infinity,
    gcTime: Infinity,
  });
  return parse(q.data?.previous_visit_at);
}
