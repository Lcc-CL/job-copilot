import type { TFunction } from "i18next";

export function translateStage(t: TFunction, value: string | null | undefined): string {
  if (!value) return "—";
  const key = `stage.${value}`;
  const result = t(key);
  return result === key ? value : result;
}

export function translateRecommendation(t: TFunction, value: string | null | undefined): string {
  if (!value) return "—";
  const key = `recommendation.${value}`;
  const result = t(key);
  return result === key ? value : result;
}

export function translateJdStatus(t: TFunction, value: string | null | undefined): string {
  if (!value) return "—";
  const key = `jdStatus.${value}`;
  const result = t(key);
  return result === key ? value : result;
}

export function formatDateLocalized(iso: string | null, locale: string): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso.slice(0, 10);
    return d.toLocaleDateString(locale === "zh-CN" ? "zh-CN" : "en-US", {
      month: "short",
      day: "numeric",
      hour: d.getHours() !== 0 || d.getMinutes() !== 0 ? "2-digit" : undefined,
      minute: d.getHours() !== 0 || d.getMinutes() !== 0 ? "2-digit" : undefined,
    });
  } catch {
    return iso.slice(0, 10);
  }
}
