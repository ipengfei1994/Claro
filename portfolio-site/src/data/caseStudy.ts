export type StatusTone =
  | "implemented"
  | "partial"
  | "missing"
  | "blocked"
  | "synthetic"
  | "raw"
  | "documented";

export interface NavigationItem {
  id: string;
  number: string;
  label: string;
  short: string;
}

export const navigation: NavigationItem[] = [
  { id: "overview", number: "01", label: "项目概览", short: "Overview" },
  { id: "context", number: "02", label: "业务语境", short: "Context" },
  { id: "strategy", number: "03", label: "策略设计", short: "Strategy" },
  { id: "architecture", number: "04", label: "系统架构", short: "System" },
  { id: "product", number: "05", label: "产品体验", short: "Product" },
  { id: "ai-development", number: "06", label: "AI 协作", short: "AI Workflow" },
  { id: "validation", number: "07", label: "验证结果", short: "Validation" },
  { id: "reflection", number: "08", label: "复盘反思", short: "Reflection" },
];

export const riskRows = [
  {
    risk: "广告 / 导流",
    signal: "促销话术、重复刷屏、站外链接",
    context: "频道、发送频率、域名白名单、举报语境",
    action: "允许 / 警告 / 标记 / 送审",
    status: "已实现",
    tone: "implemented" as StatusTone,
  },
  {
    risk: "欺诈 / 黑市",
    signal: "假奖励、凭据钓鱼、出号、代练",
    context: "交易要求、链接来源、玩家历史、风险分",
    action: "高风险送审，限制动作受置信度约束",
    status: "基础规则",
    tone: "partial" as StatusTone,
  },
  {
    risk: "骚扰 / 威胁",
    signal: "人身攻击、群体敌意、现实威胁",
    context: "重复行为、目标关系、服务器 / 联盟范围",
    action: "警告 / 送审 / 模拟处置",
    status: "已实现",
    tone: "implemented" as StatusTone,
  },
  {
    risk: "自伤信号",
    signal: "自伤相关表达与求助语境",
    context: "风险等级、置信度、原文证据",
    action: "策略路由人工审核，不直接处罚",
    status: "基础识别",
    tone: "partial" as StatusTone,
  },
  {
    risk: "色情内容",
    signal: "色情表达与变体",
    context: "语境、类别证据、模型概率",
    action: "按策略警告、送审或模拟限制",
    status: "已实现",
    tone: "implemented" as StatusTone,
  },
  {
    risk: "政治敏感",
    signal: "尚未建立对应规则与模型标签",
    context: "需要独立定义、标注与治理口径",
    action: "—",
    status: "未实现",
    tone: "missing" as StatusTone,
  },
];

export const carrierRows = [
  {
    carrier: "游戏聊天",
    scope: "内容 + 玩家 / 服务器 / 联盟 / 频道",
    target: "普通协作保留，高风险或低置信度送审",
    status: "端到端",
    tone: "implemented" as StatusTone,
  },
  {
    carrier: "联盟内容",
    scope: "招募、协作与组织化围攻",
    target: "区分正常联盟运营与群体骚扰",
    status: "部分实现",
    tone: "partial" as StatusTone,
  },
  {
    carrier: "玩家邮件",
    scope: "收件人、会话线程、发送历史",
    target: "私信高风险需要明确复核路径",
    status: "未实现",
    tone: "missing" as StatusTone,
  },
  {
    carrier: "游戏公告",
    scope: "官方来源、受众、发布前审批",
    target: "不能套用普通聊天默认动作",
    status: "未实现",
    tone: "missing" as StatusTone,
  },
  {
    carrier: "玩家昵称",
    scope: "归一化、混淆字、账号历史",
    target: "治理对象是账号，不是单条消息",
    status: "未实现",
    tone: "missing" as StatusTone,
  },
];

export interface ProductScreen {
  id: string;
  label: string;
  title: string;
  task: string;
  image: string;
  theme: "Light" | "Dark";
  alt: string;
  description: string;
  actions: string[];
  decision: string;
  evidence: string;
}

export const productScreens: ProductScreen[] = [
  {
    id: "overview",
    label: "治理总览",
    title: "先判断风险面，再进入个案。",
    task: "监控当前消息、风险与治理负荷",
    image: "/assets/screenshots/overview-light.png",
    theme: "Light",
    alt: "Claro 治理总览真实截图，展示 KPI、消息与风险趋势和低样本提示",
    description: "把风险消息、待处理案例、人工审核和处置放在同一视图中，同时公开指标口径与样本量。",
    actions: ["切换 7 天 / 30 天 / 90 天 / 近一年窗口", "查看 KPI、风险趋势与区间摘要", "识别不可计算指标并进入分析口径"],
    decision: "低样本不显示 0% 或 100%，避免把噪声当成运营结论。",
    evidence: "overview.py · analytics/definitions.py",
  },
  {
    id: "messages",
    label: "消息探查",
    title: "从一条消息，追到它为什么被这样处理。",
    task: "筛选消息并查看风险、决策与案例关联",
    image: "/assets/screenshots/message-explorer-light.png",
    theme: "Light",
    alt: "Claro 消息探查真实截图，展示多维筛选、消息结果和证据链入口",
    description: "审核员先缩小样本，再查看内容、风险等级、分数、决策、案例状态与发生时间。",
    actions: ["按数据集、频道、关键词与时间筛选", "按风险等级、类别、决策动作和案例状态过滤", "打开单条消息查看关联证据"],
    decision: "把过滤条件与业务实体并置，减少在多个页面之间重建语境。",
    evidence: "message_explorer.py · ExplorerService",
  },
  {
    id: "moderation",
    label: "审核工作台",
    title: "人工接管，不等于覆盖一个字段。",
    task: "处理队列、查看证据并提交受控结论",
    image: "/assets/screenshots/moderation-workbench-light.png",
    theme: "Light",
    alt: "Claro 审核工作台真实截图，展示审核队列、风险分布和单条审核详情",
    description: "队列、风险证据与建议动作进入同一工作流；认领、批准、拒绝、覆盖、升级和重开都受状态机约束。",
    actions: ["按状态、风险等级、负责人和关键词筛选", "选择任务并认领，提交带理由的审核结论", "显式覆盖动作、升级、二次复核或重开"],
    decision: "拒绝表示不应处置；限制玩家必须显式覆盖并给出最终动作与等级。",
    evidence: "moderation_workbench.py · governance/moderation.py",
  },
  {
    id: "policy",
    label: "策略中心",
    title: "让策略可操作，也可回到历史版本。",
    task: "管理条件、优先级、版本与策略试验",
    image: "/assets/screenshots/policy-center-light.png",
    theme: "Light",
    alt: "Claro 策略中心真实截图，展示策略清单、版本、动作、优先级和命中次数",
    description: "策略以结构化条件表达，支持启停、版本比较、回滚与冲突检测；测试通常不写正式决策，但无策略时可能创建默认项。",
    actions: ["查看策略类型、动作、优先级、版本与命中次数", "新建、编辑、启停策略并比较版本", "运行策略测试与冲突检测"],
    decision: "回滚创建新版本，不删除历史；策略快照与哈希随决策保留。",
    evidence: "policy_center.py · governance/policy.py",
  },
  {
    id: "enforcement",
    label: "处置中心",
    title: "处置必须可查询，也必须说明是模拟。",
    task: "检查模拟处置、玩家状态、到期与解除",
    image: "/assets/screenshots/enforcement-center-light.png",
    theme: "Light",
    alt: "Claro 处置中心真实截图，展示模拟处置分布、玩家状态与历史处置记录",
    description: "五类处置均写入本地记录，并关联对象、时长、审核单、策略版本和操作信息。",
    actions: ["查询处置类型、状态、对象与策略版本", "查看玩家模拟限制状态", "执行模拟处置、到期与解除"],
    decision: "所有记录标记 simulated=true，不连接真实游戏服务。",
    evidence: "enforcement_center.py · governance/enforcement.py",
  },
  {
    id: "risk",
    label: "风险情报",
    title: "区分规则命中与完整融合，避免夸大覆盖。",
    task: "检查检测层、规则目录与模型资产",
    image: "/assets/screenshots/risk-intelligence-light.png",
    theme: "Light",
    alt: "Claro 风险情报真实截图，展示检测覆盖、检测层命中和规则目录",
    description: "页面分别呈现消息量、完整融合结果、原子证据与风险事件，让检测覆盖缺口可见。",
    actions: ["区分规则事件、原子证据与完整融合结果", "查看检测层命中、规则目录与模型资产", "结合覆盖率判断后续检测投入"],
    decision: "8,856 条风险事件不等于 8,856 条完整融合结果。",
    evidence: "risk_intelligence.py · RiskService",
  },
  {
    id: "analytics",
    label: "分析总览",
    title: "指标不可计算时，产品应该直接说不可计算。",
    task: "检查统一口径、低样本抑制与趋势",
    image: "/assets/screenshots/analytics-overview-dark.png",
    theme: "Dark",
    alt: "Claro 深色分析总览真实截图，展示统一指标口径和低样本不可计算提示",
    description: "所有指标来自统一服务层；页面展示 definition version、数据窗口与合成数据来源。",
    actions: ["查看统一口径 KPI 与风险趋势", "展开指标口径与限制", "识别被剔除的低样本时间桶"],
    decision: "分母小于 30 时抑制比率，并公开真实样本量。",
    evidence: "analytics_overview.py · analytics/definitions.py",
  },
];

export const phaseTimeline = [
  { phase: "01", name: "Foundation", focus: "配置、迁移、基础设施" },
  { phase: "02", name: "Synthetic Data", focus: "可复现业务样本" },
  { phase: "03", name: "Risk Engine", focus: "规则、模型与融合" },
  { phase: "04", name: "Governance", focus: "策略、审核与处置" },
  { phase: "05", name: "Analytics", focus: "指标、评估与回放" },
  { phase: "06", name: "Productization", focus: "界面、测试与交付" },
];

export const phaseCorrections = [
  {
    phase: "Phase 04",
    title: "从功能完成，转向流程可追溯",
    finding: "主体治理功能已经存在，阶段重点是集成审查、测试补充与缺陷修复。",
    correction: "核验策略是否影响真实决策、审核是否保留原判断、处置是否能追到决策与策略。",
    lesson: "验收对象是业务链路，不是代码或页面数量。",
    evidence: "PHASE_04_COMPLETION_REPORT.md · E58–E59",
  },
  {
    phase: "Phase 05",
    title: "先检查样本与口径，再讨论指标",
    finding: "作用域常量被当作真实计数；n=1 比率成为 KPI；回放排除正常消息；测试改写共享数据。",
    correction: "加入最小分母、纳入正常样本、修正混淆矩阵语义，并以 9 张表的内容级 SHA-256 验证回放隔离。",
    lesson: "指标很高，不代表样本可信；测试通过，也需要检查测试方法。",
    evidence: "PHASE_05_ACCEPTANCE_REVIEW.md · E60–E63",
  },
  {
    phase: "Phase 06",
    title: "识别测试工具的“假绿”",
    finding: "UI 冒烟未真正渲染目标页面；-Suite all 排除集成测试；浏览器巡检误判默认页回退。",
    correction: "修正套件范围、页面渲染与深链接断言，保留失败日志而不是写成全部通过。",
    lesson: "AI 加速实现，但验收标准必须由人定义并核验。",
    evidence: "PHASE_06_TEST_REPORT.md · E64–E66",
  },
];

export const replayPolicies = [
  { policy: "gov-score-045-warn", hits: 32, precision: "0.406", recall: "0.260", review: "0.000" },
  { policy: "gov-category-spam-flag", hits: 17, precision: "0.706", recall: "0.240", review: "0.000" },
  { policy: "gov-score-070-review", hits: 38, precision: "0.974", recall: "0.740", review: "1.000" },
];

export const performanceRows = [
  { size: "1,000 行", samples: 200, p50: "128.2", p95: "189.32", p99: "271.54" },
  { size: "10,000 行", samples: 200, p50: "107.1", p95: "149.69", p99: "179.5" },
  { size: "50,000 行", samples: 200, p50: "144.51", p95: "215.5", p99: "331.59" },
];

export const evidenceSources = [
  { type: "CODE", label: "源码与配置", detail: "当前实现可直接核验，不等于真实业务效果。" },
  { type: "RAW", label: "原始运行产物", detail: "只代表某次保留运行，不自动外推到生产。" },
  { type: "DOC", label: "项目记录", detail: "阶段报告提供旁证，不等同于独立复核。" },
  { type: "TEST", label: "测试结果", detail: "在特定样本与测试条件下成立。" },
  { type: "OWNER", label: "负责人陈述", detail: "用于第一人称说明角色与工作方式。" },
  { type: "ABSENCE", label: "缺失与未运行", detail: "用代码缺席、环境缺失或未保留日志界定不能声称的能力。" },
];
