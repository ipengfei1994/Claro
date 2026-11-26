import { ArrowDown, ArrowUpRight } from "lucide-react";
import { useState } from "react";
import { Modal } from "@/components/Modal";
import { Badge } from "@/components/Primitives";

export function Hero() {
  const [open, setOpen] = useState(false);

  return (
    <section id="top" className="hero">
      <div className="shell">
        <div className="hero__meta">
          <span>Case Study 06</span>
          <span>Personal Project</span>
          <span>AI-assisted Development</span>
          <span>2026</span>
        </div>
        <div className="hero__grid">
          <div>
            <h1 className="hero__title display">Claro<span className="text-primary">.</span></h1>
            <p className="hero__statement display mt-8 max-w-[820px]">
              把“这条消息有多危险”，与“应该拿它怎么办”分开。
            </p>
            <p className="lede mt-6 max-w-[700px]">
              面向 SLG 游戏社区的内容安全与风险治理平台原型。从消息接入、风险识别、策略判断，到人工审核、模拟处置与分析复盘。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <a className="button button--primary" href="#overview">
                阅读完整案例
                <ArrowDown size={15} aria-hidden="true" />
              </a>
              <a className="button button--ghost" href="#product">
                查看产品界面
                <ArrowUpRight size={15} aria-hidden="true" />
              </a>
            </div>
          </div>
          <aside className="hero__aside">
            <div className="kicker">Case Thesis</div>
            <p className="mt-5 text-sm leading-7 text-muted">
              这不是一个“识别违规词”的分类器，而是一套让风险证据、治理动作与人工判断彼此衔接的工作流。
            </p>
            <ol className="mt-7">
              {[
                ["01", "业务判断", "内容、关系与行为上下文共同决定风险。"],
                ["02", "系统实现", "模块化单体，保留可解释、可追踪的处理链路。"],
                ["03", "验证边界", "用合成数据证明流程，不冒充真实业务效果。"],
              ].map(([number, title, copy]) => (
                <li key={number} className="grid grid-cols-[32px_minmax(0,1fr)] gap-3 border-t border-border py-4">
                  <span className="font-mono text-[10px] text-primary">{number}</span>
                  <div>
                    <p className="text-sm font-medium">{title}</p>
                    <p className="mt-1 text-xs leading-6 text-muted">{copy}</p>
                  </div>
                </li>
              ))}
            </ol>
            <div className="mt-6 flex flex-wrap gap-2">
              <Badge tone="synthetic">合成数据</Badge>
              <Badge tone="blocked">非线上部署</Badge>
            </div>
          </aside>
        </div>
      </div>
      <div className="shell">
        <figure>
          <div className="frame">
            <div className="frame__bar">
              <span>CLARO / GOVERNANCE OVERVIEW</span>
              <button type="button" className="inline-flex items-center gap-2 border-0 bg-transparent p-0 text-muted" onClick={() => setOpen(true)}>
                放大真实截图
                <ArrowUpRight size={13} aria-hidden="true" />
              </button>
            </div>
            <button type="button" className="block w-full border-0 bg-transparent p-0" onClick={() => setOpen(true)} aria-label="放大 Claro 治理总览截图">
              <img
                src="/assets/screenshots/overview-light.png"
                alt="Claro 治理总览真实界面，展示 KPI、消息与风险趋势、区间摘要和低样本不可计算提示"
                className="screenshot"
                fetchPriority="high"
              />
            </button>
          </div>
          <figcaption className="figure-caption">
            <span>项目主界面 · 治理总览 · Light theme · 特定运行状态下的真实截图</span>
            <span className="font-mono text-[10px]">1560 × 1100 PNG</span>
          </figcaption>
        </figure>
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Claro · 治理总览">
        <img src="/assets/screenshots/overview-light.png" alt="Claro 治理总览真实界面完整截图" className="mx-auto h-auto max-w-full" />
        <p className="mt-5 text-sm leading-6 text-muted">截图展示特定运行状态，不代表最新浏览器自动化测试结果。页面数据来自合成数据集。</p>
      </Modal>
    </section>
  );
}
