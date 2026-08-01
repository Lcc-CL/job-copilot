import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, LogOut, ShieldCheck, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  ApiError,
  fetchAccount,
  updateAccountPassword,
  updateAccountUsername,
} from "../api/client";
import type { AccountDetails } from "../api/types";
import {
  accountSourceTranslationKey,
  validateNewPassword,
} from "../auth/accountAccess";
import { useAuth } from "../components/AuthProvider";


function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}


export default function AccountSettings() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { logout, refreshUser, invalidateSession } = useAuth();
  const [account, setAccount] = useState<AccountDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  const [newUsername, setNewUsername] = useState("");
  const [usernamePassword, setUsernamePassword] = useState("");
  const [usernameSaving, setUsernameSaving] = useState(false);
  const [usernameError, setUsernameError] = useState("");
  const [usernameSuccess, setUsernameSuccess] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordError, setPasswordError] = useState("");

  useEffect(() => {
    fetchAccount()
      .then((result) => {
        setAccount(result);
        setNewUsername(result.username);
      })
      .catch((error: unknown) => {
        setLoadError(errorMessage(error, t("settings.account.loadFailed")));
      })
      .finally(() => setLoading(false));
  }, [t]);

  const submitUsername = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!newUsername.trim() || !usernamePassword) return;
    setUsernameSaving(true);
    setUsernameError("");
    setUsernameSuccess("");
    try {
      const result = await updateAccountUsername({
        current_password: usernamePassword,
        new_username: newUsername.trim(),
      });
      setAccount(result);
      setNewUsername(result.username);
      setUsernamePassword("");
      await refreshUser();
      setUsernameSuccess(t("settings.account.usernameSaved"));
    } catch (error: unknown) {
      setUsernameError(errorMessage(error, t("settings.account.updateFailed")));
    } finally {
      setUsernameSaving(false);
    }
  };

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    const validation = validateNewPassword(newPassword, confirmPassword);
    if (validation === "too_short") {
      setPasswordError(t("settings.account.passwordTooShort"));
      return;
    }
    if (validation === "mismatch") {
      setPasswordError(t("settings.account.passwordMismatch"));
      return;
    }
    if (!currentPassword) return;

    setPasswordSaving(true);
    setPasswordError("");
    try {
      const result = await updateAccountPassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      if (result.reauthentication_required) {
        invalidateSession();
        navigate("/login", {
          replace: true,
          state: { reason: "PASSWORD_CHANGED" },
        });
      }
    } catch (error: unknown) {
      setPasswordError(errorMessage(error, t("settings.account.updateFailed")));
    } finally {
      setPasswordSaving(false);
    }
  };

  const signOut = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  if (loading) return <div className="loading-state">{t("common.loading")}</div>;
  if (loadError || !account) {
    return <div className="alert alert-error">{loadError || t("settings.account.loadFailed")}</div>;
  }

  return (
    <div className="settings-page">
      <div className="settings-heading">
        <div>
          <h1>{t("settings.account.title")}</h1>
          <p>{t("settings.account.subtitle")}</p>
        </div>
        <ShieldCheck size={28} color="var(--primary)" />
      </div>

      <section className="section account-current">
        <div>
          <span className="account-current-label">{t("settings.account.currentUsername")}</span>
          <strong>{account.username}</strong>
        </div>
        <div>
          <span className="account-current-label">{t("settings.account.accountSource")}</span>
          <strong>{t(accountSourceTranslationKey(account.source_type))}</strong>
        </div>
        <p className="settings-note">{t("settings.account.secretNotice")}</p>
      </section>

      <div className="settings-grid">
        <section className="section">
          <h2 className="section-title"><UserRound size={16} /> {t("settings.account.changeUsername")}</h2>
          {usernameError && <div className="alert alert-error">{usernameError}</div>}
          {usernameSuccess && <div className="alert alert-success">{usernameSuccess}</div>}
          <form onSubmit={submitUsername}>
            <div className="form-group">
              <label>{t("settings.account.newUsername")}</label>
              <input
                value={newUsername}
                onChange={(event) => setNewUsername(event.target.value)}
                autoComplete="username"
              />
            </div>
            <div className="form-group">
              <label>{t("settings.account.currentPassword")}</label>
              <input
                type="password"
                value={usernamePassword}
                onChange={(event) => setUsernamePassword(event.target.value)}
                autoComplete="current-password"
              />
            </div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={usernameSaving || !newUsername.trim() || !usernamePassword}
            >
              {usernameSaving ? t("common.saving") : t("settings.account.saveUsername")}
            </button>
          </form>
        </section>

        <section className="section">
          <h2 className="section-title"><KeyRound size={16} /> {t("settings.account.changePassword")}</h2>
          <p className="settings-note">{t("settings.account.passwordSessionNotice")}</p>
          {passwordError && <div className="alert alert-error">{passwordError}</div>}
          <form onSubmit={submitPassword}>
            <div className="form-group">
              <label>{t("settings.account.currentPassword")}</label>
              <input
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className="form-group">
              <label>{t("settings.account.newPassword")}</label>
              <input
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                autoComplete="new-password"
              />
            </div>
            <div className="form-group">
              <label>{t("settings.account.confirmPassword")}</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
              />
            </div>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={passwordSaving || !currentPassword || !newPassword || !confirmPassword}
            >
              {passwordSaving ? t("common.saving") : t("settings.account.savePassword")}
            </button>
          </form>
        </section>
      </div>

      <section className="section sign-out-section">
        <div>
          <h2 className="section-title">{t("settings.account.signOutTitle")}</h2>
          <p className="settings-note">{t("settings.account.signOutDescription")}</p>
        </div>
        <button className="btn btn-secondary" type="button" onClick={signOut}>
          <LogOut size={15} /> {t("nav.signOut")}
        </button>
      </section>
    </div>
  );
}
