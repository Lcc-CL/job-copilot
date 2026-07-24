import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhCN from "./locales/zh-CN";
import enUS from "./locales/en-US";

const LANG_KEY = "job-copilot-language";

function getStoredLang(): string {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored && ["zh-CN", "en-US"].includes(stored)) return stored;
  } catch {}
  return "zh-CN";
}

i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { translation: zhCN },
    "en-US": { translation: enUS },
  },
  lng: getStoredLang(),
  fallbackLng: "en-US",
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  try { localStorage.setItem(LANG_KEY, lng); } catch {}
  document.documentElement.lang = lng;
});

// Set initial lang attribute
document.documentElement.lang = i18n.language;

export default i18n;
