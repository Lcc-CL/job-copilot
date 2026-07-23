import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchDashboard,
  fetchFollowUps,
  fetchApplications,
  fetchApplication,
  updateApplication,
  createApplication,
  followUpApplication,
} from "../api/client";
import type { ApplicationUpdate, ApplicationCreate, FollowUpAction } from "../api/types";

// ---- Dashboard ----

export function useDashboard() {
  return useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  });
}

export function useFollowUps() {
  return useQuery({
    queryKey: ["followUps"],
    queryFn: fetchFollowUps,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  });
}

// ---- Applications ----

export function useApplications(params: {
  stage?: string;
  overdue?: boolean;
  keyword?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: ["applications", params],
    queryFn: () => fetchApplications(params),
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
    staleTime: 10_000,
  });
}

export function useApplication(id: number | null) {
  return useQuery({
    queryKey: ["application", id],
    queryFn: () => fetchApplication(id!),
    enabled: id !== null,
    staleTime: 30_000,
  });
}

// ---- Mutations ----

export function useUpdateApplication() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: ApplicationUpdate }) =>
      updateApplication(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["application"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["followUps"] });
    },
  });
}

export function useCreateApplication() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, body }: { jobId: number; body: ApplicationCreate }) =>
      createApplication(jobId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}

export function useFollowUp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: FollowUpAction }) =>
      followUpApplication(id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["followUps"] });
      qc.invalidateQueries({ queryKey: ["applications"] });
      qc.invalidateQueries({ queryKey: ["application"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
