import assert from "node:assert/strict";
import test from "node:test";

import {
  accountSourceTranslationKey,
  authErrorTranslationKey,
  validateNewPassword,
} from "../src/auth/accountAccess.ts";

test("login errors distinguish credentials, unconfigured accounts, sessions, and servers", () => {
  assert.equal(
    authErrorTranslationKey("INVALID_CREDENTIALS", 401),
    "login.invalidCredentials",
  );
  assert.equal(
    authErrorTranslationKey("ACCOUNT_NOT_CONFIGURED", 503),
    "login.accountNotConfigured",
  );
  assert.equal(
    authErrorTranslationKey("SESSION_INVALID", 401),
    "login.sessionInvalid",
  );
  assert.equal(
    authErrorTranslationKey("AUTH_SERVER_ERROR", 500),
    "login.serverError",
  );
  assert.equal(
    authErrorTranslationKey("LOGIN_RATE_LIMITED", 429),
    "login.tooManyAttempts",
  );
});

test("password settings reject short and mismatched values", () => {
  assert.equal(validateNewPassword("short", "short"), "too_short");
  assert.equal(
    validateNewPassword("long-enough-password", "different-password"),
    "mismatch",
  );
  assert.equal(
    validateNewPassword("long-enough-password", "long-enough-password"),
    null,
  );
});

test("account sources have explicit user-facing labels", () => {
  assert.equal(
    accountSourceTranslationKey("database"),
    "settings.account.sourceDatabase",
  );
  assert.equal(
    accountSourceTranslationKey("environment"),
    "settings.account.sourceEnvironment",
  );
  assert.equal(
    accountSourceTranslationKey("development_default"),
    "settings.account.sourceDevelopmentDefault",
  );
});
