import { ArrowUp } from "lucide-react";
import { EvidenceNote, SectionHeader } from "@/components/Primitives";

const lessons = [
  { number: "01", title: "策略质量不能只靠命中量衡量。", copy: "误杀、漏判与审核成本必须一起评估，否则系统会奖励“处置更多”，而不是“治理更好”。" },
  { number: "02", title: "可解释性来自保留过程。", copy: "规则片段、模型概率、层间冲突、策略快照与人工最终动作需要分别保存，而不是只留下一个分数。" },
  { number: "03", title: "AI 加速实现，不替代验收。", copy: "代码存在不等于功能执行，测试通过不等于测试有效，指标很高不等于样本可信。" },
  { number: "04", title: "说清项目阶段，比堆叠功能更重要。", copy: "明确已完成、部分实现、未实现与尚未运行，才能判断下一步真正应该投入什么。" },
];

const nextSteps = [
  "补齐邮件、公告和昵称的独立数据模型与审批流程。",
  "重建内容不相交、包含困难负例与真实标注的模型评估集。",
  "优先补统一编排、部分发布失败、审核写路径与 Kafka 重启恢复测试。",
  "为治理 topic 接入真实消费者，明确 Outbox 失败后的人工恢复或 DLQ。",
  "保留需求版本、Prompt、验收清单与运行日志，完善 AI 协作复盘。",
  "在原生环境实际运行 Hive；否则继续明确标记不可用。",
];

export function Reflection() {
  return (
    <section id="reflection" className="section">
      <div className="shell">
        <SectionHeader
          number="08"
          label="Reflection & Next"
          title="这个项目最重要的产出，是知道下一步该验证什么。"
          description="Claro 展示了从游戏内容安全业务分析到系统原型的完整推进过程，也把真实业务前必须补齐的证据放在同样重要的位置。"
        />
        <div className="reflection-list">
          {lessons.map((lesson) => (
            <article key={lesson.number} className="reflection-item">
              <span className="reflection-item__number">{lesson.number}</span>
              <div><h3>{lesson.title}</h3><p>{lesson.copy}</p></div>
            </article>
          ))}
        </div>
        <div className="mt-16 grid gap-12 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] lg:gap-20">
          <div>
            <div className="kicker">What This Case Demonstrates</div>
            <p className="quote mt-5">把业务问题翻译成系统契约，再把运行结果翻译成可信结论。</p>
            <EvidenceNote>游戏内容安全策略 · 风控上下文 · 平台产品设计 · 模块化架构 · AI 协作与验证</EvidenceNote>
          </div>
          <div>
            <div className="kicker">If I Continue</div>
            <ol className="mt-5 border-t border-border">
              {nextSteps.map((step, index) => (
                <li key={step} className="grid grid-cols-[36px_minmax(0,1fr)] gap-4 border-b border-border py-4">
                  <span className="font-mono text-[10px] text-primary">0{index + 1}</span>
                  <span className="text-sm leading-6 text-muted">{step}</span>
                </li>
              ))}
            </ol>
          </div>
        </div>
        <div className="mt-16 border-y border-border py-10 lg:py-14">
          <p className="display max-w-[960px] text-[clamp(1.8rem,4vw,3.6rem)] leading-[1.25] tracking-[-0.035em]">
            一个值得信任的治理系统，不只是能给出动作，更能说明它为什么这样做，以及这个结论目前有多可靠。
          </p>
        </div>
      </div>
    </section>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="shell">
        <div className="footer-grid">
          <div>
            <a href="#top" className="footer-title">Claro<span className="text-primary">.</span></a>
            <p className="mt-3 max-w-reading text-sm leading-6 text-muted">SLG 内容安全与风险治理平台原型 · 个人工程案例 · AI 辅助开发</p>
            <p className="mt-4 font-mono text-[10px] leading-5 text-muted">LOCAL-FIRST · SYNTHETIC DATA · SIMULATED ENFORCEMENT · NOT DEPLOYED</p>
          </div>
          <div className="lg:text-right">
            <div className="footer-links lg:justify-end">
              <a href="/evidence/claro-case-study.md" target="_blank" rel="noreferrer">案例正文</a>
              <a href="/evidence/evidence-index.md" target="_blank" rel="noreferrer">证据索引</a>
              <a href="/evidence/PHASE_06_COMPLETION_REPORT.md" target="_blank" rel="noreferrer">交付记录</a>
              <a href="#top" className="inline-flex items-center gap-2">返回顶部<ArrowUp size={13} aria-hidden="true" /></a>
            </div>
            <p className="mt-5 font-mono text-[10px] text-muted">CASE BASELINE / main @ 6a78879 / 2026-11-26</p>
          </div>
        </div>
      </div>
    </footer>
  );
}
