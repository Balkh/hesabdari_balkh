import { useEffect, useState } from "react";
import { getHealth } from "../services/api";
import { translations, type Language } from "../i18n/translations";
import { tokens } from "../theme/tokens";

export function App() {
  const [language, setLanguage] = useState<Language>("fa");
  const [backendStatus, setBackendStatus] = useState("در حال بررسی…");
  const t = translations[language];

  useEffect(() => {
    getHealth().then((health) => setBackendStatus(`${health.status} / ${health.database}`))
      .catch(() => setBackendStatus(language === "fa" ? "اتصال برقرار نیست" : "Not connected"));
  }, [language]);

  return <main dir={t.dir} style={{ minHeight: "100vh", background: tokens.colors.background, color: tokens.colors.text, fontFamily: "Tahoma, sans-serif", padding: tokens.spacing.lg }}>
    <section style={{ maxWidth: 900, margin: "0 auto", background: tokens.colors.surface, borderRadius: tokens.radius.md, padding: "2rem", boxShadow: "0 8px 30px #17304214" }}>
      <button onClick={() => setLanguage(language === "fa" ? "en" : "fa")} style={{ float: t.dir === "rtl" ? "left" : "right", padding: tokens.spacing.sm, borderRadius: tokens.radius.md, border: "1px solid #d7e2e8", background: tokens.colors.surface }}>{language === "fa" ? "English" : "دری"}</button>
      <div style={{ paddingTop: "2rem" }}><p style={{ color: tokens.colors.primary, fontWeight: 700 }}>PHASE 1 · FOUNDATION</p><h1>{t.title}</h1><p style={{ color: tokens.colors.muted }}>{t.subtitle}</p><p>✓ React · TypeScript · Design Tokens · RTL/LTR · i18n</p><p>Backend: <strong>{backendStatus}</strong></p></div>
    </section>
  </main>;
}
