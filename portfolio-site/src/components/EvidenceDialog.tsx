import { evidenceSources } from "@/data/caseStudy";
import { Modal } from "@/components/Modal";

const documents = [
  { name: "完整案例正文", file: "claro-case-study.md" },
  { name: "关键论点证据索引", file: "evidence-index.md" },
  { name: "Phase 05 验收记录", file: "PHASE_05_ACCEPTANCE_REVIEW.md" },
  { name: "Phase 06 测试报告", file: "PHASE_06_TEST_REPORT.md" },
  { name: "Phase 06 性能报告", file: "PHASE_06_PERFORMANCE.md" },
  { name: "模型评估报告", file: "MODEL_EVALUATION.md" },
];

export function EvidenceDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Modal open={open} onClose={onClose} title="证据口径与原始资料">
      <div className="max-w-reading">
        <p className="body-copy">
          本站把代码事实、保留运行结果、项目记录与个人陈述分开标注。页面中的结果不被升级为生产准确率、线上收益或商业落地结论。
        </p>
        <div className="mt-8 border-t border-border">
          {evidenceSources.map((source) => (
            <div key={source.type} className="grid gap-2 border-b border-border py-4 sm:grid-cols-[90px_minmax(0,1fr)]">
              <span className="font-mono text-xs text-primary">{source.type}</span>
              <div>
                <p className="text-sm font-medium">{source.label}</p>
                <p className="mt-1 text-sm leading-6 text-muted">{source.detail}</p>
              </div>
            </div>
          ))}
        </div>
        <h3 className="mt-9 text-sm font-semibold">可核验资料</h3>
        <div className="mt-3 grid gap-2">
          {documents.map((document) => (
            <a
              key={document.file}
              href={`/evidence/${document.file}`}
              target="_blank"
              rel="noreferrer"
              className="flex items-center justify-between gap-4 border-b border-border py-3 text-sm hover:text-primary"
            >
              {document.name}
              <span className="font-mono text-[10px] text-muted">{document.file}</span>
            </a>
          ))}
        </div>
        <p className="evidence-note mt-7">基线：main @ 6a78879 · 资料整理日期：2026-11-26 · 本次建站未重跑主项目测试</p>
      </div>
    </Modal>
  );
}
