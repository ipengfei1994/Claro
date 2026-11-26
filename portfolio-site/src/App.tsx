import { useEffect, useState } from "react";
import { SiteHeader } from "@/components/SiteHeader";
import { EvidenceDialog } from "@/components/EvidenceDialog";
import { Hero } from "@/sections/Hero";
import { Overview } from "@/sections/Overview";
import { BusinessContext } from "@/sections/BusinessContext";
import { StrategyDesign } from "@/sections/StrategyDesign";
import { SystemArchitecture } from "@/sections/SystemArchitecture";
import { ProductExperience } from "@/sections/ProductExperience";
import { AIDevelopment } from "@/sections/AIDevelopment";
import { Validation } from "@/sections/Validation";
import { SiteFooter, Reflection } from "@/sections/Reflection";

export default function App() {
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  useEffect(() => {
    if (!window.location.hash) return;
    const target = document.querySelector(window.location.hash);
    window.requestAnimationFrame(() => target?.scrollIntoView({ block: "start" }));
  }, []);

  return (
    <>
      <a href="#main-content" className="skip-link">跳转到正文</a>
      <SiteHeader onOpenEvidence={() => setEvidenceOpen(true)} />
      <main id="main-content">
        <Hero />
        <Overview />
        <BusinessContext />
        <StrategyDesign />
        <SystemArchitecture />
        <ProductExperience />
        <AIDevelopment />
        <Validation />
        <Reflection />
      </main>
      <SiteFooter />
      <EvidenceDialog open={evidenceOpen} onClose={() => setEvidenceOpen(false)} />
    </>
  );
}
