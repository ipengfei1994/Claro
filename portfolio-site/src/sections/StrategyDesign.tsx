import { Badge, EvidenceNote, SectionHeader } from "@/components/Primitives";
import { ImageFigure } from "@/components/ImageFigure";

const stages = [
  { number: "01", title: "内容检测", copy: "22 条规则与 char_wb TF-IDF + One-vs-Rest 逻辑回归独立产出类别、分数与原文证据。" },
  { number: "02", title: "风险融合", copy: "按类别计算加权 noisy-OR，保留每层贡献、公式、阈值与冲突；不平均抹平分歧。" },
  { number: "03", title: "策略判断", copy: "结合作用范围、优先级、风险等级与治理置信度，从声明式条件中选择动作并保存快照。" },
  { number: "04", title: "人工与处置", copy: "低置信度或高风险进入审核；处置由策略和审核决定，五类动作全部模拟并留审计。" },
];

export function StrategyDesign() {
  return (
    <section id="strategy" className="section">
      <div className="shell">
        <SectionHeader
          number="03"
          label="Strategy Design"
          title="检测给出证据，策略才决定动作。"
          description="Claro 把风险识别与治理裁决拆开：检测器回答“多危险、为什么”，策略回答“此刻应该怎么做”。"
        />
        <div className="flow-grid">
          {stages.map((stage) => (
            <article key={stage.number} className="flow-step">
              <span className="flow-step__number">STAGE {stage.number}</span>
              <h3 className="flow-step__title">{stage.title}</h3>
              <p className="flow-step__copy">{stage.copy}</p>
            </article>
          ))}
        </div>
        <div className="mt-10 grid gap-8 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-14">
          <div>
            <h3 className="kicker">Fusion Contract</h3>
            <div className="mt-5 border-y border-border py-7 font-mono text-sm leading-7">
              score<sub>category</sub> = 1 − ∏ (1 − w<sub>layer</sub> × strength<sub>layer</sub>)
            </div>
            <p className="body-copy mt-5">总体风险分取最高类别分，同时保留分类别概率、规则证据、模型贡献和层间冲突。缺层不重新归一化，也不把缺失当作零分。</p>
            <EvidenceNote>权重为手工设定，未做统计校准 · 来源：risk_engine/fusion.py:256–302 · E19–E22</EvidenceNote>
          </div>
          <aside className="border-l border-border pl-6">
            <h3 className="kicker">Governance Guardrails</h3>
            <dl className="mt-5 space-y-5">
              <div><dt className="font-mono text-2xl">0.55</dt><dd className="mt-1 text-sm leading-6 text-muted">限制性动作低于该置信度时降级为审核。</dd></div>
              <div><dt className="font-mono text-2xl">0.70</dt><dd className="mt-1 text-sm leading-6 text-muted">high / critical 风险低于该置信度时转人工审核。</dd></div>
              <div><dt className="font-mono text-2xl">5</dt><dd className="mt-1 text-sm leading-6 text-muted">风险等级；检测阈值与治理置信度是两套口径。</dd></div>
            </dl>
          </aside>
        </div>
        <div className="mt-16">
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div><div className="kicker">Two Real Demo Traces</div><h3 className="display mt-3 text-3xl">同一套检测结果，可以走向不同治理动作。</h3></div>
            <Badge tone="synthetic">合成演示消息</Badge>
          </div>
          <div className="decision-grid mt-7">
            <article className="decision-item">
              <div className="flex items-start justify-between gap-4"><span className="text-sm font-medium">自伤信号</span><Badge tone="partial">critical</Badge></div>
              <div className="decision-item__score mt-6">0.9604</div>
              <p className="mt-2 text-xs text-muted">检测置信度 0.9861 · 建议 restrict</p>
              <div className="decision-route"><span>检测建议</span><span>→</span><span>review</span><span>→</span><span>pending_review</span></div>
              <p className="mt-5 text-sm leading-6 text-muted">治理层没有直接执行检测器的 restrict，而是创建审核案例。</p>
            </article>
            <article className="decision-item">
              <div className="flex items-start justify-between gap-4"><span className="text-sm font-medium">多信号交易消息</span><Badge tone="implemented">medium</Badge></div>
              <div className="decision-item__score mt-6">0.54</div>
              <p className="mt-2 text-xs text-muted">检测建议 review</p>
              <div className="decision-route"><span>检测建议</span><span>→</span><span>warn</span><span>→</span><span>auto_decided</span></div>
              <p className="mt-5 text-sm leading-6 text-muted">匹配策略可调整动作；两条样例证明职责分离，不证明策略最优。</p>
            </article>
          </div>
          <EvidenceNote>来源：runtime/demo_report.json:350–491 · E23–E24 / E27–E28</EvidenceNote>
        </div>
        <details className="mt-12 border-y border-border">
          <summary className="cursor-pointer py-5 text-sm font-medium">查看审核状态机：为什么“拒绝”不等于“拦截”</summary>
          <div className="pb-7">
            <ImageFigure
              src="/assets/03-moderation-state-machine.svg"
              alt="Claro 审核状态机，展示待处理、审核中、批准、拒绝、升级、二次复核和重开路径"
              title="Moderation State Machine"
              caption="受控状态迁移 + 行锁 + lock_version。拒绝解析为不处置；限制玩家必须显式覆盖并给出最终动作与等级。"
              source="governance/moderation.py · governance_repository.py · E34–E35"
            />
          </div>
        </details>
      </div>
    </section>
  );
}
