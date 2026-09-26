export function authErrorTranslationKey(
  code: string | undefined,
  status: number,
): string {
  if (code === "ACCOUNT_NOT_CONFIGURED") return "login.accountNotConfigured";
  if (code === "SESSION_INVALID") return "login.sessionInvalid";
  if (code === "AUTH_SERVER_ERROR") return "login.serverError";
  if (code === "LOGIN_RATE_LIMITED" || status === 429) return "login.tooManyAttempts";
  if (code === "INVALID_CREDENTIALS" || status === 401) {
    return "login.invalidCredentials";
  }
  return "login.serverError";
}

export function validateNewPassword(
  password: string,
  confirmation: string,
): "too_short" | "mismatch" | null {
  if (password.length < 10 || !password.trim()) return "too_short";
  if (password !== confirmation) return "mismatch";
  return null;
}

export function accountSourceTranslationKey(sourceType: string): string {
  const knownSources: Record<string, string> = {
    database: "settings.account.sourceDatabase",
    environment: "settings.account.sourceEnvironment",
    development_default: "settings.account.sourceDevelopmentDefault",
  };
  return knownSources[sourceType] || "settings.account.sourceUnknown";
}
