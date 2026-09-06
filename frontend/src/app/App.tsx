import { useEffect, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { getHealth } from "../services/api";
import { translations, type Language } from "../i18n/translations";
import { tokens } from "../theme/tokens";
import { Button, Card, StatusBadge } from "../components";

function FoundationHome({ language, setLanguage }: { language: Language; setLanguage: (value: Language) => void }) {
  const t = translations[language];
  const [backendStatus, setBackendStatus] = useState(language === "fa" ? "در حال بررسی…" : "Checking…");
  useEffect(() => {
    getHealth().then((health) => setBackendStatus(`${health.status} / ${health.database}`))
      .catch(() => setBackendStatus(language === "fa" ? "اتصال برقرار نیست" : "Not connected"));
  }, [language]);
  return <Card>
    <Button variant="secondary" onClick={() => setLanguage(language === "fa" ? "en" : "fa")} style={{ float: t.dir === "rtl" ? "left" : "right" }}>{language === "fa" ? "English" : "دری"}</Button>
    <div style={{ paddingTop: "2rem" }}><p style={{ color: tokens.colors.primary, fontWeight: 700 }}>PHASE 1 · FOUNDATION</p><h1>{t.title}</h1><p style={{ color: tokens.colors.muted }}>{t.subtitle}</p><p>✓ React · TypeScript · Design Tokens · RTL/LTR · i18n</p><p>Backend: <strong>{backendStatus}</strong> <StatusBadge status={backendStatus.startsWith("ok") ? "success" : "warning"} /></p><Link to="/about">Foundation details</Link></div>
  </Card>;
}

function About() { return <section style={{ maxWidth: 900, margin: "0 auto", background: tokens.colors.surface, borderRadius: tokens.radius.md, padding: "2rem" }}><h1>Application Foundation</h1><p>Business modules will be added only after their approved domain contracts.</p><Link to="/">Back to dashboard</Link></section>; }

export function App() {
  const [language, setLanguage] = useState<Language>("fa");
  const t = translations[language];
  return <BrowserRouter><main dir={t.dir} style={{ minHeight: "100vh", background: tokens.colors.background, color: tokens.colors.text, fontFamily: "Tahoma, sans-serif", padding: tokens.spacing.lg }}><Routes><Route path="/" element={<FoundationHome language={language} setLanguage={setLanguage} />} /><Route path="/about" element={<About />} /></Routes></main></BrowserRouter>;
}
