import { useState } from "react";
import { Check, ChevronDown, Cpu, UserRound } from "lucide-react";
import { phaseCorrections, phaseTimeline } from "@/data/caseStudy";
import { Badge, EvidenceNote, SectionHeader } from "@/components/Primitives";

const workflow = [
  "需求定义", "阶段规划", "任务拆解", "Prompt 编写", "AI 实现",
  "本地运行", "检查反馈", "修正", "阶段验收",
];

const taskTemplate = [
  ["要解决的问题", "当前业务场景、期望结果与本阶段范围"],
  ["输入", "相关文件、数据、接口与已经确认的事实"],
  ["输出", "需要修改的文件、可运行行为、测试与说明"],
  ["约束", "不改变的功能、依赖限制与必须准确的结论"],
  ["验收与反例", "运行方式、预期结果、失败案例与覆盖场景"],
];

export function AIDevelopment() {
  const [openPhase, setOpenPhase] = useState<number | null>(1);

  return (
    <section id="ai-development" className="section bg-surface/50">
      <div className="shell">
        <SectionHeader
          number="06"
          label="AI-assisted Development"
          title="我定义验收，AI 加速实现。"
          description="项目不是一句 Prompt 生成的产物。业务目标、阶段范围、任务拆解、反例与验收口径由我主导，AI 承担主要代码实现。"
        />
        <div className="grid gap-8 lg:grid-cols-2">
          <article className="border border-border bg-card p-6 lg:p-8">
            <div className="flex items-center gap-3"><UserRound size={18} className="text-primary" aria-hidden="true" /><h3 className="text-lg font-semibold">我负责判断</h3></div>
            <ul className="action-list mt-5">
              {["定义业务问题、项目范围与阶段目标", "拆解任务，编写 Prompt 与技术约束", "运行项目，检查数据、交互与测试有效性", "判断问题来源，调整需求并完成阶段验收"].map((item) => (
                <li key={item}><Check size={14} className="text-primary" aria-hidden="true" /><span>{item}</span></li>
              ))}
            </ul>
          </article>
          <article className="border border-border bg-card p-6 lg:p-8">
            <div className="flex items-center gap-3"><Cpu size={18} className="text-primary" aria-hidden="true" /><h3 className="text-lg font-semibold">AI 承担实现</h3></div>
            <ul className="action-list mt-5">
              {["根据任务说明完成主要代码编写", "实现模块、接口、迁移与测试用例", "根据运行反馈修正实现与缺陷", "保持既有架构与约束，不擅自改变验收口径"].map((item) => (
                <li key={item}><span className="text-primary" aria-hidden="true">↳</span><span>{item}</span></li>
              ))}
            </ul>
          </article>
        </div>
        <div className="mt-12">
          <div className="kicker">Development Loop</div>
          <div className="workflow-grid mt-5">
            {workflow.map((step, index) => (
              <div key={step} className="workflow-step"><span>0{index + 1}</span><p>{step}</p></div>
            ))}
          </div>
          <EvidenceNote>原始 Prompt 与完整对话未保留；本流程依据负责人陈述与阶段记录整理，不作为对话原文引用 · E02–E04 / E67</EvidenceNote>
        </div>
        <div className="mt-14 grid gap-12 lg:grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)] lg:gap-16">
          <div>
            <h3 className="kicker">Six Phases</h3>
            <div className="phase-timeline mt-5">
              {phaseTimeline.map((phase) => (
                <article key={phase.phase} className="phase-item">
                  <span className="phase-item__number">PHASE {phase.phase}</span>
                  <div><h3>{phase.name}</h3><p>{phase.focus}</p></div>
                </article>
              ))}
            </div>
          </div>
          <div>
            <div className="flex items-center justify-between gap-4">
              <h3 className="kicker">Task Brief Template</h3>
              <Badge tone="documented">整理模板 · 非原始 Prompt</Badge>
            </div>
            <dl className="mt-5 border-t border-border">
              {taskTemplate.map(([label, value]) => (
                <div key={label} className="grid gap-2 border-b border-border py-4 sm:grid-cols-[120px_minmax(0,1fr)]">
                  <dt className="text-sm font-medium">{label}</dt>
                  <dd className="text-sm leading-6 text-muted">{value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
        <div className="mt-16">
          <div className="kicker">Correction Log</div>
          <h3 className="display mt-3 text-3xl">真正体现协作质量的，是发现问题之后怎样修正。</h3>
          <div className="mt-7">
            {phaseCorrections.map((phase, index) => {
              const isOpen = openPhase === index;
              return (
                <article key={phase.phase} className="accordion">
                  <button type="button" className="accordion__trigger" onClick={() => setOpenPhase(isOpen ? null : index)} aria-expanded={isOpen} aria-controls={`phase-panel-${index}`}>
                    <span className="grid gap-2 sm:grid-cols-[90px_minmax(0,1fr)] sm:gap-5">
                      <span className="font-mono text-[10px] text-primary">{phase.phase}</span>
                      <span className="accordion__title">{phase.title}</span>
                    </span>
                    <ChevronDown size={17} className={`shrink-0 transition-transform ${isOpen ? "rotate-180" : ""}`} aria-hidden="true" />
                  </button>
                  {isOpen && (
                    <div id={`phase-panel-${index}`} className="accordion__panel">
                      <div><p className="accordion__label">发现</p><p className="accordion__copy">{phase.finding}</p></div>
                      <div><p className="accordion__label">修正</p><p className="accordion__copy">{phase.correction}</p></div>
                      <div><p className="accordion__label">方法沉淀</p><p className="accordion__copy">{phase.lesson}</p><p className="mt-3 font-mono text-[9px] leading-5 text-muted">{phase.evidence}</p></div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
