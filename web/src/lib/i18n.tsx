"use client";
import { createContext, useContext, ReactNode } from "react";
import zh from "@/i18n/messages/zh.json";
import en from "@/i18n/messages/en.json";

type Messages = typeof zh;

const messagesMap: Record<string, Messages> = { zh, en };

const I18nContext = createContext<{ locale: string; messages: Messages }>({
  locale: "zh",
  messages: zh,
});

export function I18nProvider({ locale, children }: { locale: string; children: ReactNode }) {
  const messages = messagesMap[locale] || zh;
  return (
    <I18nContext.Provider value={{ locale, messages }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useTranslations(namespace?: string) {
  const { messages } = useContext(I18nContext);
  return (key: string) => {
    const ns = namespace ? (messages as any)[namespace] : messages;
    if (!ns) return key;
    return (ns as any)[key] || key;
  };
}

export function useLocale() {
  return useContext(I18nContext).locale;
}
