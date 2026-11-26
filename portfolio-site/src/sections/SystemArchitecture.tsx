import { EvidenceNote, SectionHeader } from "@/components/Primitives";
import { ImageFigure } from "@/components/ImageFigure";

const layers = [
  { name: "UI / Streamlit", detail: "15 个业务页面 · 5 个导航组 · 页面调用服务，不直接执行 SQL，不持有事务" },
  { name: "Application", detail: "ClaroProcessingService 统一编排 · 治理、审核、反馈、回放与 Outbox 分发" },
  { name: "Domain / Risk", detail: "分类与规则 · TF-IDF / 逻辑回归 · 加权融合 · 策略纯逻辑 · 审核状态机" },
  { name: "Data Access", detail: "PostgreSQL 权威记录 · Repository + 显式事务 · 唯一约束 · 行锁与审计" },
  { name: "Infrastructure", detail: "Kafka 生产 / 消费 · Redis 缓存 · 内存事件总线 · 日志与健康检查适配器" },
];

const infrastructure = [
  { title: "PostgreSQL 18.3", copy: "业务数据、事务、JSONB、唯一约束、审核锁与分析查询。", state: "权威数据源" },
  { title: "Kafka 3.9.2", copy: "原始、处理后与风险事件；至少一次投递、重试与 consumer DLQ。", state: "内容事件链路" },
  { title: "Redis 8.10.3", copy: "规则与策略缓存；发送频次来自 PostgreSQL 查询后缓存。", state: "缓存，非权威" },
  { title: "Hive / Hadoop", copy: "已有 CSV 导出和 ODS / DWD / DWS / ADS SQL。", state: "尚未运行" },
];

export function SystemArchitecture() {
  return (
    <section id="architecture" className="section section--dark">
      <div className="shell">
        <SectionHeader
          number="04"
          label="System Architecture"
          title="模块化单体，把复杂性留在边界内。"
          description="本地联调需要清晰事务边界，而不是过早拆成分布式服务。两种运行模式复用同一套业务逻辑，用适配器替换基础设施。"
        />
        <div className="layer-stack">
          {layers.map((layer, index) => (
            <div key={layer.name} className="layer">
              <div className="layer__name"><span className="mr-3 text-night-muted">0{index + 1}</span>{layer.name}</div>
              <p className="layer__detail">{layer.detail}</p>
            </div>
          ))}
        </div>
        <div className="architecture-pipeline" aria-label="统一处理入口阶段">
          {["validate", "ingest", "detect", "publish", "governance"].map((stage, index) => (
            <span key={stage} className="flex items-center gap-2">{index > 0 && <span aria-hidden="true">→</span>}{stage}</span>
          ))}
        </div>
        <div className="infra-grid">
          {infrastructure.map((item) => (
            <article key={item.title} className={`infra-item ${item.state === "尚未运行" ? "border-danger/60" : ""}`}>
              <div className="flex items-start justify-between gap-3">
                <h3 className="infra-item__title">{item.title}</h3>
                <span className={`font-mono text-[9px] ${item.state === "尚未运行" ? "text-danger" : "text-night-muted"}`}>{item.state}</span>
              </div>
              <p className="infra-item__copy">{item.copy}</p>
            </article>
          ))}
        </div>
        <div className="mt-12 grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px] lg:gap-12">
          <div>
            <h3 className="kicker">Consistency Model</h3>
            <div className="mt-5 grid gap-px bg-night-line sm:grid-cols-3">
              {[
                ["① 接入幂等", "inbox_event：event id、topic / partition / offset 与内容哈希"],
                ["② 检测幂等", "risk_result.message_id 唯一，重复检测返回已有结果"],
                ["③ 治理幂等", "策略快照、确定性 decision_key 与处置幂等键"],
              ].map(([title, copy]) => (
                <div key={title} className="bg-night p-5">
                  <h4 className="text-sm font-medium text-night-foreground">{title}</h4>
                  <p className="mt-3 text-xs leading-6 text-night-muted">{copy}</p>
                </div>
              ))}
            </div>
            <p className="mt-5 text-sm leading-7 text-night-muted">直接路径在发布风险事件后，于同一进程调用治理；Kafka 消费链由 raw、processed、risk 三个独立消费者衔接。两者共用下游逻辑，但不是同一条调用拓扑。</p>
          </div>
          <aside className="border-l border-night-line pl-6">
            <h3 className="kicker">Known Boundary</h3>
            <p className="mt-5 text-sm leading-7 text-night-muted">Outbox 只覆盖选定治理写入；evaluation 提交后入队，耗尽后停在 failed，没有自动 DLQ。5 个治理 topic 已发布，但仓库内没有对应业务消费者。</p>
            <p className="mt-4 text-sm leading-7 text-night-muted">trace_id 尚未统一覆盖所有治理记录，追溯仍依赖实体关联。</p>
          </aside>
        </div>
        <EvidenceNote>来源：bootstrap.py · processing_service.py · infrastructure/kafka.py · governance_repository.py · E40–E54 / E57</EvidenceNote>
        <details className="mt-12 border-y border-night-line">
          <summary className="cursor-pointer py-5 text-sm text-night-foreground">展开完整事件流：直接路径、Kafka 消费链与失败处理</summary>
          <div className="pb-8">
            <ImageFigure
              src="/assets/04-event-and-idempotency.svg"
              alt="Claro Kafka 消息流、Outbox 与三层幂等图"
              title="Event Flow & Idempotency"
              caption="至少一次投递不等于 exactly-once。consumer DLQ 与 Outbox 失败是两条不同路径；治理 topic 尚无仓库内下游消费者。"
              source="application/message_events.py · infrastructure/kafka.py · E44–E54"
              className="[&_.frame]:bg-night [&_.frame]:border-night-line [&_.frame__bar]:bg-night-soft [&_.frame__bar]:text-night-muted [&_.figure-caption]:text-night-muted"
            />
          </div>
        </details>
      </div>
    </section>
  );
}
