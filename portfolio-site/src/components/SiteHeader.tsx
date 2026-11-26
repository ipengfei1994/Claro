import { useEffect, useState } from "react";
import { FileText, Menu, Moon, Sun, X } from "lucide-react";
import { navigation } from "@/data/caseStudy";

interface SiteHeaderProps {
  onOpenEvidence: () => void;
}

function getInitialTheme() {
  const saved = localStorage.getItem("claro-portfolio-theme");
  if (saved === "dark" || saved === "light") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function SiteHeader({ onOpenEvidence }: SiteHeaderProps) {
  const [active, setActive] = useState("overview");
  const [menuOpen, setMenuOpen] = useState(false);
  const [theme, setTheme] = useState(getInitialTheme);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("claro-portfolio-theme", theme);
  }, [theme]);

  useEffect(() => {
    const sections = navigation
      .map((item) => document.getElementById(item.id))
      .filter((section): section is HTMLElement => Boolean(section));
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.find((entry) => entry.isIntersecting);
        if (visible) setActive(visible.target.id);
      },
      { rootMargin: "-18% 0px -68% 0px", threshold: 0 },
    );
    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const available = document.documentElement.scrollHeight - window.innerHeight;
        setProgress(available > 0 ? window.scrollY / available : 0);
      });
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  return (
    <header className="site-header">
      <div className="shell site-header__inner">
        <a href="#top" className="wordmark" aria-label="Claro 案例首页">
          <span className="wordmark__name">Claro</span>
          <span className="wordmark__label">Engineering Case Study</span>
        </a>
        <nav className="desktop-nav" aria-label="章节导航">
          {navigation.map((item) => (
            <a
              key={item.id}
              href={`#${item.id}`}
              aria-current={active === item.id ? "location" : undefined}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="header-actions">
          <button type="button" className="button button--ghost" onClick={onOpenEvidence}>
            <FileText size={14} aria-hidden="true" />
            证据说明
          </button>
          <button
            type="button"
            className="icon-button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
            aria-pressed={theme === "dark"}
          >
            {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
          </button>
          <button
            type="button"
            className="icon-button lg:hidden"
            onClick={() => setMenuOpen(!menuOpen)}
            aria-expanded={menuOpen}
            aria-controls="mobile-navigation"
            aria-label={menuOpen ? "关闭章节菜单" : "打开章节菜单"}
          >
            {menuOpen ? <X size={18} aria-hidden="true" /> : <Menu size={18} aria-hidden="true" />}
          </button>
        </div>
      </div>
      <div className="h-px bg-border" aria-hidden="true">
        <div className="h-px bg-primary" style={{ width: `${progress * 100}%` }} />
      </div>
      {menuOpen && (
        <div id="mobile-navigation" className="mobile-menu lg:hidden">
          <nav aria-label="移动端章节导航">
            {navigation.map((item) => (
              <a
                key={item.id}
                href={`#${item.id}`}
                aria-current={active === item.id ? "location" : undefined}
                onClick={() => setMenuOpen(false)}
              >
                <span>{item.number}</span>
                {item.label}
              </a>
            ))}
          </nav>
        </div>
      )}
    </header>
  );
}
