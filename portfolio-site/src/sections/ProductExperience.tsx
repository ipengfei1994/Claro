import { useRef, useState, type KeyboardEvent } from "react";
import { ArrowLeft, ArrowRight, ArrowUpRight } from "lucide-react";
import { productScreens } from "@/data/caseStudy";
import { Badge, EvidenceNote, SectionHeader } from "@/components/Primitives";
import { Modal } from "@/components/Modal";

export function ProductExperience() {
  const [activeId, setActiveId] = useState(productScreens[0].id);
  const [open, setOpen] = useState(false);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const activeIndex = productScreens.findIndex((screen) => screen.id === activeId);
  const screen = productScreens[activeIndex];

  const move = (nextIndex: number) => {
    const index = (nextIndex + productScreens.length) % productScreens.length;
    setActiveId(productScreens[index].id);
    tabRefs.current[index]?.focus();
  };

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowRight") { event.preventDefault(); move(index + 1); }
    if (event.key === "ArrowLeft") { event.preventDefault(); move(index - 1); }
    if (event.key === "Home") { event.preventDefault(); move(0); }
    if (event.key === "End") { event.preventDefault(); move(productScreens.length - 1); }
  };

  return (
    <section id="product" className="section">
      <div className="shell">
        <SectionHeader
          number="05"
          label="Product Experience"
          title="让策略可操作，而不只是可查看。"
          description="产品围绕审核员、策略管理员和分析人员的任务组织。真实截图展示特定运行状态，不用宣传图替代界面证据。"
        />
        <div className="product-tabs" role="tablist" aria-label="Claro 核心产品页面">
          {productScreens.map((item, index) => (
            <button
              key={item.id}
              ref={(node) => { tabRefs.current[index] = node; }}
              type="button"
              role="tab"
              id={`tab-${item.id}`}
              aria-controls={`panel-${item.id}`}
              aria-selected={activeId === item.id}
              tabIndex={activeId === item.id ? 0 : -1}
              onClick={() => setActiveId(item.id)}
              onKeyDown={(event) => onTabKeyDown(event, index)}
            >
              <span>0{index + 1}</span>{item.label}
            </button>
          ))}
        </div>
        <div id={`panel-${screen.id}`} role="tabpanel" aria-labelledby={`tab-${screen.id}`} className="product-viewer mt-7 animate-soft-enter" key={screen.id}>
          <div className="frame">
            <div className="frame__bar">
              <span>CLARO / {screen.label.toUpperCase()}</span>
              <div className="flex items-center gap-4">
                <span>{screen.theme} · Synthetic Data</span>
                <button type="button" className="inline-flex items-center gap-2 border-0 bg-transparent p-0 text-primary" onClick={() => setOpen(true)}>
                  查看原图 <ArrowUpRight size={13} aria-hidden="true" />
                </button>
              </div>
            </div>
            <button type="button" className="product-viewer__image" onClick={() => setOpen(true)} aria-label={`放大 ${screen.label} 截图`}>
              <img src={screen.image} alt={screen.alt} className="screenshot" loading="lazy" />
            </button>
          </div>
          <div className="product-copy">
            <div>
              <div className="kicker">User Task</div>
              <h3 className="mt-3">{screen.title}</h3>
              <p className="body-copy mt-4">{screen.description}</p>
            </div>
            <div>
              <div className="kicker">Key Interactions</div>
              <ul className="action-list mt-3">
                {screen.actions.map((action) => (
                  <li key={action}><span className="text-primary" aria-hidden="true">↳</span><span>{action}</span></li>
                ))}
              </ul>
            </div>
            <aside className="border-l border-border pl-5">
              <div className="kicker">Design Decision</div>
              <p className="mt-3 text-sm leading-7">{screen.decision}</p>
              <div className="mt-6 flex flex-wrap gap-2">
                <Badge tone="synthetic">特定运行快照</Badge>
                <Badge tone="raw">真实 UI</Badge>
              </div>
            </aside>
          </div>
          <div className="mt-8 flex items-center justify-between border-t border-border pt-5">
            <button type="button" className="button button--ghost" onClick={() => move(activeIndex - 1)}><ArrowLeft size={14} aria-hidden="true" />上一界面</button>
            <span className="font-mono text-[10px] text-muted">0{activeIndex + 1} / 0{productScreens.length}</span>
            <button type="button" className="button button--ghost" onClick={() => move(activeIndex + 1)}>下一界面<ArrowRight size={14} aria-hidden="true" /></button>
          </div>
        </div>
        <EvidenceNote>截图：portfolio/assets/screenshots/ · 页面：src/claro/ui/screens/ · 写操作会真实写入本地数据库；处置恒为 simulated=true · E32 / E34 / E36 / E55–E56 / E91</EvidenceNote>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title={`Claro · ${screen.label}`}>
        <img src={screen.image} alt={screen.alt} className="mx-auto h-auto max-w-full" />
        <p className="mt-5 max-w-reading text-sm leading-6 text-muted">{screen.description}</p>
      </Modal>
    </section>
  );
}
