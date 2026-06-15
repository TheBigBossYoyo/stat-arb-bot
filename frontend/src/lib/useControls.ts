import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./api";
import type { CapabilitiesResp } from "./actionTypes";

/**
 * Whether dashboard controls are enabled (POST actions allowed). Read-only by
 * default. Used to disable action buttons in the UI; the backend re-checks this
 * gate regardless, so it is a UX affordance, not the security boundary.
 */
export function useControls(): boolean {
  const { data } = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => apiGet<CapabilitiesResp>("/api/dashboard/capabilities"),
    staleTime: 30_000,
  });
  return data?.controls_enabled ?? false;
}
