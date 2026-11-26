import { useState, type KeyboardEvent } from "react";
import { performanceRows, replayPolicies } from "@/data/caseStudy";
import { Badge, EvidenceNote, SectionHeader, Stat } from "@/components/Primitives";
import { ImageFigure } from "@/components/ImageFigure";

type ValidationView = "tests" | "model" | "performance";
const validationViews: ValidationView[] = ["tests", "model", "performance"];

const limitations = [
  "合成标签与批量风险事件同源，不能代表独立人工标注。",
  "模型内容重复率高，真实、困难、内容不相交样本不足。",
  "关键处理服务覆盖率为 40%，UI 写路径缺少点击后查库断言。",
  "Kafka 并发、lag 与重启恢复尚未系统验证。",
  "语义检测未实现，LLM 未做真实端点验证，Hive 尚未运行。",
  "保留浏览器日志存在连接失败，截图不代表最新端到端测试通过。",
];

export function Validation() {
  const [view, setView] = useState<ValidationView>("tests");
  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const offset = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!offset) return;
    event.preventDefault();
    const next = validationViews[(index + offset + validationViews.length) % validationViews.length];
    setView(next);
    document.getElementById(`validation-tab-${next}`)?.focus();
  };

  return (
    <section id="validation" className="section">
      <div className="shell">
        <SectionHeader
          number="07"
          label="Validation & Findings"
          title="验证的重点，不是证明它完美。"
          description="把代码测试、业务演示、模型评估与性能基线分开。每一层只回答它能回答的问题，也同时公开不能推出的结论。"
        />
        <div className="stat-grid">
          <Stat value="308" label="passed" note="保留日志：1 warning · 103.32 秒" />
          <Stat value="79%" label="整体语句覆盖率" note="不是分支覆盖率；处理服务仅 40%" />
          <Stat value="7 / 7" label="演示消息 processed" note="另有 8 组操作步骤成功" />
          <Stat value="600" label="串行流水线样本" note="三档各 200 条，不代表生产容量" />
        </div>
        <div className="segmented mt-10" role="tablist" aria-label="验证证据视图">
          <button id="validation-tab-tests" type="button" role="tab" aria-selected={view === "tests"} aria-controls="validation-panel" tabIndex={view === "tests" ? 0 : -1} onKeyDown={(event) => onTabKeyDown(event, 0)} onClick={() => setView("tests")}>测试与演示</button>
          <button id="validation-tab-model" type="button" role="tab" aria-selected={view === "model"} aria-controls="validation-panel" tabIndex={view === "model" ? 0 : -1} onKeyDown={(event) => onTabKeyDown(event, 1)} onClick={() => setView("model")}>模型评估</button>
          <button id="validation-tab-performance" type="button" role="tab" aria-selected={view === "performance"} aria-controls="validation-panel" tabIndex={view === "performance" ? 0 : -1} onKeyDown={(event) => onTabKeyDown(event, 2)} onClick={() => setView("performance")}>性能与回放</button>
        </div>
        <div id="validation-panel" role="tabpanel" aria-labelledby={`validation-tab-${view}`} className="mt-7 animate-soft-enter" key={view}>
          {view === "tests" && (
            <div className="grid gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(300px,0.7fr)] lg:gap-16">
              <div className="min-w-0">
                <h3 className="display text-3xl">功能链路可执行，关键路径仍需补强。</h3>
                <div className="table-scroll mt-7">
                  <table className="data-table min-w-[620px]">
                    <thead><tr><th>验证层</th><th>保留结果</th><th>能说明什么</th></tr></thead>
                    <tbody>
                      <tr><td className="font-medium">自动化测试</td><td>308 passed / 1 warning</td><td className="text-muted">特定代码与样本条件下的行为</td></tr>
                      <tr><td className="font-medium">端到端演示</td><td>7 条消息 + 8 组操作</td><td className="text-muted">合成场景下业务步骤可串联、可追踪</td></tr>
                      <tr><td className="font-medium">覆盖率</td><td>整体 79% / 处理服务 40%</td><td className="text-muted">核心编排与 UI 写路径仍是短板</td></tr>
                    </tbody>
                  </table>
                </div>
                <p className="body-copy mt-6">演示覆盖接入与决策、认领、覆盖系统动作、模拟禁言、临时封禁、解除、反馈和策略回放。人工审核曾把系统 block 覆盖为 mute，并继续执行模拟处置。</p>
                <EvidenceNote>runtime/tests_final.log:127–129 · runtime/demo_report.json:493–558 · PHASE_06_TEST_REPORT.md · E68–E75</EvidenceNote>
              </div>
              <aside className="border-l border-border pl-6">
                <h3 className="kicker">Evidence Limits</h3>
                <ul className="mt-5 space-y-4">
                  {limitations.slice(0, 3).map((item) => <li key={item} className="text-sm leading-6 text-muted">— {item}</li>)}
                </ul>
                <div className="callout mt-7"><p className="text-sm leading-6">测试通过不等于测试有效；代码存在不等于目标行为真正被执行。</p></div>
              </aside>
            </div>
          )}
          {view === "model" && (
            <div>
              <div className="model-contrast">
                <article className="model-panel">
                  <Badge tone="raw">普通 test 集</Badge>
                  <div className="model-panel__value mt-6">F1 1.0</div>
                  <p className="mt-4 text-sm leading-6 text-muted">二分类与多标签指标均为 1.0。训练、序列化、加载、推理、评估与错误案例持久化链路真实可运行。</p>
                </article>
                <article className="model-panel">
                  <Badge tone="blocked">内容级泛化未建立</Badge>
                  <div className="model-panel__value mt-6 text-danger">99.47%</div>
                  <div className="overlap-track" aria-label="测试消息与训练集内容哈希重复率 99.47%"><span /></div>
                  <p className="mt-4 text-sm leading-6 text-muted">5,033 / 5,060 条测试消息与训练集内容重复；玩家级隔离成立，但内容级隔离不成立。</p>
                </article>
              </div>
              <div className="mt-6 grid gap-5 sm:grid-cols-3">
                <div className="border border-border p-5"><span className="display text-3xl">27</span><p className="mt-2 text-xs leading-6 text-muted">内容不相交子集，全部为 normal</p></div>
                <div className="border border-border p-5"><span className="display text-3xl">0</span><p className="mt-2 text-xs leading-6 text-muted">该子集风险正例，无法估计 precision / recall</p></div>
                <div className="border border-border p-5"><span className="display text-3xl">0.20</span><p className="mt-2 text-xs leading-6 text-muted">8 个标签阈值全部选到搜索网格最低值</p></div>
              </div>
              <p className="quote mt-9 max-w-[900px]">模型工程链路已经验证，模型能力尚未在真实或困难样本上验证。</p>
              <details className="mt-8 border-y border-border">
                <summary className="cursor-pointer py-5 text-sm font-medium">查看模型评估证据图</summary>
                <div className="pb-7"><ImageFigure src="/assets/06-model-evaluation.svg" alt="Claro 模型评估证据，对比 F1 1.0 与 99.47% 内容重复率" title="Model Evaluation Evidence" caption="1.0 主要反映合成模板可分性，不能作为真实环境准确率。" source="models/risk_ml/*/metadata.json · MODEL_EVALUATION.md · E76–E79" /></div>
              </details>
              <EvidenceNote>玩家重叠 0 · 内容重复 99.47% · disjoint 27 条全正常 · 合成标签不是独立人工标注 · E76–E79 / E92</EvidenceNote>
            </div>
          )}
          {view === "performance" && (
            <div>
              <div className="grid gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(300px,0.7fr)] lg:gap-14">
                <div className="min-w-0">
                  <h3 className="kicker">Serial Pipeline Latency</h3>
                  <div className="table-scroll mt-5">
                    <table className="data-table min-w-[620px]">
                      <thead><tr><th>数据档位</th><th>样本</th><th>p50 / ms</th><th>p95 / ms</th><th>p99 / ms</th></tr></thead>
                      <tbody>{performanceRows.map((row) => <tr key={row.size}><td className="font-medium">{row.size}</td><td>{row.samples}</td><td>{row.p50}</td><td>{row.p95}</td><td>{row.p99}</td></tr>)}</tbody>
                    </table>
                  </div>
                  <p className="body-copy mt-5">完整 process_message() 流水线；Windows 单机、full 模式、单进程串行。不含浏览器、WebSocket、TLS、代理与并发争用。</p>
                </div>
                <aside className="border-l border-border pl-6">
                  <h3 className="kicker">Read It Correctly</h3>
                  <p className="mt-4 text-sm leading-7 text-muted">600 条样本全部 processed，但这不是 50k 历史消息的全链路执行证据，也不是生产 QPS。</p>
                  <p className="mt-4 text-sm leading-7 text-muted">批量入库 62.4–81.0 行/秒，走 persist_raw_message()，不是完整治理吞吐。</p>
                  <Badge tone="documented">JSON 为多次测量合并产物</Badge>
                </aside>
              </div>
              <div className="mt-12">
                <div className="flex flex-wrap items-end justify-between gap-4"><div><div className="kicker">Strategy Replay</div><h3 className="display mt-3 text-3xl">命中更多，不代表策略更好。</h3></div><Badge tone="synthetic">500 条合成样本</Badge></div>
                <div className="table-scroll mt-6">
                  <table className="data-table min-w-[720px]">
                    <thead><tr><th>策略</th><th>命中</th><th>Precision</th><th>Recall</th><th>审核占比</th></tr></thead>
                    <tbody>{replayPolicies.map((row) => <tr key={row.policy}><td className="font-mono text-xs">{row.policy}</td><td>{row.hits}</td><td>{row.precision}</td><td>{row.recall}</td><td>{row.review}</td></tr>)}</tbody>
                  </table>
                </div>
                <p className="body-copy mt-5">gov-score-070-review 的 Precision 为 0.974，但所有命中都进入人工审核。检测质量与审核成本必须并列看，不能用单一指标排序。</p>
              </div>
              <details className="mt-9 border-y border-border">
                <summary className="cursor-pointer py-5 text-sm font-medium">查看串行性能证据图</summary>
                <div className="pb-7"><ImageFigure src="/assets/05-latency-evidence.svg" alt="Claro 三档数据规模下的单进程串行流水线延迟与批量入库吞吐" title="Serial Performance Evidence" caption="本机串行基线，不是生产容量；批量入库不是完整风险治理吞吐。" source="docs/performance_results.json · PHASE_06_PERFORMANCE.md · E80–E86" /></div>
              </details>
              <EvidenceNote>回放只写 analytics_replay_*，不执行处置、不改正式决策 · 使用评估时刻策略，不是历史策略重建 · E80–E90</EvidenceNote>
            </div>
          )}
        </div>
        <div className="mt-12 grid gap-7 lg:grid-cols-[190px_minmax(0,1fr)]">
          <h3 className="kicker">Still Unverified</h3>
          <ul className="grid gap-x-10 gap-y-4 sm:grid-cols-2">
            {limitations.map((item) => <li key={item} className="border-l border-border pl-4 text-sm leading-6 text-muted">{item}</li>)}
          </ul>
        </div>
      </div>
    </section>
  );
}
