import zh from "@/i18n/messages/zh.json";
import en from "@/i18n/messages/en.json";

type Messages = typeof zh;

const messagesMap: Record<string, Messages> = { zh, en };

export function getTranslations(locale: string, namespace: string) {
  const messages = messagesMap[locale] || zh;
  const ns = (messages as Record<string, Record<string, string>>)[namespace];
  const fallbackNs = (zh as Record<string, Record<string, string>>)[namespace];
  return (key: string): string => {
    return ns?.[key] || fallbackNs?.[key] || key;
  };
}
