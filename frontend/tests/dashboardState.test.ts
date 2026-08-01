import assert from "node:assert/strict";
import test from "node:test";
import { resolveDashboardState } from "../src/pages/dashboardState.ts";

const realDashboard = { total_jobs: 425, greeting_ready: 3 };
const realFollowUps = { overdue: [], due_today: [], upcoming: [] };

test("shows loading while both dashboard requests are loading", () => {
  assert.equal(
    resolveDashboardState(
      { data: undefined, isLoading: true, isError: false },
      { data: undefined, isLoading: true, isError: false },
    ),
    "loading",
  );
});

test("stays loading when only one request has completed", () => {
  assert.equal(
    resolveDashboardState(
      { data: realDashboard, isLoading: false, isError: false },
      { data: undefined, isLoading: true, isError: false },
    ),
    "loading",
  );
  assert.equal(
    resolveDashboardState(
      { data: undefined, isLoading: true, isError: false },
      { data: realFollowUps, isLoading: false, isError: false },
    ),
    "loading",
  );
});

test("renders real data only after both requests succeed", () => {
  assert.equal(
    resolveDashboardState(
      { data: realDashboard, isLoading: false, isError: false },
      { data: realFollowUps, isLoading: false, isError: false },
    ),
    "ready",
  );
});

test("shows an error when either request fails", () => {
  assert.equal(
    resolveDashboardState(
      { data: undefined, isLoading: false, isError: true },
      { data: realFollowUps, isLoading: false, isError: false },
    ),
    "error",
  );
  assert.equal(
    resolveDashboardState(
      { data: realDashboard, isLoading: false, isError: false },
      { data: undefined, isLoading: false, isError: true },
    ),
    "error",
  );
});

test("never reports ready when either response data is undefined", () => {
  assert.equal(
    resolveDashboardState(
      { data: realDashboard, isLoading: false, isError: false },
      { data: undefined, isLoading: false, isError: false },
    ),
    "loading",
  );
});
