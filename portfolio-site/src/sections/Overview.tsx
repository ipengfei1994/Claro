import { EvidenceNote, SectionHeader, Stat } from "@/components/Primitives";

const questions = [
  { number: "01", title: "内容有什么风险？", copy: "系统识别出哪些规则或模型信号，为什么这样判断，证据能否回到原文？" },
  { number: "02", title: "应该如何处理？", copy: "结合玩家、服务器、联盟、频道与当前策略，应该放行、提醒、观察、送审还是限制？" },
  { number: "03", title: "如何形成闭环？", copy: "审核员如何接管，处置能否追踪，误判怎样进入下一轮策略复盘？" },
];

const stack = ["Python", "PostgreSQL", "Kafka", "Redis", "scikit-learn", "Streamlit", "Plotly", "SQL"];

export function Overview() {
  return (
    <section id="overview" className="section">
      <div className="shell">
        <SectionHeader
          number="01"
          label="Project Overview"
          title="先定义治理问题，再选择技术形态。"
          description="Claro 从 SLG 玩家交流的真实复杂性出发，把内容识别、策略配置、人工审核与分析放进同一套可运行原型。"
        />
        <div className="grid gap-14 lg:grid-cols-[minmax(0,1.15fr)_minmax(300px,0.7fr)] lg:gap-20">
          <div>
            <p className="quote">
              审核团队要回答的，不只是“这句话像不像违规”，而是“此刻、此范围内，系统应该怎么做”。
            </p>
            <div className="mt-10">
              {questions.map((question) => (
                <article key={question.number} className="overview-question">
                  <span className="overview-question__number">{question.number}</span>
                  <div>
                    <h3>{question.title}</h3>
                    <p>{question.copy}</p>
                  </div>
                </article>
              ))}
            </div>
          </div>
          <aside>
            <h3 className="kicker">Project Profile</h3>
            <dl className="mt-5 border-t border-border">
              {[
                ["项目类型", "个人项目 / AI 辅助开发"],
                ["业务领域", "SLG 游戏内容安全与风险治理"],
                ["我的角色", "业务设计、阶段规划、任务拆解与验收"],
                ["开发方式", "我主导需求与验证，AI 承担主要代码实现"],
                ["交付形态", "Windows 本地运行的功能原型"],
                ["数据性质", "固定种子合成数据，处置均为模拟"],
              ].map(([label, value]) => (
                <div key={label} className="grid gap-2 border-b border-border py-4 sm:grid-cols-[92px_minmax(0,1fr)]">
                  <dt className="text-xs text-muted">{label}</dt>
                  <dd className="text-sm leading-6">{value}</dd>
                </div>
              ))}
            </dl>
            <div className="callout mt-7">
              <p className="text-sm font-medium">当前边界</p>
              <p className="mt-2 text-sm leading-6 text-muted">不连接真实游戏服务器，不产生真实玩家处罚，尚未进行真实线上业务验证。</p>
            </div>
          </aside>
        </div>
        <div className="stat-grid mt-16">
          <Stat value="15" label="产品页面" note="5 个任务导向导航组" />
          <Stat value="22" label="检测规则" note="关键词、正则、URL、黑名单与重复模式" />
          <Stat value="7 / 19" label="风险领域 / 细分类别" note="数据库与模型使用 8 个落库类别" />
          <Stat value="2" label="运行模式" note="development 内存总线 / full 真实基础设施" />
        </div>
        <div className="mt-10 grid gap-7 lg:grid-cols-[190px_minmax(0,1fr)]">
          <h3 className="kicker">Technical Profile</h3>
          <div>
            <div className="flex flex-wrap gap-x-6 gap-y-3 font-mono text-xs text-muted">
              {stack.map((item) => <span key={item}>{item}</span>)}
            </div>
            <EvidenceNote>来源：README.zh-CN.md · src/claro/ui/app.py · config/risk_taxonomy.yaml · E01 / E13–E15 / E40 / E55</EvidenceNote>
          </div>
        </div>
      </div>
    </section>
  );
}
