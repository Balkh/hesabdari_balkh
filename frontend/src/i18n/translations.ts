export const translations = {
  fa: { dir: "rtl", title: "حسابداری بلخ", subtitle: "پایهٔ فنی سیستم مالی و تجارتی" },
  en: { dir: "ltr", title: "Hesabdari Balkh", subtitle: "Financial and trading system foundation" },
} as const;
export type Language = keyof typeof translations;
