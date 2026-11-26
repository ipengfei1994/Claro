import { useState, type KeyboardEvent } from "react";
import { carrierRows, riskRows } from "@/data/caseStudy";
import { Badge, EvidenceNote, SectionHeader } from "@/components/Primitives";

export function BusinessContext() {
  const [view, setView] = useState<"risk" | "carrier">("risk");
  const rows = view === "risk" ? riskRows : carrierRows;
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      setView(view === "risk" ? "carrier" : "risk");
    }
  };

  return (
    <section id="context" className="section bg-surface/50">
      <div className="shell">
        <SectionHeader
          number="02"
          label="Business Context"
          title="SLG 的风险，不只是一段文本。"
          description="同一标签可能对应不同动作，不同标签也可能需要同类治理。内容信号必须结合关系、场景与行为历史才有策略意义。"
        />
        <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-16">
          <div className="min-w-0">
            <div className="segmented" role="tablist" aria-label="业务风险视图">
              <button id="business-tab-risk" type="button" role="tab" aria-selected={view === "risk"} aria-controls="business-matrix" tabIndex={view === "risk" ? 0 : -1} onKeyDown={onTabKeyDown} onClick={() => setView("risk")}>风险类别</button>
              <button id="business-tab-carrier" type="button" role="tab" aria-selected={view === "carrier"} aria-controls="business-matrix" tabIndex={view === "carrier" ? 0 : -1} onKeyDown={onTabKeyDown} onClick={() => setView("carrier")}>业务载体</button>
            </div>
            <div id="business-matrix" className="table-scroll mt-6" role="tabpanel" aria-labelledby={`business-tab-${view}`}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>{view === "risk" ? "目标风险" : "载体"}</th>
                    <th>{view === "risk" ? "可观测信号" : "关键上下文"}</th>
                    <th>{view === "risk" ? "必要语境" : "策略目标"}</th>
                    <th>{view === "risk" ? "可选动作" : "当前状态"}</th>
                    {view === "risk" && <th>实现状态</th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={"risk" in row ? row.risk : row.carrier}>
                      <td className="font-medium">{"risk" in row ? row.risk : row.carrier}</td>
                      <td className="text-muted">{"signal" in row ? row.signal : row.scope}</td>
                      <td className="text-muted">{"context" in row ? row.context : row.target}</td>
                      {"risk" in row && <td className="text-muted">{row.action}</td>}
                      <td><Badge tone={row.tone}>{row.status}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <EvidenceNote>来源：config/risk_taxonomy.yaml · config/detection_rules.yaml · governance/policy.py · E07–E18 / E27–E30</EvidenceNote>
          </div>
          <aside>
            <h3 className="kicker">Boundary Matters</h3>
            <p className="mt-5 text-sm leading-7 text-muted">标注边界决定系统会误伤什么。Claro 把纳入、排除与语境条件写进分类法和规则，而不是只给类别名。</p>
            <div className="mt-7 space-y-5">
              <div className="border-l-2 border-success pl-4">
                <p className="text-sm font-medium">联盟协作 ≠ 广告</p>
                <p className="mt-2 text-xs leading-6 text-muted">游戏内组织协作、没有站外联系或付款，不应直接判为广告。</p>
              </div>
              <div className="border-l-2 border-warning pl-4">
                <p className="text-sm font-medium">商业代练 ≠ 普通招募</p>
                <p className="mt-2 text-xs leading-6 text-muted">套餐、私聊下单、站外联系方式会叠加广告、交易与欺诈信号。</p>
              </div>
              <div className="border-l-2 border-primary pl-4">
                <p className="text-sm font-medium">风险词出现 ≠ 应处罚</p>
                <p className="mt-2 text-xs leading-6 text-muted">“请勿相信”属于提醒或举报语境，规则通过 negative_terms 降低误伤。</p>
              </div>
            </div>
          </aside>
        </div>
        <div className="mt-14 grid gap-5 border-y border-border py-6 sm:grid-cols-3">
          <div><span className="display text-3xl">7</span><p className="mt-1 text-xs text-muted">风险领域</p></div>
          <div><span className="display text-3xl">19</span><p className="mt-1 text-xs text-muted">细分类别，含 1 个 normal</p></div>
          <div><span className="display text-3xl">8</span><p className="mt-1 text-xs text-muted">数据库 / 模型落库类别</p></div>
        </div>
        <p className="mt-5 max-w-reading text-sm leading-6 text-muted">细分类别用于业务定义与标注；账号交易等类别会映射到 other。政治敏感识别尚未实现，不把“敏感内容”当成已完成能力。</p>
      </div>
    </section>
  );
}
