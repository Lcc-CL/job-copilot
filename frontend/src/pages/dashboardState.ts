type QueryState<T> = {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
};

export type DashboardState = "loading" | "error" | "ready";

export function resolveDashboardState<TDashboard, TFollowUps>(
  dashboard: QueryState<TDashboard>,
  followUps: QueryState<TFollowUps>,
): DashboardState {
  if (dashboard.isError || followUps.isError) return "error";
  if (
    dashboard.isLoading ||
    followUps.isLoading ||
    dashboard.data === undefined ||
    followUps.data === undefined
  ) {
    return "loading";
  }
  return "ready";
}
