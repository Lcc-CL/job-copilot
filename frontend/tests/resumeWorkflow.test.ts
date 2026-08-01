import assert from "node:assert/strict";
import test from "node:test";
import {
  canEditResumeVersion,
  getResumeWorkflowAction,
} from "../src/components/resumeWorkflow.ts";

test("DRAFT exposes only the review action", () => {
  assert.equal(getResumeWorkflowAction("DRAFT"), "review");
  assert.equal(canEditResumeVersion("DRAFT"), true);
});

test("REVIEWED exposes only the use action and is immutable", () => {
  assert.equal(getResumeWorkflowAction("REVIEWED"), "use");
  assert.equal(canEditResumeVersion("REVIEWED"), false);
});

test("USED is terminal and read-only", () => {
  assert.equal(getResumeWorkflowAction("USED"), null);
  assert.equal(canEditResumeVersion("USED"), false);
});
